/* PEER: two consoles playing one two-player game, each with a nesp32, and
 * the nesp32s joined over the network (docs/PROTOCOL.md). nes-drmario's
 * netplay is the first to use it.
 *
 * Both consoles run the whole game, and only buttons cross: a byte for each
 * tick of the game, each way. A console takes a tick only when it holds
 * both players' buttons for it, so nothing here has to know what a button
 * is, or keep time. It is a lobby, in which one nesp32 waits and the other
 * calls it, and then a relay.
 *
 * The connection is the hardware's (nesp_hal_t's peer_*): a stream of bytes
 * each way, made and fed by another task. Once it is up each nesp32 says
 * what it is, and what is on its console, before either calls it a game:
 * something else that finds the port is not taken for a console, and
 * neither is another game. After the greetings a byte's place in the stream
 * is its tick, counted from 0.
 *
 * The console names ticks by their low 8 bits. It is never more than a few
 * ticks from what this side holds, so that is enough to tell which is
 * meant.
 *
 * Every op may be asked again with nothing done twice: an order that is
 * already what the nesp32 is doing changes nothing, and buttons it has
 * taken are passed over. So no reply here is held for a repeat.
 */
#include <stdio.h>
#include <string.h>

#include "nesp_services.h"

#define GREETING NESP_PEER_GREETING
_Static_assert(1 + NESP_PEER_PER_FRAME <= NESP_SHORT_DATA, "TICKS does not fit a short frame");
_Static_assert(NESP_PEER_PER_FRAME == 2, "a short frame's length is by counts of 2 and under");
#define SHOW_MS 500
#define WATCH_MS 2000
_Static_assert(NESP_ARQ_NEEDS == 6, "watch() names six counts");

static const char greeting_mark[4] = {'N', 'E', 'S', 'P'};

static bool up(uint8_t conn)
{
    return conn == NESP_CONN_ANSWERED || conn == NESP_CONN_CALLED;
}

static bool in_session(const nesp_peer_t *peer)
{
    return peer->lobby == NESP_LOBBY_HOST || peer->lobby == NESP_LOBBY_GUEST;
}

/* Is this nesp32 on a network, and at what address? */
static bool online(const nesp_peer_t *peer, uint8_t *address)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    peer->hal->wifi(peer->hal->ctx, &wifi);
    memcpy(address, wifi.address, 4);
    return wifi.state == NESP_WIFI_JOINED;
}

/* Whatever connection there is, or is being made, is over. */
static void drop(nesp_peer_t *peer)
{
    peer->hal->peer_close(peer->hal->ctx);
    peer->lobby = NESP_LOBBY_IDLE;
    peer->greeting = false;
    peer->lost = false;
    peer->remote_len = 0;
    peer->show = true;
}

/* --- the greetings ------------------------------------------------------------- */

static void greeting(const nesp_peer_t *peer, uint8_t *out)
{
    memcpy(out, greeting_mark, sizeof(greeting_mark));
    out[4] = NESP_PEER_VERSION;
    memcpy(out + 5, peer->sys->app, NESP_APP_ID);
    out[5 + NESP_APP_ID] = peer->sys->app_version;
}

/* The other end is not one of these, or not the same game, or has gone.
 * One that hosts goes on waiting for the right caller. */
static void refuse(nesp_peer_t *peer)
{
    peer->greeting = false;
    peer->hal->peer_close(peer->hal->ctx);
    if (peer->lobby != NESP_LOBBY_HOSTING
        || !peer->hal->peer_listen(peer->hal->ctx, NESP_PEER_PORT)) {
        peer->lobby = NESP_LOBBY_FAILED;
    }
    peer->show = true;
}

static void greet(nesp_peer_t *peer, uint8_t conn, uint32_t now)
{
    uint8_t mine[GREETING];
    greeting(peer, mine);
    if (peer->greeted < GREETING) {
        size_t sent = peer->hal->peer_send(peer->hal->ctx, mine + peer->greeted,
                                           (size_t)(GREETING - peer->greeted));
        peer->greeted = (uint8_t)(peer->greeted + sent);
    }
    size_t came = peer->hal->peer_recv(peer->hal->ctx, peer->heard + peer->heard_len,
                                       (size_t)(GREETING - peer->heard_len));
    peer->heard_len = (uint8_t)(peer->heard_len + came);
    if (peer->heard_len == GREETING && peer->greeted == GREETING) {
        if (memcmp(peer->heard, mine, GREETING) != 0) {
            refuse(peer);
            return;
        }
        /* A game. The one that was called is player 1. */
        bool called = peer->lobby == NESP_LOBBY_CONNECTING;
        peer->greeting = false;
        peer->lobby = called ? NESP_LOBBY_GUEST : NESP_LOBBY_HOST;
        peer->lost = false;
        peer->local_next = 0;
        peer->remote_base = 0;
        peer->remote_len = 0;
        peer->requests = 0;
        peer->repeats = 0;
        peer->again = 0;
        peer->delay = peer->want = 0;
        peer->up = peer->down = 0;
        peer->told = 0;
        memset(peer->spread, 0, sizeof(peer->spread));
        memset(peer->since, 0, sizeof(peer->since));
        {
            uint8_t none[NESP_ARQ_NOTE] = {0};
            peer->hal->peer_note(peer->hal->ctx, none);
        }
        peer->show = true;
        if (called) {
            peer->hal->peer_keep(peer->hal->ctx, peer->target);
        }
    } else if (!up(conn) || now - peer->greeting_at >= NESP_PEER_GREET_MS) {
        refuse(peer);
    }
}

/* --- a session ------------------------------------------------------------------ */

/* Take what the other nesp32 has sent, as far as there is room for it. */
static void pump(nesp_peer_t *peer)
{
    size_t room = (size_t)(NESP_PEER_HELD - peer->remote_len);
    if (room == 0) {
        return;
    }
    size_t came = peer->hal->peer_recv(peer->hal->ctx, peer->remote + peer->remote_len, room);
    peer->remote_len = (uint8_t)(peer->remote_len + came);
    if (came == 0 && !up(peer->hal->peer_state(peer->hal->ctx))) {
        peer->lost = true;          /* and everything it brought is here */
    }
}

/* A session's exchange, however it was asked for: this console's buttons
 * for `count` ticks from `first`, and the other's from `wanted` written to
 * out, at most NESP_PEER_PER_FRAME of them. Returns how many. */
static uint8_t exchange(nesp_peer_t *peer, uint8_t first, uint8_t wanted,
                        const uint8_t *buttons, uint8_t count, uint8_t *out)
{
    if (peer->requests == 0) {
        /* The session's first: the network's times are counted from here.
         * Those from before it are of two nesp32s with little to say, a
         * packet every 50 ms, and not of a game's sixty a second. */
        peer->hal->peer_spread(peer->hal->ctx, peer->spread);
    }
    peer->requests++;
    /* Its buttons: those of them not seen before go to the other nesp32. */
    uint8_t skip = (uint8_t)(peer->local_next - first);
    size_t sent = 0;
    if (skip < count) {
        sent = peer->hal->peer_send(peer->hal->ctx, buttons + skip, (size_t)(count - skip));
        peer->local_next = (uint8_t)(peer->local_next + sent);
    }
    if (sent == 0) {
        /* With no buttons the console had none new: its game stood still
         * for want of the other's. With some, all of them held already, it
         * did not hear the last reply and is asking again. */
        peer->repeats++;
        if (count != 0) {
            peer->again++;
        }
    }
    /* The other's: the console has everything before the tick it asks for. */
    pump(peer);
    uint8_t taken = (uint8_t)(wanted - peer->remote_base);
    if (taken != 0 && taken <= peer->remote_len) {
        memmove(peer->remote, peer->remote + taken, (size_t)(peer->remote_len - taken));
        peer->remote_len = (uint8_t)(peer->remote_len - taken);
        peer->remote_base = (uint8_t)(peer->remote_base + taken);
    }
    uint8_t ready = peer->remote_len < NESP_PEER_PER_FRAME ? peer->remote_len
                                                           : NESP_PEER_PER_FRAME;
    memcpy(out, peer->remote, ready);
    return ready;
}

static void ticks(nesp_peer_t *peer, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len < 2 || request->len > 2 + NESP_PEER_PER_FRAME
        || reply->max < 3 + NESP_PEER_PER_FRAME) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t first = request->data[0];
    uint8_t wanted = request->data[1];
    uint8_t count = (uint8_t)(request->len - 2);
    reply->len = 3;
    if (!in_session(peer)) {
        /* No session: the other console is gone. */
        reply->data[0] = first;
        reply->data[1] = wanted;
        reply->data[2] = 1;
        return;
    }
    uint8_t ready = exchange(peer, first, wanted, request->data + 2, count, reply->data + 3);
    reply->data[0] = peer->local_next;
    reply->data[1] = peer->remote_base;
    reply->data[2] = peer->lost && ready == 0 ? 1 : 0;
    reply->len = (uint8_t)(3 + ready);
}

/* --- the delay ------------------------------------------------------------------- */

/* A press on one console is used some ticks after it was read, which is
 * the time it has to reach the other console. Each console keeps that delay
 * for its own buttons, and may change it as the game goes: nothing has to
 * be agreed, since the other console only ever takes the buttons it is
 * given for each tick.
 *
 * The delay is to cover the time the network takes, and a network's times
 * are not one time: most are short, and now and again one is very long. No
 * delay covers those, and one made longer for their sake would be paid in
 * every press of the game. So the advice is the delay that covers
 * NESP_PEER_COVER in a hundred of the times measured since the console's
 * last report, a couple of seconds' worth, and a press that meets one of
 * the rest waits a frame or two: the game stands still for it.
 *
 * The advice does not follow every report. It is made longer when two
 * reports running call for it, and a tick shorter when NESP_PEER_CALM do.
 * A session's first report is the exception, and sets it outright.
 *
 * A console's report also says how the other console's buttons have been
 * arriving: how many NMIs waited for them, and the fewest ticks of them it
 * held. That is passed to the other nesp32 as a note, and nothing is made
 * of it yet. */

static uint8_t clamp(uint32_t ticks)
{
    return (uint8_t)(ticks < 1 ? 1 : ticks > NESP_PEER_DELAY_MAX ? NESP_PEER_DELAY_MAX : ticks);
}

/* What to begin with, from the network's time as it is known so far: the
 * quickest it has been (conn.c). */
static uint8_t first_delay(const nesp_peer_t *peer)
{
    uint32_t rtt = peer->hal->peer_rtt(peer->hal->ctx);
    return rtt == 0 ? NESP_PEER_DELAY_UNKNOWN : clamp(nesp_arq_ticks(rtt));
}

/* A new report: the network's times since the last one, into the advice.
 * A session's first has every time since its first exchange behind it, and
 * its answer is taken at once: the delay the session began with was a
 * guess from a packet or two, or from none. */
static void advise(nesp_peer_t *peer, bool first)
{
    uint32_t counts[NESP_ARQ_NEEDS];
    uint32_t *since = peer->since;
    uint32_t all = 0;
    peer->hal->peer_spread(peer->hal->ctx, counts);
    for (int index = 0; index < NESP_ARQ_NEEDS; index++) {
        since[index] = counts[index] - peer->spread[index];
        all += since[index];
        peer->spread[index] = counts[index];
    }
    if (all < NESP_PEER_FEW || peer->want == 0) {
        return;
    }
    /* The least delay that covers enough of them. */
    uint32_t covered = 0;
    uint8_t enough = NESP_PEER_DELAY_MAX;
    for (int index = 0; index < NESP_PEER_DELAY_MAX; index++) {
        covered += since[index];
        if (covered * 100 >= all * NESP_PEER_COVER) {
            enough = (uint8_t)(index + 1);
            break;
        }
    }
    if (first) {
        peer->up = peer->down = 0;
        peer->want = enough;
    } else if (enough > peer->want) {
        peer->down = 0;
        if (++peer->up >= NESP_PEER_UP) {
            peer->up = 0;
            peer->want = enough;
        }
    } else if (enough < peer->want) {
        peer->up = 0;
        if (++peer->down >= NESP_PEER_CALM) {
            peer->down = 0;
            peer->want--;
        }
    } else {
        peer->up = peer->down = 0;
    }
}

/* A console's report: its delay in the top three bits, then how many
 * ticks were late, then the margin. Returns the delay it is advised. */
static uint8_t tune(nesp_peer_t *peer, uint8_t report)
{
    uint8_t delay = report >> 5;
    peer->delay = delay;
    if (peer->want == 0) {
        peer->want = delay != 0 ? delay : first_delay(peer);
    }
    /* A report asked again, because its reply was not heard, is the same
     * report: one is passed on a second at the most. */
    if (delay != 0 && (peer->told == 0 || peer->now - peer->told_at >= 1000)) {
        uint8_t note[NESP_ARQ_NOTE];
        /* A session's first report is of its start, when one console
         * waits for the other to begin: nothing is made of it. */
        bool first = peer->told == 0;
        peer->told = (uint8_t)(peer->told == 0xFF ? 1 : peer->told + 1);
        peer->told_at = peer->now;
        note[0] = peer->told;
        note[1] = first ? 0 : (report >> 2) & 7;
        note[2] = first ? 1 : report & 3;
        note[3] = delay;
        peer->hal->peer_note(peer->hal->ctx, note);
        advise(peer, first);
    }
    return peer->want;
}

/* TICKS as a short frame. The two ticks are named by their low four bits,
 * in one byte, and then come the buttons: one tick's, or two with a count
 * of 2. A count of NESP_PEER_TUNE is one tick's and then the console's
 * report (the delay, above).
 *
 * The reply is one tick of the other console's buttons, if its count is 1,
 * and to a report the delay advised besides; NESP_SHORT_NONE is TICKS'
 * `LOST`. It names no ticks: that it comes at all says the nesp32 holds
 * the buttons it was sent, and its CRC says which request it answers. So
 * there is none when not all of them could be taken, and the console asks
 * again. */
static int quick(void *ctx, uint8_t count, const uint8_t *in, uint8_t *reply_count, uint8_t *out)
{
    nesp_peer_t *peer = ctx;
    uint8_t held[NESP_PEER_PER_FRAME];
    bool tuning = count == NESP_PEER_TUNE;
    uint8_t sent = tuning ? 1 : count;
    out[0] = 0;
    if (!in_session(peer)) {
        *reply_count = NESP_SHORT_NONE;
        return 1;
    }
    /* The console is never more than a few ticks from what is held here. */
    uint8_t first = (uint8_t)(peer->local_next - ((peer->local_next - (in[0] >> 4)) & 0x0F));
    uint8_t wanted = (uint8_t)(peer->remote_base + (((in[0] & 0x0F) - peer->remote_base) & 0x0F));
    uint8_t ready = exchange(peer, first, wanted, in + 1, sent, held);
    /* Not all of its buttons taken: no reply, unless that is because the
     * other console is gone, which the reply is there to say. */
    if ((uint8_t)(peer->local_next - first) < sent
        && up(peer->hal->peer_state(peer->hal->ctx))) {
        return -1;
    }
    if (ready != 0) {
        out[0] = held[0];
    }
    *reply_count = peer->lost && ready == 0 ? NESP_SHORT_NONE : (ready != 0 ? 1 : 0);
    if (tuning) {
        out[1] = tune(peer, in[2]);
        return 2;
    }
    return 1;
}

/* --- the lobby ------------------------------------------------------------------ */

static void lobby(nesp_peer_t *peer, const nesp_request_t *request, nesp_reply_t *reply)
{
    uint8_t address[4];
    bool on = online(peer, address);
    if (request->len != (request->op == NESP_PEER_JOIN ? 4 : 0)) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (!on && peer->lobby != NESP_LOBBY_IDLE) {
        drop(peer);                 /* the network went, and the connection with it */
    }
    switch (request->op) {
    case NESP_PEER_HOST:
        if (on && peer->lobby != NESP_LOBBY_HOSTING
            && !(peer->lobby == NESP_LOBBY_HOST && !peer->lost)) {
            drop(peer);
            peer->lobby = peer->hal->peer_listen(peer->hal->ctx, NESP_PEER_PORT)
                              ? NESP_LOBBY_HOSTING : NESP_LOBBY_FAILED;
        }
        break;
    case NESP_PEER_JOIN: {
        bool joining = peer->lobby == NESP_LOBBY_CONNECTING
                       || (peer->lobby == NESP_LOBBY_GUEST && !peer->lost);
        if (on && !(joining && memcmp(peer->target, request->data, 4) == 0)) {
            drop(peer);
            memcpy(peer->target, request->data, 4);
            peer->lobby = peer->hal->peer_call(peer->hal->ctx, peer->target, NESP_PEER_PORT)
                              ? NESP_LOBBY_CONNECTING : NESP_LOBBY_FAILED;
        }
        break;
    }
    case NESP_PEER_LEAVE:
        drop(peer);
        break;
    case NESP_PEER_LAST:
        if (!peer->hal->peer_last(peer->hal->ctx, address)) {
            memset(address, 0, sizeof(address));
        }
        break;
    default:                        /* NESP_PEER_STATUS */
        break;
    }
    uint8_t state = peer->lobby;
    if (!on) {
        state = NESP_LOBBY_NO_WIFI;
    } else if (in_session(peer) && peer->lost) {
        state = NESP_LOBBY_FAILED;
    }
    reply->data[0] = state;
    memcpy(reply->data + 1, address, 4);
    /* And for a console about to start a session, the delay to begin with. */
    reply->data[5] = in_session(peer) && !peer->lost ? first_delay(peer) : 0;
    reply->len = 6;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_peer_t *peer = ctx;
    reply->once = true;             /* the same request again is a new question */
    switch (request->op) {
    case NESP_PEER_STATUS:
    case NESP_PEER_HOST:
    case NESP_PEER_JOIN:
    case NESP_PEER_LEAVE:
    case NESP_PEER_LAST:
        lobby(peer, request, reply);
        break;
    case NESP_PEER_TICKS:
        ticks(peer, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* --- the clock, and the nesp32's screen ----------------------------------------- */

static void show(nesp_peer_t *peer, uint32_t now)
{
    if (!peer->show && now - peer->shown_at < SHOW_MS) {
        return;
    }
    peer->show = false;
    peer->shown_at = now;
    if (peer->hal->show == NULL) {
        return;
    }
    char text[2][48] = {"", ""};
    uint8_t address[4];
    switch (peer->lobby) {
    case NESP_LOBBY_HOSTING:
        /* Player 2 has this to enter: where the screen has the address
         * when there is no game. */
        online(peer, address);
        snprintf(text[0], sizeof(text[0]), "%u.%u.%u.%u", address[0], address[1],
                 address[2], address[3]);
        snprintf(text[1], sizeof(text[1]), "Waiting for player 2");
        break;
    case NESP_LOBBY_CONNECTING:
        snprintf(text[0], sizeof(text[0]), "%u.%u.%u.%u", peer->target[0], peer->target[1],
                 peer->target[2], peer->target[3]);
        snprintf(text[1], sizeof(text[1]), "Joining the game");
        break;
    case NESP_LOBBY_HOST:
    case NESP_LOBBY_GUEST:
        snprintf(text[0], sizeof(text[0]), "Player %d%s",
                 peer->lobby == NESP_LOBBY_HOST ? 1 : 2,
                 peer->lost ? ": peer disconnected" : "");
        /* Of the session's exchanges, those that brought nothing new: in
         * tenths of a percent. */
        uint32_t tenths = peer->requests == 0 ? 0
            : (uint32_t)(((uint64_t)peer->repeats * 1000u + peer->requests / 2u) / peer->requests);
        snprintf(text[1], sizeof(text[1]), "late frames: %lu.%lu%%",
                 (unsigned long)(tenths / 10u), (unsigned long)(tenths % 10u));
        break;
    case NESP_LOBBY_FAILED:
        snprintf(text[0], sizeof(text[0]), "No game was joined");
        break;
    default:
        break;
    }
    peer->hal->show(peer->hal->ctx, 0, text[0]);
    peer->hal->show(peer->hal->ctx, 1, text[1]);
}

/* For the log, every couple of seconds of a session: the delay and the
 * advice, the requests with those that waited for the other console's
 * buttons (late) and those that sent buttons already held, a reply not
 * having been heard (again), and the network's times behind the last
 * advice, by the delay each would take. */
static void watch(nesp_peer_t *peer, uint32_t now)
{
    char text[160];
    if (peer->hal->watch == NULL || !in_session(peer) || now - peer->watched_at < WATCH_MS) {
        return;
    }
    peer->watched_at = now;
    snprintf(text, sizeof(text),
             "player %d, delay %u, advised %u (%u for longer, %u for shorter); %lu frames, "
             "%lu late, %lu again; network needs 1:%lu 2:%lu 3:%lu 4:%lu 5:%lu more:%lu",
             peer->lobby == NESP_LOBBY_HOST ? 1 : 2, (unsigned)peer->delay, (unsigned)peer->want,
             (unsigned)peer->up, (unsigned)peer->down, (unsigned long)peer->requests,
             (unsigned long)(peer->repeats - peer->again), (unsigned long)peer->again,
             (unsigned long)peer->since[0], (unsigned long)peer->since[1],
             (unsigned long)peer->since[2], (unsigned long)peer->since[3],
             (unsigned long)peer->since[4], (unsigned long)peer->since[5]);
    peer->hal->watch(peer->hal->ctx, text);
}

static bool tick(void *ctx, uint32_t now)
{
    nesp_peer_t *peer = ctx;
    peer->now = now;
    watch(peer, now);
    uint8_t conn = peer->hal->peer_state(peer->hal->ctx);
    switch (peer->lobby) {
    case NESP_LOBBY_HOSTING:
    case NESP_LOBBY_CONNECTING:
        if (!peer->greeting && up(conn)) {
            peer->greeting = true;
            peer->greeting_at = now;
            peer->greeted = 0;
            peer->heard_len = 0;
        }
        if (peer->greeting) {
            greet(peer, conn, now);
        } else if (conn != NESP_CONN_LISTENING && conn != NESP_CONN_CALLING) {
            /* Nobody answered the call, or the wait for one broke. */
            peer->hal->peer_close(peer->hal->ctx);
            peer->lobby = NESP_LOBBY_FAILED;
            peer->show = true;
        }
        break;
    case NESP_LOBBY_HOST:
    case NESP_LOBBY_GUEST:
        if (!peer->lost) {
            pump(peer);
            if (peer->lost) {
                peer->show = true;
            }
        }
        break;
    default:
        break;
    }
    show(peer, now);
    return peer->greeting;          /* the greetings are a few bytes and soon over */
}

static void reset(nesp_peer_t *peer)
{
    const nesp_hal_t *hal = peer->hal;
    const nesp_sys_t *sys = peer->sys;
    memset(peer, 0, sizeof(*peer));
    peer->hal = hal;
    peer->sys = sys;
    peer->lobby = NESP_LOBBY_IDLE;
}

static void activate(void *ctx)
{
    nesp_peer_t *peer = ctx;
    reset(peer);
    peer->show = true;
}

/* Another ROM is on the console, or this one was reset: it is in no game. */
static void deactivate(void *ctx)
{
    nesp_peer_t *peer = ctx;
    peer->hal->peer_close(peer->hal->ctx);
    reset(peer);
    if (peer->hal->show != NULL) {
        peer->hal->show(peer->hal->ctx, 0, "");
        peer->hal->show(peer->hal->ctx, 1, "");
    }
}

void nesp_peer_service(nesp_service_t *service, nesp_peer_t *peer, const nesp_sys_t *sys,
                       const nesp_hal_t *hal)
{
    memset(peer, 0, sizeof(*peer));
    peer->hal = hal;
    peer->sys = sys;
    peer->lobby = NESP_LOBBY_IDLE;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_PEER;
    service->name = "PEER";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->quick = quick;
    service->ctx = peer;
}

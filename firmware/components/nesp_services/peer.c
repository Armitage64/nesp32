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
#define SHOW_MS 500

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
    peer->requests++;
    /* Its buttons: those of them not seen before go to the other nesp32. */
    uint8_t skip = (uint8_t)(peer->local_next - first);
    size_t sent = 0;
    if (skip < count) {
        sent = peer->hal->peer_send(peer->hal->ctx, request->data + 2 + skip,
                                    (size_t)(count - skip));
        peer->local_next = (uint8_t)(peer->local_next + sent);
    }
    if (sent == 0) {
        peer->repeats++;
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
    reply->data[0] = peer->local_next;
    reply->data[1] = peer->remote_base;
    reply->data[2] = peer->lost && ready == 0 ? 1 : 0;
    memcpy(reply->data + 3, peer->remote, ready);
    reply->len = (uint8_t)(3 + ready);
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
    reply->len = 5;
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
        /* Player 2 has this to enter. */
        online(peer, address);
        snprintf(text[0], sizeof(text[0]), "Waiting for player 2");
        snprintf(text[1], sizeof(text[1]), "at %u.%u.%u.%u", address[0], address[1],
                 address[2], address[3]);
        break;
    case NESP_LOBBY_CONNECTING:
        snprintf(text[0], sizeof(text[0]), "Joining the game");
        snprintf(text[1], sizeof(text[1]), "at %u.%u.%u.%u", peer->target[0], peer->target[1],
                 peer->target[2], peer->target[3]);
        break;
    case NESP_LOBBY_HOST:
    case NESP_LOBBY_GUEST:
        snprintf(text[0], sizeof(text[0]), "Player %d%s",
                 peer->lobby == NESP_LOBBY_HOST ? 1 : 2,
                 peer->lost ? ": the other is gone" : "");
        snprintf(text[1], sizeof(text[1]), "%lu frames, %lu waiting",
                 (unsigned long)peer->requests, (unsigned long)peer->repeats);
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

static bool tick(void *ctx, uint32_t now)
{
    nesp_peer_t *peer = ctx;
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
    service->ctx = peer;
}

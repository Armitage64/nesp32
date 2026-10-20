/* One connection to another nesp32: PEER's, for two consoles playing one
 * game (docs/PROTOCOL.md).
 *
 * A service asks from the link's task, which may not wait. So every call
 * here only leaves an order, or bytes, where this file's task finds them,
 * and takes what the task has left: the state of the connection and the
 * bytes that have come. The task has the socket to itself. It waits for a
 * caller or makes the call, and then carries bytes both ways until the
 * connection goes or another order takes its place.
 *
 * What crosses is small and wants to be there soon: a byte for each frame
 * of a game. It goes as datagrams, each of which repeats whatever the other
 * end has not said it has (the services' arq.c): a packet that is lost
 * holds nothing up, where a TCP connection stops until it has sent it
 * again. The task is woken by every byte to send, and looks for what has
 * come once a tick of the scheduler, a millisecond.
 *
 * A call is a datagram that names the connection, sent until it is
 * answered. The one that waits answers whoever calls first, and from then
 * on takes only that connection's packets. Each end gives the other up
 * when it has heard nothing of it for a few seconds, or is told goodbye.
 *
 * Whichever end it is, the socket also asks two STUN servers on the
 * Internet what address and port its datagrams come from, as the world
 * outside the router sees them, and the one that waits asks again every
 * little while, which also keeps the router's way in open. For now that is
 * written to the log, and it is what a meeting across the Internet is made
 * from, with no port forwarded (issue #12): the socket is opened first,
 * its addresses found and handed to PEER for the rendezvous, and then, on
 * the same socket, both ends send to each other's addresses at once. Each
 * one's datagrams open its own router to the other's, so that the call
 * gets in, or the answer does. The one that waits sends punches, which
 * carry nothing, and answers only the session the rendezvous named.
 *
 * An order is numbered. The task does nothing for an order that has been
 * replaced, and says nothing of it either: the state is then whatever the
 * newer order made it.
 */
#include "conn.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>

#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/dns.h"
#include "lwip/sockets.h"
#include "lwip/tcpip.h"
#include "nvs.h"

#define CONN_STACK 6144
#define CONN_PRIORITY 6             /* above the fetch: a game's buttons are waited for */
#define CONN_CORE 0                 /* with Wi-Fi; the link has core 1 */
#define RING 256                    /* bytes held each way */
#define LOOK_MS 50                  /* how often a wait looks for a newer order */
#define CALL_MS 3000                /* how long a call is given to be answered */
#define CALL_EVERY_MS 100           /* between two sendings of it */
#define GONE_US 3000000             /* nothing heard for this long: the other end is gone */
#define STUN_AGAIN_US 500000        /* a STUN request unanswered for this long goes again */
#define STUN_TRIES 3
#define STUN_KEEP_US 20000000       /* the one that waits asks again this often */
#define DATAGRAM 160                /* room for what comes: a STUN answer is longer than ours */
#define STUN_WAIT_US 1500000        /* addresses found as far as they will be, by then */
/* A meeting's call, and the wait for it, are longer than a call's: the
 * host hears of player 2 only when it next asks the rendezvous. */
#define MEET_CALL_MS 8000
/* What a game's packets say of themselves to the network when the other
 * nesp32 is on this one: class selector 6, which Wi-Fi sends as voice. That
 * class waits least for the air, on this radio and on an access point that
 * keeps to it. Across the Internet they say nothing: the class is meant for
 * what runs a network, and a network between the two may drop what claims
 * it. */
#define URGENT 0xC0
#define SETTINGS "nesp32"
#define SETTING_LAST "peer_last"

static const char *TAG = "conn";

typedef enum { WANT_NONE, WANT_LISTEN, WANT_CALL, WANT_MEET } want_t;

/* Where to send a call, or punches, and the session it is for. */
typedef struct {
    struct sockaddr_in to[NESP_PEER_CANDIDATES];
    uint8_t count;
    uint32_t session;               /* 0: any, for the one that waits */
    int ms;                         /* how long it is kept up; 0 for as long as it is wanted */
} targets_t;

typedef struct {
    uint8_t data[RING];
    size_t at;
    size_t len;
} ring_t;

static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
/* Under lock. */
static want_t want;
static uint16_t want_port;
static uint8_t want_address[4];
static uint32_t serial;             /* counts orders */
static uint8_t state = NESP_CONN_NONE;
static ring_t coming;
static ring_t going;
static bool have_last;
static uint8_t last[4];
static bool save;
static uint32_t rtt;                /* the network's time there and back, at its quickest */
static uint8_t note_out[NESP_ARQ_NOTE];
static uint8_t note_in[NESP_ARQ_NOTE];
static uint32_t spread[NESP_ARQ_NEEDS];
static conn_ping_t pings;           /* the network's times, for whoever watches the log */
static nesp_peer_candidate_t candidates[NESP_PEER_CANDIDATES];   /* a meeting socket's */
static uint8_t candidate_count;
static bool punch_given;            /* the meeting's order to punch, not yet taken by the task */
static bool punch_listen;
static targets_t punch_targets;
static TaskHandle_t task;

/* The STUN servers. Each one's address is looked up for every order, from
 * lwIP's own task, so that the conn task never waits on the DNS: on a
 * network with no way to the Internet it would wait seconds for nothing,
 * with a caller unanswered. */
typedef struct {
    const char *name;
    uint16_t port;
    uint32_t address;               /* under lock: as on the network; 0 until found */
    uint8_t id[NESP_STUN_ID];       /* the request out now */
    uint8_t tries;
    int64_t sent_at;
    bool answered;
    uint8_t mapped[4];
    uint16_t mapped_port;
} stun_server_t;

static stun_server_t stun_servers[] = {
    {.name = "stun.cloudflare.com", .port = 3478},
    {.name = "stun.l.google.com", .port = 19302},
};
#define STUN_SERVERS (sizeof(stun_servers) / sizeof(stun_servers[0]))
/* --- what the services call: no waiting ---------------------------------------- */

static bool order(want_t what, uint8_t now, const uint8_t *address, uint16_t port)
{
    if (task == NULL) {
        return false;
    }
    portENTER_CRITICAL(&lock);
    want = what;
    want_port = port;
    if (address != NULL) {
        memcpy(want_address, address, sizeof(want_address));
    }
    serial++;
    state = now;
    coming.len = going.len = 0;
    rtt = 0;
    memset(spread, 0, sizeof(spread));
    memset(&pings, 0, sizeof(pings));
    memset(note_out, 0, sizeof(note_out));
    memset(note_in, 0, sizeof(note_in));
    candidate_count = 0;
    punch_given = false;
    portEXIT_CRITICAL(&lock);
    xTaskNotifyGive(task);
    return true;
}

uint8_t conn_state(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    uint8_t now = state;
    portEXIT_CRITICAL(&lock);
    return now;
}

bool conn_listen(void *ctx, uint16_t port)
{
    (void)ctx;
    return order(WANT_LISTEN, NESP_CONN_LISTENING, NULL, port);
}

bool conn_call(void *ctx, const uint8_t *address, uint16_t port)
{
    (void)ctx;
    return order(WANT_CALL, NESP_CONN_CALLING, address, port);
}

bool conn_meet(void *ctx, uint16_t port)
{
    (void)ctx;
    return order(WANT_MEET, NESP_CONN_MEETING, NULL, port);
}

uint8_t conn_candidates(void *ctx, nesp_peer_candidate_t *out)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    uint8_t count = candidate_count;
    memcpy(out, candidates, sizeof(candidates[0]) * count);
    portEXIT_CRITICAL(&lock);
    return count;
}

bool conn_punch(void *ctx, bool listen, uint32_t session, const nesp_peer_candidate_t *other,
                uint8_t count)
{
    (void)ctx;
    targets_t targets;
    memset(&targets, 0, sizeof(targets));
    for (uint8_t index = 0; index < count && index < NESP_PEER_CANDIDATES; index++) {
        struct sockaddr_in *to = &targets.to[targets.count++];
        to->sin_family = AF_INET;
        to->sin_port = htons(other[index].port);
        memcpy(&to->sin_addr.s_addr, other[index].address, 4);
    }
    targets.session = session;
    targets.ms = MEET_CALL_MS;
    portENTER_CRITICAL(&lock);
    bool met = want == WANT_MEET && (state == NESP_CONN_MEETING || state == NESP_CONN_MET);
    if (met) {
        punch_given = true;
        punch_listen = listen;
        punch_targets = targets;
        state = listen ? NESP_CONN_LISTENING : NESP_CONN_CALLING;
    }
    portEXIT_CRITICAL(&lock);
    if (met) {
        xTaskNotifyGive(task);
    }
    return met;
}

void conn_close(void *ctx)
{
    (void)ctx;
    order(WANT_NONE, NESP_CONN_NONE, NULL, 0);
}

size_t conn_send(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    size_t taken = 0;
    portENTER_CRITICAL(&lock);
    if (state == NESP_CONN_ANSWERED || state == NESP_CONN_CALLED) {
        while (taken < len && going.len < RING) {
            going.data[(going.at + going.len) % RING] = data[taken++];
            going.len++;
        }
    }
    portEXIT_CRITICAL(&lock);
    if (taken != 0) {
        xTaskNotifyGive(task);
    }
    return taken;
}

size_t conn_recv(void *ctx, uint8_t *out, size_t max)
{
    (void)ctx;
    size_t count = 0;
    portENTER_CRITICAL(&lock);
    while (count < max && coming.len != 0) {
        out[count++] = coming.data[coming.at];
        coming.at = (coming.at + 1) % RING;
        coming.len--;
    }
    portEXIT_CRITICAL(&lock);
    return count;
}

bool conn_last(void *ctx, uint8_t *address)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    bool have = have_last;
    if (have) {
        memcpy(address, last, sizeof(last));
    }
    portEXIT_CRITICAL(&lock);
    return have;
}

void conn_keep(void *ctx, const uint8_t *address)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    bool news = !have_last || memcmp(last, address, sizeof(last)) != 0;
    if (news) {
        memcpy(last, address, sizeof(last));
        have_last = true;
        save = true;                /* the flash is the task's to write */
    }
    portEXIT_CRITICAL(&lock);
    if (news && task != NULL) {
        xTaskNotifyGive(task);
    }
}

uint32_t conn_rtt(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    uint32_t now = rtt;
    portEXIT_CRITICAL(&lock);
    return now;
}

void conn_note(void *ctx, const uint8_t *note)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    memcpy(note_out, note, sizeof(note_out));
    portEXIT_CRITICAL(&lock);
}

void conn_noted(void *ctx, uint8_t *note)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    memcpy(note, note_in, sizeof(note_in));
    portEXIT_CRITICAL(&lock);
}

void conn_spread(void *ctx, uint32_t *counts)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    memcpy(counts, spread, sizeof(spread));
    portEXIT_CRITICAL(&lock);
}

void conn_ping(conn_ping_t *out)
{
    portENTER_CRITICAL(&lock);
    *out = pings;
    portEXIT_CRITICAL(&lock);
}

/* --- the task ------------------------------------------------------------------- */

/* Is the order that began at this count still the one wanted? */
static bool wanted(uint32_t began)
{
    portENTER_CRITICAL(&lock);
    bool same = serial == began;
    portEXIT_CRITICAL(&lock);
    return same;
}

/* How the order's connection stands now, unless the order was replaced. */
static bool say(uint32_t began, uint8_t now)
{
    portENTER_CRITICAL(&lock);
    bool same = serial == began;
    if (same) {
        state = now;
    }
    portEXIT_CRITICAL(&lock);
    return same;
}

static void save_last(void)
{
    uint8_t address[4];
    portENTER_CRITICAL(&lock);
    bool asked = save;
    save = false;
    memcpy(address, last, sizeof(address));
    portEXIT_CRITICAL(&lock);
    if (!asked) {
        return;
    }
    nvs_handle_t settings;
    if (nvs_open(SETTINGS, NVS_READWRITE, &settings) == ESP_OK) {
        nvs_set_blob(settings, SETTING_LAST, address, sizeof(address));
        nvs_commit(settings);
        nvs_close(settings);
    }
}

static uint32_t clock_us(void)
{
    return (uint32_t)esp_timer_get_time();
}

/* A socket for datagrams, on a port of its own choosing if that is 0.
 * -1 if there cannot be one. */
static int open_socket(uint16_t port)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        return -1;
    }
    struct sockaddr_in here;
    memset(&here, 0, sizeof(here));
    here.sin_family = AF_INET;
    here.sin_addr.s_addr = htonl(INADDR_ANY);
    here.sin_port = htons(port);
    if (bind(sock, (struct sockaddr *)&here, sizeof(here)) != 0) {
        ESP_LOGW(TAG, "cannot take port %u: %d", (unsigned)port, errno);
        close(sock);
        return -1;
    }
    fcntl(sock, F_SETFL, fcntl(sock, F_GETFL, 0) | O_NONBLOCK);
    return sock;
}

/* The port a socket has, as this nesp32 sees it. */
static uint16_t socket_port(int sock)
{
    struct sockaddr_in here;
    socklen_t size = sizeof(here);
    if (getsockname(sock, (struct sockaddr *)&here, &size) != 0) {
        return 0;
    }
    return ntohs(here.sin_port);
}

/* Mark the socket's packets urgent if the other end is on this nesp32's
 * own network, and not at all if it is not, or if that cannot be told. */
static void mark(int sock, const struct sockaddr_in *other)
{
    esp_netif_ip_info_t here;
    esp_netif_t *wifi = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    bool near = wifi != NULL && esp_netif_get_ip_info(wifi, &here) == ESP_OK
                && here.netmask.addr != 0
                && ((other->sin_addr.s_addr ^ here.ip.addr) & here.netmask.addr) == 0;
    int class = near ? URGENT : 0;
    setsockopt(sock, IPPROTO_IP, IP_TOS, &class, sizeof(class));
    ESP_LOGI(TAG, "the other end is %s, %s this network", inet_ntoa(other->sin_addr),
             near ? "on" : "not on");
}

/* --- what the Internet sees of this socket ---------------------------------- */

static void stun_found(const char *name, const ip_addr_t *address, void *arg)
{
    (void)name;
    stun_server_t *server = arg;
    if (address != NULL) {
        portENTER_CRITICAL(&lock);
        server->address = ip4_addr_get_u32(ip_2_ip4(address));
        portEXIT_CRITICAL(&lock);
    }
}

/* In lwIP's task: look a server up, or take what lwIP already knows. */
static void stun_look_up(void *arg)
{
    stun_server_t *server = arg;
    ip_addr_t address;
    if (dns_gethostbyname(server->name, &address, stun_found, server) == ERR_OK) {
        stun_found(server->name, &address, server);
    }
}

/* Ask afresh: from a socket just opened (fresh), whose addresses are not
 * the last socket's, or as the one that waits keeps its way in open. */
static void stun_begin(bool fresh)
{
    for (size_t index = 0; index < STUN_SERVERS; index++) {
        stun_server_t *server = &stun_servers[index];
        esp_fill_random(server->id, sizeof(server->id));
        server->tries = 0;
        server->answered = false;
        if (fresh) {
            memset(server->mapped, 0, sizeof(server->mapped));
            server->mapped_port = 0;
        }
        portENTER_CRITICAL(&lock);
        server->address = 0;
        portEXIT_CRITICAL(&lock);
        tcpip_callback(stun_look_up, server);
    }
}

/* Send what is due: to each server as soon as its address is known, and
 * again while it does not answer. */
static void stun_send(int sock)
{
    int64_t now = esp_timer_get_time();
    for (size_t index = 0; index < STUN_SERVERS; index++) {
        stun_server_t *server = &stun_servers[index];
        portENTER_CRITICAL(&lock);
        uint32_t address = server->address;
        portEXIT_CRITICAL(&lock);
        if (address == 0 || server->answered || server->tries >= STUN_TRIES
            || (server->tries != 0 && now - server->sent_at < STUN_AGAIN_US)) {
            continue;
        }
        struct sockaddr_in to;
        memset(&to, 0, sizeof(to));
        to.sin_family = AF_INET;
        to.sin_port = htons(server->port);
        to.sin_addr.s_addr = address;
        uint8_t request[NESP_STUN_REQUEST];
        size_t length = nesp_stun_request(server->id, request);
        sendto(sock, request, length, 0, (const struct sockaddr *)&to, sizeof(to));
        server->tries++;
        server->sent_at = now;
    }
}

/* The meeting socket's addresses, for PEER: its own on this network, and
 * then each the servers have seen it as that is not that one. */
static void publish(uint16_t port)
{
    nesp_peer_candidate_t found[NESP_PEER_CANDIDATES];
    uint8_t count = 0;
    esp_netif_ip_info_t here;
    esp_netif_t *wifi = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (wifi != NULL && esp_netif_get_ip_info(wifi, &here) == ESP_OK && here.ip.addr != 0) {
        memcpy(found[count].address, &here.ip.addr, 4);
        found[count++].port = port;
    }
    for (size_t index = 0; index < STUN_SERVERS && count < NESP_PEER_CANDIDATES; index++) {
        const stun_server_t *server = &stun_servers[index];
        bool known = server->mapped_port != 0;
        for (uint8_t each = 0; known && each < count; each++) {
            known = memcmp(found[each].address, server->mapped, 4) != 0
                    || found[each].port != server->mapped_port;
        }
        if (known) {
            memcpy(found[count].address, server->mapped, 4);
            found[count++].port = server->mapped_port;
        }
    }
    portENTER_CRITICAL(&lock);
    memcpy(candidates, found, sizeof(found[0]) * count);
    candidate_count = count;
    portEXIT_CRITICAL(&lock);
}

/* What the servers' answers say, when both have answered: whether this
 * socket keeps one port outside whoever it sends to, which is what lets
 * the other end's datagrams in once this end has sent to it. */
static void stun_judge(uint16_t port)
{
    const stun_server_t *one = &stun_servers[0];
    const stun_server_t *other = &stun_servers[1];
    esp_netif_ip_info_t here;
    esp_netif_t *wifi = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    bool own = wifi != NULL && esp_netif_get_ip_info(wifi, &here) == ESP_OK
               && memcmp(&here.ip.addr, one->mapped, 4) == 0;
    if (own) {
        ESP_LOGI(TAG, "stun: no router between this nesp32 and the Internet");
    } else if (memcmp(one->mapped, other->mapped, 4) != 0 || one->mapped_port != other->mapped_port) {
        ESP_LOGI(TAG, "stun: the router gives this socket a port for each destination "
                      "(%u and %u): the other end's datagrams cannot be let in by sending to it",
                 (unsigned)one->mapped_port, (unsigned)other->mapped_port);
    } else {
        ESP_LOGI(TAG, "stun: the router keeps port %u for every destination%s",
                 (unsigned)one->mapped_port, one->mapped_port == port ? ", the socket's own" : "");
    }
}

/* A datagram that came: is it a server's answer? Logged if so, and only
 * if it says something new. */
static bool stun_took(const uint8_t *packet, int came, uint16_t port)
{
    if (came <= 0) {
        return false;
    }
    for (size_t index = 0; index < STUN_SERVERS; index++) {
        stun_server_t *server = &stun_servers[index];
        uint8_t mapped[4];
        uint16_t mapped_port;
        if (server->answered
            || !nesp_stun_mapped(packet, (size_t)came, server->id, mapped, &mapped_port)) {
            continue;
        }
        server->answered = true;
        bool news = memcmp(server->mapped, mapped, 4) != 0 || server->mapped_port != mapped_port;
        memcpy(server->mapped, mapped, 4);
        server->mapped_port = mapped_port;
        if (news) {
            ESP_LOGI(TAG, "stun: %s sees this socket as %u.%u.%u.%u, port %u", server->name,
                     mapped[0], mapped[1], mapped[2], mapped[3], (unsigned)mapped_port);
            publish(port);
        }
        bool all = true;
        for (size_t each = 0; each < STUN_SERVERS; each++) {
            all = all && stun_servers[each].answered;
        }
        if (all && news) {
            stun_judge(port);
        }
        return true;
    }
    return false;
}

/* --- waiting and calling ------------------------------------------------------- */

/* Wait until something has come, for LOOK_MS at the most. */
static bool readable(int sock)
{
    fd_set set;
    struct timeval wait = {.tv_sec = 0, .tv_usec = LOOK_MS * 1000};
    FD_ZERO(&set);
    FD_SET(sock, &set);
    return select(sock + 1, &set, NULL, NULL, &wait) > 0;
}

/* Has every server answered? */
static bool stun_done(void)
{
    bool all = true;
    for (size_t index = 0; index < STUN_SERVERS; index++) {
        all = all && stun_servers[index].answered;
    }
    return all;
}

static void send_punches(int sock, const targets_t *targets)
{
    uint8_t packet[NESP_ARQ_HEADER];
    size_t length = nesp_arq_punch(packet);
    for (uint8_t index = 0; index < targets->count; index++) {
        sendto(sock, packet, length, 0, (const struct sockaddr *)&targets->to[index],
               sizeof(targets->to[index]));
    }
}

/* Wait for a caller: the first datagram that is a call names the
 * connection, and where it came from is the other end. With punches, the
 * one call taken is the session's, and the wait is as long as they say. */
static bool listen_for(uint32_t began, int sock, uint16_t port, nesp_arq_t *arq,
                       struct sockaddr_in *other, const targets_t *punches)
{
    uint8_t packet[DATAGRAM];
    int64_t asked_at = esp_timer_get_time();
    int64_t began_at = asked_at;
    int64_t punched_at = 0;
    while (wanted(began)) {
        int64_t now = esp_timer_get_time();
        if (punches != NULL && punches->ms != 0 && now - began_at >= punches->ms * 1000LL) {
            return false;
        }
        if (punches != NULL && now - punched_at >= CALL_EVERY_MS * 1000) {
            punched_at = now;
            send_punches(sock, punches);
        }
        if (now - asked_at >= STUN_KEEP_US) {
            asked_at = now;
            stun_begin(false);
        }
        stun_send(sock);
        if (!readable(sock)) {
            continue;
        }
        socklen_t size = sizeof(*other);
        int came = recvfrom(sock, packet, sizeof(packet), 0, (struct sockaddr *)other, &size);
        if (stun_took(packet, came, port)) {
            continue;
        }
        if (came < NESP_ARQ_HEADER || packet[0] != 'N' || packet[1] != 'E'
            || (packet[2] & 0x7F) != NESP_ARQ_CALL) {
            continue;
        }
        uint32_t session;
        memcpy(&session, packet + 4, sizeof(session));      /* low byte first, as here */
        if (punches != NULL && punches->session != 0 && session != punches->session) {
            continue;
        }
        nesp_arq_open(arq, session);
        if (nesp_arq_take(arq, clock_us(), packet, (size_t)came) == NESP_ARQ_CALL) {
            return true;
        }
    }
    return false;
}

/* Call every address at once until one answers, or for as long as the
 * targets say. Where the answer came from is the other end. */
static bool call(uint32_t began, int sock, uint16_t port, nesp_arq_t *arq,
                 const targets_t *targets, struct sockaddr_in *other)
{
    uint8_t packet[DATAGRAM];
    nesp_arq_open(arq, targets->session);
    for (uint8_t index = 0; index < targets->count; index++) {
        ESP_LOGI(TAG, "calling %s, port %u", inet_ntoa(targets->to[index].sin_addr),
                 (unsigned)ntohs(targets->to[index].sin_port));
    }
    for (int waited = 0; waited < targets->ms && wanted(began); waited += CALL_EVERY_MS) {
        stun_send(sock);
        size_t length = nesp_arq_packet(arq, NESP_ARQ_CALL, clock_us(), packet);
        for (uint8_t index = 0; index < targets->count; index++) {
            if (sendto(sock, packet, length, 0, (const struct sockaddr *)&targets->to[index],
                       sizeof(targets->to[index])) < 0
                && waited == 0) {
                ESP_LOGW(TAG, "the call could not be sent: %d", errno);
            }
        }
        int64_t until = esp_timer_get_time() + CALL_EVERY_MS * 1000;
        while (esp_timer_get_time() < until) {
            struct sockaddr_in from;
            socklen_t size = sizeof(from);
            int came = recvfrom(sock, packet, sizeof(packet), 0, (struct sockaddr *)&from, &size);
            if (came <= 0) {
                vTaskDelay(1);
                continue;
            }
            if (stun_took(packet, came, port)) {
                continue;
            }
            if (nesp_arq_take(arq, clock_us(), packet, (size_t)came) == NESP_ARQ_ANSWER) {
                *other = from;
                return true;
            }
        }
    }
    return false;
}

/* A meeting: find the socket's addresses, keep its way in open, and wait
 * for PEER to say whom to punch to. True with the order in hand, false if
 * it was replaced. */
static bool meet_wait(uint32_t began, int sock, uint16_t port, bool *listen, targets_t *targets)
{
    uint8_t packet[DATAGRAM];
    int64_t opened = esp_timer_get_time();
    int64_t asked_at = opened;
    bool met = false;
    publish(port);                  /* its own address, before any server has answered */
    while (wanted(began)) {
        portENTER_CRITICAL(&lock);
        bool given = punch_given;
        if (given) {
            punch_given = false;
            *listen = punch_listen;
            *targets = punch_targets;
        }
        portEXIT_CRITICAL(&lock);
        if (given) {
            return true;
        }
        int64_t now = esp_timer_get_time();
        if (!met && (stun_done() || now - opened >= STUN_WAIT_US)) {
            met = true;
            portENTER_CRITICAL(&lock);
            if (serial == began && state == NESP_CONN_MEETING) {
                state = NESP_CONN_MET;
            }
            portEXIT_CRITICAL(&lock);
        }
        if (now - asked_at >= STUN_KEEP_US) {
            asked_at = now;
            stun_begin(false);
        }
        stun_send(sock);
        if (readable(sock)) {
            /* A server's answer, or what is not wanted yet: a call before
             * this end has been told of the caller is given up, and is
             * sent again. */
            stun_took(packet, recv(sock, packet, sizeof(packet), 0), port);
        }
    }
    return false;
}

/* One more measurement of the network's time, from a packet (arq.c). */
static void ping_took(uint32_t took)
{
    portENTER_CRITICAL(&lock);
    pings.last_us = took;
    if (pings.count == 0 || took < pings.least_us) {
        pings.least_us = took;
    }
    if (took > pings.most_us) {
        pings.most_us = took;
    }
    pings.over_14ms += took > 14000;
    pings.over_40ms += took > 40000;
    pings.count++;
    portEXIT_CRITICAL(&lock);
}

/* --- carrying --------------------------------------------------------------------- */

/* Carry bytes both ways until the connection goes or the order does.
 * `answering` is the end that was called: its packets say so until the
 * caller is heard to have got one. */
static void carry(uint32_t began, int sock, nesp_arq_t *arq, struct sockaddr_in *other,
                  bool answering)
{
    uint8_t packet[NESP_ARQ_PACKET];
    uint8_t chunk[NESP_ARQ_HELD];
    uint32_t measured = arq->rtt_count;
    bool gone = false;
    while (!gone) {
        ulTaskNotifyTake(pdTRUE, 1);
        save_last();
        uint32_t now = clock_us();

        /* What the services have left to send, as far as there is room,
         * and their note. */
        portENTER_CRITICAL(&lock);
        bool same = serial == began;
        size_t count = 0;
        size_t room = (size_t)(NESP_ARQ_HELD - arq->out_len);
        while (same && count < going.len && count < room) {
            chunk[count] = going.data[(going.at + count) % RING];
            count++;
        }
        if (same) {
            going.at = (going.at + count) % RING;
            going.len -= count;
            memcpy(arq->note_out, note_out, sizeof(note_out));
        }
        portEXIT_CRITICAL(&lock);
        if (!same) {
            /* Hung up from this end: say so, more than once, and go. */
            for (int times = 0; times < 3; times++) {
                size_t length = nesp_arq_packet(arq, NESP_ARQ_BYE, clock_us(), packet);
                sendto(sock, packet, length, 0, (const struct sockaddr *)other, sizeof(*other));
            }
            break;
        }
        nesp_arq_write(arq, chunk, count);

        /* What has come. */
        for (;;) {
            struct sockaddr_in from;
            socklen_t size = sizeof(from);
            int came = recvfrom(sock, packet, sizeof(packet), 0, (struct sockaddr *)&from, &size);
            if (came <= 0) {
                break;
            }
            int kind = nesp_arq_take(arq, now, packet, (size_t)came);
            if (kind < 0) {
                continue;
            }
            *other = from;          /* wherever its packets come from now */
            if (kind == NESP_ARQ_BYE) {
                gone = true;
            } else if (kind == NESP_ARQ_DATA) {
                answering = false;
            }
        }
        if (arq->rtt_count != measured) {
            measured = arq->rtt_count;
            ping_took(arq->rtt_last);
        }
        if (now - arq->last_at >= GONE_US) {
            gone = true;
        }

        /* To the services: the bytes, as far as they have room, the note
         * and the network's time. */
        portENTER_CRITICAL(&lock);
        room = RING - coming.len;
        portEXIT_CRITICAL(&lock);
        count = nesp_arq_read(arq, chunk, room < sizeof(chunk) ? room : sizeof(chunk));
        portENTER_CRITICAL(&lock);
        if (serial == began) {
            for (size_t index = 0; index < count; index++) {
                coming.data[(coming.at + coming.len) % RING] = chunk[index];
                coming.len++;
            }
            memcpy(note_in, arq->note_in, sizeof(note_in));
            memcpy(spread, arq->needs, sizeof(spread));
            /* The quickest and not the smoothed: a session's first delay
             * is taken from this a few packets into the connection, where
             * one slow packet, the call's answer as a rule, is most of any
             * mean. */
            rtt = arq->rtt_least;
        }
        portEXIT_CRITICAL(&lock);

        /* And what is due to go. */
        if (!gone && nesp_arq_due(arq, now)) {
            size_t length = nesp_arq_packet(arq, answering ? NESP_ARQ_ANSWER : NESP_ARQ_DATA,
                                            now, packet);
            sendto(sock, packet, length, 0, (const struct sockaddr *)other, sizeof(*other));
        }
    }
    if (say(began, NESP_CONN_LOST)) {
        ESP_LOGI(TAG, "the connection was lost");
    }
}

static void conn_task(void *arg)
{
    static nesp_arq_t arq;
    (void)arg;
    uint32_t done = 0;              /* the last order dealt with */
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        for (;;) {
            save_last();
            uint8_t address[4];
            struct sockaddr_in other;
            portENTER_CRITICAL(&lock);
            want_t what = want;
            uint16_t port = want_port;
            uint32_t began = serial;
            memcpy(address, want_address, sizeof(address));
            portEXIT_CRITICAL(&lock);
            if (began == done) {
                break;
            }
            done = began;
            if (what == WANT_NONE) {
                continue;
            }
            /* The one that waits has the port, and so does a meeting; the
             * one that calls, any. */
            int sock = open_socket(what == WANT_CALL ? 0 : port);
            uint16_t own = sock >= 0 ? socket_port(sock) : 0;
            bool up = false;
            bool listening = what == WANT_LISTEN;
            targets_t targets;
            memset(&targets, 0, sizeof(targets));
            if (sock >= 0) {
                stun_begin(true);
            }
            if (sock >= 0 && what == WANT_MEET) {
                if (!meet_wait(began, sock, own, &listening, &targets)) {
                    close(sock);
                    continue;               /* replaced, and says nothing */
                }
                up = listening ? listen_for(began, sock, own, &arq, &other, &targets)
                               : call(began, sock, own, &arq, &targets, &other);
            } else if (sock >= 0 && what == WANT_LISTEN) {
                up = listen_for(began, sock, own, &arq, &other, NULL);
            } else if (sock >= 0) {
                struct sockaddr_in *to = &targets.to[targets.count++];
                to->sin_family = AF_INET;
                to->sin_port = htons(port);
                memcpy(&to->sin_addr.s_addr, address, 4);
                targets.session = esp_random() | 1;
                targets.ms = CALL_MS;
                mark(sock, to);
                up = call(began, sock, own, &arq, &targets, &other);
            }
            if (up && (listening || what == WANT_MEET)) {
                mark(sock, &other);         /* known only now that it has called, or answered */
            }
            if (!up) {
                ESP_LOGI(TAG, "%s", sock < 0 ? "no socket" : "no connection was made");
                say(began, NESP_CONN_FAILED);
            } else if (say(began, listening ? NESP_CONN_ANSWERED : NESP_CONN_CALLED)) {
                ESP_LOGI(TAG, "connected: %s", listening ? "it called" : "it answered");
                carry(began, sock, &arq, &other, listening);
            }
            if (sock >= 0) {
                close(sock);
            }
        }
    }
}

void conn_start(void)
{
    nvs_handle_t settings;
    if (nvs_open(SETTINGS, NVS_READONLY, &settings) == ESP_OK) {
        size_t size = sizeof(last);
        have_last = nvs_get_blob(settings, SETTING_LAST, last, &size) == ESP_OK
                    && size == sizeof(last);
        nvs_close(settings);
    }
    xTaskCreatePinnedToCore(conn_task, "conn", CONN_STACK, NULL, CONN_PRIORITY, &task,
                            CONN_CORE);
}

uint32_t conn_stack_left(void)
{
    return task != NULL ? (uint32_t)uxTaskGetStackHighWaterMark(task) : 0;
}

/* One TCP connection to another nesp32: PEER's, for two consoles playing
 * one game (docs/PROTOCOL.md).
 *
 * A service asks from the link's task, which may not wait. So every call
 * here only leaves an order, or bytes, where this file's task finds them,
 * and takes what the task has left: the state of the connection and the
 * bytes that have come. The task has the socket to itself. It waits for a
 * caller or makes the call, and then carries bytes both ways until the
 * connection goes or another order takes its place.
 *
 * What crosses is small and wants to be there soon: a byte for each frame
 * of a game. Nagle's algorithm is off, the task is woken by every byte to
 * send, and it looks for what has come once a tick of the scheduler, a
 * millisecond.
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
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "nvs.h"

#define CONN_STACK 6144
#define CONN_PRIORITY 6             /* above the fetch: a game's buttons are waited for */
#define CONN_CORE 0                 /* with Wi-Fi; the link has core 1 */
#define RING 256                    /* bytes held each way */
#define CHUNK 64
#define LOOK_MS 50                  /* how often a wait looks for a newer order */
#define CALL_MS 3000                /* how long a call is given to be answered */
#define SETTINGS "nesp32"
#define SETTING_LAST "peer_last"

static const char *TAG = "conn";

typedef enum { WANT_NONE, WANT_LISTEN, WANT_CALL } want_t;

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
static TaskHandle_t task;

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

/* Wait for a caller. The socket of the one that came, or -1. */
static int listen_for(uint32_t began, uint16_t port)
{
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        return -1;
    }
    int yes = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    struct sockaddr_in at;
    memset(&at, 0, sizeof(at));
    at.sin_family = AF_INET;
    at.sin_port = htons(port);
    at.sin_addr.s_addr = htonl(INADDR_ANY);
    int caller = -1;
    if (bind(server, (struct sockaddr *)&at, sizeof(at)) == 0 && listen(server, 1) == 0) {
        while (caller < 0 && wanted(began)) {
            fd_set readable;
            struct timeval wait = {.tv_sec = 0, .tv_usec = LOOK_MS * 1000};
            FD_ZERO(&readable);
            FD_SET(server, &readable);
            if (select(server + 1, &readable, NULL, NULL, &wait) > 0) {
                caller = accept(server, NULL, NULL);
            }
        }
    } else {
        ESP_LOGW(TAG, "cannot listen on port %u: %d", (unsigned)port, errno);
    }
    close(server);
    return caller;
}

/* Call an address. The socket once it has answered, or -1. */
static int call(uint32_t began, const uint8_t *address, uint16_t port)
{
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        return -1;
    }
    struct sockaddr_in to;
    memset(&to, 0, sizeof(to));
    to.sin_family = AF_INET;
    to.sin_port = htons(port);
    memcpy(&to.sin_addr.s_addr, address, 4);
    fcntl(sock, F_SETFL, fcntl(sock, F_GETFL, 0) | O_NONBLOCK);
    bool answered = connect(sock, (struct sockaddr *)&to, sizeof(to)) == 0;
    bool failed = !answered && errno != EINPROGRESS;
    for (int waited = 0; !answered && !failed && waited < CALL_MS && wanted(began);
         waited += LOOK_MS) {
        fd_set writable;
        struct timeval wait = {.tv_sec = 0, .tv_usec = LOOK_MS * 1000};
        FD_ZERO(&writable);
        FD_SET(sock, &writable);
        if (select(sock + 1, NULL, &writable, NULL, &wait) > 0) {
            int error = 0;
            socklen_t size = sizeof(error);
            getsockopt(sock, SOL_SOCKET, SO_ERROR, &error, &size);
            answered = error == 0;
            failed = error != 0;
        }
    }
    if (!answered) {
        close(sock);
        return -1;
    }
    return sock;
}

/* Carry bytes both ways until the connection goes or the order does. */
static void carry(uint32_t began, int sock)
{
    uint8_t chunk[CHUNK];
    int yes = 1;
    setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
    fcntl(sock, F_SETFL, fcntl(sock, F_GETFL, 0) | O_NONBLOCK);
    for (;;) {
        ulTaskNotifyTake(pdTRUE, 1);
        save_last();
        /* What there is to send, left where it is until it has gone. */
        size_t count = 0;
        portENTER_CRITICAL(&lock);
        bool same = serial == began;
        while (same && count < going.len && count < sizeof(chunk)) {
            chunk[count] = going.data[(going.at + count) % RING];
            count++;
        }
        size_t room = RING - coming.len;
        portEXIT_CRITICAL(&lock);
        if (!same) {
            break;
        }
        bool more = count == sizeof(chunk);
        if (count != 0) {
            int sent = send(sock, chunk, count, 0);
            if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
                break;
            }
            portENTER_CRITICAL(&lock);
            if (sent > 0 && serial == began) {
                going.at = (going.at + (size_t)sent) % RING;
                going.len -= (size_t)sent;
            }
            portEXIT_CRITICAL(&lock);
        }
        if (room != 0) {
            int came = recv(sock, chunk, room < sizeof(chunk) ? room : sizeof(chunk), 0);
            if (came == 0 || (came < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
                break;              /* the other end closed, or it broke */
            }
            portENTER_CRITICAL(&lock);
            for (int index = 0; index < came && serial == began; index++) {
                coming.data[(coming.at + coming.len) % RING] = chunk[index];
                coming.len++;
            }
            portEXIT_CRITICAL(&lock);
            more = more || came == (int)sizeof(chunk);
        }
        if (more) {
            xTaskNotifyGive(task);  /* and round again without the wait */
        }
    }
    if (say(began, NESP_CONN_LOST)) {
        ESP_LOGI(TAG, "the connection was lost");
    }
    close(sock);
}

static void conn_task(void *arg)
{
    (void)arg;
    uint32_t done = 0;              /* the last order dealt with */
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        for (;;) {
            save_last();
            uint8_t address[4];
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
            int sock = what == WANT_LISTEN ? listen_for(began, port)
                                           : call(began, address, port);
            if (sock < 0) {
                say(began, NESP_CONN_FAILED);
                continue;
            }
            if (!say(began, what == WANT_LISTEN ? NESP_CONN_ANSWERED : NESP_CONN_CALLED)) {
                close(sock);
                continue;
            }
            ESP_LOGI(TAG, "connected: %s", what == WANT_LISTEN ? "it called" : "it answered");
            carry(began, sock);
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

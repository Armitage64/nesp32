/* The Stick's services, and what they ask of the hardware.
 *
 * A service answers the console from what it holds. Anything slow (joining
 * a network, a scan) is started through nesp_hal_t and asked after later;
 * none of these calls may wait. On the Stick the hal is the firmware's
 * (firmware/main); under the tests it is a stand-in (host/nesp_host.c).
 */
#ifndef NESP_SERVICES_H
#define NESP_SERVICES_H

#include "nesp_core.h"
#include "nesp_text.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NESP_FIRMWARE_MAJOR 0
#define NESP_FIRMWARE_MINOR 1
#define NESP_FIRMWARE_PATCH 0
#define NESP_FIRMWARE_TEXT "0.1.0"

typedef struct {
    uint8_t state;                  /* NESP_WIFI_* */
    uint8_t why;                    /* NESP_WHY_*, when the state is FAILED */
    int8_t rssi;                    /* dBm; 0 when not joined */
    uint8_t address[4];             /* IPv4; zeros when not joined */
    uint8_t name_len;
    char name[NESP_NAME_MAX];       /* the saved network's name */
} nesp_wifi_t;

typedef struct {
    int8_t rssi;
    uint8_t auth;                   /* NESP_AUTH_* */
    uint8_t channel;
    uint8_t name_len;
    char name[NESP_NAME_MAX];
} nesp_network_t;

/* Where a fetch's reply goes. Both are called from the task that does the
 * fetching, never from the link's. */
typedef struct {
    void *ctx;
    /* More of the reply's body. False: no more of it is wanted. */
    bool (*body)(void *ctx, uint32_t id, const uint8_t *data, size_t len);
    /* The fetch is over. ok: the whole reply came (or body said to stop).
     * Otherwise why is a few words for the console's screen. */
    void (*done)(void *ctx, uint32_t id, bool ok, const char *why);
} nesp_sink_t;

typedef struct {
    void *ctx;
    uint8_t (*board)(void *ctx);                    /* NESP_BOARD_* */
    const char *(*board_name)(void *ctx);
    uint8_t (*battery)(void *ctx);                  /* percent; 0xFF if unknown */
    bool (*time)(void *ctx, uint32_t *seconds);     /* since 1970; false if not known */
    void (*wifi)(void *ctx, nesp_wifi_t *out);
    bool (*scan_start)(void *ctx);                  /* false: cannot scan now */
    uint8_t (*scan_state)(void *ctx, uint8_t *count);   /* NESP_SCAN_* */
    bool (*scan_result)(void *ctx, uint8_t index, nesp_network_t *out);
    /* Save the network and start joining it. The password is not kept by
     * the caller. */
    bool (*join)(void *ctx, const char *name, uint8_t name_len,
                 const char *password, uint8_t password_len);
    void (*forget)(void *ctx);
    /* Shown on the Stick's screen: the application now on the console. */
    void (*app)(void *ctx, const char *id, uint8_t version);
    /* Fetch an https address, in place of any fetch under way. The reply
     * goes to the sink with this id, from another task; a sink is told
     * nothing more of a fetch that was replaced or stopped. False: it
     * could not even be started. */
    bool (*fetch)(void *ctx, const char *url, const char *agent, uint32_t id,
                  const nesp_sink_t *sink);
    void (*fetch_stop)(void *ctx);
    /* Memory for something big (an article), from wherever there is most.
     * NULL if there is not that much. */
    void *(*alloc)(void *ctx, size_t bytes);
    void (*release)(void *ctx, void *memory);
    /* Round what a service's handler and a sink both touch. Held for a
     * few instructions, never across a call that could wait. */
    void (*lock)(void *ctx);
    void (*unlock)(void *ctx);
    /* The line itself, with framing off (RAW). These three and the three
     * after them are called from a service's tick only, never on the way
     * to a reply.
     *
     * The UART's rate, both ways, in CPU cycles a bit; NESP_PERIOD is the
     * link's own. Whatever its receiver held is dropped. */
    void (*line_rate)(void *ctx, uint8_t period);
    /* Bytes for the console as they are. Returns how many were taken,
     * which is fewer when the UART has no room for more. Never waits. */
    size_t (*line_write)(void *ctx, const uint8_t *data, size_t len);
    /* True once everything written has left the UART. */
    bool (*line_idle)(void *ctx);
    /* May be NULL. A run from the console is about to come (true), or is
     * over (false). Its bytes are 8N1 with nothing between them, and a UART
     * set for the two stop bits the nesp32 sends with may want both of
     * what it hears too: the StickS3's lost a quarter of such a run. */
    void (*line_hear)(void *ctx, bool hearing);
    /* The nesp32's own files: the jukebox's tracks, in the order of their
     * names. Flash is slow, and a read may take a millisecond or two. */
    uint16_t (*tracks)(void *ctx);
    uint32_t (*track_size)(void *ctx, uint16_t track);
    /* Bytes of a track's file from an offset. Returns how many came: fewer
     * at its end, none past it or if it cannot be read. */
    size_t (*track_read)(void *ctx, uint16_t track, uint32_t offset, uint8_t *out,
                         size_t len);
    /* A line of the nesp32's screen that is the application's to fill:
     * row 0 or 1. An empty text gives it back. */
    void (*show)(void *ctx, uint8_t row, const char *text);
    /* One connection to another nesp32, a stream of bytes each way (PEER).
     * None of these waits: the listening, the calling and the sending
     * itself are another task's.
     *
     * How it stands: NESP_CONN_*. */
    uint8_t (*peer_state)(void *ctx);
    /* Wait for another nesp32 to call this port, or call the one at an
     * address, in place of whatever connection there was. False: it could
     * not even be begun. */
    bool (*peer_listen)(void *ctx, uint16_t port);
    bool (*peer_call)(void *ctx, const uint8_t *address, uint16_t port);
    void (*peer_close)(void *ctx);
    /* Bytes for the other nesp32. Returns how many were taken: none unless
     * the connection is up, and fewer when there is no room for more. */
    size_t (*peer_send)(void *ctx, const uint8_t *data, size_t len);
    /* Bytes from it, as many as have come and fit. What came before a
     * connection was lost can still be read after. */
    size_t (*peer_recv)(void *ctx, uint8_t *out, size_t max);
    /* An address kept over power-off: the last one a call to which came to
     * anything. False: none has been kept. */
    bool (*peer_last)(void *ctx, uint8_t *address);
    void (*peer_keep)(void *ctx, const uint8_t *address);
} nesp_hal_t;

/* A connection to another nesp32, as the hardware has it. */
enum {
    NESP_CONN_NONE,                 /* none asked for, or closed */
    NESP_CONN_LISTENING,
    NESP_CONN_CALLING,
    NESP_CONN_ANSWERED,             /* up: the other nesp32 called this one */
    NESP_CONN_CALLED,               /* up: this one called */
    NESP_CONN_FAILED,               /* it could not listen, or its call was not answered */
    NESP_CONN_LOST                  /* it was up, and is gone */
};

typedef struct {
    nesp_link_t *link;
    const nesp_hal_t *hal;
    char app[NESP_APP_ID];
    uint8_t app_version;
    uint8_t events[NESP_EVENT_QUEUE][2];
    uint8_t event_first;
    uint8_t event_count;
} nesp_sys_t;

typedef struct {
    const nesp_hal_t *hal;
    char name[NESP_NAME_MAX];
    uint8_t name_len;
    char password[NESP_PASSWORD_MAX];
    uint8_t password_len;
} nesp_net_t;

typedef struct {
    nesp_link_t *link;
} nesp_diag_t;

/* WIKI: an article from Wikipedia, as lines the console asks for by number
 * (wiki.c). */
typedef struct {
    const nesp_hal_t *hal;
    nesp_sink_t sink;
    /* What the link's task and the fetch's both touch, under the hal's
     * lock: the article, and the search it is for. */
    uint8_t *lines;                 /* NESP_WIKI_COLUMNS bytes each */
    uint32_t capacity;              /* lines there is room for */
    uint32_t count;                 /* lines laid out */
    bool full;
    uint8_t state;                  /* NESP_ARTICLE_* */
    uint32_t generation;            /* which fetch the article is being filled by */
    /* The link's task alone. */
    bool searched;
    uint8_t search_id;
    uint8_t query_len;
    uint8_t query[NESP_WIKI_QUERY_MAX];
    uint8_t message[NESP_WIKI_COLUMNS];     /* with ERROR, for the console's screen */
    /* The fetch's task alone. */
    uint32_t parsing;               /* the fetch the two below are in the middle of */
    bool finished;
    nesp_extract_t extract;
    nesp_wrap_t wrap;
} nesp_wiki_t;

/* RAW: the line with framing off (raw.c). A run is a stretch of bytes at a
 * rate of its own, one way: the test pattern, or whatever another service
 * has to send. */
typedef struct {
    void *ctx;
    /* More of the run, up to max bytes. 0: that was all of it. From RAW's
     * tick, so it may read flash. */
    size_t (*read)(void *ctx, uint8_t *out, size_t max);
    /* The run is over. sent: its bytes have left, and the line is the
     * link's again. Otherwise it was called off before any did. */
    void (*done)(void *ctx, bool sent);
} nesp_run_t;

#define NESP_RAW_HELD 128

typedef struct {
    nesp_link_t *link;
    const nesp_hal_t *hal;
    uint8_t state;                  /* NESP_RUN_*, as the console is told it */
    uint8_t phase;                  /* where a run has got to (raw.c) */
    bool from_console;              /* the run is the console's to send */
    bool patterned;                 /* it is the pattern, not another service's */
    uint8_t period;
    uint8_t lead;
    uint16_t seed;
    uint16_t length;                /* the pattern's, as asked for */
    uint32_t requests;              /* the link's count of them when it was agreed */
    bool stamp;                     /* agreed since the last tick: the clock starts there */
    uint32_t armed_at;
    uint32_t changed_at;            /* when the rate was changed */
    uint32_t heard_at;              /* when the console's last byte came */
    nesp_run_t run;
    bool ended;                     /* its read has said so */
    uint8_t held[NESP_RAW_HELD];    /* read, and not yet taken by the UART */
    uint8_t held_len;
    uint8_t held_at;
    uint32_t count;                 /* bytes sent, or received */
    uint32_t bad;                   /* of those received, how many were wrong */
    uint16_t rng;                   /* the pattern, where it has got to */
    uint32_t left;
    uint8_t lead_left;
} nesp_raw_t;

/* JUKE: the jukebox's playlist as a stream of bytes (juke.c). */
#define NESP_JUKE_PENDING 128
#define NESP_JUKE_INTRO (2 * (3 + NESP_JUKE_TITLE_MAX) + 2 + 5)
#define NESP_JUKE_NAME 64

typedef struct {
    nesp_link_t *link;
    const nesp_hal_t *hal;
    nesp_raw_t *raw;
    uint8_t loops;                  /* times through a looping track */
    bool repeat;                    /* start over after the last track */
    uint16_t count;                 /* tracks on the nesp32 */
    uint16_t index;                 /* the one being sent, or that Play starts */
    uint8_t state;                  /* NESP_PLAYER_* */
    /* The stream as the console has it. An epoch is a stretch of it with
     * no flush inside; base is the position of pending's first byte. */
    uint8_t epoch;
    uint8_t base;
    uint8_t offered;                /* bytes of pending in the last reply */
    uint8_t pending_len;
    uint8_t pending[NESP_JUKE_PENDING];
    /* Where the stream comes from. */
    uint8_t phase;
    uint16_t failed;                /* tracks in a row that could not be read */
    uint8_t intro_len;
    uint8_t intro_at;
    uint8_t intro[NESP_JUKE_INTRO];
    uint32_t data_at;               /* offsets in the track's file */
    uint32_t data_end;
    uint32_t loop_at;
    uint8_t passes_left;
    /* A track of sampled sound, and the run that sends it. */
    uint8_t sound;                  /* where it has got to (juke.c) */
    uint8_t sound_rate;
    uint8_t sound_period;
    uint8_t sound_press;            /* buttons pressed on the nesp32 while the line was its */
    bool sound_ended;
    uint32_t sound_at;
    uint32_t sound_end;
    nesp_run_t run;
    /* For the nesp32's screen. */
    uint16_t named;                 /* the track `name` is of, or count if none */
    char name[NESP_JUKE_NAME];
    bool show;
    uint32_t shown_at;
    uint32_t resent;                /* replies the console asked for again */
    uint32_t underruns;             /* frames the console had nothing to play */
    uint8_t underruns_seen;
    bool underruns_known;
} nesp_juke_t;

/* PEER: two consoles playing one game, each with a nesp32 (peer.c). What
 * two nesp32s say first, each to the other: who they are, the version of
 * what follows, and the application on their console with its version. */
#define NESP_PEER_GREETING (4 + 1 + NESP_APP_ID + 1)
#define NESP_PEER_HELD 64

typedef struct {
    const nesp_hal_t *hal;
    const nesp_sys_t *sys;
    uint8_t lobby;                  /* NESP_LOBBY_*, as it is while on a network */
    uint8_t target[4];              /* the address called */
    /* The greetings, once the connection is up. */
    bool greeting;
    uint32_t greeting_at;
    uint8_t greeted;                /* bytes of this one's sent */
    uint8_t heard_len;
    uint8_t heard[NESP_PEER_GREETING];
    /* A session: the consoles' buttons, a byte a tick each way. */
    bool lost;                      /* the connection is gone, and all it brought is in `remote` */
    uint8_t local_next;             /* this console's next tick to take */
    uint8_t remote_base;            /* the tick of remote[0] */
    uint8_t remote_len;
    uint8_t remote[NESP_PEER_HELD]; /* the other's buttons, not yet taken */
    /* For the nesp32's screen. */
    uint32_t requests;
    uint32_t repeats;               /* requests that brought nothing new */
    bool show;
    uint32_t shown_at;
} nesp_peer_t;

/* A Stick: the link and every service this firmware has. */
typedef struct {
    nesp_link_t link;
    nesp_sys_t sys;
    nesp_net_t net;
    nesp_diag_t diag;
    nesp_wiki_t wiki;
    nesp_raw_t raw;
    nesp_juke_t juke;
    nesp_peer_t peer;
    nesp_service_t services[7];
} nesp_stick_t;

void nesp_stick_init(nesp_stick_t *stick, const nesp_hal_t *hal);

/* What a port does with a nesp32, in place of the link's own calls.
 *
 * Bytes from the UART. Returns the length of the reply written to out, as
 * nesp_link_feed does; while a run has the line they are the run's, or
 * nothing, and there is no reply. */
size_t nesp_stick_feed(nesp_stick_t *stick, const uint8_t *data, size_t len, uint8_t *out);

/* Call it after every feed, once the reply has been handed to the UART,
 * and every few milliseconds besides. True: call again within two. */
bool nesp_stick_tick(nesp_stick_t *stick, uint32_t now_ms);

/* Something that happened on the nesp32 (NESP_EVENT_*): a button. A service
 * in use may take it; otherwise the console hears of it, unless the queue
 * is full. */
void nesp_stick_event(nesp_stick_t *stick, uint8_t code, uint8_t arg);

void nesp_sys_service(nesp_service_t *service, nesp_sys_t *sys, nesp_link_t *link,
                      const nesp_hal_t *hal);
void nesp_net_service(nesp_service_t *service, nesp_net_t *net, const nesp_hal_t *hal);
void nesp_diag_service(nesp_service_t *service, nesp_diag_t *diag, nesp_link_t *link);
void nesp_wiki_service(nesp_service_t *service, nesp_wiki_t *wiki, const nesp_hal_t *hal);
void nesp_raw_service(nesp_service_t *service, nesp_raw_t *raw, nesp_link_t *link,
                      const nesp_hal_t *hal);
void nesp_juke_service(nesp_service_t *service, nesp_juke_t *juke, nesp_link_t *link,
                       nesp_raw_t *raw, const nesp_hal_t *hal);
void nesp_peer_service(nesp_service_t *service, nesp_peer_t *peer, const nesp_sys_t *sys,
                       const nesp_hal_t *hal);

/* For a service with something to send as a run (JUKE's sampled sound).
 *
 * Agree to a run to the console at this rate, as RAW's own SEND does; the
 * caller's reply to the console is what tells it so. Asked again for a run
 * already agreed, it only starts the wait for it again. False: RAW was not
 * asked for in the hello, or the rate is none it has. */
bool nesp_raw_arm(nesp_raw_t *raw, uint8_t period, const nesp_run_t *run);

/* Call off a run that has been agreed and not begun. Its done is not
 * called. */
void nesp_raw_drop(nesp_raw_t *raw);

/* True while a run has the line: what the UART hears is not the link's. */
bool nesp_raw_owns_line(const nesp_raw_t *raw);

/* What the UART heard while a run had the line. */
void nesp_raw_heard(nesp_raw_t *raw, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif

#endif

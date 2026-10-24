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

/* An address another nesp32 may reach this one at, or the other at. */
typedef struct {
    uint8_t address[4];
    uint16_t port;
} nesp_peer_candidate_t;

/* Where a fetch's reply goes. Both are called from the task that does the
 * fetching, never from the link's. */
/* BSKY's favorites, as they are kept: handles, each with zeros after it
 * where it is shorter than NESP_BSKY_HANDLE_MAX. */
typedef struct {
    uint8_t count;
    char handles[NESP_BSKY_FAVORITES][NESP_BSKY_HANDLE_MAX];
} nesp_bsky_favorites_t;

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
    /* May be NULL: a board that cannot. The nesp32's files as a USB drive
     * for a computer: asked for, or started, or stopped (NESP_LEND_*).
     * Returns how it stands (NESP_DRIVE_*). The doing of it is another
     * task's. */
    uint8_t (*drive)(void *ctx, uint8_t lend);
    /* May be NULL: a firmware that cannot. Which way up the nesp32's
     * screen is: asked, or turned (NESP_TURN_*), and kept over power-off.
     * Returns which way up it is (NESP_SCREEN_*). The turning of it is the
     * screen's own task's. */
    uint8_t (*screen)(void *ctx, uint8_t turn);
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
    /* May be NULL. A line for whoever is watching the nesp32's log: the
     * figures a service keeps of how it is going, which its screen has no
     * room for. */
    void (*watch)(void *ctx, const char *text);
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
    /* Either may be NULL: a board that keeps nothing. An airport kept over
     * power-off, the last that RADAR found: its four letters, and where it
     * is in millionths of a degree. False: none has been kept. Keeping one
     * never waits: the writing of it is another task's. */
    bool (*airport_last)(void *ctx, char *code, int32_t *latitude, int32_t *longitude);
    void (*airport_keep)(void *ctx, const char *code, int32_t latitude, int32_t longitude);
    /* Either may be NULL, likewise. A zip code kept over power-off, the
     * last that WEATHER found: its NESP_WEATHER_ZIP_LEN digits, where it is
     * in millionths of a degree, and its place's name, NESP_WEATHER_PLACE_MAX
     * characters with spaces after it. False: none has been kept. */
    bool (*zip_last)(void *ctx, char *zip, int32_t *latitude, int32_t *longitude, char *name);
    void (*zip_keep)(void *ctx, const char *zip, int32_t latitude, int32_t longitude,
                     const char *name);
    /* Either may be NULL, likewise. BSKY's favorites, kept over power-off:
     * the last list written, whole. False: none has been kept. */
    bool (*favorites_last)(void *ctx, nesp_bsky_favorites_t *out);
    void (*favorites_keep)(void *ctx, const nesp_bsky_favorites_t *favorites);
    /* How long the network takes to the other nesp32 and back, in
     * microseconds, smoothed. 0: not known. */
    uint32_t (*peer_rtt)(void *ctx);
    /* A note of NESP_ARQ_NOTE bytes that goes with everything sent from
     * now on, in place of the last; and the latest that has come from the
     * other nesp32, zeros until one has. Unlike the stream's bytes a note
     * may never arrive: a later one takes its place. */
    void (*peer_note)(void *ctx, const uint8_t *note);
    void (*peer_noted)(void *ctx, uint8_t *note);
    /* Every measurement of the network's time since the connection came
     * up, counted by the delay it would take to cover it: NESP_ARQ_NEEDS
     * counts, for 1 tick, 2, and so on, the last for all beyond. */
    void (*peer_spread)(void *ctx, uint32_t *counts);
    /* All three may be NULL: a board that cannot meet across the Internet.
     * Open the socket a game will be played on, at this port, and find the
     * addresses it may be reached at (NESP_CONN_MEETING, and NESP_CONN_MET
     * once they are found, or as many as could be), in place of whatever
     * connection there was. False: it could not even be begun. */
    bool (*peer_meet)(void *ctx, uint16_t port);
    /* Those addresses, as they are now: its own on its network first.
     * Returns how many, NESP_PEER_CANDIDATES at the most. */
    uint8_t (*peer_candidates)(void *ctx, nesp_peer_candidate_t *out);
    /* From the socket peer_meet opened: wait for the other nesp32's call,
     * or call it, at each of the other's addresses at once, the connection
     * named by the session. The one that waits sends to them too, which
     * opens its own router to them, and answers only that session's call.
     * NESP_CONN_LISTENING or _CALLING, and then as peer_listen's and
     * peer_call's are, the wait failing too if nothing comes. False: there
     * is no socket that met. */
    bool (*peer_punch)(void *ctx, bool listen, uint32_t session,
                       const nesp_peer_candidate_t *other, uint8_t count);
} nesp_hal_t;

/* A stream of bytes over datagrams (arq.c): what a port needs to carry
 * PEER's connection over a network that loses packets. */
#define NESP_ARQ_HEADER 24
#define NESP_ARQ_CARRY 32           /* bytes a datagram carries at most */
#define NESP_ARQ_HELD 96            /* bytes kept each way */
#define NESP_ARQ_NOTE 4
#define NESP_ARQ_NEEDS (NESP_PEER_DELAY_MAX + 1)
#define NESP_ARQ_PACKET (NESP_ARQ_HEADER + NESP_ARQ_CARRY)
enum { NESP_ARQ_CALL, NESP_ARQ_ANSWER, NESP_ARQ_DATA, NESP_ARQ_BYE, NESP_ARQ_PUNCH };

typedef struct {
    uint32_t session;
    uint8_t out[NESP_ARQ_HELD];     /* sent, and not yet said to have come */
    uint16_t out_base;              /* where in the stream out[0] is */
    uint8_t out_len;
    uint8_t in[NESP_ARQ_HELD];      /* come, and not yet read */
    uint8_t in_len;
    uint16_t in_next;               /* where in the other's stream this end has got to */
    bool sent;
    bool fresh;                     /* there is something new to say */
    uint32_t sent_at;
    bool heard;
    uint32_t heard_at;              /* when the newest of its clocks came */
    uint32_t last_at;               /* when anything of it last came */
    uint32_t their_clock;
    uint32_t rtt;                   /* there and back, in microseconds: smoothed */
    uint32_t rtt_last;
    uint32_t rtt_least;             /* the quickest it has been, in this connection */
    uint32_t rtt_count;
    uint32_t needs[NESP_ARQ_NEEDS]; /* the measurements, by the delay each would take */
    uint8_t note_out[NESP_ARQ_NOTE];
    uint8_t note_in[NESP_ARQ_NOTE];
} nesp_arq_t;

/* The delay, in ticks of a game, that covers a network taking this long
 * there and back: half of it, and 9 ms that the consoles and the nesp32s
 * take besides. Not less than 1; it may be more than NESP_PEER_DELAY_MAX. */
uint32_t nesp_arq_ticks(uint32_t rtt_us);
/* A new connection, named by its caller. */
void nesp_arq_open(nesp_arq_t *arq, uint32_t session);
/* Bytes for the other end, and bytes from it: how many were taken. */
size_t nesp_arq_write(nesp_arq_t *arq, const uint8_t *data, size_t len);
size_t nesp_arq_read(nesp_arq_t *arq, uint8_t *out, size_t max);
/* Is it time a datagram went? */
bool nesp_arq_due(const nesp_arq_t *arq, uint32_t now_us);
/* One of a kind, into out (NESP_ARQ_PACKET bytes). Returns its length. */
size_t nesp_arq_packet(nesp_arq_t *arq, uint8_t kind, uint32_t now_us, uint8_t *out);
/* One that came. Its kind, or -1 if it is not this connection's. */
int nesp_arq_take(nesp_arq_t *arq, uint32_t now_us, const uint8_t *data, size_t len);
/* A datagram that carries nothing and names no connection, sent to open
 * this end's router to the other's: NESP_ARQ_HEADER bytes, into out.
 * Every connection's nesp_arq_take passes it over. */
size_t nesp_arq_punch(uint8_t *out);

/* STUN (stun.c): what address and port a socket's datagrams come from, as
 * a server on the Internet sees them. */
#define NESP_STUN_ID 12             /* a request's id, of the asker's choosing */
#define NESP_STUN_REQUEST 20        /* a Binding Request's length, and a header's */
/* A Binding Request, into out (NESP_STUN_REQUEST bytes). Returns its length. */
size_t nesp_stun_request(const uint8_t *id, uint8_t *out);
/* A datagram that came: if it is the answer to the request with this id,
 * the IPv4 address and port it gives, and true. */
bool nesp_stun_mapped(const uint8_t *data, size_t len, const uint8_t *id, uint8_t *address,
                      uint16_t *port);

/* A connection to another nesp32, as the hardware has it. */
enum {
    NESP_CONN_NONE,                 /* none asked for, or closed */
    NESP_CONN_LISTENING,
    NESP_CONN_CALLING,
    NESP_CONN_ANSWERED,             /* up: the other nesp32 called this one */
    NESP_CONN_CALLED,               /* up: this one called */
    NESP_CONN_FAILED,               /* it could not listen, or its call was not answered */
    NESP_CONN_LOST,                 /* it was up, and is gone */
    NESP_CONN_MEETING,              /* a socket is open, and its addresses are being found */
    NESP_CONN_MET                   /* and they are found, as far as they can be */
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

/* RADAR: the aircraft round an airport, as NES Radar's scope shows them
 * (radar.c). */
#define NESP_RADAR_ITEM 2048        /* the longest aircraft in a reply that is read */
#define NESP_RADAR_KEY 12
#define NESP_RADAR_SPOT 48          /* the longest place an airport is at, as it is written */

typedef struct {
    double distance;                /* nautical miles from the airport */
    uint8_t motion[NESP_RADAR_MOTION_LEN];  /* its slot not yet in it */
    uint8_t names[NESP_RADAR_NAMES_LEN];    /* nor here */
} nesp_radar_target_t;

typedef struct {
    const nesp_hal_t *hal;
    nesp_sink_t sink;
    /* What the link's task and the fetch's both touch, under the hal's
     * lock: which fetch is wanted, and that it has ended. */
    uint32_t generation;
    uint8_t landed;                 /* 0, or how the fetch ended: 1 well, 2 badly */
    /* The link's task alone: the airport, the scene, and the clock. */
    bool chosen;
    uint8_t place;                  /* what is known of where it is */
    uint8_t airport_id;
    char code[4];
    int32_t latitude;               /* millionths of a degree */
    int32_t longitude;
    /* The last airport found, which is not asked after twice, and is
     * kept over power-off where the board can. */
    bool known;
    char known_code[4];
    int32_t known_latitude;
    int32_t known_longitude;
    bool held;                      /* there is a scene */
    uint8_t serial;                 /* which scene: never 0 */
    uint8_t names_serial;           /* which names: never 0 */
    uint8_t flags;                  /* NESP_SCENE_* */
    uint8_t count;
    uint8_t motion[NESP_RADAR_TARGETS_MAX][NESP_RADAR_MOTION_LEN];
    uint8_t names[NESP_RADAR_TARGETS_MAX][NESP_RADAR_NAMES_LEN];
    bool asked;                     /* the console has asked since the last tick */
    bool timed;                     /* the three below have been set */
    uint32_t asked_at;
    uint32_t fetch_at;              /* when the last fetch began */
    bool fetching;
    bool fetched;                   /* a fetch has begun for this airport */
    bool good;                      /* and one has ended well, at good_at */
    uint32_t good_at;
    /* The fetch's task alone, until it says the fetch has landed: the reply
     * being read, and the place or the nearest aircraft in it. */
    bool lookup;                    /* the fetch is of where the airport is */
    uint32_t parsing;               /* the fetch the rest is in the middle of */
    uint8_t matched;                /* characters of "Point(" that have come */
    bool spotted;                   /* the place has come whole */
    char spot[NESP_RADAR_SPOT];
    uint8_t spot_len;
    double here[2];                 /* the airport, in degrees */
    uint8_t depth;
    bool in_string;
    bool escaped;
    bool rooted;                    /* the reply is an object */
    bool listed;                    /* inside the list of aircraft */
    bool whole;                     /* the reply's last brace has come */
    bool taking;                    /* inside one aircraft */
    bool long_item;                 /* which is longer than is read */
    uint8_t item_depth;
    char word[NESP_RADAR_KEY];      /* the last string at the top */
    uint8_t word_len;
    char key[NESP_RADAR_KEY];
    uint8_t key_len;
    char item[NESP_RADAR_ITEM];
    uint16_t item_len;
    uint16_t total;                 /* aircraft within range */
    uint8_t near_count;
    nesp_radar_target_t near[NESP_RADAR_TARGETS_MAX];
} nesp_radar_t;

/* WEATHER: the weather at a zip code, laid out as rows for a console's
 * screen (weather.c). */
#define NESP_WEATHER_REPLY 2048     /* the longest reply from either site that is read */

typedef struct {
    const nesp_hal_t *hal;
    nesp_sink_t sink;
    /* What the link's task and the fetch's both touch, under the hal's
     * lock: which fetch is wanted, and that it has ended. */
    uint32_t generation;
    uint8_t landed;                 /* 0, or how the fetch ended (weather.c) */
    /* The link's task alone: the zip code, the report, and the clock. */
    bool chosen;
    uint8_t place;                  /* what is known of where it is */
    uint8_t zip_id;
    char zip[NESP_WEATHER_ZIP_LEN];
    int32_t latitude;               /* millionths of a degree */
    int32_t longitude;
    char name[NESP_WEATHER_PLACE_MAX];
    /* The last zip code found, which is not asked after twice, and is
     * kept over power-off where the board can. */
    bool known;
    char known_zip[NESP_WEATHER_ZIP_LEN];
    int32_t known_latitude;
    int32_t known_longitude;
    char known_name[NESP_WEATHER_PLACE_MAX];
    bool held;                      /* there is a report */
    uint8_t serial;                 /* which report: never 0 */
    uint8_t rows[NESP_WEATHER_ROWS][NESP_WEATHER_COLUMNS];
    bool failed;                    /* the last fetch of the weather did, and why */
    char why[NESP_WEATHER_COLUMNS];
    uint8_t why_len;
    bool asked;                     /* the console has asked since the last tick */
    bool timed;                     /* the two below have been set */
    uint32_t asked_at;
    uint32_t fetch_at;              /* when the last fetch of the weather began */
    bool fetching;
    bool fetched;                   /* a fetch has begun for this zip code */
    bool lookup;                    /* the fetch is of where the zip code is */
    /* The fetch's task alone, until it says the fetch has landed: the
     * reply, whole, and why there is none. */
    uint32_t parsing;               /* the fetch the rest is in the middle of */
    bool long_reply;                /* which is longer than is read */
    uint16_t reply_len;
    char reply[NESP_WEATHER_REPLY];
    char said[NESP_WEATHER_COLUMNS];    /* the fetch's own words for how it failed */
    uint8_t said_len;
} nesp_weather_t;

/* BSKY: a Bluesky account's posts, laid out as lines for a console's
 * screen, and the favorites they are chosen from (bsky.c). */
#define NESP_BSKY_DEPTH 12          /* containers deep in a reply that are followed */
#define NESP_BSKY_KEY 16            /* characters of a key that are kept */
#define NESP_BSKY_FIELD 64          /* of a handle in a reply */
#define NESP_BSKY_TEXT 640          /* of a post's text, as ASCII */

typedef struct {
    const nesp_hal_t *hal;
    nesp_sink_t sink;
    /* What the link's task and the fetch's both touch, under the hal's
     * lock: the posts, and the fetch they are from. */
    uint8_t *posts;                 /* NESP_BSKY_POSTS of NESP_BSKY_ROWS lines */
    uint8_t count;                  /* posts laid out */
    uint8_t used[NESP_BSKY_POSTS];  /* lines of text each has */
    uint8_t state;                  /* NESP_FEED_* */
    uint32_t generation;            /* which fetch the posts are being filled by */
    char why[NESP_BSKY_COLUMNS];    /* with FAILED, for the console's screen */
    uint32_t clock;                 /* the time when the fetch began, */
    bool clock_known;               /* if the nesp32 knew it */
    /* The link's task alone. */
    nesp_bsky_favorites_t favorites;
    bool chosen;
    uint8_t feed_id;
    uint8_t handle_len;
    char handle[NESP_BSKY_HANDLE_MAX];
    /* The fetch's task alone: where in the reply it has got to, and the
     * post being read. */
    uint32_t parsing;               /* the fetch the rest is in the middle of */
    uint8_t depth;                  /* containers open, the root being 1 */
    uint8_t deep;                   /* and past NESP_BSKY_DEPTH, not followed */
    uint16_t lists;                 /* bit n: the container at depth n is a list */
    bool listed;                    /* inside "feed" */
    bool whole;                     /* the reply's last brace has come */
    bool in_string;
    bool is_key;
    bool want_key;                  /* the next string in this object is a key */
    uint8_t field;                  /* what the value being read is (bsky.c) */
    uint8_t escape;                 /* 0, 1 after a backslash, 2 to 5 in \uXXXX */
    uint8_t need;                   /* bytes still to come of a UTF-8 character */
    bool unknown;                   /* the last character kept was a "?" */
    bool bad_hex;
    uint16_t unit;
    uint16_t high;                  /* the first half of a \u surrogate pair */
    uint32_t code;
    char keys[NESP_BSKY_DEPTH][NESP_BSKY_KEY];  /* the key being read or last read, by depth */
    uint8_t key_lens[NESP_BSKY_DEPTH];
    size_t handle_field_len;
    char handle_field[NESP_BSKY_FIELD];
    size_t text_len;
    char text[NESP_BSKY_TEXT];
    size_t when_len;
    char when[32];
    size_t reposter_len;
    char reposter[NESP_BSKY_FIELD];
    uint32_t replies;
    uint32_t reposts;
    uint32_t likes;
} nesp_bsky_t;

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
    /* May be NULL. The console sent this many bytes while the run was
     * being sent: it is not listening for it, whatever they were (they
     * came at the run's rate, and mean nothing). */
    void (*heard)(void *ctx, size_t len);
    /* Bytes of $FF the run begins with, before read's: for a console's
     * receiver that settles on them. */
    uint8_t lead;
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
#define NESP_JUKE_LIST_NONE 0xFFFF

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
    uint32_t sound_from;            /* where this run of it began */
    uint32_t sound_began;           /* and when, in ms */
    bool sound_fresh;               /* its first bytes have gone, and tick has not noted when */
    uint32_t sound_spoke;           /* bytes heard from the console during the run */
    uint32_t sound_spoke_ms;        /* when the first of them came */
    bool sound_hushed;              /* enough of them: the console has left it */
    uint32_t sound_ramp;            /* samples a sound that was paused rises over, */
    uint32_t sound_rise;            /* and how many of them have gone */
    uint32_t now;                   /* tick's last */
    nesp_run_t run;
    /* A track's names for the console's menu (NAME): the one it asked for,
     * and the one these are of, which tick reads. NESP_JUKE_LIST_NONE if
     * none. */
    uint16_t list_want;
    uint16_t list_index;
    uint8_t list_game_len;
    uint8_t list_track_len;
    uint8_t list_game[NESP_JUKE_TITLE_MAX];
    uint8_t list_track[NESP_JUKE_TITLE_MAX];
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
#define NESP_PEER_PADS 10           /* changes in a console's buttons kept for a line of the log */
#define NESP_PEER_ANSWER 128        /* the longest line the rendezvous answers that is kept */

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
    /* The delay: what this console says it keeps, what it is advised,
     * and what goes into the advice (peer.c). */
    uint32_t now;                   /* the clock, as the last tick had it */
    uint8_t delay;                  /* 0: it has not said */
    uint8_t want;                   /* 0: no advice yet */
    uint8_t up;                     /* reports in a row that called for longer */
    uint8_t down;                   /* and for shorter */
    uint8_t told;                   /* this console's reports passed on: the count is their name */
    uint32_t told_at;
    uint32_t spread[NESP_ARQ_NEEDS];    /* the network's times, as they stood at the last report */
    uint32_t since[NESP_ARQ_NEEDS];     /* and those the last report had come since the one before */
    uint32_t watched_at;
    /* For the log: this console's buttons each time they changed, since the
     * last line of it. */
    uint8_t pad;                    /* as they last were */
    uint8_t pads;                   /* how many changes are in pad_log */
    uint32_t pad_changes;           /* how many there have been in the session */
    uint8_t pad_log[NESP_PEER_PADS][2];     /* the tick's low byte, and the buttons */
    /* For the nesp32's screen. */
    uint32_t requests;
    uint32_t repeats;               /* requests that brought nothing new */
    uint32_t again;                 /* of those, ones that sent buttons already held:
                                       the console did not hear the reply before */
    bool show;
    uint32_t shown_at;
    /* A meeting at the rendezvous (peer.c), and the line its last answer
     * was. What the link's task and the fetch's both touch is under the
     * hal's lock: which fetch is wanted, its answer, and that it ended. */
    const char *rendezvous;         /* its address, with no "/" after it */
    nesp_sink_t sink;
    uint32_t generation;
    uint8_t landed;                 /* 0, or how the fetch ended: 1 well, 2 badly */
    uint8_t answer_len;
    char answer[NESP_PEER_ANSWER];
    /* The link's task alone. */
    uint8_t meet;                   /* how far the meeting has got (peer.c) */
    bool hosting_room;              /* this one opened the room */
    char code[NESP_PEER_CODE];
    uint32_t session;
    uint8_t reason;                 /* NESP_MEET_*, when the lobby is FAILED */
    bool asking;                    /* a fetch is out, and has not been taken */
    uint32_t asked_at;
    uint8_t fails;                  /* of the host's asks, in a row */
} nesp_peer_t;

/* TUNER: a radio station as sampled sound (tuner.c). */
/* Headlines out of an RSS feed, a page each for a console's screen
 * (news.c). */
typedef struct {
    uint8_t rows[NESP_TUNER_NEWS_PAGES][NESP_TUNER_NEWS_ROWS][NESP_TUNER_NEWS_COLUMNS];
    uint8_t count;                  /* pages laid out */
    /* Where the feed has got to. */
    uint8_t mode;
    uint8_t field;                  /* which of an item's texts is being kept */
    bool in_item;
    uint8_t closing;                /* of "]]>" that have come */
    uint8_t tag_len;
    uint8_t tag[16];
    uint16_t title_len;
    uint16_t summary_len;
    uint8_t title[256];
    uint8_t summary[768];
} nesp_news_t;

void nesp_news_init(nesp_news_t *news);
void nesp_news_feed(nesp_news_t *news, const uint8_t *data, size_t len);

struct nesp_tuner_work;             /* the decoder's memory, which the fetch's task has */

typedef struct {
    const nesp_hal_t *hal;
    nesp_raw_t *raw;
    nesp_sink_t sink;
    uint8_t state;                  /* NESP_TUNER_* */
    char why[NESP_TUNER_TEXT_MAX + 1];  /* with FAILED */
    char url[NESP_TUNER_URL_MAX + 1];   /* the station the next PLAY tunes in, as URL set it */
    char tuned[NESP_TUNER_URL_MAX + 1]; /* and the one that is tuned in, or was last */
    /* What the link's task and the fetch's both touch, under the hal's
     * lock: which fetch is wanted, the ring of levels for the console's
     * DAC that it fills, and that it has ended. */
    uint32_t generation;
    uint8_t *ring;
    uint32_t ring_size;
    uint32_t head;                  /* where the oldest level held is */
    uint32_t held;
    uint32_t dropped;               /* levels lost from a ring that was full */
    uint8_t landed;                 /* not 0: the fetch has ended, and landed_why says how */
    char landed_why[NESP_TUNER_TEXT_MAX + 1];
    /* The fetch's task alone. */
    struct nesp_tuner_work *work;
    /* The run that sends the ring. */
    nesp_run_t run;
    uint8_t sound;                  /* where it has got to (tuner.c) */
    bool press;                     /* the nesp32's button, pressed while the line was its */
    bool ended;
    bool lost;                      /* the stream ended, and all of it has been played */
    bool hushed;                    /* the console left the sound: paused */
    /* The headlines, which are fetched before the station is. The fetch's
     * task has `news` until it says, under the lock, that they have
     * landed. */
    nesp_sink_t news_sink;
    nesp_news_t news;
    bool news_wanted;               /* their fetch is the one under way */
    bool news_landed;
    uint8_t mode;                   /* NESP_TUNER_MODE_*, as PLAY chose */
    uint8_t period;                 /* and its rate, in CPU cycles a bit */
    uint8_t page;                   /* the headline that is on the console's screen, or going there */
    /* Where the run's eighth bit has got to (tuner.c). */
    uint8_t chan;
    uint8_t chan_char;              /* what is left of the character being sent, */
    uint8_t chan_bits;              /* and how many bits that is */
    uint16_t chan_at;               /* characters of the page that have gone */
    uint32_t chan_sent;             /* bits, since the run began */
    uint32_t chan_turn;             /* the count at which the next page goes */
    bool chan_fresh;                /* no page has gone in this run */
    uint8_t chan_trail;
    bool holding;                   /* the ring ran dry: the DAC is held until more has come */
    uint8_t last;                   /* the level last sent */
    uint32_t rise;                  /* samples of the ramp from the DAC's rest so far */
    uint32_t fall;                  /* and of the one back to it */
    uint32_t sent;
    uint32_t spoke;                 /* bytes heard from the console during the run */
    uint32_t spoke_at;              /* the count sent when the first of them came */
    /* For the nesp32's screen. */
    uint32_t dry;                   /* times the ring ran dry */
    bool show;
    uint32_t shown_at;
} nesp_tuner_t;

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
    nesp_radar_t radar;
    nesp_tuner_t tuner;
    nesp_weather_t weather;
    nesp_bsky_t bsky;
    nesp_service_t services[11];
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

void nesp_radar_service(nesp_service_t *service, nesp_radar_t *radar, const nesp_hal_t *hal);
void nesp_tuner_service(nesp_service_t *service, nesp_tuner_t *tuner, nesp_raw_t *raw,
                        const nesp_hal_t *hal);
void nesp_weather_service(nesp_service_t *service, nesp_weather_t *weather,
                          const nesp_hal_t *hal);
void nesp_bsky_service(nesp_service_t *service, nesp_bsky_t *bsky, const nesp_hal_t *hal);

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

/* A rip of a NES game's music (an uncompressed .vgm) as the .jbs file that
 * JUKE plays, into out (vgm.c). name is the title of one that has none of
 * its own, and may be NULL. False if it is not such a rip, or cannot be
 * played, or does not fit. work is somewhere to keep a frame of it. */
#define NESP_VGM_FRAME_WRITES 512   /* a frame's writes to the chip, at most */
typedef struct {
    uint8_t writes[NESP_VGM_FRAME_WRITES][2];   /* register and value, as they came */
    uint16_t count;
    uint8_t kept[NESP_VGM_FRAME_WRITES][2];     /* those of them that go */
    uint16_t events[2][NESP_VGM_FRAME_WRITES];
} nesp_vgm_t;

bool nesp_vgm_to_jbs(nesp_vgm_t *work, const uint8_t *vgm, size_t len, const char *name,
                     uint8_t *out, size_t max, size_t *out_len);

#ifdef __cplusplus
}
#endif

#endif

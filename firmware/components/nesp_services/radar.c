/* RADAR: the aircraft round an airport, for NES Radar's scope
 * (docs/PROTOCOL.md).
 *
 * The console names an airport by its four letters. The nesp32 asks
 * Wikidata where that is, once, then asks adsb.fi every few seconds for the
 * aircraft near it, and keeps the nearest eight as a scene: for each, nine bytes of where it is and how
 * it moves, and twenty-five of its names, both as nes-radar's ROM has them.
 * The console asks for the scene, and is sent it only if it is not the one
 * it has; the names it asks for a slot at a time, when they have changed.
 *
 * AIRPORT is both "this airport" and "how does it stand". The console gives
 * each choice an id and may send the same request as often as it likes: an
 * id or letters that are new choose the airport, and the same again only
 * answers. So a lost request or reply needs no handling of its own.
 *
 * Two tasks meet here. The link's task runs handle() and tick(), and the
 * scene the console is told of is its alone. The fetch's task runs body()
 * and done(), reads the reply as it comes and keeps the place, or the
 * nearest aircraft, in it; when the reply has ended it says so (`landed`, under the hal's lock),
 * and touches nothing more until the link's task has taken them and begun
 * another fetch. `generation` is which fetch is wanted: a new airport takes
 * a new one, and whatever an older fetch brings is dropped.
 *
 * The clock is tick()'s, so the times are too: a fetch every
 * NESP_RADAR_POLL_MS while the console goes on asking, and a scene that is
 * stale when nothing good has come for NESP_RADAR_STALE_MS.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "nesp_services.h"

#define TARGETS NESP_RADAR_TARGETS_MAX
#define MOTION NESP_RADAR_MOTION_LEN
#define NAMES NESP_RADAR_NAMES_LEN
#define AGENT "nesp32-radar/0.1 (NES Radar on a nesp32; +https://github.com/Armitage64/nesp32)"
#define SOURCE "https://opendata.adsb.fi/api/v3"
/* Where an airport is: Wikidata's item with these letters as its ICAO code
 * (P239), and that item's coordinates (P625). The query is
 *   SELECT ?p WHERE { ?a wdt:P239 "KSBA"; wdt:P625 ?p } LIMIT 1
 * and the answer has the place as "Point(longitude latitude)". */
#define WHERE "https://query.wikidata.org/sparql?format=json&query=" \
              "SELECT%20%3Fp%20WHERE%20%7B%20%3Fa%20wdt%3AP239%20%22"
#define WHERE_END "%22%3B%20wdt%3AP625%20%3Fp%20%7D%20LIMIT%201"
static const char point[] = "Point(";

/* The scope: nine nautical miles to its edge, which is 71 points from its
 * middle at (72, 72). An aircraft slower than a landing one is on the
 * ground, whatever it says. */
#define RANGE_NM 9.0
#define ASKED_NM 10
#define SLOWEST_KT 40.0
#define MIDDLE 72
#define EDGE 71.0
#define LAST 143
#define PI 3.14159265358979323846
#define EARTH_NM (6371.0 * 0.539957)

/* A motion record's first byte, with its slot. */
#define NO_TRACK 0x08
#define NO_ALTITUDE 0x10
#define NO_SPEED 0x20
#define NO_RATE 0x80                /* in place of a rate of climb */

#define LANDED_WELL 1
#define LANDED_BADLY 2

/* What is known of where the airport is. */
#define PLACE_UNKNOWN 0             /* not asked yet, or being asked */
#define PLACE_KNOWN 1
#define PLACE_NONE 2                /* no airport has those letters */
#define PLACE_FAILED 3              /* the asking failed */

static void lock(nesp_radar_t *radar)
{
    radar->hal->lock(radar->hal->ctx);
}

static void unlock(nesp_radar_t *radar)
{
    radar->hal->unlock(radar->hal->ctx);
}

/* --- the fetch's task: one aircraft ------------------------------------------ */

/* The value of one of an aircraft's names: its characters, less the quotes
 * of a string. */
typedef struct {
    const char *at;
    size_t len;
    bool string;
} value_t;

static bool is_space(char letter)
{
    return letter == ' ' || (letter >= '\t' && letter <= '\r');
}

/* Past a string that begins at `at`, a quote. Returns where the character
 * after its closing quote is. */
static size_t past_string(const char *item, size_t len, size_t at)
{
    at++;
    while (at < len && item[at] != '"') {
        at += item[at] == '\\' ? 2 : 1;
    }
    return at < len ? at + 1 : len;
}

/* What an aircraft has by this name, at its top: what is inside a list or
 * another object of its own is passed over. False if it has none, or null. */
static bool member(const char *item, size_t len, const char *name, value_t *out)
{
    size_t name_len = strlen(name);
    size_t at = 1;                  /* past its brace */
    while (at < len) {
        while (at < len && item[at] != '"') {
            if (item[at] == '}') {
                return false;
            }
            at++;
        }
        size_t key = at + 1;
        size_t end = past_string(item, len, at);
        if (end >= len) {
            return false;
        }
        bool wanted = end - 1 - key == name_len && memcmp(item + key, name, name_len) == 0;
        at = end;
        while (at < len && (is_space(item[at]) || item[at] == ':')) {
            at++;
        }
        if (at >= len) {
            return false;
        }
        size_t begins = at;
        bool string = item[at] == '"';
        if (string) {
            at = past_string(item, len, at);
        } else if (item[at] == '{' || item[at] == '[') {
            unsigned depth = 0;
            do {
                if (item[at] == '"') {
                    at = past_string(item, len, at);
                    continue;
                }
                if (item[at] == '{' || item[at] == '[') {
                    depth++;
                } else if (item[at] == '}' || item[at] == ']') {
                    depth--;
                }
                at++;
            } while (at < len && depth > 0);
            wanted = false;         /* nothing wanted is a list */
        } else {
            while (at < len && item[at] != ',' && item[at] != '}' && !is_space(item[at])) {
                at++;
            }
        }
        if (wanted) {
            if (string) {
                out->at = item + begins + 1;
                out->len = at - begins - 2;
            } else {
                out->at = item + begins;
                out->len = at - begins;
            }
            out->string = string;
            return string || !(out->len == 4 && memcmp(out->at, "null", 4) == 0);
        }
    }
    return false;
}

/* A number, or a string that is one. */
static bool number(const char *item, size_t len, const char *name, double *out)
{
    value_t value;
    char text[32];
    if (!member(item, len, name, &value)) {
        return false;
    }
    while (value.len > 0 && is_space(value.at[0])) {
        value.at++;
        value.len--;
    }
    while (value.len > 0 && is_space(value.at[value.len - 1])) {
        value.len--;
    }
    if (value.len == 0 || value.len >= sizeof(text)) {
        return false;
    }
    memcpy(text, value.at, value.len);
    text[value.len] = 0;
    if (strpbrk(text, "xXnN") != NULL) {    /* hexadecimal, or not a number at all */
        return false;
    }
    char *end;
    double result = strtod(text, &end);
    if (end != text + value.len || !isfinite(result)) {
        return false;
    }
    *out = result;
    return true;
}

static bool is_text(const char *item, size_t len, const char *name, const char *text)
{
    value_t value;
    size_t text_len = strlen(text);
    if (!member(item, len, name, &value) || !value.string || value.len != text_len) {
        return false;
    }
    for (size_t index = 0; index < text_len; index++) {
        char letter = value.at[index];
        if (letter >= 'A' && letter <= 'Z') {
            letter = (char)(letter - 'A' + 'a');
        }
        if (letter != text[index]) {
            return false;
        }
    }
    return true;
}

static int hex_digit(char letter)
{
    if (letter >= '0' && letter <= '9') {
        return letter - '0';
    }
    letter = (char)(letter | 0x20);
    return letter >= 'a' && letter <= 'f' ? letter - 'a' + 10 : -1;
}

/* A value as a name on the scope: no spaces round it, capitals, a hyphen
 * for whatever the scope has no character for, cut to the width and padded
 * with spaces. A character that is not ASCII is one hyphen. */
static void put_name(const value_t *value, uint8_t *out, size_t width)
{
    char text[64];
    size_t count = 0;
    size_t at = 0;
    while (at < value->len && count < sizeof(text)) {
        unsigned char letter = (unsigned char)value->at[at++];
        if (value->string && letter == '\\' && at < value->len) {
            char escape = value->at[at++];
            switch (escape) {
            case 'n': letter = '\n'; break;
            case 't': letter = '\t'; break;
            case 'r': letter = '\r'; break;
            case 'f': letter = '\f'; break;
            case 'b': letter = 0x7F; break;
            case 'u': {
                unsigned code = 0;
                for (int digit = 0; digit < 4 && at < value->len; digit++) {
                    int hex = hex_digit(value->at[at]);
                    if (hex < 0) {
                        break;
                    }
                    code = code << 4 | (unsigned)hex;
                    at++;
                }
                if (code >= 0xDC00 && code <= 0xDFFF) {
                    continue;       /* the second half of a character already counted */
                }
                letter = code < 0x80 ? (unsigned char)code : 0x7F;
                break;
            }
            default: letter = (unsigned char)escape; break;
            }
        } else if (letter >= 0x80) {
            if (letter < 0xC0) {
                continue;           /* the rest of a character already counted */
            }
            letter = 0x7F;
        }
        text[count++] = (char)letter;
    }
    size_t first = 0;
    while (first < count && is_space(text[first])) {
        first++;
    }
    while (count > first && is_space(text[count - 1])) {
        count--;
    }
    for (size_t index = 0; index < width; index++) {
        char letter = ' ';
        if (first + index < count) {
            letter = text[first + index];
            if (letter >= 'a' && letter <= 'z') {
                letter = (char)(letter - 'a' + 'A');
            }
            if (!((letter >= 'A' && letter <= 'Z') || (letter >= '0' && letter <= '9')
                  || letter == ' ' || letter == '-')) {
                letter = '-';
            }
        }
        out[index] = (uint8_t)letter;
    }
}

/* The first of these names that an aircraft has anything by, as a name on
 * the scope; four hyphens if it has none. */
static void put_first(const char *item, size_t len, const char *const *names, size_t count,
                      uint8_t *out, size_t width)
{
    static const value_t none = {"----", 4, true};
    value_t value;
    for (size_t index = 0; index < count; index++) {
        if (member(item, len, names[index], &value) && value.len > 0) {
            put_name(&value, out, width);
            return;
        }
    }
    put_name(&none, out, width);
}

static void put_one(const char *item, size_t len, const char *name, uint8_t *out, size_t width)
{
    static const value_t none = {"", 0, true};
    value_t value;
    put_name(member(item, len, name, &value) ? &value : &none, out, width);
}

static double radians(double degrees)
{
    return degrees * (PI / 180.0);
}

/* To the nearest whole number, a half to the even one, and kept between
 * two. */
static long rounded(double value, long least, long most)
{
    double whole = nearbyint(value);
    if (whole < (double)least) {
        return least;
    }
    return whole > (double)most ? most : (long)whole;
}

/* One aircraft of the reply, whole. It is kept if it is flying, within
 * range, and among the nearest so far. */
static void aircraft(nesp_radar_t *radar, const char *item, size_t len)
{
    static const char *const calls[] = {"flight", "r", "hex"};
    static const char *const types[] = {"t"};
    double speed, latitude, longitude, value;
    if (is_text(item, len, "alt_baro", "ground")) {
        return;
    }
    bool has_speed = number(item, len, "gs", &speed);
    if (has_speed && speed < SLOWEST_KT) {
        return;
    }
    if (!number(item, len, "lat", &latitude) || !number(item, len, "lon", &longitude)) {
        return;
    }
    /* How far it is, round the earth, and which way, from north. */
    double from = radians(radar->here[0]);
    double to = radians(latitude);
    double north = radians(latitude - radar->here[0]);
    double east = radians(longitude - radar->here[1]);
    double half = sin(north / 2) * sin(north / 2)
                  + cos(from) * cos(to) * sin(east / 2) * sin(east / 2);
    half = half < 0.0 ? 0.0 : half > 1.0 ? 1.0 : half;
    double distance = EARTH_NM * 2 * atan2(sqrt(half), sqrt(1 - half));
    if (distance > RANGE_NM) {
        return;
    }
    radar->total++;
    size_t place = radar->near_count;
    while (place > 0 && distance < radar->near[place - 1].distance) {
        place--;
    }
    if (place >= TARGETS) {
        return;
    }
    size_t moved = (radar->near_count < TARGETS ? radar->near_count : TARGETS - 1) - place;
    memmove(&radar->near[place + 1], &radar->near[place], moved * sizeof(radar->near[0]));
    if (radar->near_count < TARGETS) {
        radar->near_count++;
    }
    nesp_radar_target_t *target = &radar->near[place];
    target->distance = distance;

    double bearing = fmod(atan2(sin(east) * cos(to),
                                cos(from) * sin(to) - sin(from) * cos(to) * cos(east))
                          * (180.0 / PI) + 360.0, 360.0);
    double out = distance * (EDGE / RANGE_NM);
    out = out > EDGE ? EDGE : out;
    uint8_t *motion = target->motion;
    memset(motion, 0, MOTION);
    motion[1] = (uint8_t)rounded(MIDDLE + nearbyint(sin(radians(bearing)) * out), 0, LAST);
    motion[2] = (uint8_t)rounded(MIDDLE - nearbyint(cos(radians(bearing)) * out), 0, LAST);
    if (number(item, len, "track", &value) || number(item, len, "true_heading", &value)) {
        motion[3] = (uint8_t)((unsigned long)rounded(value * 256 / 360, -65536, 65536) & 0xFF);
    } else {
        motion[0] |= NO_TRACK;
    }
    if (number(item, len, "alt_baro", &value)) {
        long hundreds = rounded(value / 100, 0, 65535);
        motion[4] = (uint8_t)hundreds;
        motion[5] = (uint8_t)(hundreds >> 8);
    } else {
        motion[0] |= NO_ALTITUDE;
    }
    if (has_speed) {
        motion[6] = (uint8_t)rounded(speed, 0, 255);
    } else {
        motion[0] |= NO_SPEED;
    }
    if (number(item, len, "baro_rate", &value) || number(item, len, "geom_rate", &value)) {
        motion[7] = (uint8_t)(rounded(value / 100, -99, 99) & 0xFF);
    } else {
        motion[7] = NO_RATE;
    }
    motion[8] = (uint8_t)rounded(distance * 10, 0, 99);

    uint8_t *names = target->names;
    put_first(item, len, calls, sizeof(calls) / sizeof(calls[0]), names + 1, 8);
    put_first(item, len, types, sizeof(types) / sizeof(types[0]), names + 9, 4);
    put_one(item, len, "r", names + 13, 6);
    put_one(item, len, "squawk", names + 19, 4);
    put_one(item, len, "category", names + 23, 2);
}

/* --- the fetch's task: the reply ---------------------------------------------- */

/* The reply is an object, and the aircraft are the objects in its list
 * named "ac". It is read a character at a time and never held whole: only
 * the aircraft being read is, and one too long for that is passed over. */
static void take(nesp_radar_t *radar, const uint8_t *data, size_t len)
{
    for (size_t index = 0; index < len; index++) {
        char letter = (char)data[index];
        if (radar->lookup && !radar->spotted) {
            /* The place is the first thing written as a point. */
            if (radar->matched < sizeof(point) - 1) {
                radar->matched = letter == point[radar->matched] ? (uint8_t)(radar->matched + 1)
                                                                 : (uint8_t)(letter == point[0]);
            } else if (letter == ')') {
                radar->spot[radar->spot_len] = 0;
                radar->spotted = true;
            } else if (radar->spot_len < NESP_RADAR_SPOT - 1) {
                radar->spot[radar->spot_len++] = letter;
            }
        }
        if (radar->taking) {
            if (radar->item_len < NESP_RADAR_ITEM) {
                radar->item[radar->item_len++] = letter;
            } else {
                radar->long_item = true;
            }
        }
        if (radar->in_string) {
            if (radar->escaped) {
                radar->escaped = false;
            } else if (letter == '\\') {
                radar->escaped = true;
            } else if (letter == '"') {
                radar->in_string = false;
            } else if (radar->depth == 1 && radar->word_len < NESP_RADAR_KEY) {
                radar->word[radar->word_len++] = letter;
            }
            continue;
        }
        switch (letter) {
        case '"':
            radar->in_string = true;
            if (radar->depth == 1) {
                radar->word_len = 0;
            }
            break;
        case ':':
            if (radar->depth == 1) {
                memcpy(radar->key, radar->word, radar->word_len);
                radar->key_len = radar->word_len;
            }
            break;
        case '[':
        case '{':
            if (radar->depth == 0) {
                radar->rooted = letter == '{';
            } else if (radar->depth == 1 && letter == '[') {
                radar->listed = (radar->key_len == 2 && memcmp(radar->key, "ac", 2) == 0)
                                || (radar->key_len == 8
                                    && memcmp(radar->key, "aircraft", 8) == 0);
            } else if (radar->depth == 2 && letter == '{' && radar->listed) {
                radar->taking = true;
                radar->long_item = false;
                radar->item[0] = letter;
                radar->item_len = 1;
            }
            if (radar->depth < 0xFF) {
                radar->depth++;
            }
            break;
        case ']':
        case '}':
            if (radar->depth > 0) {
                radar->depth--;
            }
            if (radar->depth == 2 && radar->taking) {
                radar->taking = false;
                if (!radar->long_item) {
                    aircraft(radar, radar->item, radar->item_len);
                }
            } else if (radar->depth == 1) {
                radar->listed = false;
            } else if (radar->depth == 0) {
                radar->whole = radar->rooted;
            }
            break;
        default:
            break;
        }
    }
}

static bool current(nesp_radar_t *radar, uint32_t id)
{
    lock(radar);
    bool same = radar->generation == id;
    unlock(radar);
    return same;
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_radar_t *radar = ctx;
    if (!current(radar, id)) {
        return false;
    }
    if (radar->parsing != id) {     /* the first of a new reply */
        radar->parsing = id;
        radar->depth = 0;
        radar->in_string = false;
        radar->escaped = false;
        radar->rooted = false;
        radar->listed = false;
        radar->whole = false;
        radar->taking = false;
        radar->word_len = 0;
        radar->key_len = 0;
        radar->total = 0;
        radar->near_count = 0;
        radar->matched = 0;
        radar->spotted = false;
        radar->spot_len = 0;
    }
    take(radar, data, len);
    return true;
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_radar_t *radar = ctx;
    (void)why;
    bool well = ok && radar->parsing == id && radar->whole;
    lock(radar);
    if (radar->generation == id) {
        radar->landed = well ? LANDED_WELL : LANDED_BADLY;
    }
    unlock(radar);
}

/* --- the link's task ----------------------------------------------------------- */

/* The next of a count that is never 0: what a console that has nothing
 * says it has. */
static uint8_t next(uint8_t serial)
{
    return serial == 0xFF ? 1 : (uint8_t)(serial + 1);
}

static bool online(const nesp_radar_t *radar)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    radar->hal->wifi(radar->hal->ctx, &wifi);
    return wifi.state == NESP_WIFI_JOINED;
}

/* How it stands, as the console is told. */
static uint8_t state(const nesp_radar_t *radar)
{
    if (!radar->chosen) {
        return NESP_SCOPE_IDLE;
    }
    if (radar->place == PLACE_NONE) {
        return NESP_SCOPE_NOT_FOUND;
    }
    if (radar->place == PLACE_FAILED) {
        return NESP_SCOPE_NO_LOOKUP;
    }
    if (radar->held) {
        return NESP_SCOPE_READY;
    }
    if (!online(radar)) {
        return NESP_SCOPE_NO_WIFI;
    }
    return radar->place == PLACE_KNOWN ? NESP_SCOPE_WAITING : NESP_SCOPE_LOOKING;
}

static void show(nesp_radar_t *radar)
{
    char text[32];
    if (!radar->chosen || radar->place != PLACE_KNOWN) {
        text[0] = 0;
    } else if (!radar->held) {
        snprintf(text, sizeof(text), "%.4s", radar->code);
    } else {
        snprintf(text, sizeof(text), "%.4s: %u aircraft", radar->code, (unsigned)radar->count);
    }
    radar->hal->show(radar->hal->ctx, 0, text);
}

/* No airport's aircraft are wanted any more, or another's are. */
static void drop(nesp_radar_t *radar)
{
    radar->hal->fetch_stop(radar->hal->ctx);
    lock(radar);
    radar->generation++;
    radar->landed = 0;
    unlock(radar);
    radar->fetching = false;
    radar->fetched = false;
    radar->good = false;
    radar->held = false;
    radar->count = 0;
    radar->flags = 0;
}

/* A fetch has ended, well or badly: the scene is what it brought, or the
 * one before with the flags to say what it is worth. */
static void publish(nesp_radar_t *radar, bool well, uint32_t now_ms)
{
    if (well) {
        uint8_t count = radar->near_count;
        bool renamed = !radar->held;
        for (uint8_t slot = 0; slot < TARGETS; slot++) {
            uint8_t names[NAMES];
            memset(names, ' ', NAMES);
            if (slot < count) {
                memcpy(radar->motion[slot], radar->near[slot].motion, MOTION);
                radar->motion[slot][0] |= slot;
                memcpy(names, radar->near[slot].names, NAMES);
            }
            names[0] = slot;
            renamed = renamed || memcmp(names, radar->names[slot], NAMES) != 0;
            memcpy(radar->names[slot], names, NAMES);
        }
        radar->count = count;
        radar->flags = radar->total > TARGETS ? NESP_SCENE_TRUNCATED : 0;
        radar->good = true;
        radar->good_at = now_ms;
        if (renamed) {
            radar->names_serial = next(radar->names_serial);
        }
    } else {
        if (!radar->held) {
            for (uint8_t slot = 0; slot < TARGETS; slot++) {
                memset(radar->names[slot], ' ', NAMES);
                radar->names[slot][0] = slot;
            }
            radar->names_serial = next(radar->names_serial);
        }
        radar->flags = (uint8_t)((radar->flags & NESP_SCENE_TRUNCATED) | NESP_SCENE_DOWN);
        if (!radar->good || now_ms - radar->good_at >= NESP_RADAR_STALE_MS) {
            radar->flags |= NESP_SCENE_STALE;
        }
    }
    radar->held = true;
    radar->serial = next(radar->serial);
    show(radar);
}

/* A fetch of this address, for the fetch's task to read as a place or as
 * aircraft. False if it could not be started. */
static bool begin(nesp_radar_t *radar, const char *url, bool lookup)
{
    lock(radar);
    radar->generation++;
    radar->landed = 0;
    uint32_t id = radar->generation;
    unlock(radar);
    radar->lookup = lookup;         /* nothing is being read: the last fetch has landed */
    radar->fetching = online(radar)
                      && radar->hal->fetch(radar->hal->ctx, url, AGENT, id, &radar->sink);
    return radar->fetching;
}

static void fetch(nesp_radar_t *radar, uint32_t now_ms)
{
    char url[128];
    radar->fetched = true;
    radar->fetch_at = now_ms;
    radar->here[0] = radar->latitude / 1e6;
    radar->here[1] = radar->longitude / 1e6;
    snprintf(url, sizeof(url), SOURCE "/lat/%.6f/lon/%.6f/dist/%d", radar->here[0],
             radar->here[1], ASKED_NM);
    if (!begin(radar, url, false)) {
        publish(radar, false, now_ms);
    }
}

/* Ask where the airport is. */
static void look(nesp_radar_t *radar)
{
    char url[sizeof(WHERE) + 4 + sizeof(WHERE_END)];
    memcpy(url, WHERE, sizeof(WHERE) - 1);
    memcpy(url + sizeof(WHERE) - 1, radar->code, 4);
    memcpy(url + sizeof(WHERE) + 3, WHERE_END, sizeof(WHERE_END));
    if (!begin(radar, url, true)) {
        radar->place = PLACE_FAILED;
    }
}

/* The asking has ended: the place it brought, if it brought one that is a
 * place on the earth. A whole answer with none is no such airport. */
static void located(nesp_radar_t *radar, bool well)
{
    double east, north;
    char *end;
    if (!well) {
        radar->place = PLACE_FAILED;
        return;
    }
    radar->place = PLACE_NONE;
    if (!radar->spotted) {
        return;
    }
    east = strtod(radar->spot, &end);
    if (end == radar->spot || *end != ' ') {
        return;
    }
    const char *second = end;
    north = strtod(second, &end);
    if (end == second || *end != 0 || !(north >= -90.0 && north <= 90.0)
        || !(east >= -180.0 && east <= 180.0)) {
        return;
    }
    radar->latitude = (int32_t)nearbyint(north * 1e6);
    radar->longitude = (int32_t)nearbyint(east * 1e6);
    radar->place = PLACE_KNOWN;
    radar->known = true;
    memcpy(radar->known_code, radar->code, 4);
    radar->known_latitude = radar->latitude;
    radar->known_longitude = radar->longitude;
    show(radar);
}

static bool tick(void *ctx, uint32_t now_ms)
{
    nesp_radar_t *radar = ctx;
    if (radar->asked || !radar->timed) {
        radar->asked = false;
        radar->timed = true;
        radar->asked_at = now_ms;
    }
    if (!radar->chosen) {
        return false;
    }
    if (radar->fetching) {
        lock(radar);
        uint8_t landed = radar->landed;
        radar->landed = 0;
        unlock(radar);
        if (landed == 0) {
            return false;
        }
        radar->fetching = false;
        if (radar->lookup) {
            located(radar, landed == LANDED_WELL);
        } else {
            publish(radar, landed == LANDED_WELL, now_ms);
        }
    }
    if (now_ms - radar->asked_at >= NESP_RADAR_UNASKED_MS) {
        return false;               /* nobody is looking */
    }
    if (radar->place == PLACE_UNKNOWN) {
        if (online(radar)) {
            look(radar);
        }
    } else if (radar->place == PLACE_KNOWN
               && (!radar->fetched || now_ms - radar->fetch_at >= NESP_RADAR_POLL_MS)) {
        fetch(radar, now_ms);
    }
    return false;
}

static void airport(nesp_radar_t *radar, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 5) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    const uint8_t *code = request->data + 1;
    for (size_t index = 0; index < 4; index++) {
        if (code[index] < 'A' || code[index] > 'Z') {
            reply->status = NESP_ST_BAD_ARG;
            return;
        }
    }
    if (!radar->chosen || radar->airport_id != request->data[0]
        || memcmp(radar->code, code, 4) != 0) {
        drop(radar);
        radar->chosen = true;
        radar->airport_id = request->data[0];
        memcpy(radar->code, code, 4);
        radar->place = PLACE_UNKNOWN;
        if (radar->known && memcmp(radar->known_code, code, 4) == 0) {
            radar->latitude = radar->known_latitude;
            radar->longitude = radar->known_longitude;
            radar->place = PLACE_KNOWN;
        }
        show(radar);
    }
    radar->asked = true;
    reply->data[0] = state(radar);
    reply->data[1] = radar->airport_id;
    reply->len = 2;
    reply->once = true;             /* the same request again asks how it stands now */
}

/* Is the request about the airport that is chosen? If not the reply says
 * IDLE of the airport it named, and the console chooses it again. */
static bool about(nesp_radar_t *radar, const nesp_request_t *request, nesp_reply_t *reply)
{
    reply->once = true;
    reply->data[1] = request->data[0];
    if (radar->chosen && radar->airport_id == request->data[0]) {
        radar->asked = true;
        reply->data[0] = state(radar);
        return true;
    }
    reply->data[0] = NESP_SCOPE_IDLE;
    return false;
}

static void scene(nesp_radar_t *radar, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || reply->max < 6 + TARGETS * MOTION) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    reply->len = 4;
    reply->data[2] = 0;
    reply->data[3] = 0;
    if (!about(radar, request, reply) || reply->data[0] != NESP_SCOPE_READY) {
        return;
    }
    reply->data[2] = radar->serial;
    reply->data[3] = radar->names_serial;
    if (request->data[1] == radar->serial) {
        return;                     /* the console has it */
    }
    reply->data[4] = radar->flags;
    reply->data[5] = radar->count;
    memcpy(reply->data + 6, radar->motion, (size_t)radar->count * MOTION);
    reply->len = (uint8_t)(6 + radar->count * MOTION);
}

static void identity(nesp_radar_t *radar, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || request->data[1] >= TARGETS || reply->max < 3 + NAMES) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    reply->len = 3;
    reply->data[2] = 0;
    if (!about(radar, request, reply) || reply->data[0] != NESP_SCOPE_READY) {
        return;
    }
    reply->data[2] = radar->names_serial;
    memcpy(reply->data + 3, radar->names[request->data[1]], NAMES);
    reply->len = 3 + NAMES;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_radar_t *radar = ctx;
    switch (request->op) {
    case NESP_RADAR_AIRPORT:
        airport(radar, request, reply);
        break;
    case NESP_RADAR_SCENE:
        scene(radar, request, reply);
        break;
    case NESP_RADAR_IDENTITY:
        identity(radar, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

static void activate(void *ctx)
{
    nesp_radar_t *radar = ctx;
    drop(radar);
    radar->chosen = false;
    radar->asked = false;
    radar->timed = false;
}

/* Another ROM is on the console, or this one was reset. */
static void deactivate(void *ctx)
{
    nesp_radar_t *radar = ctx;
    drop(radar);
    radar->chosen = false;
    radar->hal->show(radar->hal->ctx, 0, "");
}

void nesp_radar_service(nesp_service_t *service, nesp_radar_t *radar, const nesp_hal_t *hal)
{
    memset(radar, 0, sizeof(*radar));
    radar->hal = hal;
    radar->sink.ctx = radar;
    radar->sink.body = body;
    radar->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_RADAR;
    service->name = "RADAR";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->ctx = radar;
}

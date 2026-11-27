/* WEATHER: the weather at a place, as rows for a console's screen
 * (docs/PROTOCOL.md).
 *
 * The console names a place as it was typed, "PORTLAND, ME" or "DUBLIN,
 * IRELAND", or by a US zip code. The nesp32 asks Open-Meteo's geocoding
 * where that is and what it is called, takes the first place it gives,
 * once, and keeps the answer over power-off; then asks Open-Meteo for the
 * weather there, now and for five days, and lays it out as
 * NESP_WEATHER_ROWS rows of NESP_WEATHER_COLUMNS tiles, pictures and all.
 * The console asks for the rows by number and draws them: it works nothing
 * out. A place in the United States has its weather in degrees Fahrenheit
 * and miles an hour, and every other in degrees Celsius and kilometres an
 * hour.
 *
 * PLACE (and ZIP) is both "this place" and "how does it stand", as RADAR's
 * AIRPORT is. The console gives each choice an id and may send the same
 * request as often as it likes: an id or a place that is new chooses it,
 * and the same again only answers.
 *
 * Two tasks meet here, as in radar.c. The link's task runs handle() and
 * tick(), and the report is its alone. The fetch's task runs body() and
 * done(): it keeps the reply, which is small, whole, and when the reply
 * has ended says so (`landed`, under the hal's lock), and touches nothing
 * more until the link's task has read it and begun another fetch.
 * `generation` is which fetch is wanted.
 *
 * The clock is tick()'s: a fetch every NESP_WEATHER_POLL_MS while the
 * console goes on asking, and sooner after one that failed.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "nesp_services.h"

#define ROWS NESP_WEATHER_ROWS
#define COLUMNS NESP_WEATHER_COLUMNS
#define ZIP NESP_WEATHER_ZIP_LEN
#define QUERY NESP_WEATHER_QUERY_MAX
#define PLACE NESP_WEATHER_PLACE_MAX
#define DAYS NESP_WEATHER_DAYS
#define AGENT "nesp32-weather/0.2 (Weather on a nesp32; +https://github.com/Armitage64/nesp32)"
/* Where a place is: {"results": [{"name": "Portland", "latitude": 43.65737,
 * "longitude": -70.2589, "country_code": "US", "admin1": "Maine", ...}],
 * ...}, the likeliest first. A place there is none of has no "results". A
 * zip code is asked for with &countryCode=US, since other countries' post
 * codes have five digits too. */
#define WHERE "https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json"
#define WHERE_US "&countryCode=US"
#define NO_SUCH "THE SITE SAID 404"
/* The weather there: {"current": {"temperature_2m": 71.8, ...}, "daily":
 * {"time": ["2026-10-13", ...], "weather_code": [3, ...], ...}, ...}, in
 * the place's units, its days the place's own. */
#define SOURCE "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f" \
               "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,is_day" \
               "&daily=weather_code,temperature_2m_max,temperature_2m_min" \
               "&forecast_days=5&temperature_unit=%s&wind_speed_unit=%s&timezone=auto"
#define NONSENSE "THE SITE MADE NO SENSE"

#define LANDED_WELL 1
#define LANDED_BADLY 2
#define LANDED_NONE 3               /* the site has nothing by that name */

/* What is known of where the place is. */
#define PLACE_UNKNOWN 0             /* not asked yet, or being asked */
#define PLACE_KNOWN 1
#define PLACE_NONE 2                /* nothing goes by that name */
#define PLACE_FAILED 3              /* the asking failed */

/* The report: where on it things are. */
#define ROW_PLACE 0
#define ROW_NOW 2                   /* the picture's two rows, and the words beside them */
#define ROW_AIR 4                   /* the humidity, and under it the wind */
#define ROW_DAYS 8                  /* the days' names; under each its picture, high and low */
#define COLUMN_NOW 4
static const uint8_t day_column[DAYS] = {1, 7, 13, 19, 25};

/* The places whose weather is in degrees Fahrenheit: the United States and
 * the territories the geocoding gives countries of their own. */
static const char imperial_countries[][3] = {"US", "PR", "GU", "VI", "AS", "MP"};

/* A state's two letters, for "PORTLAND, ME": the geocoding gives its name. */
static const struct {
    const char *name;
    char code[3];
} states[] = {
    {"ALABAMA", "AL"}, {"ALASKA", "AK"}, {"ARIZONA", "AZ"}, {"ARKANSAS", "AR"},
    {"CALIFORNIA", "CA"}, {"COLORADO", "CO"}, {"CONNECTICUT", "CT"}, {"DELAWARE", "DE"},
    {"DISTRICT OF COLUMBIA", "DC"}, {"FLORIDA", "FL"}, {"GEORGIA", "GA"}, {"HAWAII", "HI"},
    {"IDAHO", "ID"}, {"ILLINOIS", "IL"}, {"INDIANA", "IN"}, {"IOWA", "IA"}, {"KANSAS", "KS"},
    {"KENTUCKY", "KY"}, {"LOUISIANA", "LA"}, {"MAINE", "ME"}, {"MARYLAND", "MD"},
    {"MASSACHUSETTS", "MA"}, {"MICHIGAN", "MI"}, {"MINNESOTA", "MN"}, {"MISSISSIPPI", "MS"},
    {"MISSOURI", "MO"}, {"MONTANA", "MT"}, {"NEBRASKA", "NE"}, {"NEVADA", "NV"},
    {"NEW HAMPSHIRE", "NH"}, {"NEW JERSEY", "NJ"}, {"NEW MEXICO", "NM"}, {"NEW YORK", "NY"},
    {"NORTH CAROLINA", "NC"}, {"NORTH DAKOTA", "ND"}, {"OHIO", "OH"}, {"OKLAHOMA", "OK"},
    {"OREGON", "OR"}, {"PENNSYLVANIA", "PA"}, {"RHODE ISLAND", "RI"},
    {"SOUTH CAROLINA", "SC"}, {"SOUTH DAKOTA", "SD"}, {"TENNESSEE", "TN"}, {"TEXAS", "TX"},
    {"UTAH", "UT"}, {"VERMONT", "VT"}, {"VIRGINIA", "VA"}, {"WASHINGTON", "WA"},
    {"WEST VIRGINIA", "WV"}, {"WISCONSIN", "WI"}, {"WYOMING", "WY"},
};

static void lock(nesp_weather_t *weather)
{
    weather->hal->lock(weather->hal->ctx);
}

static void unlock(nesp_weather_t *weather)
{
    weather->hal->unlock(weather->hal->ctx);
}

/* --- a reply, read ------------------------------------------------------------- */

/* A value in a reply, as it is written: a string with its quotes. */
typedef struct {
    const char *at;
    size_t len;
} span_t;

static bool is_space(char letter)
{
    return letter == ' ' || (letter >= '\t' && letter <= '\r');
}

/* Past a string that begins at `at`, a quote: where the character after
 * its closing quote is. */
static const char *past_string(const char *at, const char *end)
{
    at++;
    while (at < end && *at != '"') {
        at += *at == '\\' ? 2 : 1;
    }
    return at < end ? at + 1 : end;
}

static const char *past_value(const char *at, const char *end)
{
    if (at >= end) {
        return end;
    }
    if (*at == '"') {
        return past_string(at, end);
    }
    if (*at == '{' || *at == '[') {
        unsigned depth = 0;
        do {
            if (*at == '"') {
                at = past_string(at, end);
                continue;
            }
            if (*at == '{' || *at == '[') {
                depth++;
            } else if (*at == '}' || *at == ']') {
                depth--;
            }
            at++;
        } while (at < end && depth > 0);
        return at;
    }
    while (at < end && *at != ',' && *at != '}' && *at != ']' && !is_space(*at)) {
        at++;
    }
    return at;
}

/* The reply, if it is an object and all of it came: less the space round
 * it. One that was cut short may still have in it what is looked for. */
static bool entire(const char *at, size_t len, span_t *out)
{
    const char *end = at + len;
    while (at < end && is_space(*at)) {
        at++;
    }
    while (end > at && is_space(end[-1])) {
        end--;
    }
    if (at >= end || *at != '{' || past_value(at, end) != end) {
        return false;
    }
    /* Its last brace is the one that closes it, and not one inside. */
    unsigned depth = 0;
    for (const char *each = at; each < end; each++) {
        if (*each == '"') {
            each = past_string(each, end) - 1;
        } else if (*each == '{' || *each == '[') {
            depth++;
        } else if (*each == '}' || *each == ']') {
            depth--;
        }
    }
    if (depth != 0) {
        return false;
    }
    out->at = at;
    out->len = (size_t)(end - at);
    return true;
}

/* What an object has by this name. False if it has none. */
static bool member(span_t object, const char *name, span_t *out)
{
    const char *at = object.at;
    const char *end = object.at + object.len;
    size_t name_len = strlen(name);
    if (at >= end || *at != '{') {
        return false;
    }
    at++;
    for (;;) {
        while (at < end && (is_space(*at) || *at == ',')) {
            at++;
        }
        if (at >= end || *at != '"') {
            return false;
        }
        const char *key = at + 1;
        at = past_string(at, end);
        if (at >= end) {
            return false;
        }
        bool wanted = (size_t)(at - key) - 1 == name_len && memcmp(key, name, name_len) == 0;
        while (at < end && (is_space(*at) || *at == ':')) {
            at++;
        }
        const char *begins = at;
        at = past_value(at, end);
        if (at == begins) {
            return false;
        }
        if (wanted) {
            out->at = begins;
            out->len = (size_t)(at - begins);
            return true;
        }
    }
}

/* One of a list's, counted from 0. False if it has not that many. */
static bool item(span_t list, unsigned index, span_t *out)
{
    const char *at = list.at;
    const char *end = list.at + list.len;
    if (at >= end || *at != '[') {
        return false;
    }
    at++;
    for (;;) {
        while (at < end && (is_space(*at) || *at == ',')) {
            at++;
        }
        if (at >= end || *at == ']') {
            return false;
        }
        const char *begins = at;
        at = past_value(at, end);
        if (at == begins) {
            return false;
        }
        if (index-- == 0) {
            out->at = begins;
            out->len = (size_t)(at - begins);
            return true;
        }
    }
}

/* A string's characters, less its quotes. False if it is not one. */
static bool string(span_t value, span_t *out)
{
    if (value.len < 2 || value.at[0] != '"' || value.at[value.len - 1] != '"') {
        return false;
    }
    out->at = value.at + 1;
    out->len = value.len - 2;
    return true;
}

/* A number, or a string that is one. */
static bool number(span_t value, double *out)
{
    char text[32];
    span_t inside;
    if (string(value, &inside)) {
        value = inside;
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

static bool number_of(span_t object, const char *name, double *out)
{
    span_t value;
    return member(object, name, &value) && number(value, out);
}

static bool number_at(span_t object, const char *name, unsigned index, double *out)
{
    span_t list, value;
    return member(object, name, &list) && item(list, index, &value) && number(value, out);
}

/* A character for a row: a capital, a digit or a sign, whatever it was. */
static char tile(char letter)
{
    if (letter >= 'a' && letter <= 'z') {
        return (char)(letter - 'a' + 'A');
    }
    return letter >= 0x20 && letter <= 0x5F ? letter : '?';
}

static int hex_digit(char letter)
{
    if (letter >= '0' && letter <= '9') {
        return letter - '0';
    }
    if (letter >= 'a' && letter <= 'f') {
        return letter - 'a' + 10;
    }
    if (letter >= 'A' && letter <= 'F') {
        return letter - 'A' + 10;
    }
    return -1;
}

/* A string of a reply as tiles: its escapes undone, and what is not ASCII
 * made the nearest thing that is. Returns how many were written, at most
 * max. */
static size_t tiles(span_t value, char *out, size_t max)
{
    span_t text;
    size_t count = 0;
    if (!string(value, &text)) {
        return 0;
    }
    const uint8_t *at = (const uint8_t *)text.at;
    const uint8_t *end = at + text.len;
    while (at < end && count < max) {
        uint32_t code = *at++;
        if (code == '\\' && at < end) {
            code = *at++;
            if (code == 'u' && end - at >= 4) {
                code = 0;
                for (int digit = 0; digit < 4; digit++) {
                    int value_of = hex_digit((char)at[digit]);
                    code = code << 4 | (uint32_t)(value_of < 0 ? 0 : value_of);
                }
                at += 4;
            } else if (code != '"' && code != '\\' && code != '/') {
                code = ' ';         /* a tab, a newline */
            }
        } else if (code >= 0xC0) {
            unsigned more = code >= 0xF0 ? 3 : code >= 0xE0 ? 2 : 1;
            code &= 0x3Fu >> more;
            while (more-- > 0 && at < end && (*at & 0xC0) == 0x80) {
                code = code << 6 | (*at++ & 0x3Fu);
            }
        }
        char near[4];
        int length = nesp_to_ascii(code, near);
        if (length < 0) {
            near[0] = '?';
            length = 1;
        }
        for (int index = 0; index < length && count < max; index++) {
            out[count++] = tile(near[index]);
        }
    }
    return count;
}

/* --- the fetch's task ---------------------------------------------------------- */

static bool current(nesp_weather_t *weather, uint32_t id)
{
    lock(weather);
    bool same = weather->generation == id;
    unlock(weather);
    return same;
}

/* The fetch's task begins on a reply: nothing of it has come. */
static void opened(nesp_weather_t *weather, uint32_t id)
{
    if (weather->parsing != id) {
        weather->parsing = id;
        weather->reply_len = 0;
        weather->long_reply = false;
        weather->said_len = 0;
    }
}

static void say(nesp_weather_t *weather, const char *words)
{
    size_t length = strlen(words);
    if (length > sizeof(weather->said)) {
        length = sizeof(weather->said);
    }
    for (size_t index = 0; index < length; index++) {
        weather->said[index] = tile(words[index]);
    }
    weather->said_len = (uint8_t)length;
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_weather_t *weather = ctx;
    if (!current(weather, id)) {
        return false;
    }
    opened(weather, id);
    if (len > sizeof(weather->reply) - weather->reply_len) {
        weather->long_reply = true;
        return false;               /* neither site says this much */
    }
    memcpy(weather->reply + weather->reply_len, data, len);
    weather->reply_len = (uint16_t)(weather->reply_len + len);
    return true;
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_weather_t *weather = ctx;
    if (!current(weather, id)) {
        return;
    }
    opened(weather, id);
    uint8_t how = LANDED_WELL;
    if (!ok) {
        how = why != NULL && strcmp(why, NO_SUCH) == 0 ? LANDED_NONE : LANDED_BADLY;
        say(weather, why != NULL && why[0] != 0 ? why : "THE FETCH FAILED");
    } else if (weather->long_reply) {
        how = LANDED_BADLY;
        say(weather, NONSENSE);
    }
    lock(weather);
    if (weather->generation == id) {
        weather->landed = how;
    }
    unlock(weather);
}

/* --- the link's task: the report ----------------------------------------------- */

static uint8_t next(uint8_t serial)
{
    return serial == 0xFF ? 1 : (uint8_t)(serial + 1);
}

static bool online(const nesp_weather_t *weather)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    weather->hal->wifi(weather->hal->ctx, &wifi);
    return wifi.state == NESP_WIFI_JOINED;
}

/* How it stands, as the console is told. */
static uint8_t state(const nesp_weather_t *weather)
{
    if (!weather->chosen) {
        return NESP_SKY_IDLE;
    }
    if (weather->place == PLACE_NONE) {
        return NESP_SKY_NOT_FOUND;
    }
    if (weather->place == PLACE_FAILED) {
        return NESP_SKY_FAILED;
    }
    if (weather->held) {
        return NESP_SKY_READY;
    }
    if (weather->failed) {
        return NESP_SKY_FAILED;
    }
    if (!online(weather)) {
        return NESP_SKY_NO_WIFI;
    }
    return weather->place == PLACE_KNOWN ? NESP_SKY_FETCHING : NESP_SKY_LOOKING;
}

/* Why it failed, for the console's screen: the fetch's words, or these. */
static void why_is(nesp_weather_t *weather, const char *words)
{
    if (words != NULL) {
        say(weather, words);
    }
    memcpy(weather->why, weather->said, weather->said_len);
    weather->why_len = weather->said_len;
}

/* Text on a row from a column, as far as the row goes. */
static void put(uint8_t *row, size_t column, const char *text)
{
    for (; *text != 0 && column < COLUMNS; column++) {
        row[column] = (uint8_t)*text++;
    }
}

/* A picture: two tiles on this row and two on the next. */
static void picture(uint8_t rows[ROWS][COLUMNS], size_t row, size_t column, uint8_t which)
{
    uint8_t first = (uint8_t)(NESP_WEATHER_PICTURE + 4 * which);
    rows[row][column] = first;
    rows[row][column + 1] = (uint8_t)(first + 1);
    rows[row + 1][column] = (uint8_t)(first + 2);
    rows[row + 1][column + 1] = (uint8_t)(first + 3);
}

/* What a weather code of the World Meteorological Organization's is, in a
 * word or two, and as a picture: by day, or by night where there is one. */
static const char *sky(long code, bool day, uint8_t *which)
{
    if (code <= 1) {
        *which = day ? NESP_PICTURE_SUN : NESP_PICTURE_MOON;
        return code == 0 ? "CLEAR" : "MOSTLY CLEAR";
    }
    if (code == 2) {
        *which = day ? NESP_PICTURE_PARTLY : NESP_PICTURE_CLOUD;
        return "PARTLY CLOUDY";
    }
    if (code == 3) {
        *which = NESP_PICTURE_CLOUD;
        return "CLOUDY";
    }
    if (code == 45 || code == 48) {
        *which = NESP_PICTURE_FOG;
        return "FOG";
    }
    if (code >= 71 && code <= 77) {
        *which = NESP_PICTURE_SNOW;
        return "SNOW";
    }
    if (code == 85 || code == 86) {
        *which = NESP_PICTURE_SNOW;
        return "SNOW SHOWERS";
    }
    if (code >= 95 && code <= 99) {
        *which = NESP_PICTURE_STORM;
        return "THUNDERSTORM";
    }
    *which = NESP_PICTURE_RAIN;
    if (code >= 51 && code <= 55) {
        return "DRIZZLE";
    }
    if (code == 56 || code == 57) {
        return "FREEZING DRIZZLE";
    }
    if (code >= 61 && code <= 65) {
        return "RAIN";
    }
    if (code == 66 || code == 67) {
        return "FREEZING RAIN";
    }
    if (code >= 80 && code <= 82) {
        return "SHOWERS";
    }
    *which = NESP_PICTURE_CLOUD;    /* a code there is none of */
    return "";
}

/* To the nearest whole number, and one a row has room for. */
static long whole(double value)
{
    double near = nearbyint(value);
    return near < -99.0 ? -99 : near > 999.0 ? 999 : (long)near;
}

/* The day of the week of a date as the reply writes it, "2026-10-13":
 * 0 for Sunday. Less than 0 if it is not a date. */
static int weekday(span_t value)
{
    span_t text;
    if (!string(value, &text) || text.len < 10 || text.at[4] != '-' || text.at[7] != '-') {
        return -1;
    }
    long part[3] = {0, 0, 0};
    static const uint8_t begins[3] = {0, 5, 8};
    static const uint8_t digits[3] = {4, 2, 2};
    for (size_t index = 0; index < 3; index++) {
        for (size_t at = 0; at < digits[index]; at++) {
            char letter = text.at[begins[index] + at];
            if (letter < '0' || letter > '9') {
                return -1;
            }
            part[index] = part[index] * 10 + (letter - '0');
        }
    }
    if (part[1] < 1 || part[1] > 12 || part[2] < 1 || part[2] > 31) {
        return -1;
    }
    /* Days since the first of March of the year 0, a Wednesday. */
    long year = part[1] < 3 ? part[0] - 1 : part[0];
    long month = part[1] < 3 ? part[1] + 9 : part[1] - 3;
    long days = 365 * year + year / 4 - year / 100 + year / 400 + (153 * month + 2) / 5
                + part[2] - 1;
    return (int)((days + 3) % 7);
}

static bool imperial(const nesp_weather_t *weather)
{
    return (weather->here.flags & NESP_WEATHER_PLACE_IMPERIAL) != 0;
}

/* The reply as a report. False if it is not the weather. */
static bool lay_out(nesp_weather_t *weather, uint8_t rows[ROWS][COLUMNS], long *now)
{
    static const char *const names[7] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
    span_t reply, at_once, daily, dates, date;
    double temperature, code, value, high, low;
    uint8_t which;
    char text[64];

    if (!entire(weather->reply, weather->reply_len, &reply)
        || !member(reply, "current", &at_once) || !member(reply, "daily", &daily)
        || !member(daily, "time", &dates)
        || !number_of(at_once, "temperature_2m", &temperature)
        || !number_of(at_once, "weather_code", &code)) {
        return false;
    }
    memset(rows, ' ', ROWS * COLUMNS);
    memcpy(rows[ROW_PLACE], weather->here.name, PLACE);

    bool day = !number_of(at_once, "is_day", &value) || value != 0.0;
    const char *words = sky(whole(code), day, &which);
    picture(rows, ROW_NOW, 0, which);
    *now = whole(temperature);
    snprintf(text, sizeof(text), "%ld%c%c  %s", *now, NESP_WEATHER_DEGREE,
             imperial(weather) ? 'F' : 'C', words);
    put(rows[ROW_NOW], COLUMN_NOW, text);
    if (number_of(at_once, "relative_humidity_2m", &value)) {
        snprintf(text, sizeof(text), "HUMIDITY %ld%%", whole(value));
        put(rows[ROW_AIR], COLUMN_NOW, text);
    }
    if (number_of(at_once, "wind_speed_10m", &value)) {
        snprintf(text, sizeof(text), "WIND %ld %s", whole(value),
                 imperial(weather) ? "MPH" : "KM/H");
        put(rows[ROW_AIR + 1], COLUMN_NOW, text);
    }

    for (unsigned index = 0; index < DAYS; index++) {
        size_t column = day_column[index];
        int name = item(dates, index, &date) ? weekday(date) : -1;
        if (name < 0 || !number_at(daily, "weather_code", index, &code)
            || !number_at(daily, "temperature_2m_max", index, &high)
            || !number_at(daily, "temperature_2m_min", index, &low)) {
            return false;
        }
        put(rows[ROW_DAYS], column, names[name]);
        sky(whole(code), true, &which);
        picture(rows, ROW_DAYS + 1, column, which);
        snprintf(text, sizeof(text), "%ld", whole(high));
        put(rows[ROW_DAYS + 3], column, text);
        snprintf(text, sizeof(text), "%ld", whole(low));
        put(rows[ROW_DAYS + 4], column, text);
        if (index == 0) {           /* today's, with the weather now */
            snprintf(text, sizeof(text), "HIGH %ld%c  LOW %ld%c", whole(high),
                     NESP_WEATHER_DEGREE, whole(low), NESP_WEATHER_DEGREE);
            put(rows[ROW_NOW + 1], COLUMN_NOW, text);
        }
    }
    return true;
}

static void show(nesp_weather_t *weather, const char *text)
{
    weather->hal->show(weather->hal->ctx, 0, text);
}

/* No place's weather is wanted any more, or another's is. */
static void drop(nesp_weather_t *weather)
{
    weather->hal->fetch_stop(weather->hal->ctx);
    lock(weather);
    weather->generation++;
    weather->landed = 0;
    unlock(weather);
    weather->fetching = false;
    weather->fetched = false;
    weather->held = false;
    weather->failed = false;
}

/* A fetch of this address, for the fetch's task to keep the reply of.
 * False if it could not be started. */
static bool begin(nesp_weather_t *weather, const char *url, bool lookup)
{
    lock(weather);
    weather->generation++;
    weather->landed = 0;
    uint32_t id = weather->generation;
    unlock(weather);
    weather->lookup = lookup;       /* nothing is being read: the last fetch has landed */
    weather->fetching = weather->hal->fetch(weather->hal->ctx, url, AGENT, id, &weather->sink);
    return weather->fetching;
}

/* A fetch of the weather has ended: the report it brought, or the one
 * before, if there is one, and another try sooner. */
static void reported(nesp_weather_t *weather, uint8_t landed)
{
    uint8_t rows[ROWS][COLUMNS];
    char text[QUERY + 16];
    long now = 0;
    if (landed != LANDED_WELL) {
        weather->failed = true;
        why_is(weather, NULL);
        return;
    }
    if (!lay_out(weather, rows, &now)) {
        weather->failed = true;
        why_is(weather, NONSENSE);
        return;
    }
    memcpy(weather->rows, rows, sizeof(rows));
    weather->failed = false;
    weather->held = true;
    weather->serial = next(weather->serial);
    snprintf(text, sizeof(text), "%.*s: %ld%c", weather->here.query_len, weather->here.query,
             now, imperial(weather) ? 'F' : 'C');
    show(weather, text);
}

static void fetch(nesp_weather_t *weather, uint32_t now_ms)
{
    char url[400];
    weather->fetched = true;
    weather->fetch_at = now_ms;
    snprintf(url, sizeof(url), SOURCE, weather->here.latitude / 1e6,
             weather->here.longitude / 1e6, imperial(weather) ? "fahrenheit" : "celsius",
             imperial(weather) ? "mph" : "kmh");
    if (!begin(weather, url, false)) {
        weather->failed = true;
        why_is(weather, "THE NESP32 IS BUSY");
    }
}

/* Ask where the place is: its name as typed, with every character but a
 * letter or a digit written as %XX. */
static void look(nesp_weather_t *weather)
{
    static const char hex[] = "0123456789ABCDEF";
    char url[sizeof(WHERE) + sizeof(WHERE_US) + sizeof("&name=") + 3 * QUERY];
    size_t at = (size_t)snprintf(url, sizeof(url), "%s%s&name=", WHERE,
                                 (weather->here.flags & NESP_WEATHER_PLACE_US) ? WHERE_US : "");
    for (size_t index = 0; index < weather->here.query_len; index++) {
        uint8_t letter = (uint8_t)weather->here.query[index];
        if ((letter >= 'A' && letter <= 'Z') || (letter >= '0' && letter <= '9')) {
            url[at++] = (char)letter;
        } else {
            url[at++] = '%';
            url[at++] = hex[letter >> 4];
            url[at++] = hex[letter & 0x0F];
        }
    }
    url[at] = 0;
    if (!begin(weather, url, true)) {
        weather->place = PLACE_FAILED;
        why_is(weather, "THE NESP32 IS BUSY");
    }
}

/* Text for a row, as far as it goes: as tiles(), or nothing. */
static size_t text_of(span_t object, const char *name, char *out, size_t max)
{
    span_t value;
    return member(object, name, &value) ? tiles(value, out, max) : 0;
}

/* The report's first row for a place the geocoding gave: "PORTLAND, ME" in
 * the United States, "DUBLIN, LEINSTER, IE" elsewhere, or "TOKYO, JP" when
 * its region would not fit or is the city again. As much of the city's
 * name as leaves room for the rest. */
static void name_of(span_t first, char name[PLACE])
{
    char city[PLACE], region[48], country[2], after[PLACE];
    size_t city_len = text_of(first, "name", city, sizeof(city));
    size_t region_len = text_of(first, "admin1", region, sizeof(region));
    size_t country_len = text_of(first, "country_code", country, sizeof(country));
    size_t after_len = 0;
    bool state = false;
    if (country_len == 2 && memcmp(country, "US", 2) == 0) {
        for (size_t index = 0; index < sizeof(states) / sizeof(states[0]); index++) {
            if (region_len == strlen(states[index].name)
                && memcmp(region, states[index].name, region_len) == 0) {
                memcpy(after, states[index].code, 2);
                after_len = 2;
                state = true;
                break;
            }
        }
    }
    if (!state) {
        if (region_len > 0 && country_len > 0
            && !(region_len == city_len && memcmp(region, city, city_len) == 0)
            && city_len + 2 + region_len + 2 + country_len <= PLACE) {
            memcpy(after, region, region_len);
            after_len = region_len;
            after[after_len++] = ',';
            after[after_len++] = ' ';
        }
        memcpy(after + after_len, country, country_len);
        after_len += country_len;
    }
    memset(name, ' ', PLACE);
    size_t room = after_len > 0 ? PLACE - 2 - after_len : PLACE;
    size_t length = city_len < room ? city_len : room;
    memcpy(name, city, length);
    if (after_len > 0) {
        if (length > 0) {
            name[length++] = ',';
            length++;
        }
        memcpy(name + length, after, after_len);
    }
}

static bool imperial_country(span_t first)
{
    char country[2];
    if (text_of(first, "country_code", country, sizeof(country)) != 2) {
        return false;
    }
    for (size_t index = 0; index < sizeof(imperial_countries) / sizeof(imperial_countries[0]);
         index++) {
        if (memcmp(country, imperial_countries[index], 2) == 0) {
            return true;
        }
    }
    return false;
}

/* The asking has ended: the first place it brought, if it brought one that
 * is a place on the earth, and its name. */
static void located(nesp_weather_t *weather, uint8_t landed)
{
    span_t reply, results, first;
    double north, east;
    char text[QUERY + 1];
    if (landed == LANDED_NONE) {
        weather->place = PLACE_NONE;
        return;
    }
    weather->place = PLACE_FAILED;
    if (landed != LANDED_WELL) {
        why_is(weather, NULL);
        return;
    }
    why_is(weather, NONSENSE);
    if (!entire(weather->reply, weather->reply_len, &reply)) {
        return;
    }
    if (!member(reply, "results", &results) || !item(results, 0, &first)) {
        weather->place = PLACE_NONE;    /* the site knows of nothing by that name */
        return;
    }
    if (!number_of(first, "latitude", &north) || !number_of(first, "longitude", &east)
        || !(north >= -90.0 && north <= 90.0) || !(east >= -180.0 && east <= 180.0)) {
        return;
    }
    weather->here.latitude = (int32_t)nearbyint(north * 1e6);
    weather->here.longitude = (int32_t)nearbyint(east * 1e6);
    name_of(first, weather->here.name);
    weather->here.flags = (uint8_t)((weather->here.flags & NESP_WEATHER_PLACE_US)
                                    | (imperial_country(first) ? NESP_WEATHER_PLACE_IMPERIAL : 0));
    weather->place = PLACE_KNOWN;
    if (!weather->known || memcmp(&weather->kept, &weather->here, sizeof(weather->here)) != 0) {
        weather->known = true;
        weather->kept = weather->here;
        if (weather->hal->place_keep != NULL) {
            weather->hal->place_keep(weather->hal->ctx, &weather->kept);
        }
    }
    memcpy(text, weather->here.query, weather->here.query_len);
    text[weather->here.query_len] = 0;
    show(weather, text);
}

static bool tick(void *ctx, uint32_t now_ms)
{
    nesp_weather_t *weather = ctx;
    if (weather->asked || !weather->timed) {
        weather->asked = false;
        weather->timed = true;
        weather->asked_at = now_ms;
    }
    if (!weather->chosen) {
        return false;
    }
    if (weather->fetching) {
        lock(weather);
        uint8_t landed = weather->landed;
        weather->landed = 0;
        unlock(weather);
        if (landed == 0) {
            return false;
        }
        weather->fetching = false;
        if (weather->lookup) {
            located(weather, landed);
        } else {
            reported(weather, landed);
        }
    }
    if (now_ms - weather->asked_at >= NESP_WEATHER_UNASKED_MS || !online(weather)) {
        return false;               /* nobody is looking, or there is no asking */
    }
    if (weather->place == PLACE_UNKNOWN) {
        look(weather);
    } else if (weather->place == PLACE_KNOWN
               && (!weather->fetched
                   || now_ms - weather->fetch_at >= (weather->failed ? NESP_WEATHER_RETRY_MS
                                                                     : NESP_WEATHER_POLL_MS))) {
        fetch(weather, now_ms);
    }
    return false;
}

/* --- the link's task: the console's requests ----------------------------------- */

/* A place as the console gave it, made one the nesp32 asks after: its
 * characters, less the spaces round them. False if there are none, or one
 * is no character of a row's. */
static bool query_of(const uint8_t *text, size_t len, uint8_t flags, nesp_weather_place_t *out)
{
    while (len > 0 && text[0] == ' ') {
        text++;
        len--;
    }
    while (len > 0 && text[len - 1] == ' ') {
        len--;
    }
    if (len == 0 || len > QUERY) {
        return false;
    }
    memset(out, 0, sizeof(*out));
    for (size_t index = 0; index < len; index++) {
        if (text[index] < 0x20 || text[index] > 0x5F) {
            return false;
        }
        out->query[index] = (char)text[index];
    }
    out->query_len = (uint8_t)len;
    out->flags = flags;
    return true;
}

/* The same text. */
static bool same_text(const nesp_weather_place_t *one, const nesp_weather_place_t *other)
{
    return one->query_len == other->query_len
           && memcmp(one->query, other->query, one->query_len) == 0;
}

/* The same place, asked the same way. */
static bool same_query(const nesp_weather_place_t *one, const nesp_weather_place_t *other)
{
    return same_text(one, other)
           && (one->flags & NESP_WEATHER_PLACE_US) == (other->flags & NESP_WEATHER_PLACE_US);
}

/* PLACE, and ZIP, which is PLACE for a zip code: choose it if it is new,
 * and say how it stands. */
static void choose(nesp_weather_t *weather, uint8_t id, const nesp_weather_place_t *asked,
                   nesp_reply_t *reply)
{
    if (!weather->chosen || weather->choice_id != id || !same_query(&weather->here, asked)) {
        drop(weather);
        weather->chosen = true;
        weather->choice_id = id;
        weather->here = *asked;
        weather->place = PLACE_UNKNOWN;
        /* The place kept, by what was typed: and a zip code kept is the
         * same place typed in the form, which is how a ROM of places
         * gets one from firmware that knew only zip codes. */
        if (weather->known && same_text(&weather->kept, asked)) {
            weather->here = weather->kept;
            weather->here.flags = (uint8_t)((weather->kept.flags & ~NESP_WEATHER_PLACE_US)
                                            | (asked->flags & NESP_WEATHER_PLACE_US));
            weather->place = PLACE_KNOWN;
        }
        show(weather, "");
    }
    weather->asked = true;
    reply->data[0] = state(weather);
    reply->data[1] = weather->choice_id;
    reply->data[2] = weather->held ? weather->serial : 0;
    reply->len = 3;
    if (reply->data[0] == NESP_SKY_FAILED) {
        size_t length = weather->why_len;
        if (length > (size_t)(reply->max - 3)) {
            length = (size_t)(reply->max - 3);
        }
        memcpy(reply->data + 3, weather->why, length);
        reply->len = (uint8_t)(3 + length);
    }
    reply->once = true;             /* the same request again asks how it stands now */
}

static void zip(nesp_weather_t *weather, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_weather_place_t asked;
    if (request->len != 1 + ZIP) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    for (size_t index = 0; index < ZIP; index++) {
        if (request->data[1 + index] < '0' || request->data[1 + index] > '9') {
            reply->status = NESP_ST_BAD_ARG;
            return;
        }
    }
    query_of(request->data + 1, ZIP, NESP_WEATHER_PLACE_US, &asked);
    choose(weather, request->data[0], &asked, reply);
}

static void place(nesp_weather_t *weather, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_weather_place_t asked;
    if (request->len < 2 || !query_of(request->data + 1, request->len - 1u, 0, &asked)) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    choose(weather, request->data[0], &asked, reply);
}

static void row(nesp_weather_t *weather, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || request->data[1] >= ROWS || reply->max < 4 + COLUMNS) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    reply->once = true;
    reply->data[0] = NESP_SKY_IDLE;
    reply->data[1] = request->data[0];
    reply->data[2] = 0;
    reply->data[3] = request->data[1];
    reply->len = 4;
    if (!weather->chosen || weather->choice_id != request->data[0]) {
        return;                     /* another place's: the console chooses it again */
    }
    weather->asked = true;
    reply->data[0] = state(weather);
    if (reply->data[0] != NESP_SKY_READY) {
        return;
    }
    reply->data[2] = weather->serial;
    memcpy(reply->data + 4, weather->rows[request->data[1]], COLUMNS);
    reply->len = 4 + COLUMNS;
}

/* LAST: the digits of the last place found, if it was a zip code, for a
 * console from before PLACE to begin with: five bytes, or none. */
static void last(nesp_weather_t *weather, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 0) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (weather->known && (weather->kept.flags & NESP_WEATHER_PLACE_US)
        && weather->kept.query_len == ZIP) {
        memcpy(reply->data, weather->kept.query, ZIP);
        reply->len = ZIP;
    }
    reply->once = true;
}

/* LAST_PLACE: the last place found, as it was typed, or nothing. */
static void last_place(nesp_weather_t *weather, const nesp_request_t *request,
                       nesp_reply_t *reply)
{
    if (request->len != 0 || reply->max < QUERY) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (weather->known) {
        memcpy(reply->data, weather->kept.query, weather->kept.query_len);
        reply->len = weather->kept.query_len;
    }
    reply->once = true;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_weather_t *weather = ctx;
    switch (request->op) {
    case NESP_WEATHER_ZIP:
        zip(weather, request, reply);
        break;
    case NESP_WEATHER_PLACE:
        place(weather, request, reply);
        break;
    case NESP_WEATHER_ROW:
        row(weather, request, reply);
        break;
    case NESP_WEATHER_LAST:
        last(weather, request, reply);
        break;
    case NESP_WEATHER_LAST_PLACE:
        last_place(weather, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

static void activate(void *ctx)
{
    nesp_weather_t *weather = ctx;
    drop(weather);
    weather->chosen = false;
    weather->asked = false;
    if (!weather->known && weather->hal->place_last != NULL) {
        /* Nothing found since the power came on: what was kept from before. */
        weather->known = weather->hal->place_last(weather->hal->ctx, &weather->kept)
                         && weather->kept.query_len > 0 && weather->kept.query_len <= QUERY;
    }
    weather->timed = false;
}

/* Another ROM is on the console, or this one was reset. */
static void deactivate(void *ctx)
{
    nesp_weather_t *weather = ctx;
    drop(weather);
    weather->chosen = false;
    show(weather, "");
}

void nesp_weather_service(nesp_service_t *service, nesp_weather_t *weather,
                          const nesp_hal_t *hal)
{
    memset(weather, 0, sizeof(*weather));
    weather->hal = hal;
    weather->sink.ctx = weather;
    weather->sink.body = body;
    weather->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_WEATHER;
    service->name = "WEATHER";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->ctx = weather;
}

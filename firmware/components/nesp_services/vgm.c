/* VGM: a rip of a NES game's music, made into the .jbs file JUKE plays.
 *
 * nes-jukebox's converter (apps/jukebox/tools: vgm.py, vgm2jbs.py, jbs.py
 * and apu_model.py), in C, so that a nesp32 can be given the rips as they
 * are. Those files are the account of what is done here and why, and the
 * tests hold the two to the same bytes (tests/test_vgm.py). In short:
 *
 * 1. The rip's writes to the sound chip are read out with the time of each,
 *    and everything else in it is walked past.
 * 2. Each write is put on a grid of frames, 735 samples long. What the
 *    stream cannot carry is dropped (samples played by the chip, and sound
 *    written through $4011), $4017 is kept from interrupting the console,
 *    and a PAL rip's periods are rewritten for an NTSC console's pitch.
 * 3. A frame's writes become one record, the last value of each register in
 *    the order the console applies them, where that does the same as the
 *    writes did in their own order; and where it does not, several records
 *    in the order they came.
 *
 * It goes through the rip once, a frame at a time, and holds one frame.
 */
#include <string.h>

#include "nesp_services.h"

#define FRAME_SAMPLES 735
#define NTSC_CLOCK 1789773u
#define PAL_CLOCK 1662607u
#define SAMPLES_MAX 0x7FFFFFFFu     /* more than this is not a rip of anything */

#define REGISTERS 0x18              /* $4000-$4017 */
#define STATUS 0x15
#define FRAME_COUNTER 0x17
#define DMC_LEVEL 0x11
#define NOISE_PERIOD 0x0E
#define SWEEP_ENABLE 0x80
#define CHANNELS 0x0F
#define LEVEL_WRITES_MAX 4          /* more of $4011 in a frame is sampled sound */
#define PULSE_MUTE_BELOW 8
#define PERIOD_MAX 0x7FFu

#define OP_CHAIN 0x00
#define OP_CONTROL 0x80
#define CTRL_INIT 0x01
#define WAIT_MAX 0x7F
#define STAGED_MAX 64               /* writes the console's player stages in a frame */
#define INIT_WRITES 2

#define JBS_HEADER 24
#define JBS_LOOPS 0x01
#define JBS_PAL 0x02
#define TITLE_MAX 255
#define NO_LOOP 0xFFFFFFFFu

/* What a register is to the order of a frame's writes (apu_model.py). */
enum { NOT_STREAMED, PLAIN, SWEEP, LENGTH_LOAD, EVENT };
static const uint8_t kinds[REGISTERS] = {
    PLAIN, SWEEP, PLAIN, LENGTH_LOAD, PLAIN, SWEEP, PLAIN, LENGTH_LOAD,
    PLAIN, NOT_STREAMED, PLAIN, LENGTH_LOAD, PLAIN, NOT_STREAMED, PLAIN, LENGTH_LOAD,
    NOT_STREAMED, PLAIN, NOT_STREAMED, NOT_STREAMED, NOT_STREAMED, PLAIN, NOT_STREAMED, EVENT,
};
/* The channel a length load is of, as $4015 has it. */
static const uint8_t channel_bits[REGISTERS] = {
    0, 0, 0, 0x01, 0, 0, 0, 0x02, 0, 0, 0, 0x04, 0, 0, 0, 0x08,
};

/* A record's groups, in the order the console applies them. */
typedef struct {
    uint8_t bit;
    uint8_t count;
    uint8_t registers[4];
} group_t;
static const group_t groups[] = {
    {5, 1, {0x15}},
    {0, 4, {0x00, 0x01, 0x02, 0x03}},
    {1, 4, {0x04, 0x05, 0x06, 0x07}},
    {2, 3, {0x08, 0x0A, 0x0B}},
    {3, 3, {0x0C, 0x0E, 0x0F}},
    {4, 4, {0x10, 0x11, 0x12, 0x13}},
    {6, 1, {0x17}},
};
#define GROUPS (sizeof(groups) / sizeof(groups[0]))
/* A register's place in that order. */
static const uint8_t ranks[REGISTERS] = {
    1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 10, 11, 12, 0, 13, 14, 15, 16, 17, 18, 0, 0, 0, 19,
};

/* The values the console is known to hold. */
typedef struct {
    bool has[REGISTERS];
    uint8_t value[REGISTERS];
} held_t;

/* --- the rip ------------------------------------------------------------------- */

typedef struct {
    const uint8_t *data;
    size_t len;
    uint64_t pos;
    uint64_t end;
    uint64_t sample;
    uint32_t version;
    bool loops;                 /* the header gives a loop */
    uint64_t loop_pos;
    bool loop_found;
    uint64_t loop_sample;
    bool bad;
} rip_t;

static uint32_t u32(const rip_t *rip, uint64_t at)
{
    if (at + 4 > rip->len) {
        return 0;
    }
    const uint8_t *data = rip->data + at;
    return (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16
           | (uint32_t)data[3] << 24;
}

/* The length of a command that is only walked past. 0: there is none such. */
static uint8_t passed_length(uint8_t command, uint32_t version)
{
    if (command >= 0x30 && command <= 0x3F) {
        return 2;
    }
    if (command >= 0x40 && command <= 0x4E) {
        return version >= 0x160 ? 3 : 2;
    }
    if (command == 0x4F || command == 0x50) {
        return 2;
    }
    if (command >= 0x51 && command <= 0x5F) {
        return 3;
    }
    switch (command) {
    case 0x90: case 0x91: case 0x95: return 5;
    case 0x92: return 6;
    case 0x93: return 11;
    case 0x94: return 2;
    default: break;
    }
    if (command >= 0xA0 && command <= 0xBF) {
        return 3;
    }
    if (command >= 0xC0 && command <= 0xDF) {
        return 4;
    }
    if (command >= 0xE0) {
        return 5;
    }
    return 0;
}

/* The rip's next write to the chip. False at its end, or where it is not a
 * rip any more (rip->bad). */
static bool next_write(rip_t *rip, uint64_t *sample, uint8_t *reg, uint8_t *value)
{
    const uint8_t *data = rip->data;
    while (rip->pos < rip->end) {
        uint64_t pos = rip->pos;
        if (rip->loops && pos == rip->loop_pos) {
            rip->loop_found = true;
            rip->loop_sample = rip->sample;
        }
        uint8_t command = data[pos];
        if (command == 0xB4) {
            if (pos + 3 > rip->end) {
                rip->bad = true;
                return false;
            }
            rip->pos = pos + 3;
            /* Not a second chip's, and not the disk system's. */
            if (data[pos + 1] < 0x20) {
                *sample = rip->sample;
                *reg = data[pos + 1];
                *value = data[pos + 2];
                return true;
            }
        } else if (command == 0x61) {
            if (pos + 3 > rip->len) {
                rip->bad = true;
                return false;
            }
            rip->sample += (uint32_t)data[pos + 1] | (uint32_t)data[pos + 2] << 8;
            rip->pos = pos + 3;
        } else if (command == 0x62) {
            rip->sample += 735;
            rip->pos = pos + 1;
        } else if (command == 0x63) {
            rip->sample += 882;
            rip->pos = pos + 1;
        } else if (command >= 0x70 && command <= 0x7F) {
            rip->sample += (command & 0x0Fu) + 1u;
            rip->pos = pos + 1;
        } else if (command >= 0x80 && command <= 0x8F) {
            rip->sample += command & 0x0Fu;
            rip->pos = pos + 1;
        } else if (command == 0x66) {
            rip->pos = rip->end;
            return false;
        } else if (command == 0x67) {
            if (pos + 7 > rip->end || data[pos + 1] != 0x66) {
                rip->bad = true;
                return false;
            }
            rip->pos = pos + 7 + (u32(rip, pos + 3) & 0x7FFFFFFFu);
        } else if (command == 0x68) {
            rip->pos = pos + 12;
        } else {
            uint8_t length = passed_length(command, rip->version);
            if (length == 0) {
                rip->bad = true;
                return false;
            }
            rip->pos = pos + length;
        }
        if (rip->sample > SAMPLES_MAX) {
            rip->bad = true;
            return false;
        }
    }
    return false;
}

static uint32_t frame_of(uint64_t sample)
{
    return (uint32_t)((sample + FRAME_SAMPLES / 2) / FRAME_SAMPLES);
}

/* --- the order of a frame's writes (apu_model.py) ------------------------------ */

static bool is_redundant(uint8_t reg, uint8_t value, const held_t *held)
{
    if (!held->has[reg] || held->value[reg] != value) {
        return false;
    }
    return kinds[reg] == PLAIN || (kinds[reg] == SWEEP && !(value & SWEEP_ENABLE));
}

static bool is_event(uint8_t reg, uint8_t value)
{
    return kinds[reg] == LENGTH_LOAD || kinds[reg] == EVENT
           || (kinds[reg] == SWEEP && (value & SWEEP_ENABLE));
}

typedef struct {
    held_t registers;
    uint8_t enabled;
    uint8_t active;
} apu_t;

/* A frame's writes, in order: what they leave, and their events into
 * `events`, sorted. Returns how many events. */
static size_t run(apu_t *apu, const uint8_t (*writes)[2], size_t count, uint16_t *events)
{
    size_t made = 0;
    for (size_t index = 0; index < count; index++) {
        uint8_t reg = writes[index][0];
        uint8_t value = writes[index][1];
        if (reg == STATUS) {
            apu->enabled = value & CHANNELS;
            apu->active &= apu->enabled;
        } else if (kinds[reg] == LENGTH_LOAD && (apu->enabled & channel_bits[reg])) {
            apu->active |= channel_bits[reg];
        }
        if (is_event(reg, value)) {
            uint16_t event = (uint16_t)(reg << 8 | value);
            size_t at = made++;
            while (at > 0 && events[at - 1] > event) {
                events[at] = events[at - 1];
                at--;
            }
            events[at] = event;
        }
        apu->registers.has[reg] = true;
        apu->registers.value[reg] = value;
    }
    return made;
}

/* Are two orders of a frame's writes the same to the chip, whichever of its
 * channels were enabled and sounding before? */
static bool equivalent(nesp_vgm_t *work, const uint8_t (*first)[2], size_t first_count,
                       const uint8_t (*second)[2], size_t second_count, const held_t *held)
{
    static const uint8_t starts[3][2] = {{0, 0}, {CHANNELS, 0}, {CHANNELS, CHANNELS}};
    for (size_t start = 0; start < 3; start++) {
        apu_t a;
        a.registers = *held;
        a.enabled = starts[start][0];
        a.active = starts[start][1];
        if (held->has[STATUS]) {
            /* The console's enables are whatever $4015 last held. */
            a.enabled = held->value[STATUS] & CHANNELS;
            a.active &= a.enabled;
        }
        apu_t b = a;
        size_t made = run(&a, first, first_count, work->events[0]);
        if (run(&b, second, second_count, work->events[1]) != made
            || memcmp(work->events[0], work->events[1], made * sizeof(uint16_t)) != 0
            || a.enabled != b.enabled || a.active != b.active
            || memcmp(a.registers.has, b.registers.has, sizeof(a.registers.has)) != 0) {
            return false;
        }
        for (size_t reg = 0; reg < REGISTERS; reg++) {
            if (a.registers.has[reg] && a.registers.value[reg] != b.registers.value[reg]) {
                return false;
            }
        }
    }
    return true;
}

/* --- the stream ---------------------------------------------------------------- */

typedef struct {
    nesp_vgm_t *work;
    uint8_t *out;
    size_t max;
    size_t len;
    bool full;
    size_t stream_at;           /* where in out the stream begins */
    held_t held;
    uint32_t waiting;           /* frames with nothing in them, not yet written */
    bool loop;                  /* the loop's frame has been come to */
    uint32_t loop_frame;
    uint32_t loop_offset;
    bool pal;
    held_t source;              /* a PAL rip's periods, as it wrote them */
} stream_t;

static void put(stream_t *stream, uint8_t byte)
{
    if (stream->len < stream->max) {
        stream->out[stream->len++] = byte;
    } else {
        stream->full = true;
    }
}

static void put32(uint8_t *out, uint32_t value)
{
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
    out[2] = (uint8_t)(value >> 16);
    out[3] = (uint8_t)(value >> 24);
}

static void flush_wait(stream_t *stream)
{
    while (stream->waiting != 0 && !stream->full) {
        uint32_t step = stream->waiting < WAIT_MAX ? stream->waiting : WAIT_MAX;
        put(stream, (uint8_t)step);
        stream->waiting -= step;
    }
}

/* The loop begins at the frame about to be written: on a later pass the
 * console comes to it from the track's end, holding who knows what. */
static void begin_loop(stream_t *stream, uint32_t frame)
{
    flush_wait(stream);
    stream->loop = true;
    stream->loop_frame = frame;
    stream->loop_offset = (uint32_t)(stream->len - stream->stream_at);
    memset(&stream->held, 0, sizeof(stream->held));
}

/* A write record: writes of different registers, in the console's order. */
static void put_record(stream_t *stream, const uint8_t (*writes)[2], size_t count)
{
    held_t now;
    memset(&now, 0, sizeof(now));
    for (size_t index = 0; index < count; index++) {
        now.has[writes[index][0]] = true;
        now.value[writes[index][0]] = writes[index][1];
    }
    uint8_t header = 0x80;
    for (size_t index = 0; index < GROUPS; index++) {
        for (size_t at = 0; at < groups[index].count; at++) {
            if (now.has[groups[index].registers[at]]) {
                header |= (uint8_t)(1u << groups[index].bit);
            }
        }
    }
    put(stream, header);
    for (size_t index = 0; index < GROUPS; index++) {
        const group_t *group = &groups[index];
        if (!(header & (1u << group->bit))) {
            continue;
        }
        if (group->count > 1) {
            uint8_t mask = 0;
            for (size_t at = 0; at < group->count; at++) {
                if (now.has[group->registers[at]]) {
                    mask |= (uint8_t)(1u << at);
                }
            }
            put(stream, mask);
        }
        for (size_t at = 0; at < group->count; at++) {
            if (now.has[group->registers[at]]) {
                put(stream, now.value[group->registers[at]]);
            }
        }
    }
}

/* A frame's writes, as they came, into the stream. False: the console's
 * player could not stage them. */
static bool put_frame(stream_t *stream, bool first)
{
    nesp_vgm_t *work = stream->work;
    const uint8_t (*writes)[2] = (const uint8_t (*)[2])work->writes;
    size_t count = work->count;

    /* The usual case, one record: each register's last value, less what
     * could change nothing, in the console's order. */
    held_t last;
    memset(&last, 0, sizeof(last));
    for (size_t index = 0; index < count; index++) {
        last.has[writes[index][0]] = true;
        last.value[writes[index][0]] = writes[index][1];
    }
    uint8_t merged[REGISTERS][2];
    size_t merged_count = 0;
    for (size_t index = 0; index < GROUPS; index++) {
        for (size_t at = 0; at < groups[index].count; at++) {
            uint8_t reg = groups[index].registers[at];
            if (last.has[reg] && !is_redundant(reg, last.value[reg], &stream->held)) {
                merged[merged_count][0] = reg;
                merged[merged_count][1] = last.value[reg];
                merged_count++;
            }
        }
    }
    uint8_t (*kept)[2] = merged;
    size_t kept_count = merged_count;
    bool ordered = !equivalent(work, writes, count, (const uint8_t (*)[2])merged, merged_count,
                               &stream->held);
    if (ordered) {
        /* Otherwise they stay in their own order, a new record wherever
         * the console's order would be broken. */
        held_t held = stream->held;
        kept = work->kept;
        kept_count = 0;
        for (size_t index = 0; index < count; index++) {
            uint8_t reg = writes[index][0];
            uint8_t value = writes[index][1];
            if (is_redundant(reg, value, &held)) {
                continue;
            }
            held.has[reg] = true;
            held.value[reg] = value;
            kept[kept_count][0] = reg;
            kept[kept_count][1] = value;
            kept_count++;
        }
        if (!equivalent(work, writes, count, (const uint8_t (*)[2])kept, kept_count,
                        &stream->held)) {
            return false;
        }
    }
    if (kept_count == 0) {
        stream->waiting++;
        return true;
    }
    if (kept_count + (first ? (size_t)INIT_WRITES : 0u) > STAGED_MAX) {
        return false;
    }
    flush_wait(stream);
    size_t from = 0;
    for (size_t index = 1; ordered && index < kept_count; index++) {
        if (ranks[kept[index][0]] <= ranks[kept[index - 1][0]]) {
            put(stream, OP_CHAIN);
            put_record(stream, (const uint8_t (*)[2])(kept + from), index - from);
            from = index;
        }
    }
    put_record(stream, (const uint8_t (*)[2])(kept + from), kept_count - from);
    for (size_t index = 0; index < kept_count; index++) {
        stream->held.has[kept[index][0]] = true;
        stream->held.value[kept[index][0]] = kept[index][1];
    }
    return true;
}

/* --- a write, onto the grid ---------------------------------------------------- */

static bool add(nesp_vgm_t *work, uint8_t reg, uint8_t value)
{
    if (work->count == NESP_VGM_FRAME_WRITES) {
        return false;
    }
    work->writes[work->count][0] = reg;
    work->writes[work->count][1] = value;
    work->count++;
    return true;
}

/* A PAL rip's period, for the same pitch from an NTSC console's clock. The
 * pulse channels are silent below 8, and those are left alone. */
static uint32_t rescale(uint32_t period, bool pulse)
{
    if (pulse && period < PULSE_MUTE_BELOW) {
        return period;
    }
    uint64_t scaled = ((uint64_t)(period + 1) * NTSC_CLOCK * 2 + PAL_CLOCK) / (2 * PAL_CLOCK);
    return scaled - 1 > PERIOD_MAX ? PERIOD_MAX : (uint32_t)(scaled - 1);
}

/* A write of a PAL rip. A period is two registers, and writing the high one
 * starts the note again, so the low one alone is rewritten when it alone was
 * written. The noise's sixteen periods need nothing: the nearest NTSC one to
 * each PAL one is the one of the same number. */
static bool add_pal(stream_t *stream, uint8_t reg, uint8_t value)
{
    static const uint8_t timers[3][2] = {{0x02, 0x03}, {0x06, 0x07}, {0x0A, 0x0B}};
    for (size_t index = 0; index < 3; index++) {
        uint8_t low = timers[index][0];
        uint8_t high = timers[index][1];
        if (reg != low && reg != high) {
            continue;
        }
        stream->source.value[reg] = value;
        uint32_t period = (uint32_t)(stream->source.value[high] & 0x07u) << 8
                          | stream->source.value[low];
        uint32_t scaled = rescale(period, high != 0x0B);
        if (!add(stream->work, low, (uint8_t)scaled)) {
            return false;
        }
        return reg == low
               || add(stream->work, high, (uint8_t)((value & 0xF8u) | scaled >> 8));
    }
    return add(stream->work, reg, value);
}

/* --- the file ------------------------------------------------------------------ */

/* A title's character as the console's font has it. */
static void put_character(uint8_t *title, size_t *len, uint32_t character)
{
    if (*len < TITLE_MAX) {
        title[(*len)++] = character >= 0x20 && character < 0x7F ? (uint8_t)character : (uint8_t)'?';
    }
}

/* One of the strings of the rip's GD3 tag, by its number: UTF-16, each
 * ended by a zero. Returns how many characters were added. */
static size_t tag_string(const rip_t *rip, uint64_t at, uint64_t end, unsigned number,
                         uint8_t *title, size_t *len)
{
    const uint8_t *data = rip->data;
    size_t before = *len;
    while (at < end) {
        if (at + 2 > end) {
            /* Half a character, which Python reads as one it cannot. */
            if (number == 0) {
                put_character(title, len, 0xFFFD);
            }
            break;
        }
        uint32_t unit = (uint32_t)data[at] | (uint32_t)data[at + 1] << 8;
        at += 2;
        if (unit == 0) {
            if (number == 0) {
                break;
            }
            number--;
            continue;
        }
        if (unit >= 0xD800 && unit < 0xDC00 && at + 2 <= end
            && (data[at + 1] & 0xFC) == 0xDC) {
            at += 2;            /* a pair is one character */
        }
        if (number == 0) {
            put_character(title, len, unit);
        }
    }
    return *len - before;
}

/* The title: "game - track" from the rip's tag, or the name it was given. */
static size_t make_title(const rip_t *rip, uint32_t tag_offset, const char *name, uint8_t *title)
{
    size_t len = 0;
    uint64_t at = 0x14 + (uint64_t)tag_offset;
    if (tag_offset != 0 && at + 12 <= rip->len && memcmp(rip->data + at, "Gd3 ", 4) == 0) {
        uint64_t end = at + 12 + u32(rip, at + 8);
        if (end > rip->len) {
            end = rip->len;
        }
        /* The tag's first string is the track's name and its third the game's. */
        size_t game = tag_string(rip, at + 12, end, 2, title, &len);
        uint8_t track[TITLE_MAX];
        size_t track_len = 0;
        tag_string(rip, at + 12, end, 0, track, &track_len);
        if (game != 0 && track_len != 0) {
            for (const char *join = " - "; *join != 0; join++) {
                put_character(title, &len, (uint8_t)*join);
            }
        }
        for (size_t index = 0; index < track_len; index++) {
            put_character(title, &len, track[index]);
        }
    }
    if (len == 0 && name != NULL) {
        for (; *name != 0; name++) {
            /* The later bytes of a character of several are not ones of
             * their own. */
            if (((uint8_t)*name & 0xC0) != 0x80) {
                put_character(title, &len, (uint8_t)*name);
            }
        }
    }
    return len;
}

bool nesp_vgm_to_jbs(nesp_vgm_t *work, const uint8_t *vgm, size_t len, const char *name,
                     uint8_t *out, size_t max, size_t *out_len)
{
    rip_t rip;
    memset(&rip, 0, sizeof(rip));
    rip.data = vgm;
    rip.len = len;
    if (len < 4 || memcmp(vgm, "Vgm ", 4) != 0) {
        return false;
    }
    rip.version = u32(&rip, 0x08);
    uint64_t data_at = 0x40;
    if (rip.version >= 0x150 && u32(&rip, 0x34) != 0) {
        data_at = 0x34 + (uint64_t)u32(&rip, 0x34);
    }
    /* A field at or past the data belongs to a newer header, and is zero. */
#define HEADER(at) ((uint64_t)(at) + 4 <= data_at ? u32(&rip, (at)) : 0)
    uint32_t clock = (rip.version >= 0x161 ? HEADER(0x84) : 0) & 0x3FFFFFFFu;
    if (clock == 0) {
        return false;           /* no NES in this rip */
    }
    rip.end = len;
    if (u32(&rip, 0x04) != 0 && 0x04 + (uint64_t)u32(&rip, 0x04) < rip.end) {
        rip.end = 0x04 + (uint64_t)u32(&rip, 0x04);
    }
    if (HEADER(0x1C) != 0) {
        rip.loops = true;
        rip.loop_pos = 0x1C + (uint64_t)HEADER(0x1C);
    }
    uint32_t total_samples = HEADER(0x18);
    uint32_t tag_offset = HEADER(0x14);
#undef HEADER
    rip.pos = data_at;

    stream_t stream;
    memset(&stream, 0, sizeof(stream));
    stream.work = work;
    stream.out = out;
    stream.max = max;
    /* Nearer the PAL clock than the NTSC one. */
    stream.pal = (clock > PAL_CLOCK ? clock - PAL_CLOCK : PAL_CLOCK - clock)
                 < (clock > NTSC_CLOCK ? clock - NTSC_CLOCK : NTSC_CLOCK - clock);

    uint8_t title[TITLE_MAX];
    size_t title_len = make_title(&rip, tag_offset, name, title);
    if (max < JBS_HEADER + 1 + title_len) {
        return false;
    }
    memset(out, 0, JBS_HEADER);
    out[JBS_HEADER] = (uint8_t)title_len;
    memcpy(out + JBS_HEADER + 1, title, title_len);
    stream.len = stream.stream_at = JBS_HEADER + 1 + title_len;
    put(&stream, OP_CONTROL);
    put(&stream, CTRL_INIT);

    /* A rip often begins after its game enabled the channels, and the
     * console begins a track with them off: so they are enabled first, as
     * a player of rips does. */
    uint32_t frame = 0;
    uint32_t last = 0;          /* the frame of the rip's last write, kept or not */
    work->count = 0;
    add(work, STATUS, CHANNELS);

    uint32_t level_frame = 0;
    unsigned levels = 0;        /* writes of $4011 in level_frame */
    bool level_counted = false;
    uint64_t sample;
    uint8_t reg;
    uint8_t value;
    while (next_write(&rip, &sample, &reg, &value)) {
        uint32_t at = frame_of(sample);
        last = at;
        if (reg >= REGISTERS || kinds[reg] == NOT_STREAMED) {
            continue;
        }
        if (reg == DMC_LEVEL) {
            if (!level_counted || level_frame != at) {
                /* How many of them the frame has, this one and those to come. */
                rip_t ahead = rip;
                uint64_t ahead_sample;
                uint8_t ahead_reg;
                uint8_t ahead_value;
                level_counted = true;
                level_frame = at;
                levels = 1;
                while (next_write(&ahead, &ahead_sample, &ahead_reg, &ahead_value)
                       && frame_of(ahead_sample) == at) {
                    if (ahead_reg == DMC_LEVEL) {
                        levels++;
                    }
                }
            }
            if (levels > LEVEL_WRITES_MAX) {
                continue;
            }
            value &= 0x7F;
        } else if (reg == STATUS) {
            value &= CHANNELS;
        } else if (reg == FRAME_COUNTER) {
            value |= 0x40;      /* its interrupt off: nothing interrupts the receiver */
        }
        if (at != frame) {
            if (rip.loop_found && !stream.loop && frame_of(rip.loop_sample) == frame) {
                begin_loop(&stream, frame);
            }
            if (!put_frame(&stream, frame == 0)) {
                return false;
            }
            /* The frames between, with nothing in them. */
            uint32_t loop_at = frame_of(rip.loop_sample);
            if (rip.loop_found && !stream.loop && loop_at < at) {
                stream.waiting += loop_at - (frame + 1);
                begin_loop(&stream, loop_at);
                stream.waiting += at - loop_at;
            } else {
                stream.waiting += at - (frame + 1);
            }
            frame = at;
            work->count = 0;
        }
        if (!(stream.pal ? add_pal(&stream, reg, value) : add(work, reg, value))) {
            return false;
        }
    }
    if (rip.bad || (rip.loops && !rip.loop_found)) {
        return false;           /* the loop is not at a command */
    }
    uint32_t total = frame_of(total_samples);
    if (total < last + 1) {
        total = last + 1;
    }
    uint32_t loop_at = frame_of(rip.loop_sample);
    bool loops = rip.loop_found && loop_at < total;
    if (loops && !stream.loop && loop_at == frame) {
        begin_loop(&stream, frame);
    }
    if (!put_frame(&stream, frame == 0)) {
        return false;
    }
    if (loops && !stream.loop) {
        stream.waiting += loop_at - (frame + 1);
        begin_loop(&stream, loop_at);
        stream.waiting += total - loop_at;
    } else {
        stream.waiting += total - (frame + 1);
    }
    flush_wait(&stream);
    if (stream.full) {
        return false;
    }

    memcpy(out, "JBS\x1a", 4);
    out[4] = 1;
    out[5] = (uint8_t)((loops ? JBS_LOOPS : 0) | (stream.pal ? JBS_PAL : 0));
    put32(out + 8, total);
    put32(out + 12, loops ? stream.loop_frame : NO_LOOP);
    put32(out + 16, loops ? stream.loop_offset : 0);
    put32(out + 20, (uint32_t)(stream.len - stream.stream_at));
    *out_len = stream.len;
    return true;
}

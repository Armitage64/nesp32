/* A stream of bytes over datagrams, for PEER: what one nesp32 sends the
 * other, in order and all of it, over a network that may lose a packet,
 * bring one twice or bring two the wrong way round.
 *
 * A game sends a byte for each of its frames, and wants each one there
 * soon. A lost packet must not hold up what follows it, which is what a
 * TCP connection does while it waits to send the packet again. So every
 * datagram here carries all the bytes the other end has not yet said it
 * has, oldest first: the next one to arrive makes good whatever was lost
 * before it, and nothing waits for anything. The other end says what it
 * has in every datagram of its own.
 *
 * Each datagram also carries its sender's clock, and gives back the last
 * clock it heard with the time it was held added on, from which the other
 * end has how long the network takes there and back. And it carries a
 * note: four bytes of the service's, the latest only, for what one PEER
 * tells the other about the game.
 *
 * Nothing here touches a socket or a clock. The port (the firmware's
 * conn.c, or a test) says when it is, gives what came, and asks for what
 * to send.
 *
 *   0  'N', 'E'
 *   2  kind          NESP_ARQ_CALL, _ANSWER, _DATA, _BYE or _PUNCH; bit 7 set if
 *                    the clock given back is one
 *   3  count         bytes carried
 *   4  session[4]    the connection's name, of the caller's choosing
 *   8  base[2]       where in the stream the first byte carried is
 *   10 next[2]       where in the other's stream this end has got to
 *   12 clock[4]      the sender's, in microseconds
 *   16 back[4]       the other's last clock, and the time since it came
 *   20 note[4]
 *   24 the bytes
 *
 * Numbers are low byte first.
 */
#include <string.h>

#include "nesp_services.h"

#define AT_KIND 2
#define AT_COUNT 3
#define AT_SESSION 4
#define AT_BASE 8
#define AT_NEXT 10
#define AT_CLOCK 12
#define AT_BACK 16
#define AT_NOTE 20
#define KIND_BACK 0x80
/* With bytes not yet said to have come, a datagram goes again this often;
 * with none, this often, so that each end knows the other is there and
 * how long the network takes. */
#define AGAIN_US 8000
#define QUIET_US 50000

static void put16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *out, uint32_t value)
{
    put16(out, (uint16_t)value);
    put16(out + 2, (uint16_t)(value >> 16));
}

static uint16_t get16(const uint8_t *in)
{
    return (uint16_t)(in[0] | in[1] << 8);
}

static uint32_t get32(const uint8_t *in)
{
    return (uint32_t)get16(in) | (uint32_t)get16(in + 2) << 16;
}

uint32_t nesp_arq_ticks(uint32_t rtt_us)
{
    return (rtt_us / 2 + 9000 + 16666) / 16667;
}

void nesp_arq_open(nesp_arq_t *arq, uint32_t session)
{
    memset(arq, 0, sizeof(*arq));
    arq->session = session;
}

size_t nesp_arq_write(nesp_arq_t *arq, const uint8_t *data, size_t len)
{
    size_t room = (size_t)(NESP_ARQ_HELD - arq->out_len);
    if (len > room) {
        len = room;
    }
    memcpy(arq->out + arq->out_len, data, len);
    arq->out_len = (uint8_t)(arq->out_len + len);
    if (len != 0) {
        arq->fresh = true;
    }
    return len;
}

size_t nesp_arq_read(nesp_arq_t *arq, uint8_t *out, size_t max)
{
    if (max > arq->in_len) {
        max = arq->in_len;
    }
    memcpy(out, arq->in, max);
    arq->in_len = (uint8_t)(arq->in_len - max);
    memmove(arq->in, arq->in + max, arq->in_len);
    return max;
}

bool nesp_arq_due(const nesp_arq_t *arq, uint32_t now_us)
{
    uint32_t since = now_us - arq->sent_at;
    if (!arq->sent || arq->fresh) {
        return true;
    }
    return since >= (arq->out_len != 0 ? AGAIN_US : QUIET_US);
}

size_t nesp_arq_packet(nesp_arq_t *arq, uint8_t kind, uint32_t now_us, uint8_t *out)
{
    uint8_t count = arq->out_len < NESP_ARQ_CARRY ? arq->out_len : NESP_ARQ_CARRY;
    out[0] = 'N';
    out[1] = 'E';
    out[AT_KIND] = (uint8_t)(kind | (arq->heard ? KIND_BACK : 0));
    out[AT_COUNT] = count;
    put32(out + AT_SESSION, arq->session);
    put16(out + AT_BASE, arq->out_base);
    put16(out + AT_NEXT, arq->in_next);
    put32(out + AT_CLOCK, now_us);
    put32(out + AT_BACK, arq->their_clock + (now_us - arq->heard_at));
    memcpy(out + AT_NOTE, arq->note_out, NESP_ARQ_NOTE);
    memcpy(out + NESP_ARQ_HEADER, arq->out, count);
    arq->sent = true;
    arq->fresh = false;
    arq->sent_at = now_us;
    return (size_t)NESP_ARQ_HEADER + count;
}

size_t nesp_arq_punch(uint8_t *out)
{
    memset(out, 0, NESP_ARQ_HEADER);
    out[0] = 'N';
    out[1] = 'E';
    out[AT_KIND] = NESP_ARQ_PUNCH;
    return NESP_ARQ_HEADER;            /* session 0, which no connection is */
}

int nesp_arq_take(nesp_arq_t *arq, uint32_t now_us, const uint8_t *data, size_t len)
{
    if (len < NESP_ARQ_HEADER || data[0] != 'N' || data[1] != 'E'
        || len != (size_t)NESP_ARQ_HEADER + data[AT_COUNT] || data[AT_COUNT] > NESP_ARQ_CARRY
        || get32(data + AT_SESSION) != arq->session) {
        return -1;
    }
    uint8_t kind = data[AT_KIND] & (uint8_t)~KIND_BACK;
    /* What of this end's bytes the other has: they need not be kept. An
     * old datagram says less than is known, and is passed over. */
    uint16_t have = (uint16_t)(get16(data + AT_NEXT) - arq->out_base);
    if (have != 0 && have <= arq->out_len) {
        memmove(arq->out, arq->out + have, (size_t)(arq->out_len - have));
        arq->out_len = (uint8_t)(arq->out_len - have);
        arq->out_base = (uint16_t)(arq->out_base + have);
    }
    /* Its bytes: those past what has come, if they begin no later than
     * that, and as far as there is room. */
    uint16_t skip = (uint16_t)(arq->in_next - get16(data + AT_BASE));
    if (skip < data[AT_COUNT]) {
        size_t more = (size_t)(data[AT_COUNT] - skip);
        size_t room = (size_t)(NESP_ARQ_HELD - arq->in_len);
        if (more > room) {
            more = room;
        }
        memcpy(arq->in + arq->in_len, data + NESP_ARQ_HEADER + skip, more);
        arq->in_len = (uint8_t)(arq->in_len + more);
        arq->in_next = (uint16_t)(arq->in_next + more);
        if (more != 0) {
            arq->fresh = true;      /* say so soon: the other end need not send them again */
        }
    }
    /* The clocks. Only a newer datagram's count: one that came late would
     * say the network was slower than it is now. */
    uint32_t clock = get32(data + AT_CLOCK);
    if (!arq->heard || (int32_t)(clock - arq->their_clock) > 0) {
        arq->their_clock = clock;
        arq->heard_at = now_us;
        memcpy(arq->note_in, data + AT_NOTE, NESP_ARQ_NOTE);
        if (data[AT_KIND] & KIND_BACK) {
            uint32_t took = now_us - get32(data + AT_BACK);
            if (took < 0x80000000u) {
                arq->rtt_last = took;
                /* Smoothed: an eighth of the way to each new figure. */
                arq->rtt = arq->rtt_count == 0 ? took
                                               : arq->rtt + (uint32_t)((int32_t)(took - arq->rtt) / 8);
                if (arq->rtt_count == 0 || took < arq->rtt_least) {
                    arq->rtt_least = took;
                }
                arq->rtt_count++;
                uint32_t ticks = nesp_arq_ticks(took);
                arq->needs[(ticks > NESP_ARQ_NEEDS ? NESP_ARQ_NEEDS : ticks) - 1]++;
            }
        }
    }
    arq->heard = true;
    arq->last_at = now_us;
    return kind;
}

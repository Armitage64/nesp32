/* STUN (RFC 8489), as far as PEER needs it: asking a server on the
 * Internet what address and port a socket's datagrams come from, as the
 * world outside this network's router sees them. Two nesp32s that each
 * know theirs can be told the other's, and send to it.
 *
 * A Binding Request is a header with no attributes. The answer carries the
 * address in XOR-MAPPED-ADDRESS (the address and port mixed with the magic
 * cookie, so that a router that rewrites addresses it finds in packets
 * leaves this one alone), or in the older MAPPED-ADDRESS from a server
 * that predates it.
 *
 * Nothing here touches a socket. The port (the firmware's conn.c, or a
 * test) sends what is made here and hands back what came.
 *
 *   0  type[2]       0x0001 a Binding Request, 0x0101 its answer
 *   2  length[2]     of the attributes, a multiple of 4
 *   4  cookie[4]     0x2112A442
 *   8  id[12]        the request's, given back in its answer
 *   20 attributes    type[2], length[2], value, padded to 4 bytes
 *
 * Numbers are high byte first, as everywhere on the network.
 */
#include <string.h>

#include "nesp_services.h"

#define BINDING_REQUEST 0x0001
#define BINDING_ANSWER 0x0101
#define COOKIE 0x2112A442u
#define MAPPED_ADDRESS 0x0001
#define XOR_MAPPED_ADDRESS 0x0020
#define FAMILY_IPV4 0x01

static uint16_t get16(const uint8_t *in)
{
    return (uint16_t)(in[0] << 8 | in[1]);
}

static void put16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)(value >> 8);
    out[1] = (uint8_t)value;
}

size_t nesp_stun_request(const uint8_t *id, uint8_t *out)
{
    put16(out, BINDING_REQUEST);
    put16(out + 2, 0);
    out[4] = (uint8_t)(COOKIE >> 24);
    out[5] = (uint8_t)(COOKIE >> 16);
    out[6] = (uint8_t)(COOKIE >> 8);
    out[7] = (uint8_t)COOKIE;
    memcpy(out + 8, id, NESP_STUN_ID);
    return NESP_STUN_REQUEST;
}

/* An address attribute's value: IPv4 only, which is all a nesp32 has. */
static bool address_of(const uint8_t *value, uint16_t length, bool mixed, uint8_t *address,
                       uint16_t *port)
{
    if (length < 8 || value[1] != FAMILY_IPV4) {
        return false;
    }
    uint16_t at = get16(value + 2);
    memcpy(address, value + 4, 4);
    if (mixed) {
        at ^= (uint16_t)(COOKIE >> 16);
        address[0] ^= (uint8_t)(COOKIE >> 24);
        address[1] ^= (uint8_t)(COOKIE >> 16);
        address[2] ^= (uint8_t)(COOKIE >> 8);
        address[3] ^= (uint8_t)COOKIE;
    }
    *port = at;
    return true;
}

bool nesp_stun_mapped(const uint8_t *data, size_t len, const uint8_t *id, uint8_t *address,
                      uint16_t *port)
{
    if (len < NESP_STUN_REQUEST || get16(data) != BINDING_ANSWER
        || data[4] != (uint8_t)(COOKIE >> 24) || data[5] != (uint8_t)(COOKIE >> 16)
        || data[6] != (uint8_t)(COOKIE >> 8) || data[7] != (uint8_t)COOKIE
        || memcmp(data + 8, id, NESP_STUN_ID) != 0) {
        return false;
    }
    /* As far as the message says it goes, and no further than what came:
     * a datagram larger than the buffer it was read into is cut short. */
    size_t end = NESP_STUN_REQUEST + get16(data + 2);
    if (end > len) {
        end = len;
    }
    bool found = false;
    for (size_t at = NESP_STUN_REQUEST; at + 4 <= end;) {
        uint16_t type = get16(data + at);
        uint16_t length = get16(data + at + 2);
        const uint8_t *value = data + at + 4;
        if (at + 4 + length > end) {
            break;
        }
        if (type == XOR_MAPPED_ADDRESS && address_of(value, length, true, address, port)) {
            return true;            /* the one to believe, wherever it comes */
        }
        if (type == MAPPED_ADDRESS && !found) {
            found = address_of(value, length, false, address, port);
        }
        at += 4 + (size_t)((length + 3u) & ~3u);
    }
    return found;
}

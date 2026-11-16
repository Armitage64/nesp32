#!/usr/bin/env python3
"""Write a patch from a game's ROM to a netplay ROM, for players to apply to
their own copy of the game.

    tools/gen_patch.py BASE.nes TARGET.nes OUT.bps
    tools/gen_patch.py --apply BASE.nes PATCH.bps OUT.nes

The patch is BPS (byuu's): it holds the base ROM's CRC32 and the target's,
and a patcher refuses a ROM that is not the one it is for. It holds only
what the netplay build adds: none of the game. What the target has of the
base, the patch says where to copy it from in the player's own ROM: a
source read for what is where it was, a source copy for what has moved.
A build may keep the game where it is (TMNT II), move a block of it
(Family BASIC's CHR, after its PRG has grown), or shift the code after
each line it puts in (Contra, Dr. Mario, Tetris, built from disassemblies),
and each comes out the same way. Only the rest, the target reads, is
carried in the patch: the netplay's code and data, its header, and the
game's instructions that the shift has changed (an address, a branch).

That is checked before anything is written: a run of the carried bytes as
long as MATCH_LIMIT that is found anywhere in the base ROM would be the
game's own, and the patch is refused. Runs of one byte over and over
(padding, cleared tables) are passed over: they are in every ROM. So is
where two of them meet, one byte and then another (the end of one stretch
of padding and the start of the next).

There is no IPS: it cannot copy, so a build that moves any of the game
would have to carry it.

--apply applies a BPS patch, checking all three CRCs, as a player's
patcher would; the tests use it to see that a patch gives the ROM back,
and carried() to see what it holds.
"""

import argparse
import sys
import zlib

MATCH_LIMIT = 16            # bytes in a row of the patch that may not be the base's
SHORTEST = 4                # a read or copy shorter than this is carried instead
INDEX = 6                   # bytes the base is looked up by, for a copy from elsewhere
CANDIDATES = 64             # places in the base tried for each


def padding(window):
    """One byte over and over, or one and then another."""
    changes = sum(1 for a, b in zip(window, window[1:]) if a != b)
    return changes <= 1


def borrowed(base, runs, limit=MATCH_LIMIT):
    """The runs of `limit` bytes or more of the patch that are found in the
    base ROM, as (offset in the target, offset in the base), passing over
    those of one byte repeated."""
    found = []
    for start, data in runs:
        for at in range(0, len(data) - limit + 1):
            window = data[at:at + limit]
            if padding(window):
                continue
            where = base.find(window)
            if where >= 0:
                found.append((start + at, where))
                break
    return found


def common(a, i, b, j):
    """How many bytes from a[i] are the same as from b[j]."""
    most = min(len(a) - i, len(b) - j)
    if most <= 0:
        return 0
    same, step = 0, 16
    while same < most:
        end = min(same + step, most)
        if a[i + same:i + end] != b[j + same:j + end]:
            break
        same, step = end, step * 2
    high = min(same + step, most)       # a[..same] matches; a[..high] does not
    while high - same > 1:
        middle = (same + high) // 2
        if a[i + same:i + middle] == b[j + same:j + middle]:
            same = middle
        else:
            high = middle
    return same


SOURCE_READ, TARGET_READ, SOURCE_COPY = 0, 1, 2


def pieces(base, target):
    """The target as (SOURCE_READ, length, None), (SOURCE_COPY, length,
    where in the base) and (TARGET_READ, length, bytes), in order: the
    longest of the base found at each place, and what is not, carried."""
    index = {}
    for where in range(len(base) - INDEX + 1):
        places = index.setdefault(base[where:where + INDEX], [])
        if len(places) < CANDIDATES:
            places.append(where)
    out = []
    carry = bytearray()
    at = 0
    source = 0                  # where the last copy or read left off, in the base

    def flush():
        if carry:
            out.append((TARGET_READ, len(carry), bytes(carry)))
            carry.clear()

    while at < len(target):
        read = common(base, at, target, at) if at < len(base) else 0
        # A shifted game goes on in the base where it left off, after the
        # bytes put in, or as far on as the bytes changed.
        tried = [source, source + len(carry)]
        tried += index.get(bytes(target[at:at + INDEX]), [])
        length, where = 0, None
        for place in tried:
            if place != at and 0 <= place < len(base):
                same = common(base, place, target, at)
                if same > length:
                    length, where = same, place
        if read >= SHORTEST and read >= length:
            flush()
            out.append((SOURCE_READ, read, None))
            at += read
            source = at
        elif length >= SHORTEST:
            flush()
            out.append((SOURCE_COPY, length, where))
            at += length
            source = where + length
        else:
            carry.append(target[at])
            at += 1
    flush()
    return out


def number(value):
    """BPS's variable-length number."""
    out = bytearray()
    while True:
        low = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(0x80 | low)
            return bytes(out)
        out.append(low)
        value -= 1


def read_number(data, at):
    value, shift = 0, 1
    while True:
        byte = data[at]
        at += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, at
        shift <<= 7
        value += shift


def bps(base, target, metadata=b""):
    out = bytearray(b"BPS1")
    out += number(len(base)) + number(len(target)) + number(len(metadata)) + metadata
    source_copy = 0             # where the last source copy left off, in the base
    for kind, length, what in pieces(base, target):
        out += number((length - 1) << 2 | kind)
        if kind == TARGET_READ:
            out += what
        elif kind == SOURCE_COPY:
            delta = what - source_copy
            out += number(abs(delta) << 1 | (delta < 0))
            source_copy = what + length
    out += zlib.crc32(base).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(out).to_bytes(4, "little")
    return bytes(out)


def actions(patch):
    """A BPS patch's sizes of the base and the target, and its actions as
    (kind, length, what): the bytes of a target read, the change in place
    of a copy."""
    if patch[:4] != b"BPS1":
        raise ValueError("not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ValueError("the patch is damaged")
    at = 4
    source_size, at = read_number(patch, at)
    target_size, at = read_number(patch, at)
    metadata_size, at = read_number(patch, at)
    at += metadata_size
    out = []
    end = len(patch) - 12
    while at < end:
        word, at = read_number(patch, at)
        kind, length = word & 3, (word >> 2) + 1
        what = None
        if kind == TARGET_READ:
            what = patch[at:at + length]
            at += length
        elif kind != SOURCE_READ:
            delta, at = read_number(patch, at)
            what = (-1 if delta & 1 else 1) * (delta >> 1)
        out.append((kind, length, what))
    return source_size, target_size, out


def carried(patch):
    """(offset in the target, bytes) of each target read of a BPS patch:
    what it holds of the ROM it makes."""
    _, _, done = actions(patch)
    runs = []
    at = 0
    for kind, length, what in done:
        if kind == TARGET_READ:
            runs.append((at, what))
        at += length
    return runs


def apply_bps(base, patch):
    """The target a BPS patch makes of `base`; ValueError if any CRC is
    wrong."""
    source_size, target_size, done = actions(patch)
    if source_size != len(base) or zlib.crc32(base) != int.from_bytes(patch[-12:-8], "little"):
        raise ValueError("this is not the ROM the patch is for")
    target = bytearray()
    source_copy = target_copy = 0
    for kind, length, what in done:
        if kind == SOURCE_READ:
            target += base[len(target):len(target) + length]
        elif kind == TARGET_READ:
            target += what
        elif kind == SOURCE_COPY:
            source_copy += what
            target += base[source_copy:source_copy + length]
            source_copy += length
        else:
            target_copy += what
            for _ in range(length):
                target.append(target[target_copy])
                target_copy += 1
    if len(target) != target_size or zlib.crc32(target) != int.from_bytes(patch[-8:-4], "little"):
        raise ValueError("the patch does not give the ROM it was made for")
    return bytes(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="apply a BPS patch instead")
    parser.add_argument("files", nargs=3)
    args = parser.parse_args()
    if args.apply:
        base_path, patch_path, out_path = args.files
        with open(base_path, "rb") as handle:
            base = handle.read()
        with open(patch_path, "rb") as handle:
            patch = handle.read()
        try:
            target = apply_bps(base, patch)
        except ValueError as error:
            sys.exit("%s: %s" % (patch_path, error))
        with open(out_path, "wb") as handle:
            handle.write(target)
        return
    base_path, target_path, out_path = args.files
    with open(base_path, "rb") as handle:
        base = handle.read()
    with open(target_path, "rb") as handle:
        target = handle.read()
    patch = bps(base, target)
    runs = carried(patch)
    found = borrowed(base, runs)
    if found:
        where = ", ".join("$%X (the base's $%X)" % pair for pair in found[:8])
        sys.exit("%s has %d bytes or more in a row of %s's own: %s. A patch is "
                 "for the netplay's bytes only." % (target_path, MATCH_LIMIT, base_path, where))
    if apply_bps(base, patch) != target:
        sys.exit("the BPS patch does not give %s back" % target_path)
    with open(out_path, "wb") as handle:
        handle.write(patch)
    held = sum(len(data) for _, data in runs)
    print("%s: %d bytes carried in %d places, of %d" % (out_path, held, len(runs), len(target)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Write a patch from a game's ROM to a netplay ROM, for players to apply to
their own copy of the game.

    tools/gen_patch.py BASE.nes TARGET.nes OUT.bps [--ips OUT.ips]
                       [--moved FROM:TO:LENGTH ...]
    tools/gen_patch.py --apply BASE.nes PATCH.bps OUT.nes

A patch here holds only the bytes the netplay build changes, at the places
it changes them: none of the game. The build keeps every byte of the game
where it is (each change is the length of what it replaces), so what
differs is the netplay's own code, its header, and the instructions that
call it. That is checked before anything is written: a run of the
patch's bytes as long as MATCH_LIMIT that is found anywhere in the base ROM
would be the game's own, moved, and the patch is refused. Runs of one byte
over and over (padding, cleared tables) are passed over: they are in every
ROM. So is where two of them meet, one byte and then another (the end of
one stretch of padding and the start of the next).

A build that does move some of the game says so with --moved: LENGTH bytes
at FROM in the base are at TO in the target (Family BASIC's CHR, after
its PRG has grown). They are checked to be the base's, and the BPS patch
copies them from the player's own ROM, so it holds none of them either.

Two formats:

- BPS (byuu's), which players should use: it holds the base ROM's CRC32
  and the target's, and a patcher refuses a ROM that is not the one it is
  for. Written with source reads for what is unchanged and target reads
  for what is new, which is all a build that moves nothing needs.
- IPS, for tools that take nothing else: offsets and bytes, and no check
  of the ROM it is applied to. It cannot copy, so there is none for a
  build that moves the game's bytes.

--apply applies a BPS patch, checking all three CRCs, as a player's
patcher would; the tests use it to see that a patch gives the ROM back.
"""

import argparse
import sys
import zlib

MATCH_LIMIT = 16            # bytes in a row of the patch that may not be the base's
IPS_EOF = 0x454F46          # an IPS record may not begin here: it reads as "EOF"
IPS_RECORD_MAX = 0xFFFF


def differing_runs(base, target, moves=()):
    """(offset, bytes) of each run of the target that differs from the
    base, and of what the target has past the base's end, less the moves:
    (from, to, length) of what was moved."""
    moved = set()
    for _, to, length in moves:
        moved.update(range(to, to + length))
    runs = []
    start = None
    for offset in range(len(target)):
        same = (offset < len(base) and base[offset] == target[offset]) or offset in moved
        if not same and start is None:
            start = offset
        elif same and start is not None:
            runs.append((start, target[start:offset]))
            start = None
    if start is not None:
        runs.append((start, target[start:]))
    return runs


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


SOURCE_READ, TARGET_READ, SOURCE_COPY = 0, 1, 2


def bps(base, target, runs, moves=(), metadata=b""):
    out = bytearray(b"BPS1")
    out += number(len(base)) + number(len(target)) + number(len(metadata)) + metadata
    at = 0
    source_copy = 0             # where the last source copy left off, in the base

    def action(kind, length):
        out.extend(number((length - 1) << 2 | kind))

    pieces = sorted([(start, data, None) for start, data in runs]
                    + [(to, None, (where, length)) for where, to, length in moves])
    for start, data, move in pieces:
        if start > at:
            action(SOURCE_READ, start - at)
        if move is None:
            action(TARGET_READ, len(data))
            out.extend(data)
            at = start + len(data)
        else:
            where, length = move
            action(SOURCE_COPY, length)
            delta = where - source_copy
            out.extend(number(abs(delta) << 1 | (delta < 0)))
            source_copy = where + length
            at = start + length
    if at < len(target):
        action(SOURCE_READ, len(target) - at)
    out += zlib.crc32(base).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(out).to_bytes(4, "little")
    return bytes(out)


def apply_bps(base, patch):
    """The target a BPS patch makes of `base`; ValueError if any CRC is
    wrong."""
    if patch[:4] != b"BPS1":
        raise ValueError("not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ValueError("the patch is damaged")
    if zlib.crc32(base) != int.from_bytes(patch[-12:-8], "little"):
        raise ValueError("this is not the ROM the patch is for")
    at = 4
    source_size, at = read_number(patch, at)
    target_size, at = read_number(patch, at)
    metadata_size, at = read_number(patch, at)
    at += metadata_size
    if source_size != len(base):
        raise ValueError("this is not the ROM the patch is for")
    target = bytearray()
    source_copy = target_copy = 0
    end = len(patch) - 12
    while at < end:
        word, at = read_number(patch, at)
        kind, length = word & 3, (word >> 2) + 1
        if kind == 0:
            target += base[len(target):len(target) + length]
        elif kind == 1:
            target += patch[at:at + length]
            at += length
        else:
            delta, at = read_number(patch, at)
            delta = (-1 if delta & 1 else 1) * (delta >> 1)
            if kind == 2:
                source_copy += delta
                target += base[source_copy:source_copy + length]
                source_copy += length
            else:
                target_copy += delta
                for _ in range(length):
                    target.append(target[target_copy])
                    target_copy += 1
    if len(target) != target_size or zlib.crc32(target) != int.from_bytes(patch[-8:-4], "little"):
        raise ValueError("the patch does not give the ROM it was made for")
    return bytes(target)


def ips(runs):
    out = bytearray(b"PATCH")
    for start, data in runs:
        at = 0
        while at < len(data):
            offset = start + at
            chunk = data[at:at + IPS_RECORD_MAX]
            if offset == IPS_EOF:
                raise ValueError("a change at $454F46, which IPS cannot say")
            out += offset.to_bytes(3, "big") + len(chunk).to_bytes(2, "big") + chunk
            at += len(chunk)
    if any(start + len(data) > 0xFFFFFF for start, data in runs):
        raise ValueError("a change past 16 MB, which IPS cannot say")
    out += b"EOF"
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="apply a BPS patch instead")
    parser.add_argument("--ips", help="write an IPS patch here too")
    parser.add_argument("--moved", action="append", default=[], metavar="FROM:TO:LENGTH",
                        help="LENGTH bytes at FROM in the base are at TO in the target")
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
    moves = [tuple(int(part, 0) for part in move.split(":")) for move in args.moved]
    for where, to, length in moves:
        if length <= 0 or base[where:where + length] != target[to:to + length] \
                or len(base) < where + length:
            sys.exit("%s's $%X to $%X is not where --moved says in %s"
                     % (base_path, where, where + length, target_path))
    if moves and args.ips:
        sys.exit("an IPS patch cannot move the base's bytes: write the BPS alone")
    runs = differing_runs(base, target, moves)
    found = borrowed(base, runs)
    if found:
        where = ", ".join("$%X (the base's $%X)" % pair for pair in found[:8])
        sys.exit("%s has %d bytes or more in a row of %s's own: %s. A patch is "
                 "for the netplay's bytes only." % (target_path, MATCH_LIMIT, base_path, where))
    patch = bps(base, target, runs, moves)
    if apply_bps(base, patch) != target:
        sys.exit("the BPS patch does not give %s back" % target_path)
    with open(out_path, "wb") as handle:
        handle.write(patch)
    if args.ips:
        with open(args.ips, "wb") as handle:
            handle.write(ips(runs))
    changed = sum(len(data) for _, data in runs)
    print("%s: %d bytes changed in %d places, of %d" % (out_path, changed, len(runs), len(target)))
    for where, to, length in moves:
        print("%s: %d bytes of the base's moved from $%X to $%X" % (out_path, length, where, to))


if __name__ == "__main__":
    main()

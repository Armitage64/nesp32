"""The .jbs jukebox stream: record encoding, decoding, and the file container.

docs/PROTOCOL.md is the specification. In short, the stream is a sequence of
records, and the NES decodes one frame's worth per NMI:

    $00         the next write record does not advance a frame
    $01-$7F     wait n frames with no writes
    $80 cc      control record (cc: $00 end of track, $01 APU init)
    $81-$FF     write record, then advance one frame

A write record's header bits select register groups. Each selected group
follows in apply order: a submask byte for groups of more than one register,
then the values of the selected registers in ascending address order.
"""

import struct
from collections import namedtuple
from dataclasses import dataclass

import apu_model

OP_CHAIN = 0x00
OP_CONTROL = 0x80
MAX_WAIT = 0x7F

CTRL_END = 0x00
CTRL_INIT = 0x01
CONTROL_CODES = frozenset({CTRL_END, CTRL_INIT})

Group = namedtuple("Group", "name bit registers")

# The order groups appear in a record, which is the order the NES applies
# them: $4015 first so channel enables precede length loads, then the
# channels, then $4017.
APPLY_ORDER = (
    Group("status", 5, (0x15,)),
    Group("pulse1", 0, (0x00, 0x01, 0x02, 0x03)),
    Group("pulse2", 1, (0x04, 0x05, 0x06, 0x07)),
    Group("triangle", 2, (0x08, 0x0A, 0x0B)),
    Group("noise", 3, (0x0C, 0x0E, 0x0F)),
    Group("dmc", 4, (0x10, 0x11, 0x12, 0x13)),
    Group("frame_counter", 6, (0x17,)),
)
RANK = {
    register: rank
    for rank, register in enumerate(r for group in APPLY_ORDER for r in group.registers)
}

Control = namedtuple("Control", "code")


class StreamError(ValueError):
    """Bytes that are not a valid .jbs stream."""


def encode_record(writes):
    """Encode writes, already in apply order with unique registers."""
    if not writes:
        raise ValueError("a write record needs at least one write")
    ranks = [RANK[register] for register, _ in writes]
    if ranks != sorted(set(ranks)):
        raise ValueError("writes must be unique and in apply order")
    values = dict(writes)
    header = 0x80
    body = bytearray()
    for group in APPLY_ORDER:
        present = [r for r in group.registers if r in values]
        if not present:
            continue
        header |= 1 << group.bit
        if len(group.registers) > 1:
            body.append(sum(1 << group.registers.index(r) for r in present))
        body.extend(values[r] for r in present)
    return bytes([header]) + bytes(body)


def _decode_record(data, pos):
    header = _byte(data, pos)
    if header <= OP_CONTROL:
        raise StreamError("expected a write record at %d" % pos)
    pos += 1
    writes = []
    for group in APPLY_ORDER:
        if not header & (1 << group.bit):
            continue
        if len(group.registers) == 1:
            writes.append((group.registers[0], _byte(data, pos)))
            pos += 1
            continue
        mask = _byte(data, pos)
        pos += 1
        if not mask or mask >> len(group.registers):
            raise StreamError("bad %s submask $%02X at %d" % (group.name, mask, pos - 1))
        for index, register in enumerate(group.registers):
            if mask & (1 << index):
                writes.append((register, _byte(data, pos)))
                pos += 1
    return writes, pos


def _byte(data, pos):
    if pos >= len(data):
        raise StreamError("stream truncated at %d" % pos)
    return data[pos]


def decode(data, start=0):
    """Decode a stream into frames.

    Returns (frames, tail). Each frame is a list of (register, value)
    writes and Control items in the order the NES applies them. tail holds
    items after the last frame advance, such as a final end-of-track
    control.
    """
    frames = []
    current = []
    pos = start
    while pos < len(data):
        op = data[pos]
        if op == OP_CHAIN:
            writes, pos = _decode_record(data, pos + 1)
            current.extend(writes)
        elif op < OP_CONTROL:
            frames.append(current)
            frames.extend([] for _ in range(op - 1))
            current = []
            pos += 1
        elif op == OP_CONTROL:
            code = _byte(data, pos + 1)
            if code not in CONTROL_CODES:
                raise StreamError("unknown control code $%02X at %d" % (code, pos + 1))
            current.append(Control(code))
            pos += 2
        else:
            writes, pos = _decode_record(data, pos)
            current.extend(writes)
            frames.append(current)
            current = []
    return frames, current


@dataclass
class Encoded:
    data: bytes
    loop_offset: int  # 0 when the track does not loop
    frame_bytes: list  # stream bytes attributed to each frame


def encode(frames, loop_frame=None):
    """Encode per-frame writes (original order) into a stream.

    The stream opens with an APU init control. At loop_frame the encoder
    forgets which register values the console holds, because on a repeat
    pass the console arrives there from the end of the track, not from the
    frame before. The returned loop_offset points at that frame's first
    record.
    """
    out = bytearray([OP_CONTROL, CTRL_INIT])
    frame_bytes = [0] * len(frames)
    known = {}
    loop_offset = 0
    waiting = 0

    def flush_wait(frame):
        nonlocal waiting
        before = len(out)
        while waiting:
            step = min(waiting, MAX_WAIT)
            out.append(step)
            waiting -= step
        if frame < len(frames):
            frame_bytes[frame] += len(out) - before

    for index, writes in enumerate(frames):
        if index == loop_frame:
            flush_wait(index)
            loop_offset = len(out)
            known.clear()
        records = plan_frame(writes, known)
        if not records:
            waiting += 1
            continue
        flush_wait(index)
        before = len(out)
        for record in records[:-1]:
            out.append(OP_CHAIN)
            out += encode_record(record)
        out += encode_record(records[-1])
        frame_bytes[index] += len(out) - before
        for record in records:
            known.update(record)
    flush_wait(len(frames))
    return Encoded(bytes(out), loop_offset, frame_bytes)


def plan_frame(writes, known):
    """Turn one frame's writes into write records.

    The common case is a single record: the last value per register, minus
    writes that cannot change anything, sorted into apply order. If that is
    not equivalent to the original order under the APU model, the writes
    are kept in original order and split into chained records wherever the
    apply order would otherwise be violated.
    """
    last = {}
    for register, value in writes:
        last.pop(register, None)
        last[register] = value
    merged = sorted(
        ((r, v) for r, v in last.items() if not apu_model.is_redundant(r, v, known)),
        key=lambda write: RANK[write[0]],
    )
    if apu_model.equivalent(writes, merged, known):
        return [merged] if merged else []

    records = []
    record = []
    held = dict(known)
    for register, value in writes:
        if apu_model.is_redundant(register, value, held):
            continue
        held[register] = value
        if record and RANK[register] <= RANK[record[-1][0]]:
            records.append(record)
            record = []
        record.append((register, value))
    if record:
        records.append(record)
    flat = [write for record in records for write in record]
    if not apu_model.equivalent(writes, flat, known):
        raise AssertionError("ordered fallback changed the frame's effect")
    return records


# --- .jbs file container -----------------------------------------------------

FILE_MAGIC = b"JBS\x1a"
FILE_VERSION = 1
FLAG_LOOPS = 0x01
FLAG_PAL_SOURCE = 0x02
NO_LOOP = 0xFFFFFFFF
_HEADER = struct.Struct("<4sBBHIIII")
MAX_TITLE = 255


@dataclass
class JbsFile:
    stream: bytes
    total_frames: int
    loop_frame: int = None
    loop_offset: int = 0
    pal_source: bool = False
    title: str = ""

    def to_bytes(self):
        flags = (FLAG_LOOPS if self.loop_frame is not None else 0) | (
            FLAG_PAL_SOURCE if self.pal_source else 0
        )
        title = _ascii_title(self.title)
        header = _HEADER.pack(
            FILE_MAGIC,
            FILE_VERSION,
            flags,
            0,
            self.total_frames,
            NO_LOOP if self.loop_frame is None else self.loop_frame,
            self.loop_offset,
            len(self.stream),
        )
        return header + bytes([len(title)]) + title + self.stream

    @classmethod
    def from_bytes(cls, data):
        if len(data) < _HEADER.size + 1:
            raise StreamError("file too short for a .jbs header")
        magic, version, flags, _, frames, loop_frame, loop_offset, length = (
            _HEADER.unpack_from(data)
        )
        if magic != FILE_MAGIC or version != FILE_VERSION:
            raise StreamError("not a version %d .jbs file" % FILE_VERSION)
        title_length = data[_HEADER.size]
        start = _HEADER.size + 1 + title_length
        stream = data[start:start + length]
        if len(stream) != length:
            raise StreamError("stream truncated")
        return cls(
            stream=bytes(stream),
            total_frames=frames,
            loop_frame=loop_frame if flags & FLAG_LOOPS else None,
            loop_offset=loop_offset,
            pal_source=bool(flags & FLAG_PAL_SOURCE),
            title=data[_HEADER.size + 1:start].decode("ascii"),
        )


def _ascii_title(title):
    text = "".join(c if " " <= c <= "~" else "?" for c in title)
    return text[:MAX_TITLE].encode("ascii")

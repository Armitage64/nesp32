"""The .jbs jukebox stream: record encoding, decoding, and the file container.

docs/PROTOCOL.md is the specification. In short, the stream is a sequence of
records, and the NES decodes one frame's worth per NMI:

    $00         the next write record does not advance a frame
    $01-$7F     wait n frames with no writes
    $80 cc      control record (cc: $00 end of track, which also ends the
                frame; $01 APU init, which does not; $02 track name and
                $03 game name, each followed by a length and that many
                characters; $04 track length, followed by five characters)
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

# The player stages a frame's writes before applying them, and has room for
# this many. The init control stages two.
MAX_FRAME_WRITES = 64
INIT_WRITES = 2

CTRL_END = 0x00
CTRL_INIT = 0x01
CTRL_TITLE = 0x02
CTRL_GAME = 0x03
CTRL_LENGTH = 0x04
CONTROL_CODES = frozenset({CTRL_END, CTRL_INIT})  # those with nothing after the code
TITLE_MAX = 28  # characters: one line of the console's screen
LENGTH_CHARS = 5
FRAMES_PER_SECOND = 60

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
Title = namedtuple("Title", "text")      # the track's name
Game = namedtuple("Game", "text")        # the game it came from
Length = namedtuple("Length", "text")    # "M:SS ", as the console shows it
TEXT_CONTROLS = {CTRL_TITLE: Title, CTRL_GAME: Game}


def split_title(title):
    """(game, track) as the console shows them: printable ASCII, a line each.

    The converter's titles are "game - track". A title without the hyphen is
    a track's name with no game."""
    text = _ascii_title(title).decode("ascii")
    game, separator, track = text.partition(" - ")
    if not separator:
        game, track = "", text
    return game[:TITLE_MAX].strip(), track[:TITLE_MAX].strip()


def play_frames(total_frames, loop_frame, loops):
    """How long a track plays in a playlist: once through, then its loop
    another loops - 1 times."""
    if loop_frame is None:
        return total_frames
    return total_frames + (max(1, loops) - 1) * (total_frames - loop_frame)


def length_text(frames):
    """A length as the five characters the console shows, "M:SS " or
    "MM:SS". None, for a track that never ends, is dashes."""
    if frames is None:
        return b"-:-- "
    seconds = min(frames // FRAMES_PER_SECOND, 99 * 60 + 59)
    return (b"%d:%02d" % (seconds // 60, seconds % 60)).ljust(LENGTH_CHARS)


def intro(title, frames=None):
    """The control records a host sends ahead of a track: the game's name,
    the track's name, and how long it will play. They write nothing to the
    APU and advance no frame. The length record also starts the console's
    clock again from zero."""
    game, track = (part.encode("ascii") for part in split_title(title))
    return (bytes([OP_CONTROL, CTRL_GAME, len(game)]) + game
            + bytes([OP_CONTROL, CTRL_TITLE, len(track)]) + track
            + bytes([OP_CONTROL, CTRL_LENGTH]) + length_text(frames))


def _control_end(data, pos):
    """The position after the control record at pos."""
    code = _byte(data, pos + 1)
    if code in TEXT_CONTROLS:
        length = _byte(data, pos + 2)
        if length > TITLE_MAX:
            raise StreamError("title of %d characters at %d" % (length, pos))
        end = pos + 3 + length
    elif code == CTRL_LENGTH:
        end = pos + 2 + LENGTH_CHARS
    elif code in CONTROL_CODES:
        end = pos + 2
    else:
        raise StreamError("unknown control code $%02X at %d" % (code, pos + 1))
    if end > len(data):
        raise StreamError("stream truncated at %d" % len(data))
    return end


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
    items after the last frame advance.
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
            end = _control_end(data, pos)
            code = data[pos + 1]
            if code in TEXT_CONTROLS:
                current.append(TEXT_CONTROLS[code](data[pos + 3:end].decode("latin-1")))
                pos = end
                continue
            if code == CTRL_LENGTH:
                current.append(Length(data[pos + 2:end].decode("latin-1")))
                pos = end
                continue
            current.append(Control(code))
            pos += 2
            if code == CTRL_END:  # the last thing in its frame
                frames.append(current)
                current = []
        else:
            writes, pos = _decode_record(data, pos)
            current.extend(writes)
            frames.append(current)
            current = []
    return frames, current


def frame_units(data):
    """Split a stream into [(start, end)] units that are safe to cut between.

    A unit is one control record, or the records of one frame up to and
    including the record that advances it (a write record, or a wait). A
    chain prefix stays with the record it chains. Cutting anywhere else
    would hand the NES half a frame.
    """
    units = []
    start = pos = 0
    while pos < len(data):
        op = data[pos]
        if op == OP_CHAIN:
            _, pos = _decode_record(data, pos + 1)
            continue
        if op == OP_CONTROL:
            if pos != start:
                raise StreamError("control record inside a frame at %d" % pos)
            pos = _control_end(data, pos)
        elif op < OP_CONTROL:
            pos += 1
        else:
            _, pos = _decode_record(data, pos)
        units.append((start, pos))
        start = pos
    if start != pos:
        raise StreamError("stream ends inside a frame")
    return units


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
        staged = sum(len(record) for record in records) + (INIT_WRITES if index == 0 else 0)
        if staged > MAX_FRAME_WRITES:
            raise ValueError(
                "frame %d has %d writes; the player stages at most %d"
                % (index, staged, MAX_FRAME_WRITES)
            )
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

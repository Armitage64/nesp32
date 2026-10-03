"""Tracks on the Stick's flash, and the playlist as one stream for the NES.

Playlist is a port of host/playlist.py's PlaylistSource and produces the
same bytes. It differs in two ways that save memory: only the current track
is loaded, and frame boundaries are found by walking the stream as it is
sent, not listed up front.

The files are checked on the Mac at deploy time (tools/pack_tracks.py): each
stream decodes, and each loop offset is a frame boundary. This module trusts
them.
"""

import os
import struct

FILE_MAGIC = b"JBS\x1a"
FILE_VERSION = 1
FLAG_LOOPS = 0x01
HEADER = "<4sBBHIIII"
HEADER_SIZE = 24

OP_CHAIN = 0x00
OP_CONTROL = 0x80
CTRL_TITLE = 0x02
CTRL_GAME = 0x03
CTRL_LENGTH = 0x04
END_OF_TRACK = b"\x80\x00"
TITLE_MAX = 28  # characters: one line of the console's screen
FRAMES_PER_SECOND = 60

# Set bits in a group's submask, which is how many values follow it.
_BITS = b"\x00\x01\x01\x02\x01\x02\x02\x03\x01\x02\x02\x03\x02\x03\x03\x04"


def load_jbs(path):
    """Return (title, stream, loop offset or None, frames, loop frame) from
    a .jbs file. The loop frame means nothing without a loop offset."""
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) <= HEADER_SIZE:
        raise ValueError("not a .jbs file: " + path)
    magic, version, flags, _, frames, loop_frame, loop_offset, length = struct.unpack_from(
        HEADER, data, 0)
    if magic != FILE_MAGIC or version != FILE_VERSION:
        raise ValueError("not a .jbs file: " + path)
    start = HEADER_SIZE + 1 + data[HEADER_SIZE]
    stream = data[start:start + length]
    if len(stream) != length:
        raise ValueError("truncated: " + path)
    title = str(data[HEADER_SIZE + 1:start], "ascii")
    return title, stream, loop_offset if flags & FLAG_LOOPS else None, frames, loop_frame


def list_tracks(directory):
    return sorted(directory + "/" + name for name in os.listdir(directory)
                  if name.endswith(".jbs"))


def intro(title, frames):
    """The control records sent ahead of a track, as tools/jbs.py builds
    them: the game's name, the track's name, and how long it will play. The
    converter's titles are "game - track"."""
    cut = title.find(" - ")
    if cut < 0:
        game, track = "", title
    else:
        game, track = title[:cut], title[cut + 3:]
    game = bytes(game[:TITLE_MAX].strip(), "ascii")
    track = bytes(track[:TITLE_MAX].strip(), "ascii")
    seconds = min(frames // FRAMES_PER_SECOND, 99 * 60 + 59)
    return (bytes((OP_CONTROL, CTRL_GAME, len(game))) + game
            + bytes((OP_CONTROL, CTRL_TITLE, len(track))) + track
            + bytes((OP_CONTROL, CTRL_LENGTH))
            + bytes(("%d:%02d " % (seconds // 60, seconds % 60))[:5], "ascii"))


def unit_frames(data, pos):
    """How many frames the unit starting at pos plays for."""
    op = data[pos]
    if op == OP_CONTROL:
        return 1 if data[pos + 1] == 0 else 0   # only end-of-track takes one
    if OP_CHAIN < op < OP_CONTROL:
        return op                               # a wait
    return 1


def _record_end(data, pos):
    """The position after the write record at pos (docs/PROTOCOL.md, part 1)."""
    header = data[pos]
    pos += 1
    if header & 0x20:           # $4015, a single value
        pos += 1
    for bit in (0x01, 0x02, 0x04, 0x08, 0x10):
        if header & bit:        # a submask, then its values
            pos += 1 + _BITS[data[pos] & 0x0F]
    if header & 0x40:           # $4017, a single value
        pos += 1
    return pos


def unit_end(data, pos):
    """The end of the unit starting at pos: one control record, or one
    frame's records. The stream may be cut only between units."""
    op = data[pos]
    while op == OP_CHAIN:
        pos = _record_end(data, pos + 1)
        op = data[pos]
    if op == OP_CONTROL:
        code = data[pos + 1]
        if code == CTRL_TITLE or code == CTRL_GAME:
            return pos + 3 + data[pos + 2]
        return pos + 7 if code == CTRL_LENGTH else pos + 2
    if op < OP_CONTROL:
        return pos + 1
    return _record_end(data, pos)


class Playlist:
    def __init__(self, count, load, loops=2, repeat=False, on_track=None):
        """load(index) returns load_jbs's tuple for one of the count tracks.
        on_track(index, title) is called when the host starts sending a
        track.

        For a clock: frames_out counts the frames handed out since the
        stream last started over (a jump or a restart), track_start is its
        value where the current track began, and track_frames is how long
        that track plays."""
        if not count:
            raise ValueError("empty playlist")
        self.count = count
        self.load = load
        self.loops = max(1, loops)
        self.repeat = repeat
        self.on_track = on_track
        self.pending = b""
        self.finished = False
        self.requested = None
        self.frames_out = 0
        self._start(0)

    def _start(self, index):
        self.data = b""  # let go of the old track before loading the next
        title, self.data, self.loop_offset, frames, loop_frame = self.load(index)
        if self.loop_offset is not None:
            frames += (self.loops - 1) * (frames - loop_frame)
        self.index = index
        self.pos = 0
        self.passes_left = self.loops
        self.track_start = self.frames_out
        self.track_frames = frames
        self.intro = intro(title, frames)
        if self.on_track:
            self.on_track(index, title)

    def skip(self, delta):
        """Switch tracks at the next frame boundary the host generates."""
        base = self.requested if self.requested is not None else self.index
        self.requested = (base + delta) % self.count
        self.finished = False

    def jump(self, delta):
        """Switch tracks now, dropping what was generated but not yet taken.
        The NES still holds the old track, so the host must flush it."""
        base = self.requested if self.requested is not None else self.index
        self.requested = None
        self.pending = b""
        self.finished = False
        self.frames_out = 0
        self._start((base + delta) % self.count)

    def restart(self):
        """Begin the current track again, for a NES that has just reset."""
        self.pending = b""
        self.finished = False
        self.requested = None
        self.frames_out = 0
        self._start(self.index)

    def take(self, count):
        while len(self.pending) < count and not self.finished:
            self.pending += self._next_unit()
        out = self.pending[:count]
        self.pending = self.pending[count:]
        return out

    def _next_unit(self):
        if self.requested is not None:
            index, self.requested = self.requested, None
            self._start(index)
        if self.pos >= len(self.data):
            if self.loop_offset is not None and self.passes_left > 1:
                self.passes_left -= 1
                self.pos = self.loop_offset
            elif self.index + 1 < self.count or self.repeat:
                self._start((self.index + 1) % self.count)
            else:
                self.finished = True
                return END_OF_TRACK
        if self.intro:
            intro, self.intro = self.intro, None
            return intro
        start = self.pos
        self.frames_out += unit_frames(self.data, start)
        self.pos = unit_end(self.data, start)
        return self.data[start:self.pos]

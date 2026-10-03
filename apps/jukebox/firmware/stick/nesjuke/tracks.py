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
END_OF_TRACK = b"\x80\x00"

# Set bits in a group's submask, which is how many values follow it.
_BITS = b"\x00\x01\x01\x02\x01\x02\x02\x03\x01\x02\x02\x03\x02\x03\x03\x04"


def load_jbs(path):
    """Return (title, stream, loop offset or None) from a .jbs file."""
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) <= HEADER_SIZE:
        raise ValueError("not a .jbs file: " + path)
    magic, version, flags, _, _, _, loop_offset, length = struct.unpack_from(HEADER, data, 0)
    if magic != FILE_MAGIC or version != FILE_VERSION:
        raise ValueError("not a .jbs file: " + path)
    start = HEADER_SIZE + 1 + data[HEADER_SIZE]
    stream = data[start:start + length]
    if len(stream) != length:
        raise ValueError("truncated: " + path)
    title = str(data[HEADER_SIZE + 1:start], "ascii")
    return title, stream, loop_offset if flags & FLAG_LOOPS else None


def list_tracks(directory):
    return sorted(directory + "/" + name for name in os.listdir(directory)
                  if name.endswith(".jbs"))


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
        return pos + 2
    if op < OP_CONTROL:
        return pos + 1
    return _record_end(data, pos)


class Playlist:
    def __init__(self, count, load, loops=2, repeat=False, on_track=None):
        """load(index) returns (title, stream, loop offset or None) for one
        of the count tracks. on_track(index, title) is called when the host
        starts sending a track."""
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
        self._start(0)

    def _start(self, index):
        self.data = b""  # let go of the old track before loading the next
        title, self.data, self.loop_offset = self.load(index)
        self.index = index
        self.pos = 0
        self.passes_left = self.loops
        if self.on_track:
            self.on_track(index, title)

    def skip(self, delta):
        """Switch tracks at the next frame boundary the host generates."""
        base = self.requested if self.requested is not None else self.index
        self.requested = (base + delta) % self.count
        self.finished = False

    def restart(self):
        """Begin the current track again, for a NES that has just reset."""
        self.pending = b""
        self.finished = False
        self.requested = None
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
        start = self.pos
        self.pos = unit_end(self.data, start)
        return self.data[start:self.pos]

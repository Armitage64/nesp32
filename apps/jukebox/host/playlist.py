"""A playlist as one continuous stream for the NES.

Each track's stream starts with an APU init control, so the NES needs no
notice of a track change: the next track's bytes simply follow the last
frame of the previous one. Tracks are cut only between frame units
(jbs.frame_units), never inside a frame.

A looping track plays its loop `loops` times in all, then the playlist moves
on. After the last track the stream ends with an end-of-track control,
unless the playlist repeats.
"""

import jbs

END_OF_TRACK = bytes([jbs.OP_CONTROL, jbs.CTRL_END])


class PlaylistSource:
    def __init__(self, tracks, loops=2, repeat=False, on_track=None):
        """tracks is a list of (title, JbsFile). on_track(index, title) is
        called when the host starts sending a track."""
        if not tracks:
            raise ValueError("empty playlist")
        self.tracks = tracks
        self.loops = max(1, loops)
        self.repeat = repeat
        self.on_track = on_track
        self.pending = bytearray()
        self.finished = False
        self.requested = None
        self._start(0)

    def _start(self, index):
        title, song = self.tracks[index]
        self.index = index
        self.data = song.stream
        self.units = jbs.frame_units(song.stream)
        self.unit = 0
        self.loop_unit = None
        if song.loop_frame is not None:
            starts = [start for start, _ in self.units]
            if song.loop_offset not in starts:
                raise ValueError("%s: loop offset is not a frame boundary" % title)
            self.loop_unit = starts.index(song.loop_offset)
        self.passes_left = self.loops
        if self.on_track:
            self.on_track(index, title)

    def skip(self, delta):
        """Switch tracks at the next frame boundary the host generates."""
        base = self.requested if self.requested is not None else self.index
        self.requested = (base + delta) % len(self.tracks)
        self.finished = False

    def restart(self):
        """Begin the current track again, for a NES that has just reset."""
        self.pending.clear()
        self.finished = False
        self.requested = None
        self._start(self.index)

    def take(self, count):
        while len(self.pending) < count and not self.finished:
            self.pending += self._next_unit()
        out = bytes(self.pending[:count])
        del self.pending[:count]
        return out

    def _next_unit(self):
        if self.requested is not None:
            index, self.requested = self.requested, None
            self._start(index)
        if self.unit >= len(self.units):
            if self.loop_unit is not None and self.passes_left > 1:
                self.passes_left -= 1
                self.unit = self.loop_unit
            elif self.index + 1 < len(self.tracks) or self.repeat:
                self._start((self.index + 1) % len(self.tracks))
            else:
                self.finished = True
                return END_OF_TRACK
        start, end = self.units[self.unit]
        self.unit += 1
        return self.data[start:end]

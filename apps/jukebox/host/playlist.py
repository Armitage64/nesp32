"""A playlist as one continuous stream for the NES.

Each track's stream starts with an APU init control, so the NES needs no
notice of a track change: the next track's bytes simply follow the last
frame of the previous one. Tracks are cut only between frame units
(jbs.frame_units), never inside a frame.

Ahead of each track go its game's name, its own name and its length
(jbs.intro), which reach the console's screen at the moment its first frame
plays.

A looping track plays its loop `loops` times in all, then the playlist moves
on. After the last track the stream ends with an end-of-track control,
unless the playlist repeats.

A track may be sampled sound (pcm.Sound), which is not part of this stream:
its samples go to the console at a rate of their own. Its place in the
stream is its names and length and then a sound record. Once that has been
handed out, `sound` is the track and the stream gives nothing more until
sound_done() is called, which is when the samples have been sent.
"""

import jbs
import pcm

END_OF_TRACK = bytes([jbs.OP_CONTROL, jbs.CTRL_END])


class PlaylistSource:
    def __init__(self, tracks, loops=2, repeat=False, on_track=None):
        """tracks is a list of (title, JbsFile or pcm.Sound).
        on_track(index, title) is called when the host starts sending a
        track."""
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
        self.sound = None
        self.sound_next = None
        if isinstance(song, pcm.Sound):
            self.sound_next = song
            self.data = jbs.sound_record(song.rate)
            self.units = [(0, len(self.data))]
            self.unit = 0
            self.loop_unit = None
            self.passes_left = 1
            self.intro = jbs.intro(title, song.frames)
            if self.on_track:
                self.on_track(index, title)
            return
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
        self.intro = jbs.intro(title, jbs.play_frames(song.total_frames, song.loop_frame,
                                                      self.loops))
        if self.on_track:
            self.on_track(index, title)

    def skip(self, delta):
        """Switch tracks at the next frame boundary the host generates."""
        base = self.requested if self.requested is not None else self.index
        self.requested = (base + delta) % len(self.tracks)
        self.finished = False

    def jump(self, delta):
        """Switch tracks now, dropping what was generated but not yet taken.
        The NES still holds the old track, so the host must flush it."""
        base = self.requested if self.requested is not None else self.index
        self.requested = None
        self.pending.clear()
        self.finished = False
        self._start((base + delta) % len(self.tracks))

    def restart(self):
        """Begin the current track again, for a NES that has just reset."""
        self.pending.clear()
        self.finished = False
        self.requested = None
        self._start(self.index)

    def sound_done(self):
        """The sound's samples have been sent, or will not be."""
        self.sound = None

    def take(self, count):
        while len(self.pending) < count and not self.finished and self.sound is None:
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
        if self.intro:
            intro, self.intro = self.intro, None
            return intro
        start, end = self.units[self.unit]
        self.unit += 1
        self.sound = self.sound_next    # after a sound record, wait for the sound
        return self.data[start:end]

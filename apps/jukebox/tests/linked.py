"""What the link ROM's tests share: tracks as the nesp32 holds them, the
stream it makes of them, and a hand on the buttons.

The nesp32's end of the link is its own firmware (link_harness.py), so what
it sends is not this repository's to decide. These helpers say what it
should be, from the same tools that make the files: each track's names and
length, its stream, round its loop as often as the nesp32 was told, then
the next track's.
"""

import dataclasses
import itertools

import jbs
import nesp_proto as p
import pcm
from nes_harness import PAD_START, expected_frames

LINK_WAITING, LINK_STOPPED, LINK_STREAMING = 0, 1, 2    # link_state, in nes/jukebox.s


def jbs_file(song, title):
    """A .jbs file's bytes for a song, under a title."""
    return dataclasses.replace(song, title=title).to_bytes()


def pcm_file(sound, title=None):
    """A .pcm file's bytes for a sound."""
    return dataclasses.replace(sound, title=title or sound.title).to_bytes()


def short_track():
    """A looping track of 17 frames, unlike the demo in every note."""
    frames = [[(0x15, 0x0F)], [(0x04, 0xBF), (0x07, 0x08)]] + [[(0x04, 0xB0 | n)] for n in range(15)]
    encoded = jbs.encode(frames, loop_frame=1)
    return jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=1,
                       loop_offset=encoded.loop_offset)


def ending_track(frames=12):
    """A track with no loop: a note, and some frames of it."""
    notes = [[(0x15, 0x0F)], [(0x00, 0xBF), (0x03, 0x08)]] + [[] for _ in range(frames - 2)]
    return jbs.JbsFile(stream=jbs.encode(notes).data, total_frames=frames)


def track_stream(title, track, loops=2):
    """One track as the nesp32 sends it."""
    if isinstance(track, pcm.Sound):
        return jbs.intro(title, track.frames) + jbs.sound_record(track.rate)
    out = jbs.intro(title, jbs.play_frames(track.total_frames, track.loop_frame, loops))
    out += track.stream
    if track.loop_frame is not None:
        out += track.stream[track.loop_offset:] * (loops - 1)
    return out


def playlist_stream(tracks, loops=2, times=1, end=False):
    """A playlist of (title, track) as one stream, `times` over; with
    `end`, as a playlist that is not to repeat ends."""
    once = b"".join(track_stream(title, track, loops) for title, track in tracks)
    return once * times + (bytes((jbs.OP_CONTROL, jbs.CTRL_END)) if end else b"")


def files(tracks):
    """The nesp32's files for a playlist of (title, track)."""
    return [pcm_file(track, title) if isinstance(track, pcm.Sound) else jbs_file(track, title)
            for title, track in tracks]


def frames_of(stream, count):
    """The first `count` frames of APU writes a stream plays as."""
    return list(itertools.islice(expected_frames(stream, None), count))


def press(machine, buttons, frames=3):
    """Hold buttons on controller 1 for some frames, then let go."""
    machine.pad = buttons
    machine.run(frames)
    machine.pad = 0


def wait_for(machine, done, limit=3000, step=1):
    """Run a frame at a time until done() is true."""
    start = len(machine.frames)
    while not done():
        assert len(machine.frames) - start < limit, "still waiting after %d frames" % limit
        machine.run(step)


def greet(machine):
    """Run until the nesp32 has answered the ROM's hello and its first
    question: the music is stopped, and the screen can say so."""
    wait_for(machine, lambda: machine.byte("greeted")
             and machine.byte("link_state") == LINK_STOPPED, limit=60)


def start(machine, how="stick"):
    """Greet, and start the music: with the nesp32's own button A, or with
    Start on the controller."""
    greet(machine)
    if how == "stick":
        machine.press_button(p.NESP_EVENT_BUTTON_A)
    else:
        press(machine, PAD_START)
    return machine


def played_exactly(machine, stream, count):
    """Play `count` frames, and see that they are the stream's first."""
    machine.run_until_played(count)
    for index, (got, want) in enumerate(zip(machine.played_frames(), frames_of(stream, count))):
        assert got == want, "frame %d" % index
    assert machine.byte("stream_error") == 0


def flip_random_bit(rng, rate):
    """A fault for the Port's to_console: now and then, one bit of a reply
    is wrong."""
    def fault(reply):
        if rng.random() >= rate:
            return reply
        data = bytearray(reply)
        data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        return bytes(data)
    return fault


def drop_random_byte(rng, rate):
    def fault(reply):
        if rng.random() >= rate:
            return reply
        index = rng.randrange(len(reply))
        return reply[:index] + reply[index + 1:]
    return fault


def damage_requests(machine, rng, rate):
    """From now on, now and then one bit of what the nesp32's UART hears
    is wrong."""
    read = machine.port.read

    def noisy():
        data = read()
        if not data:
            return data
        return bytes(byte ^ (1 << rng.randrange(8)) if rng.random() < rate else byte
                     for byte in data)
    machine.port.read = noisy

"""Tracks on their way to a nesp32: tools/pack_tracks.py, which makes the
files, and the nesp32's own JUKE service, which makes the stream of them.

The service is nesp32's firmware, built for this computer (conftest.py),
and it knows nothing of this repository: it reads the two containers and
sends what it finds. Here its stream is held to what the tools that write
those containers say it should be (linked.py), so the two cannot drift.
"""

import os
import random
import wave

import nesp
import nesp_proto as p
import pytest

import jbs
import pack_tracks
import pcm
from linked import files, playlist_stream
from vgmbuild import VgmBuilder

JUKE, RAW = p.NESP_SVC_JUKE, p.NESP_SVC_RAW


def song(frames, loop_frame=None, title=""):
    encoded = jbs.encode(frames, loop_frame)
    return jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=loop_frame,
                       loop_offset=encoded.loop_offset, title=title)


A = song([[(0x00, 0x30)], [(0x00, 0x31)], [], [], [(0x00, 0x32)]], loop_frame=1)
B = song([[(0x04, 0x40)], [(0x04, 0x41)]])
VOICE = pcm.Sound("Voices - Hello", 12, pcm.encode([index & 0x7F for index in range(900)]))


# --- the files --------------------------------------------------------------------------

def test_tracks_load_from_rips_and_jbs(tmp_path):
    (tmp_path / "tune.vgm").write_bytes(
        VgmBuilder().write(0x00, 0x30).frame(3).build(title="Tune", game="G"))
    (tmp_path / "b.jbs").write_bytes(B.to_bytes())
    (tmp_path / "notes.txt").write_text("not music")
    paths = pack_tracks.expand_paths([str(tmp_path)])
    assert [os.path.basename(path) for path in paths] == ["b.jbs", "tune.vgm"]
    assert [pack_tracks.load_track(path)[0] for path in paths] == ["b", "G - Tune"]


def test_sound_tracks_load_from_pcm_and_wav(tmp_path):
    (tmp_path / "a.pcm").write_bytes(VOICE.to_bytes())
    untitled = pcm.Sound("", VOICE.period, VOICE.samples)
    (tmp_path / "b named by its file.pcm").write_bytes(untitled.to_bytes())
    with wave.open(str(tmp_path / "c.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(bytes(1600))
    paths = pack_tracks.expand_paths([str(tmp_path)])
    assert [os.path.basename(path) for path in paths] == [
        "a.pcm", "b named by its file.pcm", "c.wav"]
    loaded = [pack_tracks.load_track(path) for path in paths]
    assert [title for title, _ in loaded] == ["Voices - Hello", "b named by its file", "c"]
    assert all(isinstance(track, pcm.Sound) for _, track in loaded)
    assert loaded[2][1].period == pcm.DEFAULT_PERIOD
    assert pack_tracks.expand_paths(["x.mp3"]) == ["x.mp3"]


def test_tracks_pack_in_playlist_order_under_names_that_sort(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "b tune.vgm").write_bytes(
        VgmBuilder().write(0x00, 0x30).frame(3).build(title="Tune", game="G"))
    (music / "a.jbs").write_bytes(A.to_bytes())
    (music / "c voice.pcm").write_bytes(pcm.Sound("", 16, VOICE.samples).to_bytes())
    (music / "broken.jbs").write_bytes(b"nope")
    out = tmp_path / "tracks"
    out.mkdir()
    (out / "09.jbs").write_bytes(b"left over from last time")
    (out / "07.pcm").write_bytes(b"and this")
    written = pack_tracks.pack([str(music)], str(out))
    assert [(name, title) for name, title, _ in written] == [
        ("00.jbs", "a"), ("01.jbs", "G - Tune"), ("02.pcm", "c voice")]
    assert written[0][2] == len(A.stream) and written[2][2] == len(VOICE.samples)
    assert sorted(os.listdir(str(out))) == ["00.jbs", "01.jbs", "02.pcm"]
    packed = jbs.JbsFile.from_bytes((out / "00.jbs").read_bytes())
    assert (packed.title, packed.stream, packed.loop_offset) == ("a", A.stream, A.loop_offset)
    sound = pcm.Sound.from_bytes((out / "02.pcm").read_bytes())
    assert (sound.title, sound.period, sound.samples) == ("c voice", 16, VOICE.samples)


def test_the_packers_tool_says_what_it_wrote(tmp_path, capsys):
    (tmp_path / "a.jbs").write_bytes(A.to_bytes())
    assert pack_tracks.main([str(tmp_path / "out"), str(tmp_path)]) == 0
    assert "1 tracks, %d bytes" % len(A.stream) in capsys.readouterr().out
    assert pack_tracks.main([str(tmp_path / "none"), str(tmp_path / "none")]) == 1


# --- what a nesp32 makes of them ------------------------------------------------------------

class Listener:
    """A console's side of JUKE with no console: it takes the stream as it
    comes, and sits through each sound."""

    def __init__(self, tracks, loops, repeat=False):
        self.stick = nesp.Stick()
        for data in tracks:
            self.stick.add_track(data)
        self.stick.set_juke(loops=loops, repeat=repeat)
        assert self.stick.hello(app=b"JUKE", reply_max=63, services=(JUKE, RAW)).ok
        self.now = 0
        self.epoch = self.pos = 0
        self.stream = b""           # every byte of every epoch, in order
        self.sounds = []            # (period, the samples sent) of each
        self.wait()

    def wait(self, ms=5):
        for _ in range(ms):
            self.now += 1
            self.stick.tick(self.now)

    def ask(self, room):
        reply = self.stick.ask(JUKE, p.NESP_JUKE_STREAM, bytes((self.epoch, self.pos, room, 0)))
        self.wait()
        state, epoch, data = reply.payload[0], reply.payload[1], reply.payload[2:]
        if epoch != self.epoch:
            self.epoch, self.pos = epoch, 0
        self.pos = (self.pos + len(data)) & 0xFF
        self.stream += data
        return state

    def play(self, rng, limit=20000):
        """Press Play and take everything, to the playlist's end."""
        self.stick.event(p.NESP_EVENT_BUTTON_A)
        for _ in range(limit):
            state = self.ask(rng.randrange(1, 57))
            if not state & p.NESP_PLAYER_DRAIN:
                continue
            if self.stream.endswith(bytes((jbs.OP_CONTROL, jbs.CTRL_END))):
                return
            # A sound is due: its record is the last thing that came.
            rate = self.stream[-1]
            reply = self.stick.ask(JUKE, p.NESP_JUKE_SOUND, bytes((self.epoch, rate)))
            assert reply.payload[1] == p.NESP_SOUND_GO
            line = self.stick.line
            line.sent.clear()
            del line.rates[:]
            while len(line.rates) < 2:
                self.wait()
            self.sounds.append((line.rates[0], bytes(line.sent)))
        raise AssertionError("the playlist did not end")


def random_song(rng):
    frames = [[(rng.choice((0x00, 0x04, 0x08)), rng.randrange(256))] if rng.random() < 0.7 else []
              for _ in range(rng.randrange(5, 400))]
    return song(frames, loop_frame=rng.randrange(len(frames)) if rng.random() < 0.6 else None)


def random_title(rng):
    words = ["Game", "Stage 1", "A Very Long Title That Goes On And On", "Boss", "x", "~!?"]
    return rng.choice(["%s - %s", "%s%s", "%s -%s"]) % (rng.choice(words), rng.choice(words))


@pytest.mark.parametrize("seed", range(8))
def test_the_nesp32_sends_the_stream_these_tools_describe(seed):
    rng = random.Random(seed)
    tracks = []
    for index in range(rng.randrange(1, 6)):
        if rng.random() < 0.3:
            period = rng.choice(pcm.PERIODS)
            samples = pcm.encode([rng.randrange(128) for _ in range(rng.randrange(1, 3000))])
            tracks.append((random_title(rng), pcm.Sound("", period, samples)))
        else:
            tracks.append((random_title(rng), random_song(rng)))
    loops = rng.randrange(1, 4)
    listener = Listener(files(tracks), loops)
    listener.play(rng)
    assert listener.stream == playlist_stream(tracks, loops=loops, end=True)
    sounds = [track for _, track in tracks if isinstance(track, pcm.Sound)]
    assert listener.sounds == [(sound.period, sound.samples + pcm.LAST_BYTE) for sound in sounds]


def test_a_length_past_the_clocks_last_minute_and_a_title_of_the_longest():
    """What the console's screen can show, at its edges: 99:59, and a name
    as long as a file may hold, cut to a line."""
    long = song([[]] * 10, title="")
    long.total_frames = 60 * 60 * 200
    tracks = [("G" * 100 + " - " + "T" * 152, long), ("  padded  -  both ways  ", B)]
    listener = Listener(files(tracks), loops=2)
    listener.play(random.Random(0))
    assert listener.stream == playlist_stream(tracks, loops=2, end=True)
    assert b"\x80\x0499:59" in listener.stream
    assert b"\x80\x03\x06padded\x80\x02\x09both ways" in listener.stream

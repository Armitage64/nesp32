"""The Stick firmware (firmware/stick) against the desktop host it ports.

protocol.py and tracks.py must send exactly what host/protocol.py and
host/playlist.py send, so most of this file drives both with the same random
input and compares bytes. The rest runs the firmware against the simulated
NES, and runs device.py on stand-ins for UIFlow's modules, which checks the
wiring between the modules but not the real M5 or machine APIs.
"""

import os
import random
import shutil
import sys
import traceback
import types

import pytest

import jbs
import protocol as desktop
from playlist import PlaylistSource
from test_playlist import A, B, song, titled

STICK = os.path.join(os.path.dirname(__file__), "..", "firmware", "stick")
sys.path.insert(0, STICK)
sys.path.insert(0, os.path.join(STICK, "tools"))

from nesjuke import protocol, tracks  # noqa: E402
from nesjuke.player import Player  # noqa: E402

C = song([[(0x15, 0x0F), (0x00, 0xBF), (0x03, 0x08), (0x17, 0x40)], [],
          [(0x08, 0x81), (0x0A, 0x42), (0x0B, 0x00)], [(0x0C, 0x30), (0x11, 0x20)]] * 6,
         loop_frame=3)
SONGS = [("A", A), ("B", B), ("C", C)]


def stick_playlist(songs=SONGS, **kwargs):
    def load(index):
        title, item = songs[index]
        return (title, item.stream, item.loop_offset if item.loop_frame is not None else None,
                item.total_frames, item.loop_frame)
    return tracks.Playlist(len(songs), load, **kwargs)


def sent(reply):
    return bytes(reply) if reply is not None else b""


# -- protocol ----------------------------------------------------------------

def test_crc_matches_the_desktop():
    assert protocol.crc16(b"123456789") == 0x29B1
    rng = random.Random(1)
    for _ in range(50):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(40)))
        assert protocol.crc16(data) == desktop.crc16(data)


def test_decoder_finds_the_same_requests_in_noise():
    rng = random.Random(2)
    line = bytearray()
    for _ in range(400):
        roll = rng.random()
        if roll < 0.6:
            line += desktop.request_bytes(rng.choice([0x4A, 0x48, 0x42, 0x53]),
                                          rng.randrange(256), rng.randrange(256))
        elif roll < 0.8:
            line += bytes(rng.randrange(256) for _ in range(rng.randrange(1, 6)))
        else:
            line += desktop.request_bytes(0x4A, 3, 24)[:rng.randrange(1, 4)]  # cut short
    theirs = desktop.RequestDecoder()
    expected = [(r.op, r.seq, r.arg) for r in theirs.feed(bytes(line))]
    ours = protocol.RequestDecoder()
    found = [(ours.op, ours.seq, ours.arg) for byte in line if ours.push(byte)]
    assert found == expected and len(found) > 200
    assert ours.discarded == theirs.discarded > 0


def random_requests(rng, count, hellos=True, presses=True):
    seq = 0
    for _ in range(count):
        roll = rng.random()
        if roll < 0.02 and hellos:
            seq = 0
            yield desktop.OP_HELLO, 0, 0
        elif roll < 0.04:
            yield desktop.OP_BUTTON, 0, rng.randrange(8) if presses else 0
        elif roll < 0.07:
            yield desktop.OP_STATS, rng.randrange(9), rng.randrange(256)
        elif roll < 0.20:
            yield desktop.OP_DATA, (seq - 1) & 0xFF, rng.choice([24, 24, 8, 255])  # again
        elif roll < 0.22:
            seq = rng.randrange(256)                                 # out of order
            yield desktop.OP_DATA, seq, 24
            seq = (seq + 1) & 0xFF
        else:
            yield desktop.OP_DATA, seq, rng.choice([24, 24, 24, 24, 8, 13, 0, 255])
            seq = (seq + 1) & 0xFF


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("prepare", ["never", "always", "sometimes"])
@pytest.mark.parametrize("repeat", [False, True])
def test_host_sends_the_same_bursts_as_the_desktop(seed, prepare, repeat):
    # A hello restarts the track the source is on. A host that prepares has
    # read up to one burst further, so near a track boundary it can restart
    # the next track where the desktop restarts the old one. That is the
    # only difference, so hellos are compared without preparing. A button
    # press that jumps or plays has the same difference, so the buttons here
    # press nothing; the next test presses them on tracks that never end.
    rng = random.Random(seed)
    theirs = desktop.Host(PlaylistSource(SONGS, loops=2, repeat=repeat))
    ours = protocol.Host(PlaylistSource(SONGS, loops=2, repeat=repeat))
    for op, seq, arg in random_requests(rng, 1500, hellos=prepare == "never", presses=False):
        want = theirs.handle(desktop.Request(op, seq, arg))
        assert sent(ours.handle(op, seq, arg)) == want
        if prepare == "always" or (prepare == "sometimes" and rng.random() < 0.5):
            ours.prepare()
    assert ours.stats == theirs.stats
    assert ours.nes == theirs.nes
    if prepare != "never":  # no hellos, which start the counters over
        assert len(ours.nes) == 7 and max(ours.nes.values()) > 255  # totals, not low bytes
    assert ours.stats["resends"] > 50 and ours.stats["unexpected_seq"] > 5


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("prepare", ["never", "always", "sometimes"])
def test_stop_play_and_jump_match_the_desktop(seed, prepare):
    """Stop, play and jump drop whatever was read ahead, so the two hosts
    agree byte for byte even while the Stick prepares.

    The tracks here loop without end, so only a jump changes the track. When
    a track ends by itself, a Stick that has read ahead is already on the
    next one, and a jump or play made in that moment starts from there."""
    rng = random.Random(seed)
    songs = [("A", A), ("C", C)]
    theirs = desktop.Host(PlaylistSource(songs, loops=10 ** 9), stopped=True)
    ours = protocol.Host(stick_playlist(songs, loops=10 ** 9), stopped=True)
    flushes = 0
    for op, seq, arg in random_requests(rng, 2500, hellos=False):
        roll = rng.random()
        if roll < 0.01:
            theirs.stop()
            ours.stop()
        elif roll < 0.03:
            theirs.play()
            ours.play()
        elif roll < 0.05 and not ours.stopped:
            delta = rng.choice([1, -1])
            for host in (theirs, ours):
                host.source.jump(delta)
                host.flush()
        want = theirs.handle(desktop.Request(op, seq, arg))
        got = sent(ours.handle(op, seq, arg))
        assert got == want
        flushes += got[:1] == bytes([protocol.FLUSH_MARKER]) and got[2] > 0
        if prepare == "always" or (prepare == "sometimes" and rng.random() < 0.5):
            ours.prepare()
    assert ours.stats == theirs.stats
    assert flushes > 20     # flush bursts that carried the start of a track


def test_prepare_has_the_next_burst_ready():
    ours = protocol.Host(PlaylistSource(SONGS, repeat=True))
    ours.prepare()
    taken = []
    take = ours.source.take
    ours.source.take = lambda count: taken.append(count) or take(count)
    for seq in range(20):
        ours.handle(desktop.OP_DATA, seq, 24)
        assert taken == [], "the reply path reached into the source"
        ours.prepare()
        assert taken == [24]
        taken.clear()


# -- tracks ------------------------------------------------------------------

def test_unit_end_walks_the_same_units_as_the_converter():
    data = C.stream + bytes([0x00, 0x81, 0x01, 0x30, 0xA0, 0x0F]) + B.stream
    units, pos = [], 0
    while pos < len(data):
        end = tracks.unit_end(data, pos)
        units.append((pos, end))
        pos = end
    assert units == jbs.frame_units(data)


@pytest.mark.parametrize("seed", range(8))
def test_playlist_matches_the_desktop(seed):
    rng = random.Random(seed)
    loops, repeat = rng.choice([1, 2, 3]), rng.random() < 0.5
    started = ([], [])
    theirs = PlaylistSource(SONGS, loops=loops, repeat=repeat,
                            on_track=lambda i, t: started[0].append((i, t)))
    ours = stick_playlist(loops=loops, repeat=repeat,
                          on_track=lambda i, t: started[1].append((i, t)))
    total = 0
    for _ in range(600):
        roll = rng.random()
        if roll < 0.05:
            delta = rng.choice([1, 1, -1, 0])
            theirs.skip(delta)
            ours.skip(delta)
        elif roll < 0.07:
            theirs.restart()
            ours.restart()
        else:
            count = rng.choice([24, 24, 1, 7, 100])
            data = theirs.take(count)
            assert ours.take(count) == data
            total += len(data)
    assert started[0] == started[1] and total > 2000


def test_tracks_pack_on_the_mac_and_load_on_the_stick(tmp_path):
    import pack_tracks
    from vgmbuild import VgmBuilder

    music = tmp_path / "music"
    music.mkdir()
    (music / "b tune.vgm").write_bytes(
        VgmBuilder().write(0x00, 0x30).frame(3).build(title="Tune", game="G"))
    (music / "a.jbs").write_bytes(C.to_bytes())
    (music / "broken.jbs").write_bytes(b"nope")
    out = tmp_path / "tracks"
    out.mkdir()
    (out / "09.jbs").write_bytes(b"left over from last time")
    written = pack_tracks.pack([str(music)], str(out))
    assert [(name, title) for name, title, _ in written] == [("00.jbs", "a"), ("01.jbs", "G - Tune")]

    paths = tracks.list_tracks(str(out))
    assert [os.path.basename(path) for path in paths] == ["00.jbs", "01.jbs"]
    title, stream, loop_offset, frames, loop_frame = tracks.load_jbs(paths[0])
    assert (title, stream, loop_offset) == ("a", C.stream, C.loop_offset)
    assert (frames, loop_frame) == (C.total_frames, C.loop_frame)
    title, stream, loop_offset, frames, loop_frame = tracks.load_jbs(paths[1])
    assert title == "G - Tune" and loop_offset is None and stream[:2] == b"\x80\x01"
    with pytest.raises(ValueError):
        tracks.load_jbs(str(music / "broken.jbs"))


# -- player ------------------------------------------------------------------

class ScriptedUart:
    """readinto() hands out one scripted chunk per call; write() records."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []
        self.inits = []         # the settings of each change of rate
        self.rate = 38400
        self.rates = []         # the rate each write went out at

    def init(self, **settings):
        self.inits.append(settings)
        self.rate = settings["baudrate"]

    def read(self):
        return None

    def readinto(self, buffer):
        if not self.chunks:
            return None
        chunk = self.chunks.pop(0)
        buffer[:len(chunk)] = chunk
        return len(chunk) or None

    def write(self, data):
        self.written.append(bytes(data))
        self.rates.append(self.rate)


def test_player_answers_requests_split_across_reads():
    hello = desktop.request_bytes(0x48, 0, 0)
    first = desktop.request_bytes(0x4A, 0, 24)
    second = desktop.request_bytes(0x4A, 1, 24)
    uart = ScriptedUart([b"\x00" + hello + first[:2], first[2:], b"", second])
    clock = iter(range(0, 10000, 300))
    player = Player(uart, protocol.Host(stick_playlist()), ticks_us=lambda: next(clock))
    assert [player.poll() for _ in range(5)] == [False, True, False, True, False]
    stream = stick_playlist().take(48)
    assert uart.written == [desktop.burst_bytes(0, stream[:24]), desktop.burst_bytes(1, stream[24:])]
    assert player.requests == 3 and player.data_requests == 2
    assert player.host.nes == {}
    assert player.decoder.discarded == 1
    assert player.take_reply_us() == (300, 300, 300) and player.take_reply_us() == (0, 0, 0)


def test_player_knows_when_the_next_request_cannot_be_near():
    request = desktop.request_bytes(0x4A, 0, 24)
    now = [0]
    uart = ScriptedUart([b"", request, b"", desktop.request_bytes(0x4A, 1, 24)])
    player = Player(uart, protocol.Host(stick_playlist()), ticks_us=lambda: now[0])
    assert player.quiet(123456)             # nothing heard yet: any time will do
    player.poll()
    now[0] = 500
    assert player.poll() is True            # a request, 0.5 ms after an empty poll
    frame = 16639
    for frames in (0, 1, 7, 200):
        start = 500 + frames * frame
        assert not player.quiet(start + 500)        # the reply is going out
        assert player.quiet(start + 1000) and player.quiet(start + 6000)
        assert not player.quiet(start + 6500)       # too close to the next one
        assert not player.quiet(start + frame - 100)
    assert player.quiet(500 + 5000001 + 9000)       # too long ago to go by

    # Bytes found after a pause were waiting in the UART: they do not move
    # the phase.
    now[0] = 20000
    assert player.poll() is False
    now[0] = 29000                          # 9 ms spent on something else
    assert player.poll() is True
    assert player.request_us == 500


def test_player_keeps_the_counters_the_nes_reports():
    uart = ScriptedUart([desktop.request_bytes(0x48, 0, 0)
                         + desktop.request_bytes(0x53, 1, 7) + desktop.request_bytes(0x53, 5, 2)
                         + desktop.request_bytes(0x53, 99, 1)])
    player = Player(uart, protocol.Host(stick_playlist()))
    assert player.poll() is False and uart.written == []
    assert player.host.nes == {"timeouts": 7, "underruns": 2}
    assert protocol.NES_COUNTERS == desktop.NES_COUNTERS


def test_player_answers_only_the_latest_of_several_waiting_requests():
    again = desktop.request_bytes(0x4A, 0, 24)
    uart = ScriptedUart([again * 3, again + desktop.request_bytes(0x48, 0, 0)])
    player = Player(uart, protocol.Host(stick_playlist()))
    assert player.poll() is True
    assert len(uart.written) == 1 and player.stale == 2
    assert player.host.stats["bursts"] == 1 and player.host.stats["resends"] == 0
    assert player.poll() is False      # a hello after it cancels the request
    assert player.host.stats["hello"] == 1 and len(uart.written) == 1


# -- the firmware against the simulated NES ----------------------------------

class AsDesktopHost:
    """Lets LinkConsole drive the Stick's Host the way Player does."""

    def __init__(self, host):
        self.host = host
        self.stats = host.stats

    def handle(self, request):
        reply = sent(self.host.handle(request.op, request.seq, request.arg))
        self.host.prepare()
        return reply


needs_cc65 = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed")


@needs_cc65
@pytest.mark.parametrize("turnaround_ms", [1.0, 12.0])
def test_stick_host_plays_frame_exact_on_the_simulated_nes(tmp_path_factory, turnaround_ms):
    import itertools
    import subprocess

    from link_harness import LinkConsole, ms
    from nes_harness import expected_frames
    from test_link import complete_frames

    build = tmp_path_factory.mktemp("stick_system")
    root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=root, check=True)
    demo = jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())

    log = bytearray()
    playlist = stick_playlist([("demo", demo), ("C", C)], loops=1, repeat=True)
    take = playlist.take
    playlist.take = lambda count: (lambda data: log.extend(data) or data)(take(count))
    restart = playlist.restart
    playlist.restart = lambda: (log.clear(), restart())
    machine = LinkConsole(str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels"),
                          host=AsDesktopHost(protocol.Host(playlist)),
                          turnaround=lambda: ms(turnaround_ms))
    machine.run(200)
    playlist.skip(1)
    machine.run_until_played(500)

    played = machine.played_frames()
    expected = list(itertools.islice(expected_frames(complete_frames(log), None), len(played)))
    assert played == expected and len(played) >= 500
    assert machine.byte("stream_error") == 0
    assert machine.word("link_crc_errors") == machine.word("link_rejects") == 0
    assert C.stream[2:] in bytes(log)
    if turnaround_ms < 6:
        assert machine.host.stats["resends"] == 0 and machine.word("underruns") == 0


@needs_cc65
def test_stick_host_stops_and_plays_on_the_simulated_nes(tmp_path_factory):
    import itertools
    import subprocess

    from link_harness import LinkConsole
    from nes_harness import expected_frames

    build = tmp_path_factory.mktemp("stick_stop")
    root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=root, check=True)
    demo = jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())
    want = list(itertools.islice(expected_frames(demo.stream, demo.loop_offset), 200))

    host = protocol.Host(stick_playlist([("demo", demo)], loops=10 ** 9), stopped=True)
    machine = LinkConsole(str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels"),
                          host=AsDesktopHost(host))
    machine.run(100)                # as the Stick powers up: answered, but silent
    assert machine.played_frames() == [] and machine.word("link_timeouts") == 0
    host.play()                     # button A
    machine.run_until_played(200)
    assert machine.played_frames()[:200] == want
    host.stop()                     # the power button
    machine.run(60)
    played = len(machine.played_frames())
    assert machine.byte("playing") == 0
    host.play()
    machine.run_until_played(played + 200)
    assert machine.played_frames()[played:played + 200] == want
    assert machine.word("underruns") == 0 and machine.word("link_timeouts") == 0


# -- device.py on stand-ins for UIFlow ---------------------------------------

class FakeTime:
    """MicroPython's time functions on a clock that moves 5 ms per reading."""

    def __init__(self):
        self.now_us = 0

    def ticks_us(self):
        self.now_us += 5000
        return self.now_us

    def ticks_ms(self):
        return self.ticks_us() // 1000

    def ticks_diff(self, a, b):
        return a - b

    def ticks_add(self, a, delta):
        return a + delta

    def sleep_ms(self, ms):
        self.now_us += ms * 1000


class FakeLcd:
    FONTS = types.SimpleNamespace(Montserrat12=12, Montserrat14=14)

    def __init__(self):
        self.text = {}  # (x, y) -> the last string drawn there

    def drawString(self, text, x, y):
        self.text[(x, y)] = text

    def textWidth(self, text):
        return 7 * len(text)

    def __getattr__(self, name):  # fills, colors, fonts, brightness
        return lambda *args: None


class FakeButton:
    def __init__(self):
        self.presses = 0
        self.held = False

    def wasPressed(self):
        pressed, self.presses = self.presses > 0, max(0, self.presses - 1)
        return pressed

    wasClicked = wasPressed

    def pressedFor(self, ms):
        return self.held


def forget_hardware_modules():
    """Make the next import of the modules that import M5 or machine a fresh one."""
    import nesjuke
    for name in ("board", "ui", "device"):
        sys.modules.pop("nesjuke." + name, None)
        if hasattr(nesjuke, name):
            delattr(nesjuke, name)


@pytest.fixture
def uiflow(monkeypatch, tmp_path):
    """Import nesjuke.device with fake M5 and machine modules in place."""
    m5 = types.ModuleType("M5")
    m5.BOARD = types.SimpleNamespace(M5StickS3=142, M5StickCPlus2=5)
    m5.board = m5.BOARD.M5StickCPlus2
    m5.getBoard = lambda: m5.board
    m5.begin = m5.update = lambda: None
    m5.Lcd = FakeLcd()
    m5.BtnA, m5.BtnB, m5.BtnPWR = FakeButton(), FakeButton(), FakeButton()
    m5.powered_off = []
    m5.Power = types.SimpleNamespace(getBatteryLevel=lambda: 87,
                                     powerOff=lambda: m5.powered_off.append(True))
    machine = types.ModuleType("machine")
    machine.opened = []

    class UART(ScriptedUart):
        INV_TX, INV_RX = 4, 1

        def __init__(self, uart_id, **settings):
            super().__init__(machine.script)
            machine.opened.append((uart_id, settings))
            machine.uart = self

    machine.UART = UART
    machine.script = []
    # MicroPython's way to print a traceback.
    monkeypatch.setattr(sys, "print_exception", traceback.print_exception, raising=False)
    monkeypatch.setitem(sys.modules, "M5", m5)
    monkeypatch.setitem(sys.modules, "machine", machine)
    forget_hardware_modules()
    from nesjuke import device

    (tmp_path / "tracks").mkdir()
    for index, (title, item) in enumerate(SONGS):
        item = jbs.JbsFile(stream=item.stream, total_frames=item.total_frames,
                           loop_frame=item.loop_frame, loop_offset=item.loop_offset, title=title)
        (tmp_path / "tracks" / ("%02d.jbs" % index)).write_bytes(item.to_bytes())
    monkeypatch.setattr(device, "time", FakeTime())
    monkeypatch.setattr(device, "TRACKS_PATH", str(tmp_path / "tracks"))
    monkeypatch.setattr(device, "CONFIG_PATH", str(tmp_path / "config.json"))
    yield types.SimpleNamespace(M5=m5, machine=machine, device=device, root=tmp_path)
    forget_hardware_modules()


def run_device(uiflow, script, on_idle=None, press_a=True):
    """Run the device until the script is used up, then hold B to power off.
    The device starts stopped, so button A is pressed at once unless told not."""
    m5, machine = uiflow.M5, uiflow.machine
    machine.script = list(script)
    calls = [0]

    def update():
        calls[0] += 1
        if calls[0] == 1 and press_a:
            m5.BtnA.presses = 1
        if on_idle:
            on_idle(calls[0])
        if not machine.uart.chunks:
            m5.BtnB.held = True

    m5.update = update
    uiflow.device.main()
    # As the UART opens: for a console left in the middle of a sound.
    assert machine.uart.written.pop(0) == bytes(4)
    machine.uart.rates.pop(0)
    return machine.uart


def music(uart):
    """The stream the device sent: every burst's payload, in order. Also
    checks that the bursts are well formed and count up."""
    stream = bytearray()
    for seq, burst in enumerate(uart.written):
        payload = burst[3:-2]
        assert burst == desktop.burst_bytes(seq & 0xFF, payload, flush=burst[0] == 0x5A,
                                            pause=burst[0] == 0x3C)
        stream += payload
    return bytes(stream)


def flush_bursts(uart):
    return [burst[3:-2] for burst in uart.written if burst[0] == 0x5A]


def drawn(uiflow):
    return " | ".join(uiflow.M5.Lcd.text.values())


def data_requests(count, credit=24):
    return [desktop.request_bytes(0x48, 0, 0)] + [
        desktop.request_bytes(0x4A, seq & 0xFF, credit) for seq in range(count)]


def test_device_plays_on_a_plus2_and_powers_off(uiflow, capsys):
    uart = run_device(uiflow, data_requests(300))
    stream = music(uart)
    assert stream == stick_playlist(loops=2, repeat=True).take(len(stream))
    assert len(uart.written) == 300 and len(stream) > 295 * 24
    # Starting to play flushes the NES, in the first burst that carries music.
    assert [payload for payload in flush_bursts(uart) if payload] == [stream[:24]]
    uart_id, settings = uiflow.machine.opened[0]
    assert (uart_id, settings["tx"], settings["rx"]) == (1, 26, 36)
    assert settings["baudrate"] == 38400 and settings["stop"] == 2 and settings["invert"] == 5
    assert uiflow.M5.powered_off == [True]
    screen = drawn(uiflow)
    assert "StickC Plus2" in screen and "PLAYING" in screen and "87%" in screen
    assert "TX G26, RX G36, 3 tracks" in capsys.readouterr().out


def test_device_waits_for_button_a_before_the_first_track(uiflow):
    uart = run_device(uiflow, data_requests(300), press_a=False)
    # The NES is answered, so it does not time out, but with nothing to play.
    assert uart.written == [desktop.burst_bytes(seq & 0xFF, b"", flush=True) for seq in range(300)]
    assert "| STOPPED |" in drawn(uiflow) and "1/3" in drawn(uiflow)


def test_device_button_a_pauses_and_resumes_where_it_was(uiflow):
    directory = uiflow.root / "tracks"
    (directory / "00.jbs").write_bytes(C.to_bytes())    # long enough to pause in

    def press(call):
        if call in (3, 30):
            uiflow.M5.BtnA.presses = 1

    uart = run_device(uiflow, data_requests(80), on_idle=press)
    markers = [burst[0] for burst in uart.written]
    paused = [index for index, marker in enumerate(markers) if marker == 0x3C]
    assert len(paused) > 10 and paused == list(range(paused[0], paused[-1] + 1))
    assert all(uart.written[index][2] == 0 for index in paused)     # empty
    assert set(markers[paused[-1] + 1:]) == {0xA5}                  # on, with no flush
    # Nothing was dropped or sent twice: the music is one unbroken stream.
    stream = music(uart)
    assert stream == stick_playlist([("", C), ("B", B), ("C", C)], loops=2,
                                    repeat=True).take(len(stream))


def test_device_says_paused(uiflow):
    def press(call):
        if call == 3:
            uiflow.M5.BtnA.presses = 1

    run_device(uiflow, data_requests(300), on_idle=press)
    assert "| PAUSED |" in drawn(uiflow)


def test_device_power_button_is_the_next_track(uiflow):
    directory = uiflow.root / "tracks"
    (directory / "00.jbs").write_bytes(C.to_bytes())

    def press(call):
        if call == 3:
            uiflow.M5.BtnPWR.presses = 1

    uart = run_device(uiflow, data_requests(30), on_idle=press)
    music(uart)
    assert flush_bursts(uart)[-1].startswith(titled("B", B)[:20])


def test_device_shows_the_counters_the_nes_reports(uiflow, capsys):
    script = data_requests(1200)    # long enough for the 5 s USB log line
    script[100:100] = [desktop.request_bytes(0x53, 0, 3), desktop.request_bytes(0x53, 1, 12),
                       desktop.request_bytes(0x53, 5, 4)]
    run_device(uiflow, script)
    assert "NES" not in drawn(uiflow).replace("NES JUKEBOX", "")  # the log only
    out = capsys.readouterr().out
    assert "NES aborts 3 timeouts 12 underruns 4" in out
    # On the fake clock every reading is 5 ms. The log line is timed apart
    # from the chore it runs in, so it does not show up as a long chore.
    assert "chore max 10000 us log 5000 us" in out.splitlines()[-1]


def test_device_uses_the_s3_pins_on_an_s3(uiflow):
    uiflow.M5.board = uiflow.M5.BOARD.M5StickS3
    run_device(uiflow, data_requests(3))
    settings = uiflow.machine.opened[0][1]
    assert (settings["tx"], settings["rx"]) == (8, 1)
    assert "StickS3" in drawn(uiflow)


def test_device_buttons_change_the_track(uiflow):
    # C first: it is long enough that a button lands in the middle of it.
    directory = uiflow.root / "tracks"
    (directory / "00.jbs").write_bytes(C.to_bytes())
    (directory / "02.jbs").write_bytes(A.to_bytes())

    def press(call):
        if call == 3:
            uiflow.M5.BtnB.presses = 1    # previous, which wraps to the last track

    uart = run_device(uiflow, data_requests(40), on_idle=press)
    stream = music(uart)
    # Left alone, C would play through its loop twice and B would follow.
    two_passes = 2 * len(C.stream) - C.loop_offset
    assert stream.startswith(titled("", C)[:24])
    assert 0 < stream.find(A.stream) < two_passes < stream.find(B.stream)
    # The change is at once: the new track starts a flush burst of its own.
    assert flush_bursts(uart)[-1] == titled("", A, 2)[:24]
    assert "/3" in drawn(uiflow)


def test_device_clock_follows_what_the_nes_is_playing(uiflow):
    device = uiflow.device
    host = types.SimpleNamespace(fresh_starts=1, sent=0, drained=False, stopped=False,
                                 paused=False)
    playlist = types.SimpleNamespace(track_start=0, track_frames=60 * 100)
    it = types.SimpleNamespace(player=types.SimpleNamespace(host=host), playlist=playlist,
                               _fresh_starts=0, _playing_since=None, _paused_at=None)
    position = lambda now: device.Device.position(it, now)  # noqa: E731

    assert position(1000) == 0              # the NES is still filling its buffer
    host.sent = 800
    assert position(2000) == 0              # full: it starts to play now
    assert position(12000) == 601           # ten seconds on, at 60.1 frames a second
    assert device.clock_text(position(12000)) == "0:10"

    host.paused = True                      # paused: the clock holds
    assert position(12000) == 601 and position(50000) == 601
    host.paused = False                     # and goes on from there
    assert position(50000) == 601 and position(51000) == 661
    playlist.track_start = 0
    host.fresh_starts, host.sent = 2, 800   # the track starts over
    assert position(60000) == 0 and position(70000) == 601
    host.fresh_starts, host.sent = 3, 800
    position(100000)

    # The next track follows by itself. It was sent ahead of being heard, so
    # the clock waits at zero until the NES gets there.
    playlist.track_start = 900
    assert position(101000) == 0
    assert position(120000) == 1202 - 900
    assert position(10 ** 6) == playlist.track_frames   # and stops at the end

    host.fresh_starts, host.sent = 4, 24    # a jump: the NES starts over
    playlist.track_start = 0
    assert position(2000000) == 0
    host.sent = 100
    host.drained = True                     # a stream shorter than the prefill
    assert position(2001000) == 0 and position(2002000) == 60
    host.stopped = True
    assert position(2010000) == 0


def test_device_shows_the_clock_and_plain_stopped(uiflow):
    run_device(uiflow, data_requests(300))
    assert "| TIME | 0:0" in drawn(uiflow) and " / 0:0" in drawn(uiflow)
    assert "A PLAYS" not in drawn(uiflow)


def test_stick_host_counts_what_the_nes_holds():
    host = protocol.Host(stick_playlist(loops=10 ** 6), stopped=True)
    host.handle(protocol.OP_DATA, 0, 24)
    assert (host.sent, host.drained) == (0, False)
    host.play()
    starts = host.fresh_starts
    host.handle(protocol.OP_DATA, 1, 24)
    host.handle(protocol.OP_DATA, 2, 24)
    host.handle(protocol.OP_DATA, 2, 24)    # a resend sends nothing new
    assert (host.sent, host.fresh_starts) == (48, starts + 1)
    host.source.jump(1)
    host.flush()
    host.handle(protocol.OP_DATA, 3, 10)
    assert (host.sent, host.fresh_starts) == (10, starts + 2)
    assert host.source.frames_out >= 0 and host.source.track_start == 0


def test_stick_playlist_counts_frames_for_the_clock():
    playlist = stick_playlist(loops=2)
    assert playlist.track_frames == jbs.play_frames(A.total_frames, A.loop_frame, 2)
    while playlist.index == 0:
        playlist.take(1)
    # B has begun: everything before it was A, which played track_frames.
    assert playlist.track_start == jbs.play_frames(A.total_frames, A.loop_frame, 2)
    assert playlist.track_frames == B.total_frames
    playlist.jump(1)
    assert playlist.track_start == 0 and playlist.frames_out == 0


def test_device_obeys_the_nes_controller(uiflow):
    # Button requests from the NES: Right twice, then Start, then Start. The
    # first Start pauses and the second goes on.
    script = data_requests(60)
    script[10:10] = [desktop.request_bytes(0x42, 0, protocol.BUTTON_NEXT)]
    script[20:20] = [desktop.request_bytes(0x42, 0, protocol.BUTTON_NEXT)]
    script[30:30] = [desktop.request_bytes(0x42, 0, protocol.BUTTON_PLAY)]
    script[45:45] = [desktop.request_bytes(0x42, 0, protocol.BUTTON_PLAY)]
    uart = run_device(uiflow, script)
    music(uart)
    # Each start is a flush burst: button A's at the beginning, then Right's.
    begun = [payload for payload in flush_bursts(uart) if payload]
    assert len(begun) == 3 and begun[0][:7] == titled("A", A)[:7]
    markers = [burst[0] for burst in uart.written]
    assert markers.count(0x3C) > 10 and markers[-1] == 0xA5


def test_device_config_overrides_board_and_pins(uiflow):
    uiflow.M5.board = 999
    (uiflow.root / "config.json").write_text(
        '{"board": "s3", "tx": 9, "invert": false, "repeat": false, "loops": 1}')
    uart = run_device(uiflow, data_requests(200))
    settings = uiflow.machine.opened[0][1]
    assert (settings["tx"], settings["rx"], settings["invert"]) == (9, 1, 0)
    assert uart.written[-1] == desktop.burst_bytes(199, b"")  # the playlist ended


@pytest.mark.parametrize("break_it, message", [
    (lambda u: shutil.rmtree(u.root / "tracks"), "no tracks"),
    (lambda u: setattr(u.M5, "board", 999), "unknown board 999"),
    (lambda u: (u.root / "config.json").write_text('{"board": "c"}'), "board must be"),
])
def test_device_shows_what_is_wrong(uiflow, capsys, break_it, message):
    break_it(uiflow)
    uiflow.device.main()
    assert message in drawn(uiflow) and "ERROR" in drawn(uiflow)
    assert not uiflow.machine.opened


# -- sampled sound -------------------------------------------------------------

import pcm  # noqa: E402
from nesjuke import sound as stick_sound  # noqa: E402

VOICE = pcm.Sound("Voices - Hello", 12, pcm.encode([index & 0x7F for index in range(1500)]))


def test_the_sound_module_matches_the_desktops(tmp_path):
    assert stick_sound.PERIODS == pcm.PERIODS and stick_sound.CPU_HZ == pcm.CPU_HZ
    assert [stick_sound.baud(period) for period in pcm.PERIODS] == [
        pcm.baud(period) for period in pcm.PERIODS]
    assert stick_sound.LAST_BYTE == pcm.LAST_BYTE and stick_sound.FILLER == pcm.FILLER
    assert stick_sound.FRAME_BITS == pcm.FRAME_BITS
    assert (protocol.SOUND_LISTEN_MS, protocol.SOUND_START_MS, protocol.SOUND_MARKER) == (
        desktop.SOUND_LISTEN_MS, desktop.SOUND_START_MS, desktop.SOUND_MARKER)
    path = tmp_path / "00.pcm"
    path.write_bytes(VOICE.to_bytes())
    title, track = stick_sound.load(str(path))
    assert (title, track.period, track.rate, track.count) == (
        "Voices - Hello", 12, VOICE.rate, len(VOICE.samples))
    assert path.read_bytes()[track.start:] == VOICE.samples
    assert stick_sound.frames(track) == VOICE.frames
    for bad in (b"JBS\x1a" + bytes(30), VOICE.to_bytes()[:5],
                b"NPCM\x01\x2f" + VOICE.to_bytes()[6:]):
        path.write_bytes(bad)
        with pytest.raises(ValueError):
            stick_sound.load(str(path))


def mixed_playlists(tmp_path, **kwargs):
    """The same playlist, music and sound, as the desktop's and the Stick's."""
    path = tmp_path / "01.pcm"
    path.write_bytes(VOICE.to_bytes())
    songs = [("A", A), ("Voices - Hello", VOICE), ("C", C)]

    def load(index):
        title, item = songs[index]
        if item is VOICE:
            return tracks.load_sound(str(path))
        return (title, item.stream, item.loop_offset if item.loop_frame is not None else None,
                item.total_frames, item.loop_frame)

    return (PlaylistSource(songs, **kwargs), tracks.Playlist(len(songs), load, **kwargs))


@pytest.mark.parametrize("seed", range(4))
def test_playlist_with_sound_matches_the_desktop(tmp_path, seed):
    rng = random.Random(40 + seed)
    theirs, ours = mixed_playlists(tmp_path, loops=2, repeat=True)
    sounds = total = 0
    for _ in range(800):
        roll = rng.random()
        assert (ours.sound is None) == (theirs.sound is None)
        if theirs.sound is not None:
            assert ours.sound.rate == theirs.sound.rate
        if theirs.sound is not None and roll < 0.3:
            theirs.sound_done()
            ours.sound_done()
            sounds += 1
        elif roll < 0.05:
            delta = rng.choice([1, -1])
            theirs.jump(delta)
            ours.jump(delta)
        elif roll < 0.08:
            theirs.restart()
            ours.restart()
        else:
            count = rng.choice([24, 24, 1, 7, 100])
            data = theirs.take(count)
            assert ours.take(count) == data
            total += len(data)
    assert sounds > 5 and total > 1000


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("prepare", [False, True])
def test_host_with_sound_matches_the_desktop(tmp_path, seed, prepare):
    """Data requests and sound requests at both hosts: the same bytes back,
    and the same moments at which a sound is due. A sound request comes
    when a console would send one, after the last of the sound's record;
    and as in the tests above, nothing here jumps, since a host that has
    read ahead does that from a burst further on."""
    rng = random.Random(60 + seed)
    theirs_source, ours_source = mixed_playlists(tmp_path, loops=1, repeat=True)
    theirs, ours = desktop.Host(theirs_source), protocol.Host(ours_source)
    seq = 0
    go_bursts = refused = 0
    for _ in range(1500):
        roll = rng.random()
        asking = theirs_source.sound is not None and not theirs_source.pending
        if asking and roll < 0.7:
            op, arg = desktop.OP_SOUND, VOICE.rate if roll < 0.6 else 0xFF
        else:
            op, arg = 0x4A, rng.choice([24, 24, 24, 8, 0])
        this = seq if rng.random() > 0.15 else (seq - 1) & 0xFF     # now and then a repeat
        expected = theirs.handle(desktop.Request(op, this, arg))
        assert sent(ours.handle(op, this, arg)) == expected
        assert ours.sound_due == theirs.sound_due
        if this == seq:
            seq = (seq + 1) & 0xFF
            go_bursts += expected[:1] == bytes([desktop.SOUND_MARKER])
            refused += op == desktop.OP_SOUND and arg == 0xFF
        if theirs.sound_due and rng.random() < 0.4:         # the samples went
            assert ours.sound_begin().rate == theirs.sound_begin().rate
            theirs.sound_end()
            ours.sound_end()
        if prepare:
            ours.prepare()
    assert go_bursts > 5 and refused > 2
    assert ours.stats == theirs.stats


def test_sound_packs_on_the_mac_and_loads_on_the_stick(tmp_path):
    import pack_tracks

    music = tmp_path / "music"
    music.mkdir()
    (music / "a.jbs").write_bytes(C.to_bytes())
    untitled = pcm.Sound("", 16, VOICE.samples)
    (music / "b voice.pcm").write_bytes(untitled.to_bytes())
    out = tmp_path / "tracks"
    out.mkdir()
    (out / "07.pcm").write_bytes(b"left over from last time")
    written = pack_tracks.pack([str(music)], str(out))
    assert written == [("00.jbs", "a", len(C.stream)), ("01.pcm", "b voice", len(VOICE.samples))]
    paths = tracks.list_tracks(str(out))
    assert [os.path.basename(path) for path in paths] == ["00.jbs", "01.pcm"]
    assert tracks.load_track(paths[0])[:2] == ("a", C.stream)
    title, stream, loop_offset, frames, _, track = tracks.load_track(paths[1])
    assert (title, stream, loop_offset) == ("b voice", jbs.sound_record(1), None)
    assert frames == untitled.frames and track.period == 16


class SoundFile:
    """What LinkConsole needs of a sound: the Stick's has only its path."""

    def __init__(self, track):
        self.period = track.period
        with open(track.path, "rb") as handle:
            handle.seek(track.start)
            self.samples = handle.read()


class AsDesktopHostWithSound(AsDesktopHost):
    @property
    def sound_due(self):
        return self.host.sound_due

    def sound_begin(self):
        return SoundFile(self.host.sound_begin())

    def sound_end(self):
        self.host.sound_end()
        self.host.prepare()


@needs_cc65
@pytest.mark.parametrize("turnaround_ms", [1.0, 12.0])
def test_stick_host_plays_a_sound_track_on_the_simulated_nes(tmp_path_factory, tmp_path,
                                                             turnaround_ms):
    import subprocess

    from link_harness import LinkConsole, ms
    from test_sound import music_is_exact

    build = tmp_path_factory.mktemp("stick_sound")
    root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=root, check=True)
    path = tmp_path / "01.pcm"
    path.write_bytes(VOICE.to_bytes())
    songs = [("C", C), ("Voices - Hello", VOICE), ("A", A)]

    def load(index):
        title, item = songs[index]
        if item is VOICE:
            return tracks.load_sound(str(path))
        return (title, item.stream, item.loop_offset if item.loop_frame is not None else None,
                item.total_frames, item.loop_frame)

    playlist = tracks.Playlist(len(songs), load, loops=3, repeat=True)
    log = bytearray()
    take = playlist.take
    playlist.take = lambda count: (lambda data: log.extend(data) or data)(take(count))
    restart = playlist.restart
    playlist.restart = lambda: (log.clear(), restart())
    machine = LinkConsole(str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels"),
                          host=AsDesktopHostWithSound(protocol.Host(playlist)),
                          turnaround=lambda: ms(turnaround_ms))
    machine.level_log = []
    while len(machine.sounds) < 2:
        assert len(machine.frames) < 3000
        machine.run(10)
    machine.run(60)
    # The music writes $4011 too (C sets the level); a sound is what was
    # written while its samples were on the line.
    whole = pcm.decode(VOICE.samples) + [0]
    for start, end, _ in machine.sounds[:2]:
        assert [value & 0x7F for cycle, value in machine.level_log
                if start <= cycle <= end + 1000] == whole
    music_is_exact(machine, types.SimpleNamespace(log=log))
    assert machine.word("link_crc_errors") == machine.word("link_rejects") == 0


def sound_device(uiflow, script, **kwargs):
    """Run the device with a sound as its first track and music after it."""
    directory = uiflow.root / "tracks"
    (directory / "00.pcm").write_bytes(VOICE.to_bytes())
    (directory / "00.jbs").unlink()
    (directory / "02.jbs").unlink()
    return run_device(uiflow, script, **kwargs)


def sound_script(after=40):
    """The console as a sound track plays: hello, a request answered while
    the Stick is still stopped (button A comes after it), the requests that
    fetch the sound's names and its record, its sound request, silence
    while it waits and plays, and then requests for the music after it."""
    return ([desktop.request_bytes(0x48, 0, 0), desktop.request_bytes(0x4A, 0, 24),
             desktop.request_bytes(0x4A, 1, 24), desktop.request_bytes(0x4A, 2, 24),
             desktop.request_bytes(0x50, 3, VOICE.rate)]
            + [b""] * 30
            + [desktop.request_bytes(0x4A, seq, 24) for seq in range(4, 4 + after)])


PLACE = jbs.intro("Voices - Hello", VOICE.frames) + jbs.sound_record(VOICE.rate)
GO = desktop.burst_bytes(3, bytes([VOICE.rate]), go=True)
# The playlist is the sound and then B, over and over.
AFTER = desktop.burst_bytes(4, (titled("B", B, loops=2) + PLACE)[:24], flush=True)


def test_device_plays_a_sound_track_and_takes_the_link_back(uiflow, capsys):
    uart = sound_device(uiflow, sound_script())
    written = uart.written
    assert written[0] == desktop.burst_bytes(0, b"", flush=True)
    assert written[1] == desktop.burst_bytes(1, PLACE[:24], flush=True)
    assert written[2] == desktop.burst_bytes(2, PLACE[24:])
    assert written[3] == GO
    # Then the samples, in chunks, at their own rate, and the byte that ends them.
    chunks = len(VOICE.samples) // stick_sound.CHUNK + 1
    assert b"".join(written[4:4 + chunks]) == VOICE.samples
    assert written[4 + chunks] == pcm.LAST_BYTE
    assert [init["baudrate"] for init in uart.inits] == [pcm.baud(12), 38400]
    assert all(init["stop"] == 2 and init["invert"] == 5 for init in uart.inits)
    assert uart.rates[:4] == [38400] * 4
    assert uart.rates[4:5 + chunks] == [pcm.baud(12)] * (chunks + 1)
    # The link is back: the music after the sound, from an emptied buffer.
    assert uart.rates[5 + chunks] == 38400 and written[5 + chunks] == AFTER
    assert "sound: 1500 samples at 149148 baud" in capsys.readouterr().out


def test_device_does_not_send_samples_to_a_console_that_asks_again(uiflow):
    """Another request inside the wait means the console missed the go
    burst. It gets the same one, and the wait starts over."""
    script = sound_script()
    script[5:5] = [b""] * 5 + [desktop.request_bytes(0x50, 3, VOICE.rate)]
    uart = sound_device(uiflow, script)
    assert uart.written[3:5] == [GO, GO]
    assert uart.rates[:5] == [38400] * 5 and uart.rates[5] == pcm.baud(12)
    assert [init["baudrate"] for init in uart.inits] == [pcm.baud(12), 38400]


def test_device_button_stops_a_sound(uiflow):
    m5 = uiflow.M5
    polls = []

    def on_idle(count):
        # The first poll inside the sound is the first after the go burst.
        if uiflow.machine.uart.inits and not polls:
            polls.append(count)
            m5.BtnPWR.presses = 1

    uart = sound_device(uiflow, sound_script(), on_idle=on_idle)
    written = uart.written
    assert written[4] == VOICE.samples[:stick_sound.CHUNK] and written[5] == pcm.LAST_BYTE
    assert [init["baudrate"] for init in uart.inits] == [pcm.baud(12), 38400]
    # The power button is "next": the track after the sound, flushed.
    assert written[6] == AFTER

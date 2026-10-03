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
from test_playlist import A, B, song

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
        return title, item.stream, item.loop_offset if item.loop_frame is not None else None
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


def random_requests(rng, count, hellos=True):
    seq = 0
    for _ in range(count):
        roll = rng.random()
        if roll < 0.02 and hellos:
            seq = 0
            yield desktop.OP_HELLO, 0, 0
        elif roll < 0.04:
            yield desktop.OP_BUTTON, 0, rng.randrange(8)
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
    # only difference, so hellos are compared without preparing.
    rng = random.Random(seed)
    theirs = desktop.Host(PlaylistSource(SONGS, loops=2, repeat=repeat))
    ours = protocol.Host(PlaylistSource(SONGS, loops=2, repeat=repeat))
    for op, seq, arg in random_requests(rng, 1500, hellos=prepare == "never"):
        want = theirs.handle(desktop.Request(op, seq, arg))
        assert sent(ours.handle(op, seq, arg)) == want
        if prepare == "always" or (prepare == "sometimes" and rng.random() < 0.5):
            ours.prepare()
    assert ours.stats == theirs.stats and ours.buttons == theirs.buttons
    assert ours.nes == theirs.nes and len(ours.nes) == 7
    assert ours.stats["resends"] > 50 and ours.stats["unexpected_seq"] > 5


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
    title, stream, loop_offset = tracks.load_jbs(paths[0])
    assert (title, stream, loop_offset) == ("a", C.stream, C.loop_offset)
    title, stream, loop_offset = tracks.load_jbs(paths[1])
    assert title == "G - Tune" and loop_offset is None and stream[:2] == b"\x80\x01"
    with pytest.raises(ValueError):
        tracks.load_jbs(str(music / "broken.jbs"))


# -- player ------------------------------------------------------------------

class ScriptedUart:
    """readinto() hands out one scripted chunk per call; write() records."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []

    def readinto(self, buffer):
        if not self.chunks:
            return None
        chunk = self.chunks.pop(0)
        buffer[:len(chunk)] = chunk
        return len(chunk) or None

    def write(self, data):
        self.written.append(bytes(data))


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
    assert player.take_reply_us_max() == 300 and player.take_reply_us_max() == 0


def test_player_keeps_the_counters_the_nes_reports():
    uart = ScriptedUart([desktop.request_bytes(0x53, 1, 7) + desktop.request_bytes(0x53, 5, 2)
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
    m5.BtnA, m5.BtnB = FakeButton(), FakeButton()
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


def run_device(uiflow, script, on_idle=None):
    """Run the device until the script is used up, then hold B to power off."""
    m5, machine = uiflow.M5, uiflow.machine
    machine.script = list(script)
    calls = [0]

    def update():
        calls[0] += 1
        if on_idle:
            on_idle(calls[0])
        if not machine.uart.chunks:
            m5.BtnB.held = True

    m5.update = update
    uiflow.device.main()
    return machine.uart


def drawn(uiflow):
    return " | ".join(uiflow.M5.Lcd.text.values())


def data_requests(count, credit=24):
    return [desktop.request_bytes(0x48, 0, 0)] + [
        desktop.request_bytes(0x4A, seq & 0xFF, credit) for seq in range(count)]


def test_device_plays_on_a_plus2_and_powers_off(uiflow, capsys):
    uart = run_device(uiflow, data_requests(300))
    expected = stick_playlist(loops=2, repeat=True)
    assert uart.written == [desktop.burst_bytes(seq & 0xFF, expected.take(24)) for seq in range(300)]
    uart_id, settings = uiflow.machine.opened[0]
    assert (uart_id, settings["tx"], settings["rx"]) == (1, 26, 36)
    assert settings["baudrate"] == 38400 and settings["stop"] == 2 and settings["invert"] == 5
    assert uiflow.M5.powered_off == [True]
    screen = drawn(uiflow)
    assert "StickC Plus2" in screen and "PLAYING" in screen and "87%" in screen
    assert "TX G26, RX G36, 3 tracks" in capsys.readouterr().out


def test_device_shows_the_counters_the_nes_reports(uiflow, capsys):
    script = data_requests(1200)    # long enough for the 5 s USB log line
    script[100:100] = [desktop.request_bytes(0x53, 0, 3), desktop.request_bytes(0x53, 1, 12),
                       desktop.request_bytes(0x53, 5, 4)]
    run_device(uiflow, script)
    assert "3/12/-/-/4" in drawn(uiflow)
    assert "NES aborts 3 timeouts 12 underruns 4" in capsys.readouterr().out


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
    stream = b"".join(burst[3:-2] for burst in uart.written)
    # Left alone, C would play through its loop twice and B would follow.
    two_passes = 2 * len(C.stream) - C.loop_offset
    assert stream.startswith(C.stream[:24])
    assert 0 < stream.find(A.stream) < two_passes < stream.find(B.stream)
    assert "/3" in drawn(uiflow)


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

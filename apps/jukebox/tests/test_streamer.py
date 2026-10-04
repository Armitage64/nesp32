import os

import jbs
import jukebox
import protocol
from playlist import PlaylistSource
from protocol import Host
from test_playlist import A, B, titled


def test_streamer_answers_requests_and_times_itself():
    streamer = jukebox.Streamer(Host(PlaylistSource([("A", A)])))
    out = streamer.on_bytes(b"\x00" + protocol.request_bytes(0x4A, 0, 24), 10.0, clock=lambda: 10.0005)
    expected = PlaylistSource([("A", A)]).take(24)  # A, then into its loop
    assert out == protocol.burst_bytes(0, expected)
    assert abs(streamer.reply_ms[0] - 0.5) < 1e-6
    assert streamer.data_requests == 1
    assert "req 1" in streamer.status() and "noise 1" in streamer.status()


def test_status_shows_the_nes_counters_and_the_log_shows_each_read():
    import io
    log = io.StringIO()
    streamer = jukebox.Streamer(Host(PlaylistSource([("A", A)])), log=log)
    again = protocol.request_bytes(0x4A, 0, 24)
    streamer.on_bytes(again, 5.0)
    streamer.on_bytes(again + protocol.request_bytes(0x53, 1, 176)
                      + protocol.request_bytes(0x53, 1, 180), 5.232)
    assert "resends 1 (50.0%)" in streamer.status()
    assert streamer.status().endswith("NES: timeouts 4")
    lines = log.getvalue().splitlines()
    assert lines[0] == "0.00 read 4a 00 18 f7"
    assert lines[1].startswith("0.00 J seq 0 arg 24 -> ") and "resend" not in lines[1]
    # The 232 ms between reads is what gave away a mis-set latency timer.
    assert lines[2].startswith("232.00 read ") and lines[3].endswith("(resend)")
    assert lines[4] == "232.00 S seq 1 arg 176 -> 0 bytes"


def test_low_latency_asks_macos_for_milliseconds(monkeypatch):
    """Apple's header says microseconds, but 1000 set a real FTDI cable's
    timer to 1000 & 255 = 232 ms, and the NES timed out on every request."""
    import fcntl
    import struct
    import sys
    asked = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fcntl, "ioctl", lambda fd, request, arg: asked.append((fd, request, arg)))

    class Port:
        def fileno(self):
            return 7

    assert jukebox.set_low_latency(Port()) == "1 ms requested"
    assert asked == [(7, jukebox.IOSSDATALAT, struct.pack("L", 1))]

    def refuse(fd, request, arg):
        raise OSError("not a serial port")
    monkeypatch.setattr(fcntl, "ioctl", refuse)
    assert jukebox.set_low_latency(Port()).startswith("driver default")


def test_tracks_load_from_rips_and_jbs(tmp_path):
    from vgmbuild import VgmBuilder
    vgm_path = tmp_path / "tune.vgm"
    vgm_path.write_bytes(VgmBuilder().write(0x00, 0x30).frame(3).build(title="Tune", game="G"))
    jbs_path = tmp_path / "b.jbs"
    jbs_path.write_bytes(B.to_bytes())
    (tmp_path / "notes.txt").write_text("not music")
    paths = jukebox.expand_paths([str(tmp_path)])
    assert [os.path.basename(p) for p in paths] == ["b.jbs", "tune.vgm"]
    titles = [jukebox.load_track(p)[0] for p in paths]
    assert titles == ["b", "G - Tune"]


class PipePort:
    """Enough of a pyserial port for run(): the NES side writes into a pipe."""

    def __init__(self):
        self.read_fd, self.nes_fd = os.pipe()
        self.written = bytearray()

    def fileno(self):
        return self.read_fd

    @property
    def in_waiting(self):
        import fcntl
        import struct
        import termios
        return struct.unpack("i", fcntl.ioctl(self.read_fd, termios.FIONREAD, b"\0\0\0\0"))[0]

    def read(self, count):
        return os.read(self.read_fd, count)

    def write(self, data):
        self.written += data


class PipeKeys:
    def __init__(self):
        self.fd, self.typist = os.pipe()

    def read(self):
        return os.read(self.fd, 16).decode()


def test_run_answers_the_port_and_obeys_keys():
    port, keys = PipePort(), PipeKeys()
    source = PlaylistSource([("A", A), ("B", B)], loops=1)
    streamer = jukebox.Streamer(Host(source))
    os.write(port.nes_fd, protocol.request_bytes(0x48, 0, 0) + protocol.request_bytes(0x4A, 0, 8))
    os.write(keys.typist, b"nq")

    class Quiet:
        def write(self, text):
            pass

        def flush(self):
            pass

    jukebox.run(port, source, streamer, keys, out=Quiet())
    assert port.written == protocol.burst_bytes(0, titled("A", A)[:8])
    # 'n' went to the next track at once; its first burst will flush the NES.
    assert source.index == 1 and streamer.host.flush_next
    assert streamer.host.handle(protocol.Request(0x4A, 1, 8)) == protocol.burst_bytes(
        1, titled("B", B)[:8], flush=True)


def test_stop_and_play_keys():
    port, keys = PipePort(), PipeKeys()
    source = PlaylistSource([("A", A), ("B", B)], loops=1)
    streamer = jukebox.Streamer(Host(source))
    os.write(port.nes_fd, protocol.request_bytes(0x4A, 0, 8))
    os.write(keys.typist, b"sq")

    class Quiet:
        def write(self, text):
            pass

        def flush(self):
            pass

    jukebox.run(port, source, streamer, keys, out=Quiet())
    host = streamer.host
    assert host.stopped
    assert host.handle(protocol.Request(0x4A, 1, 8)) == protocol.burst_bytes(1, b"", flush=True)
    os.write(keys.typist, b"rq")
    jukebox.run(port, source, streamer, keys, out=Quiet())
    assert not host.stopped
    assert host.handle(protocol.Request(0x4A, 2, 8)) == protocol.burst_bytes(
        2, titled("A", A)[:8], flush=True)
    assert host.handle(protocol.Request(0x4A, 3, 2)) == protocol.burst_bytes(
        3, titled("A", A)[8:10])


# -- sound ---------------------------------------------------------------------

def voice(count=1000):
    import pcm
    return pcm.Sound("Voices - Hello", 12, pcm.encode([index & 0x7F for index in range(count)]))


def test_sound_tracks_load_from_pcm_and_wav(tmp_path):
    import wave

    import pcm

    (tmp_path / "a.pcm").write_bytes(voice().to_bytes())
    untitled = voice()
    untitled.title = ""
    (tmp_path / "b named by its file.pcm").write_bytes(untitled.to_bytes())
    with wave.open(str(tmp_path / "c.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(bytes(1600))
    paths = jukebox.expand_paths([str(tmp_path)])
    assert [os.path.basename(p) for p in paths] == ["a.pcm", "b named by its file.pcm", "c.wav"]
    loaded = [jukebox.load_track(p) for p in paths]
    assert [title for title, _ in loaded] == ["Voices - Hello", "b named by its file", "c"]
    assert all(isinstance(track, pcm.Sound) for _, track in loaded)
    assert loaded[2][1].period == pcm.DEFAULT_PERIOD
    assert jukebox.expand_paths(["x.mp3"]) == ["x.mp3"]


class SoundPort:
    """A pyserial port as play_sound uses it, on a clock that only it and
    the sleeps move."""

    def __init__(self):
        self.baudrate = jukebox.BAUD
        self.events = []
        self.now = 10.0

    def write(self, data):
        self.events.append((self.baudrate, bytes(data)))

    def flush(self):
        self.events.append("flush")

    def reset_input_buffer(self):
        self.events.append("reset")

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.events.append(("sleep", round(seconds, 3)))
        self.now += seconds


def waiting_host(sound):
    source = PlaylistSource([("Voices - Hello", sound), ("B", B)], loops=1)
    host = Host(source)
    seq = 0
    while host.handle(protocol.Request(0x4A, seq, 24))[2]:
        seq += 1
    host.handle(protocol.Request(protocol.OP_SOUND, seq + 1, sound.rate))
    assert host.sound_due
    return host, source


def test_play_sound_sends_the_samples_at_their_rate_and_gives_the_link_back():
    import pcm

    sound = voice(3000)
    host, source = waiting_host(sound)
    port = SoundPort()
    keys = jukebox.play_sound(port, host, go_at=port.now - 0.1, clock=port.clock,
                              sleep=port.sleep)
    assert keys == ""
    baud = pcm.baud(12)
    # What was queued at the link's rate leaves first, and the samples
    # start 175 ms after the go burst.
    assert port.events[:2] == ["flush", ("sleep", 0.075)]
    sent = [event for event in port.events if isinstance(event[1], bytes)]
    assert {rate for rate, _ in sent} == {baud}
    assert b"".join(data for _, data in sent) == sound.samples + pcm.LAST_BYTE
    assert port.events[-2:] == ["flush", "reset"] and port.baudrate == jukebox.BAUD
    # Paced: the port was never more than 0.1 s ahead of the samples' time.
    slept = sum(event[1] for event in port.events[2:] if event[0] == "sleep")
    assert abs(slept - (3000 / (baud / 11) - jukebox.SOUND_AHEAD)) < 0.03
    assert not host.sound_due and source.sound is None and host.flush_next


def test_a_key_stops_a_sound_and_is_handed_back():
    import pcm

    sound = voice(3000)
    host, source = waiting_host(sound)
    port = SoundPort()
    pressed = iter(["", "", "n"])
    keys = jukebox.play_sound(port, host, go_at=port.now - 1, poll_keys=lambda: next(pressed),
                              clock=port.clock, sleep=port.sleep)
    assert keys == "n"
    sent = b"".join(event[1] for event in port.events if isinstance(event[1], bytes))
    assert sent == sound.samples[:3 * jukebox.SOUND_CHUNK] + pcm.LAST_BYTE
    assert port.baudrate == jukebox.BAUD and not host.sound_due
    assert not jukebox.press_key("n", host, source) and source.index == 1   # and then it is obeyed


def test_run_plays_a_sound_once_the_console_has_gone_quiet(monkeypatch):
    import pcm

    sound = voice(600)
    port, keys = PipePort(), PipeKeys()
    port.baudrate = jukebox.BAUD
    port.flush = port.reset_input_buffer = lambda: None
    rates = []
    write = port.write

    def record(data):
        rates.append(port.baudrate)
        write(data)
        if data == pcm.LAST_BYTE:
            os.write(keys.typist, b"q")     # typed as the sound ends

    port.write = record
    monkeypatch.setattr(jukebox, "SOUND_START_MS", 0)
    source = PlaylistSource([("Voices - Hello", sound), ("B", B)], loops=1)
    streamer = jukebox.Streamer(Host(source))
    place = jbs.intro("Voices - Hello", sound.frames) + jbs.sound_record(sound.rate)
    os.write(port.nes_fd, protocol.request_bytes(0x4A, 0, 64)
             + protocol.request_bytes(protocol.OP_SOUND, 1, sound.rate))

    class Out:
        text = ""

        def write(self, text):
            Out.text += text

        def flush(self):
            pass

    jukebox.run(port, source, streamer, keys, out=Out())
    go = protocol.burst_bytes(1, bytes([sound.rate]), go=True)
    assert bytes(port.written) == (protocol.burst_bytes(0, place) + go + sound.samples
                                   + pcm.LAST_BYTE)
    # Both answers went out in one write, at the link's rate; the rest is sound.
    assert rates[0] == jukebox.BAUD and set(rates[1:]) == {pcm.baud(12)}
    assert "playing sound: Voices - Hello" in Out.text
    assert port.baudrate == jukebox.BAUD and source.sound is None

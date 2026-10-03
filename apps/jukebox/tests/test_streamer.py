import os

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

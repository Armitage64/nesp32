import os

import jukebox
import protocol
from playlist import PlaylistSource
from protocol import Host
from test_playlist import A, B


def test_streamer_answers_requests_and_times_itself():
    streamer = jukebox.Streamer(Host(PlaylistSource([("A", A)])))
    out = streamer.on_bytes(b"\x00" + protocol.request_bytes(0x4A, 0, 24), 10.0, clock=lambda: 10.0005)
    expected = PlaylistSource([("A", A)]).take(24)  # A, then into its loop
    assert out == protocol.burst_bytes(0, expected)
    assert abs(streamer.reply_ms[0] - 0.5) < 1e-6
    assert streamer.data_requests == 1
    assert "req 1" in streamer.status() and "noise 1" in streamer.status()


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
    assert port.written == protocol.burst_bytes(0, A.stream[:8])
    assert source.requested == 1  # 'n' queued the next track

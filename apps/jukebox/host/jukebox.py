#!/usr/bin/env python3
"""NES Jukebox desktop streamer: plays a playlist to the link ROM over a
serial cable (the FTDI 5 V cable from nes-radar).

    host/jukebox.py --port /dev/cu.usbserial-XXXX music/
    host/jukebox.py --port /dev/cu.usbserial-XXXX --loops 1 a.vgz b.vgz
    host/jukebox.py --list-ports

Keys while playing: n next track, p previous, r restart, q quit.

The NES paces everything. It sends a request right after each vblank and
waits for the burst; this program's only job is to answer quickly. For full
throughput the reply should start within 6 ms of the request (see
docs/PROTOCOL.md), and the status line reports how the link is doing.
Resends are the number to watch: each is a burst the NES missed.

A track change reaches the speakers after what is already buffered on the
NES has played, a few seconds.
"""

import argparse
import os
import select
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import jbs  # noqa: E402
import vgm  # noqa: E402
import vgm2jbs  # noqa: E402
from playlist import PlaylistSource  # noqa: E402
from protocol import OP_DATA, Host, RequestDecoder  # noqa: E402

BAUD = 38400
MUSIC_SUFFIXES = (".vgm", ".vgz", ".jbs")
STATUS_INTERVAL = 1.0


def load_track(path):
    """Return (title, JbsFile) for a .vgm, .vgz or .jbs file."""
    if path.lower().endswith(".jbs"):
        with open(path, "rb") as handle:
            song = jbs.JbsFile.from_bytes(handle.read())
    else:
        song, _ = vgm2jbs.convert(vgm.load(path))
    title = song.title or os.path.splitext(os.path.basename(path))[0]
    return title, song


def expand_paths(paths):
    found = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith(MUSIC_SUFFIXES):
                    found.append(os.path.join(path, name))
        else:
            found.append(path)
    return found


class Streamer:
    """Requests in, bursts out, with timing statistics. No I/O of its own."""

    def __init__(self, host):
        self.host = host
        self.decoder = RequestDecoder()
        self.requests = 0
        self.data_requests = 0
        self.reply_ms = []  # this program's own time from bytes in to bytes out

    def on_bytes(self, data, received_at, clock=time.monotonic):
        out = bytearray()
        for request in self.decoder.feed(data):
            self.requests += 1
            if request.op == OP_DATA:
                self.data_requests += 1
            out += self.host.handle(request)
        if out:
            self.reply_ms.append((clock() - received_at) * 1000.0)
        return bytes(out)

    def status(self):
        stats = self.host.stats
        replies = self.reply_ms or [0.0]
        resend_pct = 100.0 * stats["resends"] / max(1, self.data_requests)
        self.reply_ms = []
        return ("req %d  bursts %d  resends %d (%.1f%%)  noise %d  host reply max %.1f ms"
                % (self.requests, stats["bursts"], stats["resends"], resend_pct,
                   self.decoder.discarded, max(replies)))


def open_port(path):
    import serial  # pyserial

    port = serial.Serial(
        path,
        baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO,  # transmit; the receiver accepts 1
        timeout=0,
        write_timeout=1.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    port.break_condition = False
    port.reset_input_buffer()
    port.reset_output_buffer()
    time.sleep(0.02)
    return port


class Keys:
    """Single keypresses from the terminal, without waiting for Enter."""

    def __init__(self, enabled):
        self.fd = None
        if enabled and sys.stdin.isatty():
            import termios
            import tty

            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)

    def read(self):
        return os.read(self.fd, 16).decode(errors="ignore") if self.fd is not None else ""

    def close(self):
        if self.fd is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


def run(port, source, streamer, keys, out=sys.stdout):
    watched = [port.fileno()] + ([keys.fd] if keys.fd is not None else [])
    next_status = time.monotonic() + STATUS_INTERVAL
    while True:
        ready, _, _ = select.select(watched, [], [], 0.05)
        if port.fileno() in ready:
            received_at = time.monotonic()
            data = port.read(port.in_waiting or 1)
            reply = streamer.on_bytes(data, received_at)
            if reply:
                port.write(reply)
        if keys.fd is not None and keys.fd in ready:
            for key in keys.read().lower():
                if key == "q":
                    return
                if key == "n":
                    source.skip(1)
                elif key == "p":
                    source.skip(-1)
                elif key == "r":
                    source.skip(0)
        now = time.monotonic()
        if now >= next_status:
            next_status = now + STATUS_INTERVAL
            out.write("\r\033[K" + streamer.status())
            out.flush()


def list_ports():
    from serial.tools import list_ports as tools

    for info in tools.comports():
        print("%-32s %s" % (info.device, info.description))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("music", nargs="*", help="files or directories (.vgm, .vgz, .jbs)")
    parser.add_argument("--port", help="serial device, e.g. /dev/cu.usbserial-XXXX")
    parser.add_argument("--loops", type=int, default=2, help="times through a looping track")
    parser.add_argument("--repeat", action="store_true", help="start over after the last track")
    parser.add_argument("--no-keys", action="store_true", help="don't read the keyboard")
    parser.add_argument("--list-ports", action="store_true", help="show serial ports and exit")
    args = parser.parse_args(argv)

    if args.list_ports:
        list_ports()
        return 0
    if not args.port or not args.music:
        parser.error("need --port and at least one track")

    tracks = []
    for path in expand_paths(args.music):
        try:
            tracks.append(load_track(path))
        except (OSError, ValueError) as error:
            print("skipping %s: %s" % (path, error), file=sys.stderr)
    if not tracks:
        print("no playable tracks", file=sys.stderr)
        return 1

    def announce(index, title):
        sys.stdout.write("\r\033[Ksending %d/%d: %s\n" % (index + 1, len(tracks), title))
        sys.stdout.flush()

    try:
        port = open_port(args.port)
    except OSError as error:  # serial.SerialException is an OSError
        print("can't open %s: %s" % (args.port, error), file=sys.stderr)
        return 1
    source = PlaylistSource(tracks, loops=args.loops, repeat=args.repeat, on_track=announce)
    streamer = Streamer(Host(source))
    keys = Keys(enabled=not args.no_keys)
    print("streaming at %d baud on %s; keys: n next, p previous, r restart, q quit"
          % (BAUD, args.port))
    try:
        run(port, source, streamer, keys)
    except KeyboardInterrupt:
        pass
    finally:
        keys.close()
        port.close()
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

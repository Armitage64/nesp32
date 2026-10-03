"""Wire the Stick's hardware to the Player (UIFlow 2.0 firmware only).

The loop does one thing as often as it can: Player.poll(). The buttons, the
screen and garbage collection run right after a burst goes out, when the NES
cannot ask again before its next vblank. A collection is forced there every
GC_EVERY bursts so that one never starts by itself in the middle of a reply.

Tracks are the .jbs files in /flash/tracks, in name order, as
tools/deploy.sh leaves them. /flash/config.json is optional:

    board    "s3" or "plus2", if the board is not recognised
    tx, rx   link pins, for a hat wired differently from board.py's table
    invert   false for a non-inverting level shifter (default true)
    loops    times through a looping track before the next one (default 2)
    repeat   start over after the last track (default true)
"""

import gc
import json
import sys
import time

from nesjuke import VERSION, board, tracks
from nesjuke.player import Player
from nesjuke.protocol import Host
from nesjuke.ui import StatusScreen

FS_ROOT = "/flash"
CONFIG_PATH = FS_ROOT + "/config.json"
TRACKS_PATH = FS_ROOT + "/tracks"

GC_EVERY = 64               # bursts, about one second of playing
IDLE_CHORES_MS = 20         # buttons and screen while no bursts are going out
STATUS_MS = 1000
LOG_MS = 5000
BATTERY_MS = 10000
PLAYING_WITHIN_MS = 500     # of the last data request
SLEEP_AFTER_MS = 2000       # with no requests, stop spinning and nap
NAP_MS = 2


# The counters the NES reports (protocol.NES_COUNTERS) that go on the screen.
NES_ROW = ("aborts", "timeouts", "rejects", "crc_errors", "underruns")


class PowerOff(Exception):
    pass


def load_config():
    try:
        with open(CONFIG_PATH) as handle:
            config = json.load(handle)
    except OSError:
        config = {}  # config.json is optional
    if not isinstance(config.get("invert", True), bool):
        raise ValueError("invert must be true (NPN shifter) or false")
    return config


class Device:
    def __init__(self):
        board.init()
        self.screen = StatusScreen(VERSION)
        self.buttons = board.Buttons()
        self.playlist = None
        self.player = None
        self.track_count = 0
        self.gc_us_max = 0
        now = time.ticks_ms()
        self._chores_at = now
        self._status_at = now
        self._log_at = now
        self._battery_at = time.ticks_add(now, -BATTERY_MS)
        self._request_at = time.ticks_add(now, -SLEEP_AFTER_MS)

    def on_track(self, index, title):
        # The track being sent. The NES plays it once its buffer catches up.
        self.screen.set(track="%d/%d" % (index + 1, self.track_count), title=title)

    def chores(self, now):
        """Everything except the link. Called between requests; keep it short."""
        self._chores_at = now
        a_pressed, b_clicked, b_held = self.buttons.poll()
        if b_held:
            raise PowerOff()
        if a_pressed:
            self.playlist.skip(1)
        if b_clicked:
            self.playlist.skip(-1)
        if time.ticks_diff(now, self._battery_at) >= BATTERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % board.battery_percent())
        if time.ticks_diff(now, self._status_at) >= STATUS_MS:
            self._status_at = now
            self.show_status(now)
        self.screen.refresh()

    def show_status(self, now):
        player = self.player
        stats = player.host.stats
        playing = time.ticks_diff(now, self._request_at) < PLAYING_WITHIN_MS
        resend_pct = 100 * stats["resends"] // max(1, player.data_requests)
        reply_us = player.take_reply_us_max()
        # The NES's own counters (low bytes) say why it asked again: bursts
        # cut off by its NMI, waits that timed out, rejects, CRC errors and
        # underruns. They start at zero when the console is switched on.
        nes = player.host.nes
        counters = " ".join("%s %d" % (name, nes[name]) for name in NES_ROW if name in nes)
        self.screen.set(
            # The row is too narrow for names: values only, in NES_ROW's order.
            nes="/".join(str(nes.get(name, "-")) for name in NES_ROW) if nes else "",
            state="PLAYING" if playing else "WAITING FOR NES",
            link="%d sent, %d%% resent" % (stats["bursts"], resend_pct),
            reply="%d.%d ms max, noise %d" % (reply_us // 1000, reply_us % 1000 // 100,
                                           player.decoder.discarded),
        )
        if time.ticks_diff(now, self._log_at) >= LOG_MS:
            self._log_at = now
            print("req %d bursts %d resends %d hello %d noise %d stale %d gc max %d us; NES %s"
                  % (player.requests, stats["bursts"], stats["resends"], stats["hello"],
                     player.decoder.discarded, player.stale, self.gc_us_max,
                     counters or "has not reported"))
            self.gc_us_max = 0

    def collect(self):
        started = time.ticks_us()
        gc.collect()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.gc_us_max:
            self.gc_us_max = elapsed

    def serve(self):
        player = self.player
        since_gc = 0
        while True:
            if player.poll():
                now = time.ticks_ms()
                self._request_at = now
                self.chores(now)
                since_gc += 1
                if since_gc >= GC_EVERY:
                    since_gc = 0
                    self.collect()
                continue
            now = time.ticks_ms()
            if time.ticks_diff(now, self._chores_at) >= IDLE_CHORES_MS:
                self.chores(now)
            if time.ticks_diff(now, self._request_at) >= SLEEP_AFTER_MS:
                time.sleep_ms(NAP_MS)

    def start(self):
        config = load_config()
        label, tx, rx = board.detect(config.get("board"))
        tx = config.get("tx", tx)
        rx = config.get("rx", rx)
        self.screen.set(board=label, state="STARTING")
        self.screen.refresh(everything=True)
        try:
            paths = tracks.list_tracks(TRACKS_PATH)
        except OSError:
            paths = []
        if not paths:
            raise ValueError("no tracks; run tools/deploy.sh")
        print("NES Jukebox %s on %s: TX G%d, RX G%d, %d tracks"
              % (VERSION, label, tx, rx, len(paths)))
        self.track_count = len(paths)
        # Open the UART before loading anything, so TX rests at mark.
        uart = board.open_link_uart(tx, rx, invert=config.get("invert", True))
        self.playlist = tracks.Playlist(
            len(paths),
            lambda index: tracks.load_jbs(paths[index]),
            loops=config.get("loops", 2),
            repeat=config.get("repeat", True),
            on_track=self.on_track,
        )
        self.player = Player(uart, Host(self.playlist))
        self.collect()

    def run(self):
        try:
            self.start()
            self.serve()
        except PowerOff:
            # The UART stays open so TX rests at mark (D0 high at the NES).
            self.screen.off()
            board.power_off()
        except Exception as error:
            sys.print_exception(error)
            self.screen.set(state="ERROR", error="%s: %s" % (type(error).__name__, error))
            self.screen.refresh(everything=True)


def main():
    Device().run()

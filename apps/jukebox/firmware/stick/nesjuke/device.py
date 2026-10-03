"""Wire the Stick's hardware to the Player (UIFlow 2.0 firmware only).

The loop does one thing as often as it can: Player.poll(). The buttons, the
screen and garbage collection run right after a burst goes out, when the NES
cannot ask again before its next vblank. A collection is forced there every
GC_EVERY bursts so that one never starts by itself in the middle of a reply.

Between bursts the same chores run only at the point in the NES's frame
where a request has just been due (Player.quiet). On hardware, chores run at
any time delayed about one reply every 3 s by a screen row's worth, and the
NES cut those bursts off.

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
from nesjuke.protocol import BUTTON_NEXT, BUTTON_PLAY, BUTTON_PREVIOUS, Host
from nesjuke.ui import StatusScreen

FS_ROOT = "/flash"
CONFIG_PATH = FS_ROOT + "/config.json"
TRACKS_PATH = FS_ROOT + "/tracks"

GC_EVERY = 64               # bursts, about one second of playing
IDLE_CHORES_MS = 20         # buttons and screen while no bursts are going out
STATUS_MS = 1000
CLOCK_MS = 250
LOG_MS = 5000
BATTERY_MS = 10000
PLAYING_WITHIN_MS = 500     # of the last data request
NES_PREFILL = 768           # PREFILL in nes/jukebox.s: bytes before it plays
SLEEP_AFTER_MS = 2000       # with no requests, stop spinning and nap
NAP_MS = 2


# The counters the NES reports (protocol.NES_COUNTERS) that go in the log.
NES_LOG = ("aborts", "timeouts", "rejects", "crc_errors", "underruns")


def clock_text(frames):
    seconds = frames // 60
    return "%d:%02d" % (seconds // 60, seconds % 60)


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
        self.write_us_max = 0
        self.chore_us_max = 0
        self.log_us = 0         # time the last chore spent printing the log line
        self.last_log_us = 0
        now = time.ticks_ms()
        self._chores_at = now
        self._status_at = now
        self._clock_at = now
        self._log_at = now
        self._battery_at = time.ticks_add(now, -BATTERY_MS)
        self._request_at = time.ticks_add(now, -SLEEP_AFTER_MS)
        self._fresh_starts = 0
        self._playing_since = None  # when the NES began to play what it holds
        self._paused_at = None      # when it was paused, while it is

    def on_track(self, index, title):
        # The track being sent, or the one button A will start.
        self.screen.set(track="%d/%d" % (index + 1, self.track_count), title=title)

    def chores(self, now):
        """Everything except the link. Called between requests; keep it short."""
        self._chores_at = now
        started = time.ticks_us()
        try:
            self._chores(now)
        finally:
            # The USB log line is timed by itself: it is the longest thing
            # here by far, and would hide what the other chores take.
            elapsed = time.ticks_diff(time.ticks_us(), started) - self.log_us
            self.log_us = 0
            if elapsed > self.chore_us_max:
                self.chore_us_max = elapsed

    def _chores(self, now):
        a_pressed, b_clicked, b_held, power_clicked = self.buttons.poll()
        if b_held:
            raise PowerOff()
        # The buttons do what the NES's controller does (Host.press). A
        # pauses and resumes, or from stopped plays the current track from
        # its beginning. B is the previous track and the power button the
        # next, played at once: the next burst is a flush burst, so the NES
        # drops the seconds of music it already holds.
        host = self.player.host
        if a_pressed:
            host.press(BUTTON_PLAY)
        if b_clicked:
            host.press(BUTTON_PREVIOUS)
        if power_clicked:
            host.press(BUTTON_NEXT)
        if time.ticks_diff(now, self._battery_at) >= BATTERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % board.battery_percent())
        if time.ticks_diff(now, self._clock_at) >= CLOCK_MS:
            self._clock_at = now
            self.screen.set(time="%s / %s" % (clock_text(self.position(now)),
                                              clock_text(self.playlist.track_frames)))
        if time.ticks_diff(now, self._status_at) >= STATUS_MS:
            self._status_at = now
            self.show_status(now)
        self.screen.refresh()

    def position(self, now):
        """Frames into the track that the NES is playing now, worked out
        from the clock: the NES does not report it.

        The NES plays one frame per vblank from the moment its buffer
        reaches the prefill, so it is that many frames into what was sent
        since its buffer was last emptied. The playlist knows where in that
        the track it is sending began. That track is a few seconds ahead of
        the one being heard when one follows another by itself, so the
        clock rests at zero for those seconds."""
        host = self.player.host
        if host.fresh_starts != self._fresh_starts:
            self._fresh_starts = host.fresh_starts
            self._playing_since = None
        if host.stopped:
            self._playing_since = None
            return 0
        if self._playing_since is None:
            self._paused_at = None
            if host.paused or (host.sent < NES_PREFILL and not host.drained):
                return 0
            self._playing_since = now
        # A pause stops the NES's frames. The time spent paused is taken out
        # by moving the start later when the music goes on.
        if host.paused:
            if self._paused_at is None:
                self._paused_at = now
            now = self._paused_at
        elif self._paused_at is not None:
            self._playing_since = time.ticks_add(
                self._playing_since, time.ticks_diff(now, self._paused_at))
            self._paused_at = None
        played = time.ticks_diff(now, self._playing_since) * 601 // 10000  # 60.1 a second
        playlist = self.playlist
        return min(max(played - playlist.track_start, 0), playlist.track_frames)

    def show_status(self, now):
        player = self.player
        stats = player.host.stats
        playing = time.ticks_diff(now, self._request_at) < PLAYING_WITHIN_MS
        resend_pct = 100 * stats["resends"] // max(1, player.data_requests)
        reply_us, average_us, write_us = player.take_reply_us()
        if write_us > self.write_us_max:
            self.write_us_max = write_us
        # The NES's own counters (low bytes) say why it asked again: bursts
        # cut off by its NMI, waits that timed out, rejects, CRC errors and
        # underruns, as totals since this Stick first heard from it. They go
        # in the USB log line.
        nes = player.host.nes
        counters = " ".join("%s %d" % (name, nes[name]) for name in NES_LOG if name in nes)
        self.screen.set(
            state=("WAITING FOR NES" if not playing
                   else "STOPPED" if player.host.stopped
                   else "PAUSED" if player.host.paused else "PLAYING"),
            link="%d sent, %d%% resent" % (stats["bursts"], resend_pct),
            reply="%d.%d avg %d.%d max, noise %d" % (
                average_us // 1000, average_us % 1000 // 100,
                reply_us // 1000, reply_us % 1000 // 100, player.decoder.discarded),
        )
        if time.ticks_diff(now, self._log_at) >= LOG_MS:
            self._log_at = now
            started = time.ticks_us()
            print("req %d bursts %d resends %d hello %d noise %d stale %d "
                  "write max %d us chore max %d us log %d us gc max %d us; NES %s"
                  % (player.requests, stats["bursts"], stats["resends"], stats["hello"],
                     player.decoder.discarded, player.stale, self.write_us_max,
                     self.chore_us_max, self.last_log_us, self.gc_us_max,
                     counters or "has not reported"))
            self.gc_us_max = self.write_us_max = self.chore_us_max = 0
            self.log_us = self.last_log_us = time.ticks_diff(time.ticks_us(), started)

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
            if (time.ticks_diff(now, self._chores_at) >= IDLE_CHORES_MS
                    and player.quiet(time.ticks_us())):
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
        # Nothing plays until button A is pressed.
        self.player = Player(uart, Host(self.playlist, stopped=True))
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

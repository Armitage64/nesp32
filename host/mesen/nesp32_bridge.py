#!/usr/bin/env python3
"""NESP32 bridge for Mesen's Lua script (nesp32.lua).

Mesen runs the console. nesp32.lua watches controller port 2: every change
of OUT0 ($4016 bit 0) it sends here with its CPU cycle, and what the console
reads from D0 ($4017 bit 0) it works out from the bytes this bridge says are
on the line, and when.

This side is the NESP32 itself: the board's own firmware (its link and
services, built for a computer as nesp32's build/libnesp_host) behind
nesp32's own line model (tests/wire.py), with real Internet fetches, real
time, a Wi-Fi network that is always there, a Bluetooth keyboard that is
the computer's own (what Mesen's window is typed on, in typing mode), and
the files a ROM keeps (Family BASIC's SAVE), in a directory if one is given.

    nesp32_bridge.py [--host 0.0.0.0] [--port 7878] [--nesp32 /path/to/nesp32]
                     [--data DIR] [--bt-helper HOST:PORT]

Protocol, one line each way, ASCII:
  Mesen -> bridge   S <cycle> <n> <c1> <l1> ... <cn> <ln>
                    (the console's time, and OUT0's changes since the last S)
                    B <button>     the NESP32's own button pressed (1 = A, 2 = B)
                    K <modifiers> [<usage>...]
                                   the keys down on the computer's keyboard,
                                   as a Bluetooth keyboard's report has them:
                                   HID's modifier bits, and up to 6 usages
                                   (the keyboard page). Sent when they change.
  bridge -> Mesen   R <busy> <runs> [<start> <period> <hexbytes>]... K <keyboard> <on>
                    (bytes newly on the line: each run back to back from
                    <start>, <period> cycles a bit, 11 bits a byte. busy 1:
                    a byte from the console is partway in, so sync again
                    on the next read of $4017. Then how the keyboard stands
                    (enum KEYBOARD), and 1 if a ROM has KBD in use.)
"""

import argparse
import os
import queue
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

KEYBOARD_NAME = b"Mesen PC keyboard"
KEYBOARD_SIGNAL = -40           # dBm, as a scan finds it
SCAN_MS = 1000                  # a scan takes this long, in the console's time
PAIR_MS = 500                   # and a pairing this
HELD = 64                       # keys typed and not yet taken (the firmware's HELD)
NAME_MAX = 24                   # bytes of a keyboard's name (proto's KBD_NAME_MAX)
FOUND_MAX = 8                   # keyboards a scan keeps (KBD_FOUND_MAX)
HELPER_SCAN = 6                 # seconds a real scan listens for
HELPER_WAIT_MS = 30000          # what the helper gets to scan, and 75 s to pair
HELPER_PAIR_MS = 75000
FETCH_TIMEOUT = 10              # seconds, as the firmware's TIMEOUT_MS


def log(text):
    print(time.strftime("%H:%M:%S ") + text, flush=True)


def redact(url):
    """An address as the log shows it: no keys, tokens or passwords."""
    return re.sub(r"(?i)((?:api_?)?key|token|password|username|secret)=[^&]*", r"\1=...",
                  str(url))


def default_nesp32():
    """nesp32's checkout: the one this file is in (host/mesen/), or one
    beside this repository."""
    inside = os.path.join(HERE, "..", "..")
    if os.path.isfile(os.path.join(inside, "host", "nesp.py")):
        return os.path.abspath(inside)
    return os.path.abspath(os.path.join(HERE, "..", "nesp32"))


def load_nesp32(root=None):
    """Import nesp32's protocol, host library and line model, from a
    checkout with `make host` done (or, with no root, from wherever the
    path already finds them)."""
    if root is not None:
        for sub in ("host", "build", "tests"):
            sys.path.insert(0, os.path.join(root, sub))
    global nesp, proto, wire
    import nesp_proto as proto
    import nesp
    import wire
    # The board's UART holds 2048 bytes; the tests' model holds 256, which
    # is less than a frame of a radio station's sound.
    wire.TX_BUFFER = 2048


# --- the keyboard ---------------------------------------------------------------

# HID's usages (the USB HID usage tables, the keyboard page), as
# firmware/main/keyboard.c has them.
USAGE_ROLLOVER = 0x01
USAGE_A = 0x04
USAGE_ENTER = 0x28
USAGE_ESCAPE = 0x29
USAGE_SLASH = 0x38
USAGE_CAPS_LOCK = 0x39
USAGE_F1 = 0x3A
USAGE_F8 = 0x41
USAGE_F12 = 0x45
USAGE_INSERT = 0x49
USAGE_HOME = 0x4A
USAGE_PAGE_UP = 0x4B
USAGE_DELETE = 0x4C
USAGE_PAGE_DOWN = 0x4E
USAGE_RIGHT = 0x4F
USAGE_UP = 0x52
SHIFT = 0x22                    # the left and right Shift in the modifiers' byte
CHORD = 0xDD                    # Ctrl, Alt and GUI: a key with one does not repeat
CTRL = 0x11
ALT = 0x44
GUI = 0x88                      # the Windows or Command key: a key with it is none
REPEAT_DELAY_MS = 500
REPEAT_EVERY_MS = 40

# Each usage from USAGE_A to USAGE_SLASH, and with Shift (a US layout).
PLAIN = b"abcdefghijklmnopqrstuvwxyz1234567890\n\x1b\b\t -=[]\\#;'`,./"
SHIFTED = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()\n\x1b\b\t _+{}|~:\"~<>?"
assert len(PLAIN) == len(SHIFTED) == USAGE_SLASH - USAGE_A + 1


class Keyboard:
    """What the nesp32's firmware makes of a keyboard's reports
    (firmware/main/keyboard.c): characters and KBD's keys, with Shift and
    Caps Lock, a key with Ctrl or Alt after WITH_CTRL or WITH_ALT, and a key
    held down typed again, after REPEAT_DELAY_MS and every REPEAT_EVERY_MS
    from then on, only once everything typed before has been taken.

    keep(key) is called with each character or key typed. The clock is the
    caller's, in milliseconds."""

    def __init__(self, keep):
        self.keep = keep
        self.down = []
        self.caps = False
        self.repeating = 0
        self.repeat_modifiers = 0
        self.next_repeat = None

    @staticmethod
    def typed(usage, modifiers, caps=False):
        """What a key types with these modifiers, Ctrl and Alt aside: a
        character or a NESP_KEY_*, or 0 for nothing."""
        if USAGE_RIGHT <= usage <= USAGE_UP:
            return (proto.NESP_KEY_RIGHT, proto.NESP_KEY_LEFT, proto.NESP_KEY_DOWN,
                    proto.NESP_KEY_UP)[usage - USAGE_RIGHT]
        if usage == USAGE_PAGE_UP:
            return proto.NESP_KEY_PAGE_UP
        if usage == USAGE_PAGE_DOWN:
            return proto.NESP_KEY_PAGE_DOWN
        if USAGE_F1 <= usage <= USAGE_F8:
            return (proto.NESP_KEY_F1, proto.NESP_KEY_F2, proto.NESP_KEY_F3, proto.NESP_KEY_F4,
                    proto.NESP_KEY_F5, proto.NESP_KEY_F6, proto.NESP_KEY_F7,
                    proto.NESP_KEY_F8)[usage - USAGE_F1]
        if usage == USAGE_F12:
            return proto.NESP_KEY_F12
        if usage == USAGE_HOME:
            return proto.NESP_KEY_SHIFT_HOME if modifiers & SHIFT else proto.NESP_KEY_HOME
        if usage == USAGE_INSERT:
            return proto.NESP_KEY_INSERT
        if usage == USAGE_DELETE:
            return proto.NESP_KEY_DELETE
        if usage < USAGE_A or usage > USAGE_SLASH:
            return 0
        plain = PLAIN[usage - USAGE_A]
        shift = bool(modifiers & SHIFT)
        if caps and ord("a") <= plain <= ord("z"):
            shift = not shift
        return SHIFTED[usage - USAGE_A] if shift else plain

    def pressed(self, usage, modifiers):
        if usage == USAGE_CAPS_LOCK:
            self.caps = not self.caps
            return
        if modifiers & GUI:
            return
        if (modifiers & CHORD) == (modifiers & CTRL) and modifiers & CTRL \
                and usage in (USAGE_ENTER, USAGE_ESCAPE):
            self.keep(proto.NESP_KEY_START if usage == USAGE_ENTER else proto.NESP_KEY_SELECT)
            return
        key = self.typed(usage, modifiers, self.caps)
        if key == 0:
            return
        if modifiers & CTRL:
            self.keep(proto.NESP_KEY_WITH_CTRL)
        if modifiers & ALT:
            self.keep(proto.NESP_KEY_WITH_ALT)
        self.keep(key)

    @staticmethod
    def repeats(usage, modifiers):
        """Whether a key held down is typed again."""
        if modifiers & CHORD:
            return False
        if USAGE_RIGHT <= usage <= USAGE_UP or usage in (USAGE_PAGE_UP, USAGE_PAGE_DOWN,
                                                         USAGE_DELETE, USAGE_INSERT):
            return True
        if usage < USAGE_A or usage > USAGE_SLASH:
            return False
        return PLAIN[usage - USAGE_A] not in b"\n\x1b"

    def repeat_from(self, usage, modifiers, now):
        self.repeating = usage
        self.repeat_modifiers = modifiers
        self.next_repeat = now + REPEAT_DELAY_MS if usage else None

    def report(self, modifiers, keys, now):
        """A report: the modifiers, and the keys down (up to 6). A key is
        typed when it was not down in the report before."""
        keys = [key for key in keys if key][:6]
        if USAGE_ROLLOVER in keys:
            return
        newest = 0
        for key in keys:
            if key not in self.down:
                self.pressed(key, modifiers)
                newest = key
        self.down = keys
        if newest:
            self.repeat_from(newest if self.repeats(newest, modifiers) else 0, modifiers, now)
        elif self.repeating and self.repeating not in keys:
            self.repeat_from(0, 0, now)                 # let go of
        elif self.repeating and not self.repeats(self.repeating, modifiers):
            self.repeat_from(0, 0, now)                 # Ctrl or the like went down with it
        else:
            self.repeat_modifiers = modifiers           # Shift, say, let go of or pressed

    def tick(self, now, waiting):
        """The repeats due by now. waiting() says whether something typed
        before has yet to be taken."""
        if not self.repeating:
            return
        if now - self.next_repeat > 1000:
            self.next_repeat = now                      # the clock jumped
        while self.repeating and now >= self.next_repeat:
            if not waiting():
                self.pressed(self.repeating, self.repeat_modifiers)
            self.next_repeat += REPEAT_EVERY_MS


class Memory:
    """What a nesp32 keeps over power-off, for every board this bridge
    makes: which keyboard is paired, and a ROM's files. With a directory,
    they are kept there; without, for as long as the bridge runs."""

    def __init__(self, directory=None):
        self.directory = directory
        self.paired = False
        self.address = None             # of a real keyboard (--bt-helper), and its name
        self.name = None
        self.files = {}                 # name: bytes, in the order first written
        if directory is not None:
            os.makedirs(os.path.join(directory, "files"), exist_ok=True)
            self.paired = os.path.exists(self.paired_path())
            if self.paired:
                with open(self.paired_path(), errors="replace") as f:
                    lines = f.read().splitlines()
                if len(lines) >= 2 and lines[0]:
                    self.address, self.name = lines[0], lines[1] or None
            folder = os.path.join(directory, "files")
            names = sorted(os.listdir(folder),
                           key=lambda name: os.path.getmtime(os.path.join(folder, name)))
            for name in names:
                if safe_name(name):
                    with open(os.path.join(folder, name), "rb") as f:
                        self.files[name] = f.read()

    def paired_path(self):
        return os.path.join(self.directory, "keyboard-paired")

    def set_paired(self, paired, address=None, name=None):
        """address and name (of a real keyboard) are kept in the file's two lines."""
        self.paired = paired
        self.address = address if paired else None
        self.name = name if paired else None
        if self.directory is not None:
            if paired:
                with open(self.paired_path(), "w") as f:
                    if address:
                        f.write("%s\n%s\n" % (address, name or ""))
            elif os.path.exists(self.paired_path()):
                os.remove(self.paired_path())

    def keep_file(self, name, data):
        if self.files.get(name) == data or not safe_name(name):
            return
        self.files[name] = data
        if self.directory is not None:
            with open(os.path.join(self.directory, "files", name), "wb") as f:
                f.write(data)
        log("file kept: %s, %d bytes" % (name, len(data)))


def safe_name(name):
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name


class HelperLink:
    """The connection to nesp32_bt_helper.py, on a machine with a Bluetooth
    radio. Lines it sends are queued for whoever polls; one is made when a
    request is sent and there is none, so the helper may start after the
    bridge, or restart."""

    def __init__(self, address):
        host, _, port = address.rpartition(":")
        self.address = (host, int(port))
        self.lines = queue.Queue()
        self.conn = None
        self.lock = threading.Lock()

    def send(self, line):
        """True if the helper took the line."""
        with self.lock:
            if self.conn is None:
                try:
                    conn = socket.create_connection(self.address, timeout=5)
                except OSError as e:
                    log("Bluetooth helper %s:%d: %s" % (self.address + (e,)))
                    return False
                conn.settimeout(None)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.conn = conn
                threading.Thread(target=self.read, args=(conn,), daemon=True).start()
                log("Bluetooth helper connected")
            try:
                self.conn.sendall((line + "\n").encode())
                return True
            except OSError:
                self.conn = None
                return False

    def read(self, conn):
        try:
            for raw in conn.makefile("r", errors="replace"):
                self.lines.put(raw.strip())
        except OSError:
            pass
        with self.lock:
            if self.conn is conn:
                self.conn = None
        conn.close()
        log("Bluetooth helper gone")

    def poll(self):
        """The lines that have come since the last poll."""
        got = []
        while True:
            try:
                got.append(self.lines.get_nowait())
            except queue.Empty:
                return got


def short(name):
    """A device's name as the firmware holds one: up to NAME_MAX bytes, whole characters."""
    data = name.encode("utf-8")[:NAME_MAX]
    return data.decode("utf-8", "ignore").encode("utf-8")


class BluetoothKeyboard:
    """The nesp32's Bluetooth, with one keyboard about: the computer's own.
    A scan finds it, a pairing pairs it, and once paired it is connected
    whenever a ROM has KBD in use. What is typed on it (report) is typed on
    the nesp32 only then, as on a StickS3."""

    def __init__(self, stick, memory, helper=None):
        self.stick = stick
        self.memory = memory
        self.helper = helper
        self.heard = []                 # (address, name, rssi) of a real scan
        self.asked_at = None            # the helper's scan or pairing under way
        self.pairing = None
        self.keyboard = Keyboard(self.keep)
        self.scans = stick.kbd_scans
        self.pairs = stick.kbd_pairs
        self.forgets = stick.kbd_forgets
        self.done_at = None             # when the scan or the pairing under way is over
        if helper is not None:
            if memory.paired and memory.address:
                stick.kbd_paired(short(memory.name or memory.address))
                stick.kbd_state = proto.NESP_KEYBOARD_CONNECTED
        elif memory.paired:
            stick.kbd_paired(KEYBOARD_NAME)
            stick.kbd_state = proto.NESP_KEYBOARD_CONNECTED

    @property
    def state(self):
        return self.stick.kbd_state

    def keep(self, key):
        stick = self.stick
        if stick.kbd_on and stick.kbd_state == proto.NESP_KEYBOARD_CONNECTED \
                and stick.kbd_unread < HELD:
            stick.kbd_type(bytes((key,)))

    def report(self, modifiers, keys, now):
        """Keys down on the computer's keyboard. With a helper, they are not
        the nesp32's: its real keyboard's come from the helper."""
        if self.helper is None:
            self.keyboard.report(modifiers, keys, now)

    def update_helper(self, now):
        """update, with a real radio: what the helper says is what happens."""
        stick, helper = self.stick, self.helper
        for line in helper.poll():
            words = line.split(None, 3)
            if not words:
                continue
            if words[0] == "K" and len(words) > 1:
                words = line.split()
                self.keyboard.report(int(words[1]), [int(w) for w in words[2:]], now)
            elif words[0] == "D" and len(words) == 4 and self.asked_at is not None \
                    and stick.kbd_state == proto.NESP_KEYBOARD_SCANNING:
                self.heard.append((words[1], short(words[3]), max(-128, min(127, int(words[2])))))
            elif words[0] == "SCANDONE" and stick.kbd_state == proto.NESP_KEYBOARD_SCANNING:
                self.finish_scan()
            elif words[0] == "PASSKEY":
                log("keyboard passkey %s (confirmed for it)" % words[1])
            elif words[0] == "PAIRED" and stick.kbd_state == proto.NESP_KEYBOARD_PAIRING:
                name = short(line.split(None, 2)[2] if len(words) > 2 else self.pairing)
                stick.kbd_paired(name)
                stick.kbd_state = proto.NESP_KEYBOARD_CONNECTED
                self.memory.set_paired(True, self.pairing, name.decode("utf-8", "replace"))
                self.asked_at = None
                log("keyboard paired: %s %s" % (self.pairing, name.decode("utf-8", "replace")))
            elif words[0] == "PAIRFAIL" and stick.kbd_state == proto.NESP_KEYBOARD_PAIRING:
                stick.kbd_state = proto.NESP_KEYBOARD_FAILED
                self.asked_at = None
                log("keyboard pairing failed: %s" % " ".join(words[1:]))
        if stick.kbd_forgets != self.forgets:
            self.forgets = stick.kbd_forgets
            if self.memory.address:
                helper.send("FORGET " + self.memory.address)
            self.memory.set_paired(False)
            self.asked_at = None
            log("keyboard forgotten")
        if stick.kbd_scans != self.scans:
            self.scans = stick.kbd_scans
            self.heard = []
            log("keyboard scan")
            if helper.send("SCAN %d" % HELPER_SCAN):
                self.asked_at = now
            else:
                self.finish_scan()
        if stick.kbd_pairs != self.pairs:
            self.pairs = stick.kbd_pairs
            index = stick.kbd_pair_index
            found = self.heard[:FOUND_MAX]
            if index < len(found) and helper.send("PAIR " + found[index][0]):
                self.pairing = found[index][0]
                self.asked_at = now
            else:
                stick.kbd_state = proto.NESP_KEYBOARD_FAILED
        if self.asked_at is not None:
            if stick.kbd_state == proto.NESP_KEYBOARD_SCANNING and now - self.asked_at > HELPER_WAIT_MS:
                self.finish_scan()
            elif stick.kbd_state == proto.NESP_KEYBOARD_PAIRING and now - self.asked_at > HELPER_PAIR_MS:
                stick.kbd_state = proto.NESP_KEYBOARD_FAILED
                self.asked_at = None
        self.keyboard.tick(now, lambda: stick.kbd_unread != 0)

    def finish_scan(self):
        """The helper has said what it heard (or nothing is to be heard)."""
        self.asked_at = None
        self.heard.sort(key=lambda d: -d[2])
        self.heard = self.heard[:FOUND_MAX]
        self.stick.kbd_found([(name, rssi) for _, name, rssi in self.heard])
        self.stick.kbd_state = proto.NESP_KEYBOARD_SCANNED

    def update(self, now):
        """What the Bluetooth does by now (ms): a scan or a pairing the
        console started comes to its end, and a key held down repeats."""
        if self.helper is not None:
            return self.update_helper(now)
        stick = self.stick
        if stick.kbd_forgets != self.forgets:
            self.forgets = stick.kbd_forgets
            self.done_at = None
            self.memory.set_paired(False)
            log("keyboard forgotten")
        if stick.kbd_scans != self.scans:
            self.scans = stick.kbd_scans
            self.done_at = now + SCAN_MS
            log("keyboard scan")
        if stick.kbd_pairs != self.pairs:
            self.pairs = stick.kbd_pairs
            self.done_at = now + PAIR_MS
        if self.done_at is not None and now >= self.done_at:
            self.done_at = None
            if stick.kbd_state == proto.NESP_KEYBOARD_SCANNING:
                stick.kbd_found([(KEYBOARD_NAME, KEYBOARD_SIGNAL)])
                stick.kbd_state = proto.NESP_KEYBOARD_SCANNED
            elif stick.kbd_state == proto.NESP_KEYBOARD_PAIRING:
                stick.kbd_paired(KEYBOARD_NAME)
                stick.kbd_state = proto.NESP_KEYBOARD_CONNECTED
                self.memory.set_paired(True)
                log("keyboard paired: %s" % KEYBOARD_NAME.decode())
        self.keyboard.tick(now, lambda: stick.kbd_unread != 0)


# --- the Internet ---------------------------------------------------------------

class Fetcher:
    """A fetch on a thread of its own, as the firmware's fetch.c makes one.
    What it gets is queued, and handed to the firmware's sink from the main
    thread between syncs. A sink with a head (HTTP's) hears every reply,
    whatever its status, and its status, type and length before its body;
    for any other, a status but 200 is a fetch that failed."""

    def __init__(self, fetch_id, url, agent, icy, head):
        self.id = fetch_id
        self.items = queue.Queue()
        self.cancelled = False
        self.thread = threading.Thread(target=self.run, args=(url, agent, icy, head),
                                       daemon=True)
        self.thread.start()

    def run(self, url, agent, icy, head):
        headers = {"User-Agent": agent or "nesp32", "Accept-Encoding": "identity"}
        if icy:
            headers["Icy-MetaData"] = "1"
        try:
            try:
                reply = urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                               timeout=FETCH_TIMEOUT)
            except urllib.error.HTTPError as error:
                if not head:
                    self.items.put(("done", False, b"THE SITE SAID %d" % error.code))
                    return
                reply = error           # a reply all the same, with a body
            with reply:
                if icy:
                    self.items.put(("icy", int(reply.headers.get("icy-metaint") or 0)))
                if head:
                    length = reply.headers.get("Content-Length")
                    length = int(length) if length and length.isdigit() \
                        and int(length) <= 0xFFFFFFFE else proto.NESP_HTTP_LENGTH_UNKNOWN
                    self.items.put(("head", reply.status if hasattr(reply, "status")
                                    else reply.code,
                                    (reply.headers.get("Content-Type") or "").encode(), length))
                while not self.cancelled:
                    chunk = reply.read1(8192) if hasattr(reply, "read1") else reply.read(8192)
                    if not chunk:
                        break
                    self.items.put(("body", chunk))
            self.items.put(("done", True, b""))
        except urllib.error.URLError:
            self.items.put(("done", False, b"THE SITE DID NOT ANSWER"))
        except Exception:
            self.items.put(("done", False, b"THE CONNECTION DROPPED"))


# --- the board ------------------------------------------------------------------

class Console:
    """What wire.Port asks of a console: the time, in CPU cycles."""

    def __init__(self):
        self.now = 0


class Board:
    """One NESP32, for one Mesen."""

    def __init__(self, memory=None, helper=None):
        self.memory = memory if memory is not None else Memory()
        self.console = Console()
        self.port = wire.Port(self.console, turnaround=wire.ms(0.1))
        self.stick = nesp.Stick(self.port)
        self.stick.set_wifi(proto.NESP_WIFI_JOINED, rssi=-45, address=(192, 168, 0, 32))
        self.stick.set_saved(b"Mesen")
        self.stick.set_time(int(time.time()))
        for name, data in self.memory.files.items():
            self.stick.put_file(name, data)
        self.file_writes = self.stick.file_writes
        self.bluetooth = BluetoothKeyboard(self.stick, self.memory, helper)
        self.sent = 0               # how many of the wire's bytes Mesen has been told of
        self.scans = 0
        self.joins = 0
        self.fetches = 0
        self.fetch_stops = 0
        self.fetch = None
        self.counted = (0, 0, 0)
        self.last_end = None        # where the last byte sent to Mesen ends, for gaps
        self.instrument()

    def now_ms(self):
        return self.console.now * 1000.0 / wire.NESP_CPU_HZ

    def instrument(self):
        """Log the radio's requests, the line's changes of rate (a sound run
        starting or ending), and gaps in a run's samples."""
        port = self.port
        read, line_rate = port.read, port.line_rate
        names = {proto.NESP_TUNER_PLAY: "PLAY", proto.NESP_TUNER_STOP: "STOP",
                 proto.NESP_TUNER_SOUND: "SOUND", proto.NESP_TUNER_URL: "URL"}

        def logged_read():
            data = read()
            if data:
                for i in range(len(data) - 2):
                    if (data[i] == proto.NESP_REQUEST_MARKER and data[i + 1] == proto.NESP_SVC_TUNER
                            and data[i + 2] in names):
                        log("console: TUNER %s (cycle %d)" % (names[data[i + 2]], self.console.now))
            return data

        def logged_rate(period):
            log("line rate %d cycles a bit (%s) at cycle %d" % (
                period, "link" if period == proto.NESP_PERIOD else "sound run", self.console.now))
            line_rate(period)

        port.read, port.line_rate = logged_read, logged_rate

    def counters(self):
        stick = self.stick
        # Noise rises every frame on its own (the strobe for controller 1
        # looks like a start bit to the UART, on a real console too), so
        # only repeats and drops are worth a line.
        now = (stick.repeats, stick.dropped, stick.noise)
        if now[:2] != self.counted[:2]:
            log("link: requests %d, repeats %d, dropped %d, noise %d (console cycle %d)"
                % ((stick.requests,) + now + (self.console.now,)))
            self.counted = now

    def sync(self, cycle, changes):
        console, port, stick = self.console, self.port, self.stick
        console.now = cycle
        for at, level in changes:
            port.tap.write(at, level)
        stick.set_time(int(time.time()))
        self.network()
        self.deliver()
        self.bluetooth.update(self.now_ms())
        stick.poll()
        self.network()
        self.files()
        self.counters()
        return self.report()

    def network(self):
        """What the hardware does for the services: scans, joins, fetches."""
        stick = self.stick
        if stick.scans != self.scans:
            self.scans = stick.scans
            stick.scan_set([(b"Mesen", -45, proto.NESP_AUTH_OPEN, 6)])
            stick.scan_finish()
        if stick.joins != self.joins:
            self.joins = stick.joins
            stick.set_wifi(proto.NESP_WIFI_JOINED, rssi=-45, address=(192, 168, 0, 32))
        if stick.fetch_stops != self.fetch_stops:
            self.fetch_stops = stick.fetch_stops
            self.cancel()
        if stick.fetches != self.fetches:
            self.fetches = stick.fetches
            self.cancel()
            log("fetch %d: %s" % (stick.fetch_id, redact(stick.fetch_url)))
            self.fetch = Fetcher(stick.fetch_id, stick.fetch_url, stick.fetch_agent,
                                 stick.fetch_wants_icy, stick.fetch_wants_head)

    def cancel(self):
        if self.fetch is not None:
            self.fetch.cancelled = True
            self.fetch = None

    def deliver(self):
        fetch = self.fetch
        if fetch is None:
            return
        while True:
            try:
                item = fetch.items.get_nowait()
            except queue.Empty:
                return
            if item[0] == "icy":
                self.stick.fetch_icy(item[1], fetch=fetch.id)
            elif item[0] == "head":
                self.stick.fetch_head(item[1], item[2], item[3], fetch=fetch.id)
            elif item[0] == "body":
                if not self.stick.fetch_body(item[1], fetch=fetch.id):
                    fetch.cancelled = True
                    self.fetch = None
                    self.stick.fetch_done(True, b"", fetch=fetch.id)
                    return
            else:
                self.fetch = None
                log("fetch %d done: %s %s" % (fetch.id, "ok" if item[1] else "FAILED",
                                              item[2].decode()))
                self.stick.fetch_done(item[1], item[2], fetch=fetch.id)
                return

    def files(self):
        """A ROM's files written since the last sync, kept."""
        stick = self.stick
        if stick.file_writes != self.file_writes:
            self.file_writes = stick.file_writes
            for name in stick.file_names:
                data = stick.file(name)
                if data is not None:
                    self.memory.keep_file(name, data)

    def report(self):
        """The reply line: bytes on the wire that Mesen hasn't been told of,
        and how the keyboard stands."""
        w = self.wire_trim()
        runs = []
        index = self.sent
        while index < len(w.starts):
            start, bit = w.starts[index], w.bits[index]
            data = bytearray([w.bytes[index]])
            index += 1
            while (index < len(w.starts) and w.bits[index] == bit
                   and abs(w.starts[index] - (start + bit * wire.NESP_TO_NES_BITS * len(data)))
                   < 0.01):
                data.append(w.bytes[index])
                index += 1
            if (bit != proto.NESP_PERIOD and self.last_end is not None
                    and start - self.last_end > bit * 22):
                log("GAP in sound: %.1f ms with nothing on the line (cycle %d)" % (
                    (start - self.last_end) * 1000 / wire.NESP_CPU_HZ, start))
            self.last_end = start + bit * wire.NESP_TO_NES_BITS * len(data)
            runs.append("%d %d %s" % (round(start), round(bit), data.hex()))
        self.sent = index
        return "R %d %d %s K %d %d\n" % (1 if self.busy() else 0, len(runs), " ".join(runs),
                                         self.stick.kbd_state, 1 if self.stick.kbd_on else 0)

    def busy(self):
        """A byte from the console is partway in: its start bit has come,
        and not its stop bit."""
        tap = self.port.tap
        return any(at > self.port.search_from and level == wire.SPACE
                   for at, level in zip(tap.times[-4:], tap.levels[-4:]))

    def wire_trim(self):
        """Forget bytes long gone from the line, so a radio station that
        plays for hours does not fill the memory."""
        w = self.port.wire
        old = self.console.now - wire.NESP_CPU_HZ   # a second ago
        cut = 0
        while cut < self.sent and cut < len(w.starts) - 1 and w.starts[cut + 1] < old:
            cut += 1
        if cut > 4096:
            del w.starts[:cut], w.bits[:cut], w.bytes[:cut]
            self.sent -= cut
        tap = self.port.tap
        if len(tap.times) > 8192:
            keep = max(0, len(tap.times) - 64)
            del tap.times[1:keep], tap.levels[1:keep]
        return w

    def button(self, which):
        code = proto.NESP_EVENT_BUTTON_A if which == 1 else proto.NESP_EVENT_BUTTON_B
        self.stick.event(code)

    def keys(self, modifiers, usages):
        self.bluetooth.report(modifiers, usages, self.now_ms())


def serve(conn, address, memory, helper=None):
    log("Mesen connected from %s" % (address,))
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    board = Board(memory, helper)
    last = 0
    buffered = conn.makefile("rb")
    try:
        for raw in buffered:
            words = raw.split()
            if not words:
                continue
            if words[0] == b"S":
                cycle = int(words[1])
                if cycle < last:
                    log("console reset: a new board")
                    board.cancel()
                    board = Board(memory, helper)
                last = cycle
                count = int(words[2])
                changes = [(int(words[3 + 2 * i]), int(words[4 + 2 * i])) for i in range(count)]
                conn.sendall(board.sync(cycle, changes).encode())
            elif words[0] == b"B":
                board.button(int(words[1]))
            elif words[0] == b"K":
                board.keys(int(words[1]), [int(word) for word in words[2:]])
    except (ConnectionError, OSError):
        pass
    finally:
        board.cancel()
        conn.close()
        log("Mesen disconnected")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7878)
    parser.add_argument("--nesp32", default=default_nesp32(),
                        help="a checkout of github.com/Armitage64/nesp32 with `make host` done")
    parser.add_argument("--data", default=None,
                        help="a directory to keep the keyboard's pairing and a ROM's files in "
                             "over restarts of the bridge (by default they last as long as "
                             "it runs)")
    parser.add_argument("--bt-helper", default=None, metavar="HOST:PORT",
                        help="real Bluetooth: scan, pair and type with nesp32_bt_helper.py "
                             "running there, instead of the computer's keyboard as a "
                             "pretend Bluetooth one")
    args = parser.parse_args()
    load_nesp32(os.path.abspath(args.nesp32))
    memory = Memory(args.data)
    helper = HelperLink(args.bt_helper) if args.bt_helper else None
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(4)
    print("NESP32 bridge listening on %s:%d" % (args.host, args.port), flush=True)
    while True:
        conn, address = server.accept()
        threading.Thread(target=serve, args=(conn, address, memory, helper), daemon=True).start()


if __name__ == "__main__":
    main()

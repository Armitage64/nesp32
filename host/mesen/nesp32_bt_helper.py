#!/usr/bin/env python3
"""Bluetooth for nesp32_bridge.py, on a machine that has a radio (a Raspberry Pi).

The bridge (run with --bt-helper HOST:PORT) asks this program to scan, pair
and forget, and gets the keys of the paired keyboard back. It uses BlueZ
(bluetoothctl) for the radio and python3-evdev for the keys, so BlueZ must be
running and `sudo apt-get install python3-evdev` done.

    nesp32_bt_helper.py [--host 0.0.0.0] [--port 7980] [--state DIR]

It prints its key when it starts; the bridge needs it (--bt-key).

Protocol, one line each way, ASCII. A bridge -> helper, first:
  HELLO <key>      the key this helper prints when it starts (kept in
                   DIR/key). A connection that does not start with it is
                   closed, and hears nothing: not a key typed, not a scan.
Then:
  SCAN <seconds>   D <address> <rssi> <name>, one for each named device heard,
                   then SCANDONE
  PAIR <address>   pair, trust and connect it. PASSKEY <digits> if the keyboard
                   is to show one (it is confirmed for it), then PAIRED
                   <address> <name> or PAIRFAIL <why>
  FORGET <address> remove it, then FORGOTTEN
Any time, to every bridge that has said HELLO:
  K <modifiers> [<usage>...]   the keys down on the keyboard paired, as a
                   Bluetooth keyboard's report has them (HID's modifier bits
                   and up to 6 usages, the keyboard page)
  UP / DOWN        the keyboard connected, or not

Only the keyboard paired through here (its address is kept in DIR/keyboard)
is read, and it is grabbed, so it types nothing on this machine. It idles on
blocking reads and a slow retry, no busy loop.
"""

import argparse
import hmac
import os
import re
import secrets
import select
import socket
import subprocess
import sys
import threading
import time

try:
    import evdev
    from evdev import ecodes
except ImportError:             # the tests, and a machine without it
    evdev = None
    ecodes = None

ADDRESS = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\x01\x02]")
RETRY = 10                      # seconds between looks for the keyboard
HELLO_WAIT = 10                 # seconds a connection has to say HELLO
MODIFIERS = {"KEY_LEFTCTRL": 0x01, "KEY_LEFTSHIFT": 0x02, "KEY_LEFTALT": 0x04,
             "KEY_LEFTMETA": 0x08, "KEY_RIGHTCTRL": 0x10, "KEY_RIGHTSHIFT": 0x20,
             "KEY_RIGHTALT": 0x40, "KEY_RIGHTMETA": 0x80}


def build_usages():
    """evdev key code -> HID usage (keyboard page)."""
    names = {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        names["KEY_" + c] = 0x04 + i
    for i, c in enumerate("1234567890"):
        names["KEY_" + c] = 0x1E + i
    for i, n in enumerate(("ENTER ESC BACKSPACE TAB SPACE MINUS EQUAL LEFTBRACE RIGHTBRACE "
                           "BACKSLASH HASHTILDE SEMICOLON APOSTROPHE GRAVE COMMA DOT SLASH "
                           "CAPSLOCK").split()):
        names["KEY_" + n] = 0x28 + i
    for i in range(12):
        names["KEY_F%d" % (i + 1)] = 0x3A + i
    for i, n in enumerate(("SYSRQ SCROLLLOCK PAUSE INSERT HOME PAGEUP DELETE END PAGEDOWN "
                           "RIGHT LEFT DOWN UP NUMLOCK KPSLASH KPASTERISK KPMINUS KPPLUS "
                           "KPENTER").split()):
        names["KEY_" + n] = 0x46 + i
    for i in range(9):
        names["KEY_KP%d" % (i + 1)] = 0x59 + i
    names["KEY_KP0"] = 0x62
    names["KEY_KPDOT"] = 0x63
    names["KEY_102ND"] = 0x64
    names["KEY_COMPOSE"] = 0x65
    return names


def keycodes():
    """The two tables, by evdev's numbers: usages, modifier bits."""
    usages, mods = {}, {}
    for name, usage in build_usages().items():
        code = getattr(ecodes, name, None)
        if code is not None:
            usages[code] = usage
    for name, bit in MODIFIERS.items():
        mods[getattr(ecodes, name)] = bit
    return usages, mods


def report_line(modifiers, usages):
    return "K %d%s" % (modifiers, "".join(" %d" % u for u in usages))


class Keys:
    """Key state from evdev's events, as reports."""

    def __init__(self, usages, mods):
        self.usages = usages
        self.mods = mods
        self.down = []              # usages, in the order pressed
        self.modifiers = 0

    def event(self, code, value):
        """A key event (value 1 down, 0 up, 2 repeat); the new report line,
        or None when nothing changed."""
        if value == 2:
            return None
        if code in self.mods:
            bit = self.mods[code]
            now = self.modifiers | bit if value else self.modifiers & ~bit
            if now == self.modifiers:
                return None
            self.modifiers = now
        elif code in self.usages:
            usage = self.usages[code]
            if value and usage not in self.down:
                self.down.append(usage)
            elif not value and usage in self.down:
                self.down.remove(usage)
            else:
                return None
        else:
            return None
        return report_line(self.modifiers, self.down[:6])


def clean(text):
    return ANSI.sub("", text)


def ctl(*args, timeout=20):
    """One bluetoothctl command; its output."""
    try:
        done = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True,
                              timeout=timeout)
        return clean(done.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return ""


def info(address):
    out = ctl("info", address)
    got = {}
    for line in out.splitlines():
        key, _, value = line.strip().partition(": ")
        got[key] = value
    return got


def scan(seconds):
    """[(address, rssi, name)] of the devices heard with a name, strongest first."""
    seconds = max(1, min(int(seconds), 30))
    out = ctl("--timeout", str(seconds), "scan", "on", timeout=seconds + 15)
    rssi = {}
    for line in out.splitlines():
        m = re.search(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) RSSI: (?:0x[0-9a-f]+ )?\(?(-?\d+)", line)
        if m:
            rssi[m.group(1)] = int(m.group(2))
    names = {}                  # BlueZ remembers a device's name from before
    for line in ctl("devices").splitlines():
        m = re.search(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.*)$", line)
        if m:
            names[m.group(1)] = m.group(2).strip()
    found = []
    for address, level in rssi.items():
        name = names.get(address, "")
        if name and name.replace("-", ":").upper() != address:
            found.append((address, level, name))
    found.sort(key=lambda d: -d[1])
    return found


def pair(address, say):
    """Pair, trust and connect; (True, name) or (False, why). say(line) is
    told of a passkey."""
    proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)

    def send(text):
        proc.stdin.write(text + "\n")
        proc.stdin.flush()

    why = "timed out"
    ok = False
    try:
        for text in ("agent KeyboardDisplay", "default-agent", "pairable on",
                     "pair " + address):
            send(text)
        end = time.time() + 60
        while time.time() < end:
            ready, _, _ = select.select([proc.stdout], [], [], max(0.1, end - time.time()))
            if not ready:
                continue
            line = clean(proc.stdout.readline())
            if not line:
                break
            m = re.search(r"(?:Passkey|passkey)[: ]+(\d+)", line)
            if m:
                say("PASSKEY " + m.group(1))
            if "Confirm passkey" in line or "Request confirmation" in line:
                send("yes")
            if "Pairing successful" in line or "AlreadyExists" in line:
                ok = True
                break
            if "Failed to pair" in line:
                why = line.split("Failed to pair:")[-1].strip() or "failed"
                break
        if ok:
            send("trust " + address)
            time.sleep(1)
            send("connect " + address)
            time.sleep(4)
        send("pairable off")
        send("quit")
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if not ok:
        return False, why
    return True, info(address).get("Name", address)


class Helper:
    def __init__(self, state):
        self.state = state
        os.makedirs(state, exist_ok=True)
        self.clients = []
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.pairing = threading.Lock()
        self.key = self.load_key()

    def load_key(self):
        """The key a bridge says HELLO with: made at random the first time,
        then kept in DIR/key, readable by this user alone."""
        path = os.path.join(self.state, "key")
        try:
            with open(path) as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            pass
        key = secrets.token_hex(16)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key + "\n")
        return key

    def hello(self, conn):
        """True if the connection's first line is HELLO with the key. It has
        HELLO_WAIT seconds to say it."""
        conn.settimeout(HELLO_WAIT)
        line = b""
        try:
            while not line.endswith(b"\n") and len(line) < 128:
                got = conn.recv(1)
                if not got:
                    return False
                line += got
        except OSError:
            return False
        conn.settimeout(None)
        words = line.decode("ascii", "replace").split()
        return (len(words) == 2 and words[0] == "HELLO"
                and hmac.compare_digest(words[1].encode(), self.key.encode()))

    def path(self):
        return os.path.join(self.state, "keyboard")

    def address(self):
        try:
            with open(self.path()) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def set_address(self, address):
        if address:
            with open(self.path(), "w") as f:
                f.write(address + "\n")
        elif os.path.exists(self.path()):
            os.remove(self.path())
        self.wake.set()

    def tell(self, line, only=None):
        data = (line + "\n").encode()
        with self.lock:
            for conn in ([only] if only else list(self.clients)):
                try:
                    conn.sendall(data)
                except OSError:
                    if conn in self.clients:
                        self.clients.remove(conn)

    def handle(self, conn, line):
        words = line.split()
        if not words:
            return
        say = lambda text: self.tell(text, conn)
        if words[0] == "SCAN":
            for address, rssi, name in scan(words[1] if len(words) > 1 else 8):
                say("D %s %d %s" % (address, rssi, name))
            say("SCANDONE")
        elif words[0] == "PAIR" and len(words) == 2 and ADDRESS.match(words[1]):
            address = words[1].upper()
            with self.pairing:
                ok, what = pair(address, say)
                if ok:
                    self.set_address(address)
                    say("PAIRED %s %s" % (address, what))
                else:
                    say("PAIRFAIL " + what)
        elif words[0] == "FORGET" and len(words) == 2 and ADDRESS.match(words[1]):
            address = words[1].upper()
            ctl("disconnect", address)
            ctl("remove", address)
            if self.address() == address:
                self.set_address(None)
            say("FORGOTTEN")
        else:
            say("ERR " + line[:40])

    def serve(self, conn):
        if not self.hello(conn):
            print("a connection without the key, closed", flush=True)
            conn.close()
            return
        with self.lock:
            self.clients.append(conn)
        if self.address():
            self.wake.set()
        try:
            for raw in conn.makefile("r", errors="replace"):
                self.handle(conn, raw.strip())
        except OSError:
            pass
        finally:
            with self.lock:
                if conn in self.clients:
                    self.clients.remove(conn)
            conn.close()

    def find(self, address):
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            if (device.uniq or "").upper() == address:
                return device
            device.close()
        return None

    def keys(self):
        """The thread that reads the paired keyboard, if any."""
        usages, mods = keycodes()
        while True:
            address = self.address()
            device = None
            if address and self.clients:
                device = self.find(address)
                if device is None and "yes" not in info(address).get("Connected", ""):
                    ctl("connect", address, timeout=15)
                    device = self.find(address)
            if device is None:
                self.wake.wait(RETRY)
                self.wake.clear()
                continue
            print("keyboard %s up: %s" % (address, device.name), flush=True)
            keys = Keys(usages, mods)
            self.tell("UP")
            try:
                device.grab()
            except OSError:
                pass
            try:
                while self.address() == address:
                    ready, _, _ = select.select([device.fd], [], [], 5)
                    if not ready:
                        continue
                    for event in device.read():
                        if event.type == ecodes.EV_KEY:
                            line = keys.event(event.code, event.value)
                            if line:
                                self.tell(line)
            except OSError:
                pass
            self.tell("K 0")
            self.tell("DOWN")
            print("keyboard down", flush=True)
            try:
                device.close()
            except OSError:
                pass
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7980)
    parser.add_argument("--state", default=os.path.expanduser("~/.nesp32-bt"))
    args = parser.parse_args()
    helper = Helper(args.state)
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(4)
    print("NESP32 Bluetooth helper listening on %s:%d" % (args.host, args.port), flush=True)
    print("its key (the bridge's --bt-key): %s" % helper.key, flush=True)
    threading.Thread(target=helper.keys, daemon=True).start()
    while True:
        conn, _ = server.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=helper.serve, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()

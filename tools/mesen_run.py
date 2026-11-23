#!/usr/bin/env python3
"""Run a ROM in Mesen with no window, press buttons, and keep what it shows.

    mesen_run.py ROM [--frames N] [--press SPEC ...] [--shot FRAME ...]
                     [--ram FRAME ...] [--out DIR] [--timeout SECONDS]

Mesen's --testrunner mode runs the ROM as fast as it can, under a Lua
script this writes, and quits when the script says. What it keeps goes in
--out (build/mesen-run by default):

    shot-FRAME.png    the picture at the end of that frame
    ram-FRAME.bin     the console's 2 KB of RAM at the end of that frame

--press FRAME:BUTTONS[:LENGTH] holds controller 1's buttons (a, b, select,
start, up, down, left, right, joined with +) from that frame for LENGTH
frames, 1 if not given. Frames count from 1, the first after power-on.

    mesen_run.py build/web/nesp32.nes --press 200:down --press 220:a \\
        --shot 300

--bridge puts a nesp32 on controller port 2: host/mesen/nesp32_bridge.py
(the firmware's own code, from `make host`) on a free port, and
host/mesen/nesp32.lua in Mesen to reach it, so the cartridge's programs
get past WAITING FOR LINK. The bridge's log is bridge.log in --out, and
--bridge-data DIR keeps its files (a paired keyboard, a ROM's saves) over
runs. The bridge fetches from the Internet as the firmware would.

MESEN is the Mesen program (default: the one in /Applications).
"""

import argparse
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NESP32_LUA = os.path.join(ROOT, "host", "mesen", "nesp32.lua")
BRIDGE = os.path.join(ROOT, "host", "mesen", "nesp32_bridge.py")
MESEN = os.environ.get("MESEN", "/Applications/Mesen.app/Contents/MacOS/Mesen")
BUTTONS = ("a", "b", "select", "start", "up", "down", "left", "right")


def press(spec):
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("FRAME:BUTTONS[:LENGTH]")
    frame, length = int(parts[0]), int(parts[2]) if len(parts) == 3 else 1
    names = parts[1].lower().split("+")
    for n in names:
        if n not in BUTTONS:
            raise argparse.ArgumentTypeError(f"no button {n!r}: {', '.join(BUTTONS)}")
    return frame, length, names


def lua_bridge(port):
    """Lua that runs nesp32.lua, pointed at a bridge on this port, which it
    does not start: start_bridge does."""
    return f"""
do
  local src = assert(io.open({lua_str(os.path.abspath(NESP32_LUA))})):read("a")
  src = src:gsub("local BRIDGE_PORT = %d+", "local BRIDGE_PORT = {port}", 1)
  src = src:gsub("local BRIDGE_START = true", "local BRIDGE_START = false", 1)
  assert(load(src, "nesp32.lua"))()
end
"""


def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_bridge(port, out, data):
    """nesp32_bridge.py on the port, once it listens."""
    lib = "libnesp_host.dylib" if sys.platform == "darwin" else "libnesp_host.so"
    for need in ("nesp_proto.py", lib):
        if not os.path.exists(os.path.join(ROOT, "build", need)):
            sys.exit(f"no build/{need}: `make host` first")
    cmd = [sys.executable, BRIDGE, "--port", str(port), "--nesp32", os.path.abspath(ROOT)]
    if data:
        cmd += ["--data", os.path.abspath(data)]
    path = os.path.join(out, "bridge.log")
    log = open(path, "w")
    proc = subprocess.Popen([*cmd[:1], "-u", *cmd[1:]], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(100):
        if proc.poll() is not None:
            sys.exit(f"the bridge stopped: see {path}")
        with open(path) as f:
            if "listening" in f.read():
                return proc
        time.sleep(0.1)
    proc.kill()
    sys.exit(f"the bridge never listened on {port}: see {log.name}")


def lua_script(frames, presses, shots, rams, out, port=None):
    held = {}
    for frame, length, names in presses:
        for f in range(frame, frame + length):
            held.setdefault(f, set()).update(names)
    lines = [
        lua_bridge(port) if port else "",
        "local OUT = " + lua_str(out),
        "local held = {",
        *(f"  [{f}] = {{{', '.join(f'{b}=true' for b in sorted(bs))}}},"
          for f, bs in sorted(held.items())),
        "}",
        f"local shots = {{{', '.join(f'[{f}]=true' for f in shots)}}}",
        f"local rams = {{{', '.join(f'[{f}]=true' for f in rams)}}}",
        f"local last = {frames}",
        """
local frame = 1
local function save(path, data)
  local f = assert(io.open(OUT .. "/" .. path, "wb"))
  f:write(data)
  f:close()
end

emu.addEventCallback(function()
  local b = held[frame]
  if b then emu.setInput(b, 0) end
end, emu.eventType.inputPolled)

emu.addEventCallback(function()
  local ok, err = pcall(function()
    if shots[frame] then save("shot-" .. frame .. ".png", emu.takeScreenshot()) end
    if rams[frame] then
      local r = {}
      for a = 0, 0x7FF do
        r[#r + 1] = string.char(emu.read(a, emu.memType.nesInternalRam))
      end
      save("ram-" .. frame .. ".bin", table.concat(r))
    end
  end)
  if not ok then
    print("error: " .. tostring(err))
    emu.stop(2)
  elseif frame >= last then
    emu.stop(0)
  end
  frame = frame + 1
end, emu.eventType.endFrame)
""",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--press", type=press, action="append", default=[])
    ap.add_argument("--shot", type=int, action="append", default=[])
    ap.add_argument("--ram", type=int, action="append", default=[])
    ap.add_argument("--out", default="build/mesen-run")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--bridge", action="store_true")
    ap.add_argument("--bridge-data")
    args = ap.parse_args()

    asked = args.shot + args.ram + [f + n - 1 for f, n, _ in args.press]
    frames = args.frames or max(asked, default=60)
    if not args.shot and not args.ram:
        args.shot = [frames]
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    port = free_port() if args.bridge or args.bridge_data else None
    script = os.path.join(out, "run.lua")
    with open(script, "w") as f:
        f.write(lua_script(frames, args.press, args.shot, args.ram, out, port))

    bridge = start_bridge(port, out, args.bridge_data) if port else None
    try:
        r = subprocess.run([MESEN, "--testrunner", os.path.abspath(args.rom), script],
                           capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"Mesen ran past {args.timeout:g} s")
    finally:
        if bridge:
            bridge.terminate()
            bridge.wait()
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit(f"Mesen stopped with {r.returncode}")
    for f in sorted(set(args.shot)):
        print(os.path.join(out, f"shot-{f}.png"))
    for f in sorted(set(args.ram)):
        print(os.path.join(out, f"ram-{f}.bin"))


if __name__ == "__main__":
    main()

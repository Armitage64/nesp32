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

MESEN is the Mesen program (default: the one in /Applications).
"""

import argparse
import os
import subprocess
import sys

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


def lua_script(frames, presses, shots, rams, out):
    held = {}
    for frame, length, names in presses:
        for f in range(frame, frame + length):
            held.setdefault(f, set()).update(names)
    q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = [
        "local OUT = " + q(out),
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
    args = ap.parse_args()

    asked = args.shot + args.ram + [f + n - 1 for f, n, _ in args.press]
    frames = args.frames or max(asked, default=60)
    if not args.shot and not args.ram:
        args.shot = [frames]
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    script = os.path.join(out, "run.lua")
    with open(script, "w") as f:
        f.write(lua_script(frames, args.press, args.shot, args.ram, out))

    try:
        r = subprocess.run([MESEN, "--testrunner", os.path.abspath(args.rom), script],
                           capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"Mesen ran past {args.timeout:g} s")
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

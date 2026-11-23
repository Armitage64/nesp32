# Mesen: a nesp32 in an emulator

A nesp32 on controller port 2 of [MesenCE](https://github.com/nesdev-org/MesenCE),
with no hardware: the cartridge's programs, and any ROM written for a
nesp32, run in the emulator against the nesp32's own firmware, and reach
the Internet. Made for [issue #45](https://github.com/Armitage64/nesp32/issues/45).

Two parts, which talk over a TCP connection:

- **`nesp32.lua`** runs in Mesen's Script Window, in a stock Mesen. It is
  the console's end of the controller port's two wires: it hooks `$4016`
  writes (OUT0, bit 0) and `$4017` reads (D0, bit 0), and times each
  with the CPU's cycle count. Every change of OUT0 goes to the bridge
  with its cycle; the bridge says which bytes go on D0 and when, and
  every read of `$4017` is answered from that.
- **`nesp32_bridge.py`** is the nesp32. It runs the firmware's link and
  services as `make host` builds them for a computer (`build/libnesp_host`,
  through `host/nesp.py`), behind the serial line's model the tests use
  (`tests/wire.py`). The hardware under them is this computer's: real
  HTTPS fetches (with a stream's titles, and HTTP's status and headers),
  real time, a Wi-Fi network that is always joined, the computer's
  keyboard as the Bluetooth keyboard, and the files a ROM keeps.

The board's clock is the console's CPU cycle count, so the link's timing is
the same as the tests model it, whatever speed Mesen runs at.

## Status

| Part | State |
|---|---|
| The link: the cartridge's menu and programs get past WAITING FOR LINK | working in MesenCE on Windows, with the bridge on Linux, and in a headless MesenCE on Linux |
| Setup, NES Radar, NESradio (sound and titles), Weather | working |
| HTTP (the HTTPS sample's 200 and 404) | working |
| The Bluetooth keyboard (KBD): pairing in Setup, forgetting, typing in Setup, Weather and the keyboard sample, Ctrl with a key, keys held down | working in a headless MesenCE on Linux; tested against KBD in `tests/test_mesen.py`; not yet tried on Windows |
| Family BASIC's SAVE and LOAD (TAPE) as files | tested against TAPE in `tests/test_mesen.py`; not yet tried with the game |
| PEER (the games for two) | not yet |
| Save states, rewind | not supported (Known limits) |
| The script starting and stopping the bridge | working in a headless MesenCE on macOS, also with the script named as the Script Window names it (its file's name alone); not yet tried in Mesen's window, on Linux, or on Windows (`BRIDGE_COMMAND`) |

## Setting up

### 1. The bridge

It needs Python 3 and a C compiler for the firmware's code: Linux, macOS,
or WSL on Windows. From the top of this repository, once:

```sh
make host                    # on Linux: make host CC=clang
```

On macOS and Linux that is all: `nesp32.lua`, run from its place in this
repository, starts the bridge itself when none answers, and the bridge
stops 5 seconds after the script or Mesen does (`--exit-when-idle`). Its
log is `bridge.log` in Mesen's folder for the script's data (on macOS
`~/Library/Application Support/Mesen2/LuaScriptData/nesp32/`), and the
script's message at the top of the screen names it while the bridge does
not answer. Settings at the top of `nesp32.lua`: `BRIDGE_START = false`
to start it by hand, `BRIDGE_DIR` for a script copied away from the bridge (Mesen's Script
Window gives a script only its file's name, so the script finds its
folder in the window's recent scripts, in Mesen's `settings.json`),
`BRIDGE_PYTHON`, and `BRIDGE_ARGS` for the options below (such as
`--data`). A bridge already running, started by hand, is used as it is
and keeps running.

On Windows the bridge is in WSL, so the script starts it only with
`BRIDGE_COMMAND` set, such as
`"wsl.exe python3 ~/nesp32/host/mesen/nesp32_bridge.py"`; this has not
been tried yet. Otherwise start it by hand, as anywhere:

```sh
python3 host/mesen/nesp32_bridge.py
```

It listens on port 7878 (`--port`), on this computer alone (`127.0.0.1`).
In WSL 2 the bridge is reached from Windows at `127.0.0.1` as it is. To run
it on another computer on the network, start it with `--host 0.0.0.0` and
set `BRIDGE_HOST` at the top of `nesp32.lua` to that computer's address;
anyone who can reach the port can then use the bridge, and have it fetch
for them, so do that only on a network you trust.

The bridge fetches `http` and `https` addresses alone, as the firmware
does, and follows a redirect only to one of those: a ROM cannot have it
open a file on this computer.

`--data DIR` keeps what a nesp32 keeps over power-off in that directory:
which keyboard is paired, and a ROM's files (Family BASIC's SAVE). Without
it they last as long as the bridge runs.

The log says what the console asked of the radio, every fetch (with any
key, token or password in its address left out), and each pairing.

### 2. Mesen, once

MesenCE is best: it has `emu.getCpuCycleCount()` and `emu.getPressedKeys()`.
A Mesen 2 without the first works, from `emu.getState()["cpu.cycleCount"]`,
but that copies the whole state at each of thousands of calls a frame, so
NESradio's sound may stutter.

- **Settings > Input**: controller **port 2** to **None**. The script is
  port 2.
- **Debug > Script Window**, then the gear (Settings): tick **Allow access
  to I/O and OS functions** and **Allow network access**. The script
  reaches the bridge with Mesen's own LuaSocket.
- **Settings > Audio**: turn off the option that lowers the volume while
  Mesen is in the background, or NESradio is very quiet whenever another
  window has focus.
- For typing (below): **Settings > Preferences > Shortcut Keys**, clear the
  shortcuts on keys that will be typed. Mesen's own are Esc (pause), Tab
  (fast forward), Backspace (rewind), `` ` `` (one frame), `-` and `=`
  (speed), F1 to F8 (load a state), Shift and F1 to F7 (save one), F9 to
  F12, and Ctrl with R, T, S, O or L. The script cannot keep a key from
  them: Esc pauses the emulator even in typing mode.

### 3. Playing

1. Load the cartridge (`build/nesp32.nes` from `make cart`, or the one on
   the [home page](https://nesp32.retrobits.tv/)), or any ROM for a nesp32.
2. Open `nesp32.lua` in the Script Window and run it. The log says
   `NESP32: started the bridge` if it had to, then
   `NESP32: connected to ...`, and the programs get past WAITING FOR LINK.

The nesp32's own two buttons are **Insert** (A) and **Delete** (B), out of
typing mode. `KEY_A` and `KEY_B` at the top of the script change them.

## The keyboard

The computer's keyboard is the nesp32's Bluetooth keyboard: a scan finds
one keyboard, named `Mesen PC keyboard`, and Setup pairs it as it would a
real one. From then on, what is typed in **typing mode** goes to the
nesp32 as a keyboard's reports, and the firmware's own code
(`firmware/main/keyboard.c`, as the bridge has it) makes characters of
them: a US layout, Shift and Caps Lock, Ctrl and Enter for Start, Ctrl and
Escape for Select, a key with Ctrl or Alt for KEYS_ALL, and a key held
down typed again after half a second and 25 times a second, at the ROM's
pace. Where the keyboard comes from does not matter: a laptop's own, or
one paired with the computer over Bluetooth.

**Pair it first.** The keyboard is pretend, but it starts unpaired, as a
real keyboard does with a new nesp32: until Setup has paired it, typing
mode says `No keyboard paired: Setup > Bluetooth` and nothing typed
reaches the nesp32. To pair, out of typing mode: Setup's **BLUETOOTH**,
then **PAIR DEVICE**, and A on `Mesen PC keyboard`. The pairing lasts as
long as the bridge runs, or over restarts with `--data DIR`.

**Scroll Lock** or **End** turns typing mode on and off (`TYPING_KEYS`).
On a Mac, which has neither, **Fn and Right Arrow** is End. Mesen shows
typing mode at the bottom of the screen, with a word when no keyboard is
paired or the program asks for none. In typing mode every key goes to
the nesp32, and none to controller 1 or to the nesp32's buttons; the
cartridge's programs take the arrows, Enter and Escape as the
controller's buttons anyway (PROTOCOL.md, KBD). `PAD_WHILE_TYPING = true`
leaves controller 1 its keys as well.

To try it, once paired: typing mode, and type on Setup's
**TYPE HERE** line, in Weather's place, NESpedia's search, or
`samplecode/keyboard`.

The script reads the keys once a frame, so a key must be down for a frame
(1/60 s) to count; a person typing is far slower than that, but a
program that types for you (a macro) may need to hold each key longer.
Mesen hears the keyboard only while its game window has focus.

## Real Bluetooth (Raspberry Pi)

There are two keyboard modes.

1. **Pretend Bluetooth** (the default, above). The computer's own physical
   keyboard acts as the nesp32's Bluetooth keyboard. No Bluetooth hardware is
   needed, anywhere.
2. **Real Bluetooth.** A machine with a Bluetooth radio, such as a Raspberry
   Pi, runs `nesp32_bt_helper.py`. Setup's scan then lists the real keyboards
   near it, and it pairs the one you choose. What is typed on that keyboard
   is what the nesp32 gets. `Mesen PC keyboard` stays first on the list, so
   the computer's own keyboard can still be paired in this mode; whichever
   keyboard is paired is the only one that types.

On the Pi (BlueZ running, `sudo apt-get install python3-evdev`):

    nice python3 nesp32_bt_helper.py --port 7980

It prints its key, made at random the first time and kept in
`~/.nesp32-bt/key` (readable by its user alone). On the bridge's machine,
add `--bt-helper PI_ADDRESS:7980 --bt-key KEY` (or set `NESP32_BT_KEY`),
in `BRIDGE_ARGS` when the script starts the bridge.
Without `--bt-helper` nothing changes.

The helper takes a connection only if it starts with that key: one without
it is closed, and hears neither the keys typed nor anything else. The key
and the keys typed still cross the network unencrypted, so keep the helper
on a network you trust.

What it does: a scan listens for 6 seconds and lists the devices with a name,
strongest first, after `Mesen PC keyboard`, as the firmware keeps them: 8
at most, names cut to 24 bytes. Any device with a name is listed, keyboard or not. A pairing pairs,
trusts and connects the one chosen. If it shows a passkey, the helper
confirms it and the bridge logs it (the nesp32 has no screen for it). Forget
removes it. The keyboard's address is kept in the helper's `~/.nesp32-bt`
and in the bridge's `--data` directory, and only that keyboard is read. The
helper grabs it, so it types nothing on the Pi. It has no loops that spin:
it waits on its sockets and the keyboard, and looks for a missing keyboard
every 10 seconds.

Not done: the helper is not a service (start it by hand, or write the unit),
its port has a key but no encryption (keep it on your LAN), and one paired
keyboard at a time.

## Known limits

- **PEER** (the online games for two) is not emulated yet.
- **Save states and rewind** are not supported: the nesp32's state is in
  the bridge, not in Mesen. A reset, a loaded state or a rewind is a
  console with a fresh nesp32, whose link starts again.
- **Turbo A**: NESradio's A both plays and stops a station, so Turbo A
  (Mesen's default for the keyboard is X; plain A is S) plays it and stops
  it a frame later. Tap plain A.
- **The Wi-Fi** is always joined, to a network named `Mesen`; a scan finds
  that one, and a join of any network succeeds.
- **Timing**: Mesen runs the console as fast as it can, and the bridge
  answers as the firmware would, but over TCP: a bridge on another
  computer works, and a slow network makes the emulator wait.

## Tests

`tests/test_mesen.py`, in `make test`: the keyboard's reports to
characters, held to `keyboard.c`; real Bluetooth with a fake helper; pairing, forgetting and typing through
the firmware's own KBD; a ROM's files kept and loaded again; fetches,
with the test as the site; and the bridge stopping once no Mesen is
connected (`--exit-when-idle`).

## Running a ROM with no window

`tools/mesen_run.py` runs a ROM in Mesen's `--testrunner` mode (no window,
as fast as it goes), holds controller 1's buttons on the frames it is told,
and keeps the picture and the 2 KB of RAM at the end of chosen frames:

```sh
python3 tools/mesen_run.py build/web/nesp32.nes \
    --press 200:down:3 --press 230:down:3 --press 270:a:3 --shot 400 --ram 400
```

The files go in `build/mesen-run`. It is for the picture, sound and mapper
timing that the py65 consoles in the apps' tests leave out. With no bridge
a nesp32 ROM stops at WAITING FOR LINK; `--bridge` (after `make host`)
starts `nesp32_bridge.py` on a free port and runs `nesp32.lua` ahead of the
runner's own script, so the programs reach the Internet as above, and the
bridge's log is `bridge.log` beside the shots. Mesen runs faster than real
time with no window, so a stream's sound has gaps in the log. `MESEN` names the
program (default: `/Applications/Mesen.app`). Tried with MesenCE on macOS.

`tools/png_diff.py A.png B.png [--out DIFF.png]` says which pixels of two
shots differ (and draws them in red), to hold two ROMs to the same picture.
With the same buttons, Contra's netplay ROM with no session is the
original 3 frames on: its frame 1097 and the original's 1100 differ only
where the buttons came at different points of the game.

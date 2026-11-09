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

## Setting up

### 1. The bridge

It needs Python 3 and a C compiler for the firmware's code: Linux, macOS,
or WSL on Windows. From the top of this repository:

```sh
make host                    # on Linux: make host CC=clang
python3 host/mesen/nesp32_bridge.py
```

It listens on port 7878 (`--port`), on every address of the computer. Run
it on the computer Mesen is on, or on another on the network; then set
`BRIDGE_HOST` at the top of `nesp32.lua` to that computer's address. In
WSL 2 the bridge is reached from Windows at `127.0.0.1` as it is.

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

**Scroll Lock** or **End** turns typing mode on and off (`TYPING_KEYS`).
Mesen shows it at the bottom of the screen, with a word when no keyboard
is paired or the program asks for none. In typing mode every key goes to
the nesp32, and none to controller 1 or to the nesp32's buttons; the
cartridge's programs take the arrows, Enter and Escape as the
controller's buttons anyway (PROTOCOL.md, KBD). `PAD_WHILE_TYPING = true`
leaves controller 1 its keys as well.

To pair: Setup's **BLUETOOTH**, then **PAIR DEVICE**, and A on
`Mesen PC keyboard`. To try it: typing mode, and type on Setup's
**TYPE HERE** line, in Weather's zip code, NESpedia's search, or
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
   is what the nesp32 gets. The computer's keyboard (Mesen's `K` reports) is
   ignored in this mode, not merged.

On the Pi (BlueZ running, `sudo apt-get install python3-evdev`):

    nice python3 nesp32_bt_helper.py --port 7980

On the bridge's machine, add `--bt-helper PI_ADDRESS:7980`. Without the flag
nothing changes.

What it does: a scan listens for 6 seconds and lists the devices with a name,
strongest first, as the firmware keeps them: 8 at most, names cut to 24
bytes. Any device with a name is listed, keyboard or not. A pairing pairs,
trusts and connects the one chosen. If it shows a passkey, the helper
confirms it and the bridge logs it (the nesp32 has no screen for it). Forget
removes it. The keyboard's address is kept in the helper's `~/.nesp32-bt`
and in the bridge's `--data` directory, and only that keyboard is read. The
helper grabs it, so it types nothing on the Pi. It has no loops that spin:
it waits on its sockets and the keyboard, and looks for a missing keyboard
every 10 seconds.

Not done: the helper is not a service (start it by hand, or write the unit),
there is no encryption or authentication on its port (keep it on your LAN),
and one paired keyboard at a time.

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
the firmware's own KBD; a ROM's files kept and loaded again; and fetches,
with the test as the site.

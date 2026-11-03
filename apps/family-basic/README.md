# Family BASIC

Family BASIC V3 (NS-HUBASIC V3.0, Nintendo, Sharp and Hudson's BASIC for
the Famicom) on a NES, typed on with a Bluetooth keyboard. The Famicom's
own keyboard plugs into the Famicom's expansion port, which a NES has none
of; here a [nesp32](../..) on controller port 2 has the keyboard (its KBD
service), and the game reads what is typed on it as if from its own.

## Status

**A prototype, working on hardware**, on the MiSTer and on an EverDrive
N8: a hello world program typed in on a Bluetooth keyboard through a
nesp32, and run; the characters, signs and shifted signs typed as
themselves, small letters as capitals; Backspace, the arrows, editing a
line on the screen, Page Up (CLR HOME) and Page Down (INS); programs
listed and run, and Escape (STOP) breaking one; a program
kept over the reset button on the MiSTer, and over a reset to the N8's
menu after `SYSTEM` (Keeping a program). The N8 started nothing of the
first builds, a grey screen; it starts this one, which no longer counts on
how the MMC1 comes up at power-on (How it works). On py65, against nesp32's
own firmware code over a line that models every bit, with the test as the
keyboard: BASIC starts, lines typed are run, a program typed in lists and
runs, every sign the keyboard has comes out as itself, Backspace and the
arrows edit, Escape stops a running program, the reset button keeps the
keyboard, and with no nesp32 BASIC still starts.

| Part | State |
|---|---|
| The ROM (`build/fbasic.nes`): the game on an MMC1, the keyboard's code in the cartridge's memory | done; tested on py65 against nesp32's KBD |
| Characters typed on a Bluetooth keyboard, as keys of the Family keyboard | done for every character it has a key for, Enter, Backspace, the arrows and Escape; tested on py65 |
| BASIC's memory, `$6000-$6FFF`, kept apart from the keyboard's code at `$7000` | done; tested on py65 with BASIC's memory full |
| The nesp32's own screen: "NES: Family BASIC" for the hello's `FBAS` | done in `firmware/main/main.cpp`; not yet built |
| Real hardware: an MMC1 with 8 KB of battery-backed memory, a StickS3 and a keyboard | working on the MiSTer and on an EverDrive N8 |
| The Family keyboard's keys that KBD does not send | not started (see Not done) |
| SAVE and LOAD to the nesp32's flash, in place of the data recorder | not started (see Not done) |

## Building

The game is not in this repository. Put a copy of Family BASIC V3 in
`baserom.nes` (iNES, 40976 bytes; `tools/fbasic.py` checks its SHA-1), or
say where it is with `BASEROM=`.

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler,
Python 3, and nesp32, the top of this repository.

```sh
make            # build/fbasic.nes (MMC1, mapper 1: 64 KB PRG, 8 KB CHR, 8 KB battery RAM)
make test
```

## Using it

With a keyboard paired to the nesp32 (in [Setup](../setup)) and the
nesp32 on controller port 2, start `build/fbasic.nes`. The keys type what
is printed on them, in capitals: the game has small letters only in kana.

| Key | On the Family keyboard |
|---|---|
| Letters, digits, and `! " # $ % & ' ( ) * + , - . / : ; < = > ? @ [ ] ^ _` | the key that types that character, with SHIFT if it takes it |
| `\` | `¥`, where the game has it |
| Enter | RETURN |
| Backspace | DEL |
| the arrows | the cursor keys |
| Escape | STOP: it stops a running program, and at the prompt leaves the line for a new one, as STOP does |
| Page Up | CLR HOME (SHIFT and CLR HOME, which clears the screen, is not yet to be had) |
| Page Down | INS |

`{ | } ~` and the backquote have no key, and Tab none: they are dropped. The
game types over what is under the cursor; INS opens a space.

## Keeping a program

BASIC keeps a program over the reset button by itself (`BASIC HOT
START`): it marks its start in the console's own memory, which a reset
leaves alone. Over a power-off, or a flash cartridge's reset to its menu,
which clear that memory, it keeps it only if it was told to with
`SYSTEM`. The cartridge had a BACKUP switch that kept the game from
writing its memory; `SYSTEM` marks the program as kept and then asks for
the switch to be turned ON, and waits. A flash cartridge has no such
switch, so: type `SYSTEM`, press Escape (STOP) at its message, and then
switch off or reset. BASIC finds the mark when it next starts, and has the
program back (`BASIC HOT START`). The mark is used up then: `SYSTEM` again
before the next power-off. The cartridge's memory must still be kept by
its battery, or saved to the flash cartridge's card.

## How it works

The game is a 32 KB NROM, and full: there is no room in it for the link.
So the ROM is an MMC1 with twice that, and the game, unchanged but for 28
bytes, is its first 32 KB. The second has `nes/fbkbd.s`, whose `boot`
copies the code into `$7000-$7FFF`, sets the MMC1 to give the game all 32
KB of its own, and starts the game's own reset (`BASIC HOT START` after
the reset button, with the program kept). The game's memory is the 4 KB
at `$6000` (`4086 BYTES FREE`); filled up, it never writes past `$6F5D`,
and the tests hold it to that.

An MMC1 is meant to have its last 16 KB at `$C000` at power-on, and that
is where `boot` is. A board whose registers come up at 0 has the game's
32 KB instead, and the game's reset vector; so that vector is changed to
`reset_stub`, which is at the same place in the game's first 16 KB and in
ours, and resets the MMC1 (the last 16 KB at `$C000`) and goes to `boot`.
The reset button goes the same way. Before the cartridge's memory is
used, `boot` clears bit 4 of the PRG register, which turns an MMC1B's
memory off, and of both CHR registers, which turns an SNROM board's off,
as a flash cartridge may copy. The first builds set the CHR registers
only after the copy, and a board that came up with their bit 4 set had no
code at `$7000`; the N8 gave them a grey screen, and starts this one. The tests start the ROM with the registers each of
these ways, and with the memory turned off by bit 4.

`tools/build_rom.py` changes these of the game's bytes
(`tools/fbasic.py`'s `PATCH_SITES`, each checked against the game first):

| Where | What the game did | What it does |
|---|---|---|
| `$FFFC` | its reset vector, `$80BA` | `reset_stub`, which goes by `boot` to `$80BA` |
| `$B95E` | the rest of its keyboard scan | `reset_stub` |
| `$80CD`, `$80D1` | its reset put its NMI handler's address, `$8971`, in the jump at `$00ED` | puts `fb_nmi`'s, which runs the game's handler and then the link |
| `$B958` | scanned the keyboard's 9 rows into its matrix at `$0634` | `fb_scan` copies the matrix the NMI made, and the game reads it at `$B9A1` as it did its own |
| `$883A` | while a program ran, read the STOP key alone | `fb_stop` reads it from that matrix |
| `$AD15` | read a controller, and left OUT0 low | `fb_pad` does the same and leaves OUT0 at mark, where the line to the nesp32 rests |

Every exchange with the nesp32 is made in the NMI, after the game's
handler: a hello for KBD, and then KBD KEYS, every other frame while the
game is waiting for a key and every eighth while a program only looks for
STOP. The nesp32 sends characters; each is put into the matrix as the key
that types it, with SHIFT if it is shifted, and kept down until the game
has scanned it twice and a frame has passed, then up until it has scanned
it twice more. That is about four frames a character, 15 a second. Which
key types what is read out of the game's own tables at `$BAA9` and `$BAF1`
when it is built (`tools/gen_keys.py`).

A KEYS with nothing typed takes about 5000 cycles of a frame, with the
nesp32's time to answer, so the link costs a waiting BASIC about 8% of the
console's time. With no nesp32, a hello is tried once a second, and each
one unanswered costs the frame a receiver's wait.

## Not done

- **More on hardware.** Not yet tried: a long program typed fast, a key held down (KBD repeats 25
  times a second and the ROM types 15, so the repeats may run on after the
  key is let go), and BASIC with no nesp32. Not yet measured: the time to
  type a character on a real console, the 5000 cycles a KEYS takes with a real
  nesp32's time to answer, and the keyboard's wait to type again after it
  sleeps (nesp32's `docs/TODO.md`).
- **The keys KBD does not send.** F1 to F8 (which type BASIC's own
  words), GRPH and KANA (the game's graphics and kana), CTR, CLR HOME and
  INS on keys of their own, SHIFT with CLR HOME (which clears the
  screen), and Delete, Home and End. Each wants a code from the nesp32's
  firmware, among those below `$20` that KBD KEYS does not use
  (`proto/nesp.toml`'s `enums.KEY`), and a line in `tools/gen_keys.py`:
  every program that takes KBD would see them, so each must be checked to
  pass over a code it does not know. Or, for a keyboard laid out as the Family's,
  an op that sends which keys are down and not characters; that would
  also let a program hold a key, which characters cannot.
- **SAVE and LOAD to the nesp32's flash.** The game saves to and loads
  from a data recorder on the Famicom's expansion port, which a NES does
  not have. Its routines are at about `$BDE7-$BFCD` (the reads of bit 1
  of `$4016`, the writes at `$BFBA`) and are untouched. In their place: a
  service on the nesp32 that keeps a program, by name, as a file in its
  filing system, and the game's SAVE and LOAD (and perhaps FILES) sending
  it the 4 KB at `$6000` in pieces, as the other services' requests do.
  About 2 KB of `$7000-$7FFF` is still free for its code (`build/fbkbd.map`).
- **The cost to a running program.** While a program runs, KEYS is asked
  for every eighth frame, for STOP; a program that reads the keyboard
  (INKEY$) has it every other frame, about 8% of the console's time. The
  game's own scans are not slowed, as they read a matrix in memory.
- **Kana and small letters.** A small letter is typed as its capital,
  since the game has small letters only in its kana modes; nothing types
  kana.
- **On nesp32's cartridge.** The cartridge's MMC1 has no memory at
  `$6000`, which both the game and this need.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`make test` does the same, with nesp32's Python if it has one. They need
cc65 and a copy of the game in `baserom.nes` (or `BASEROM=`), and skip
without either. The console and the serial line are nesp32's own tests'
(`../../tests/console.py`, `wire.py`); `tests/basic.py` adds what more of
the PPU the game uses, reading the nametable back, and times the link's
part of each NMI, which comes after the game's handler has returned.
The test is the keyboard: what it types goes to nesp32's KBD, and the
screen is read back as text.

## What is where

| Path | Purpose |
|---|---|
| `nes/fbkbd.s` | power-on, and the code in the cartridge's memory: the NMI, the link, and the matrix |
| `nes/mmc1.cfg` | where the linker puts it: the PRG's second 32 KB, its code kept at `$D000` and run at `$7000` |
| `tools/fbasic.py` | what is known of the game: its checksum, its keys' tables, and the bytes changed |
| `tools/gen_keys.py` | `build/keys.inc`: for each character, the key that types it |
| `tools/build_rom.py` | the game, its bytes changed, and the second 32 KB, as an MMC1 |
| `tests/` | the ROM on py65 against nesp32's firmware, with the test as the keyboard |
| `requirements-dev.txt` | what the tests need |

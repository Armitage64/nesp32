# Family BASIC

Family BASIC V3 (NS-HUBASIC V3.0, Nintendo, Sharp and Hudson's BASIC for
the Famicom) on a NES, typed on with a Bluetooth keyboard. The Famicom's
own keyboard plugs into the Famicom's expansion port, which a NES has none
of; here a [nesp32](../..) on controller port 2 has the keyboard (its KBD
service), and the game reads what is typed on it as if from its own.

## Status

**A prototype, working on hardware**, on the MiSTer and on an EverDrive
N8, with a StickS3 and a Logitech MX Keys S. Tried there, on one or the
other:

- programs typed in, listed, edited and run, and Escape (STOP) breaking
  one;
- every character and sign, shifted ones too, typed as itself, and small
  letters as capitals; a long line typed fast, every key in its place;
- every key in Using it: Backspace and Delete, the arrows, Home, Shift and
  Home, Insert, Page Up and Page Down, F1 to F8, F12 (KANA), and Ctrl
  (CTR) and Alt (GRPH) with a key;
- a key held down repeating at the game's pace, and stopping when it is
  let go;
- a program kept over the reset button on the MiSTer, and over a reset to
  the N8's menu after `SYSTEM` (Keeping a program);
- BASIC with no nesp32.

SAVE and LOAD to the nesp32's flash, in place of the data recorder, work
on the MiSTer and on a real NES: a program saved, the console reset, and
the program loaded again (Saving and loading).

The N8 started nothing of the first builds, a grey screen; it starts this
one, which no longer counts on how the MMC1 comes up at power-on (How it
works). Of BASIC's own, `GAME 0` (F1) wants the Famicom's microphone, so
only its demo plays (Using it). On py65, against nesp32's own firmware
code over a line that models every bit, with the test as the keyboard,
the tests hold the ROM to all of this but the microphone (Tests).

| Part | State |
|---|---|
| The ROM (`build/fbasic.nes`): the game on an MMC1, the keyboard's code in the cartridge's memory | done; tested on py65 against nesp32's KBD |
| Characters typed on a Bluetooth keyboard, as keys of the Family keyboard | done for every character it has a key for, Enter, Backspace, the arrows and Escape; working on hardware |
| BASIC's memory, `$6000-$6FFF`, kept apart from the keyboard's code at `$7000` | done; tested on py65 with BASIC's memory full |
| The nesp32's own screen: "NES: Family BASIC" for the hello's `FBAS` | done in `firmware/main/main.cpp`, and in the firmware on hardware; not yet looked for on the screen |
| Real hardware: an MMC1 with 8 KB of battery-backed memory, a StickS3 and a keyboard | working on the MiSTer and on an EverDrive N8 |
| The Family keyboard's other keys: F1 to F8, KANA, CTR, GRPH, CLR HOME, INS, and a Delete | done, with the firmware's KBD KEYS_ALL; working on hardware |
| SAVE and LOAD to the nesp32's flash, in place of the data recorder | done, with the firmware's TAPE: working on the MiSTer and a real NES, and tested on py65; BG GRAPHIC's not tried |

## The patch, for players

To play, there is no need to build anything. `dist/fbasic.bps` is the ROM
as a patch to Family BASIC V3: apply it to your own copy of the game with
any BPS patcher (Floating IPS, or RomPatcher.js in a browser), and put the
ROM it makes on a flash cartridge or the MiSTer. A BPS patch knows the ROM
it is for, and a patcher refuses any other: Family BASIC V3 with its iNES
header, 40976 bytes, CRC32 `667F6EA6` (the SHA-1 `tools/fbasic.py`
checks). The nesp32 needs its firmware from the same release.

There is no IPS patch. The game's 8 KB of CHR comes after its PRG in the
file, and the ROM's PRG is twice the game's, so the CHR is further on in
the ROM than in the game: the BPS patch copies it from the player's own
copy, and an IPS patch, which cannot copy, would have to hold it. The
patch holds none of the game: what it carries is the second half of the
PRG, which is this ROM's own (and mostly empty), the 46 bytes changed in
the game's (How it works), and the header. `tools/gen_patch.py` (at the
top of this repository) refuses to write a patch that carries sixteen
bytes in a row of the game's; and `tests/test_patch.py` holds the patch to the ROM this tree
builds: after a change to the ROM, `make bps` writes it again.

## Building

The game is not in this repository. Put a copy of Family BASIC V3 in
`baserom.nes` (iNES, 40976 bytes; `tools/fbasic.py` checks its SHA-1), or
say where it is with `BASEROM=`.

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler,
Python 3, and nesp32, the top of this repository.

```sh
make            # build/fbasic.nes (MMC1, mapper 1: 64 KB PRG, 8 KB CHR, 8 KB battery RAM)
make test
make bps        # dist/fbasic.bps again, for players (The patch, above)
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
| Delete | the character under the cursor: the cursor right, then DEL |
| Home, and Page Up | CLR HOME: the cursor to the top of the screen |
| Shift and Home | SHIFT and CLR HOME: the screen cleared |
| Insert, and Page Down | INS: a space opened under the cursor |
| F1 to F8 | F1 to F8: the game's words for them, which `KEY` changes. As it starts, F1 to F4 are `GAME 0` to `GAME 3`, F5 `SPRITE`, F6 `LOAD` (the first program on the nesp32: Saving and loading), F7 `LIST` and F8 `RUN`, each with RETURN but F5. `GAME 0` is played with the Famicom's microphone (it waits on bit 2 of `$4016`, which a NES's never changes), so only its demo plays: N to `PLAY ? Y/N` |
| F12 | KANA: kana on, or off. In kana the keys type their kana, as on the Family keyboard |
| Ctrl and a key | CTR and that key: a control code, as CTR and L clears the screen |
| Alt and a key | GRPH and that key: in kana, the game's graphic for it (out of kana the game types nothing for it) |

`{ | } ~` and the backquote have no key, and Tab and End none: they are
dropped. The game types over what is under the cursor; INS opens a space.

## Saving and loading

`SAVE "NAME"` keeps the program as a file on the nesp32, and `LOAD
"NAME"` has it back, after a power-off too, as the data recorder did:

```
SAVE "HELLO"
WRITING HELLO
OK
NEW
OK
LOAD "HELLO"
LOADING HELLO
OK
```

`LOAD` with no name has the first program the nesp32 has, and `LOAD?
"NAME"` checks the program in memory against the file. A SAVE of a name
there is already a program of is in its place. Where the tape would have
gone on looking, or a SAVE could not be written, the game says `?TP
ERROR`: no such file, a nesp32 that does not answer, or one whose
firmware is from before SAVE and LOAD (the keyboard works with it still).
BG GRAPHIC's own SAVE and LOAD keep its screen the same way.

The files are in `basic` on the nesp32's drive (lent to a computer from
Setup), `HELLO.fbp` for a program and `HELLO.fbg` for a screen: the
blocks as the game would have written them to tape. One copied there from
a computer loads by its file's name. A program is up to 4 KB: one of 4000 bytes
loads in 0.9 s on py65's line, and saves in about as long, with the
nesp32's time to write its flash besides. The nesp32's protocol has the details (TAPE, in
`docs/PROTOCOL.md`).

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
before the next power-off.

To start BASIC as from power-on, without switching off: `POKE &H9E,0`,
and the reset button. The game's reset takes the hot start when `$9E`, in
the console's memory, holds `$59`, and otherwise, with no `SYSTEM` mark,
starts afresh (`4086 BYTES FREE`). After a `SYSTEM`, `POKE &H6001,0` too. The cartridge's memory must still be kept by
its battery, or saved to the flash cartridge's card.

## How it works

The game is a 32 KB NROM, and full: there is no room in it for the link.
So the ROM is an MMC1 with twice that, and the game, unchanged but for 46
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
| `$BF1F`, `$BF30` | wrote a header block and a data block to tape | `fb_save_header` and `fb_save_data` send them to the nesp32 (TAPE PUT and SAVE) |
| `$9D9C` | SAVE's jump to the second | `fb_save_program`: the same, and `?TP ERROR` if the file was not kept |
| `$BE53` | read a header block from tape, for LOAD | `fb_find_program` asks the nesp32 for the program of the name (TAPE FIND), and reads its header |
| `$C56D` | BG GRAPHIC's call of the same | `fb_find_screen`: a pair of its screen, by the page |
| `$BE24`, `$BE1C` | read a data block, or checked one against memory (LOAD?) | `fb_load_data` and `fb_check_data` read it from the nesp32 (TAPE GET) |

Every exchange with the nesp32 is made in the NMI, after the game's
handler: a hello for KBD, and then KBD KEYS_ALL, every other frame while the
game is waiting for a key and every eighth while a program only looks for
STOP, and only once the game has had every key of the last reply. The
nesp32 sends characters; each is put into the matrix as the key
that types it, with SHIFT if it is shifted, and kept down until the game
has scanned it twice and a frame has passed, then up until it has scanned
it twice more. That is about four frames a character, 15 a second. A key
held down on the keyboard repeats faster than that, 25 times a second,
but the nesp32 keeps a repeat only once everything before it has been
taken, so it repeats as fast as the game types it. (Before the firmware
did that, a key held down on hardware ran on after it was let go, with
the repeats queued up; the tests hold a key for 3 s, with the firmware's
repeats modelled, and one or two more come after it at the most.) Which
key types what is read out of the game's own tables at `$BAA9` and `$BAF1`
when it is built (`tools/gen_keys.py`).

SAVE and LOAD are made where the game's tape routines were, which turn
the NMI off for as long as they take, so their exchanges are made there,
outside the NMI, with the zero page the link needs borrowed as the NMI's
link borrows it. Each takes what the game's routine took and gives back
what it gave, so the game does the rest as it did with a tape: the
messages, the checks of the name and the type, and what is done with a
program once it is in memory. A block goes in pieces of 120 bytes, each
sent again until it is answered, eight times at the most; a SAVE or a FIND
is asked again until it has ended, 2048 times at the most, which is eight
seconds and more of the nesp32 not answering while it writes or reads its
flash. The tape's own `LOAD` of a
name it had not got to went on looking until STOP; here a name the nesp32
has no file of is `?TP ERROR` at once, and so is a nesp32 that is not
there.

A KEYS with nothing typed takes about 5000 cycles of a frame, with the
nesp32's time to answer, so the link costs a waiting BASIC about 8% of the
console's time. With no nesp32, a hello is tried once a second, and each
one unanswered costs the frame a receiver's wait.

## Not done

- **More on hardware.** Not yet measured: the time to type a character
  on a real console, the 5000 cycles a KEYS takes with a real
  nesp32's time to answer, and the keyboard's wait to type again after it
  sleeps (nesp32's `docs/TODO.md`).
- **The time a SAVE takes on hardware**, with the nesp32 writing its
  flash while the console waits: not measured.
- **GAME 2 after a STOP.** Started with F3 (`GAME 2`) it plays; stopped
  with Escape and started again with `RUN`, after a reset to `BASIC HOT
  START` or after a SAVE and a LOAD, it says GAME OVER within a couple of
  seconds, most times. The program in memory is the same, so `GAME` must
  set up something more than it that `RUN` does not; whether a Famicom
  does the same, or the cause is here, is not known.
- **BG GRAPHIC's SAVE and LOAD.** They go the same way, a pair of blocks
  for each of the screen's four pages, and the nesp32's side of that is
  tested; the game's side is not, as BG GRAPHIC is reached through
  `SYSTEM`'s wait for the BACKUP switch, which the tests cannot turn.
- **A list of the files.** The game has no FILES; `LOAD` of a name not
  there could list what is (the tape's `SKIP` messages), or a key could.
  For now the drive, lent to a computer, is the list.
- **STOP during a SAVE or a LOAD**, which the tape's routines took. Here
  the NMI is off, and the keys come in it.
- About 1.3 KB of `$7000-$7FFF` is still free (`build/fbkbd.map`: the
  code and its memory end at `$7AF8`).
- **The cost to a running program.** While a program runs, KEYS is asked
  for every eighth frame, for STOP; a program that reads the keyboard
  (INKEY$) has it every other frame, about 8% of the console's time. The
  game's own scans are not slowed, as they read a matrix in memory.
- **Small letters.** A small letter is typed as its capital, since the
  game has small letters only in its kana modes.
- **The microphone.** Controller II of a Famicom has one, which BASIC reads
  as bit 2 of `$4016` (`PEEK(&H4016) AND 4`), as `GAME 0` does. A key held
  down could stand for it, by a change to the game's PEEK (`$A978`) for
  `$4016`. Left alone for now.
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
| `nes/fbkbd.s` | power-on, and the code in the cartridge's memory: the NMI, the link, the matrix, and SAVE and LOAD |
| `nes/mmc1.cfg` | where the linker puts it: the PRG's second 32 KB, its code kept at `$D000` and run at `$7000` |
| `tools/fbasic.py` | what is known of the game: its checksum, its keys' tables, and the bytes changed |
| `tools/gen_keys.py` | `build/keys.inc`: for each character, the key that types it |
| `tools/build_rom.py` | the game, its bytes changed, and the second 32 KB, as an MMC1 |
| `tests/` | the ROM on py65 against nesp32's firmware, with the test as the keyboard, and the patch held to the ROM |
| `dist/fbasic.bps` | the ROM as a patch to the game, for players (`make bps`) |
| `requirements-dev.txt` | what the tests need |

# Tecmo Super Bowl, two consoles

A netplay build of Tecmo Super Bowl (US, NES), in progress: a two-player
game on two consoles, each with a [nesp32](../..) on controller port 2.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
netplay games share.

**Where it stands.** The game builds from its disassembly with ca65, and
the original matches the ROM byte for byte. The netplay ROM's session is
done and tested in the simulation: two consoles, each with nesp32's
firmware, play the same game tick by tick from a session's start through
the menus to a preseason game, MAN VS MAN, and on into play. There is no
menu yet (Select at the title goes to a stub that leaves the console
stuck: don't press it), the save RAM is not yet
made the same on both consoles, and nothing has been tried on hardware.
"To do", at the end, is where to pick it up.

**The game is not in this repository.** Whoever builds puts a copy of
it, the US release, in this directory as `baserom.nes` (or says where it
is with `BASEROM=`); `make verify` checks what is built against its
SHA-512.

```sh
git submodule update --init third_party/Tecmo_Super_Bowl_NES_Disassembly
make            # build/tsb.nes, the original, and build/tsb_net.nes
make verify     # the original matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make patches    # patches/ again, from what has been changed in build/src
make import     # tools/game.map again, from the disassembly (needs asm6f)
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
tests run the ROM against nesp32's firmware built for this computer. The
tests take some minutes each: `make test PYTHON=../../.venv/bin/python`.

## The source

The disassembly ([bruddog's](https://github.com/bruddog/Tecmo_Super_Bowl_NES_Disassembly),
`third_party/Tecmo_Super_Bowl_NES_Disassembly`) is complete and commented,
but it is asm6f source, and its macros are more than ca65 can take as
they are: some choose an instruction by how far away a label is that
comes later. So it is not converted line by line.

- `tools/import.py` assembles the disassembly once with asm6f and reads
  its listing, macros and all, into `tools/game.map`: where each 8 KB bank
  sits, which bytes are instructions, every label, the value of every
  other name, each instruction's operand as the disassembly writes it,
  and the comments. Addresses, names and comments only: none of the
  game's bytes. Only `make import` needs asm6f
  ([freem/asm6f](https://github.com/freem/asm6f), built from its one C
  file), and only when the disassembly changes; the map is committed, and
  making it again makes the same file.
- `tools/convert.py` makes ca65 source of `baserom.nes` with the map, in
  `build/gen`. Each instruction is decoded from the ROM, with its
  addressing mode as it is there; its operand is the disassembly's
  expression where that comes to the same value (27,690 of 37,427), and a
  number where it does not. Each label asserts its address, which ld65
  checks, so a change that moves any of the game does not link. Each run
  of 32 bytes or more of $00 or $FF that is not code is a label,
  `FREE_b_aaaa` (its 8 KB bank and address), that a netplay build can fill
  with a macro.

asm6f's local labels belong to the stretch between two other labels, as
ca65's cheap locals do, but asm6f counts the disassembly's `_F{` folding
markers, which are not written out. A local used outside the stretch ca65
gives it is given a name of its own, defined at the end of the file as an
offset from a label: in ca65 a label, `X = *` and `X := *` all end a
stretch.

The source is copied to `build/src`, and `patches/` puts the netplay's
lines into the copy, all under `.ifdef NETPLAY` and each the same length
as what it replaces. Change `build/src`, then `make patches`, then `make`
before changing it again (`make patches` can make the copy again from the
old patches).

## How the game runs

All of the game's logic is eight tasks that its NMI runs
(`UPDATE_ALL_TASKS`, $CAEE): each sleeps for a count of frames, wakes,
runs, and sleeps again, on a stack of its own in page 1. The NMI writes to
the PPU (a buffer of writes, or a column of the field), runs the sound
engine, reads both controllers, steps the random numbers ($3B-$3D) and the
frame counter ($30), and then the tasks. The main thread is the
scheduler's idle loop (`CHECK_TASKS`, $CB4E).

A task that runs past the next NMI is broken into by it: the controllers
and the numbers change under it, and a task of more weight may be run in
the middle of it. In the simulation, a game for two lagged like that in
about 1% of its frames, mostly the sprites' sorting (task $25) and the
players' update ($20).

The cartridge is an MMC3 with 256 KB of PRG ROM, 128 KB of CHR ROM and
8 KB of save RAM kept by a battery. The game picks each 8 KB window on its
own and keeps what it picked in `SOFT_8000_BANK` and `SOFT_A000_BANK`;
the end of its NMI puts them back from there. The save RAM is full: the
season, the playbooks, the starters, the teams' control, the random
numbers' seed, and scratch for the menus. The game turns its writes on
and off ($A001) 158 times, and keeps them off but while it writes.

## The netplay ROM

**The cartridge** (`net/superbowl_net.cfg`, `patches/header.patch`): the
same board with twice the PRG ROM, 512 KB, and an NES 2.0 header. The
game's banks 0 to 29 are where they were, its fixed two are the last in
the file, and the netplay's are between: bank 30, the session and nesp32's
library, at $A000, and bank 31, the menu, at $8000. The fixed bank's hooks
(`net/cart.inc`) are in the 112 bytes the game leaves empty at $FF80 and
in place of an unused routine at $D05F.

**The memory** (`net/net_ram.inc`). The game leaves no run of the
console's RAM alone, so the session keeps its memory in the save RAM's 142
bytes past the season ($7F72), which the game's checksum leaves out and
nothing writes. Before it writes there it finds out, by a byte of its own
($7FFF), whether the game had the writes on, and puts $A001 back as it
was. The three bytes the fixed bank's hooks look at in every NMI are in
the console's RAM, at $067D-$067F, which the disassembly has no name for
and the game was never seen to write. The library's zero page is the
game's `LOCAL_1` to `LOCAL_8` ($3E-$45), which a task keeps on its own
stack while it sleeps.

**An NMI in a session** (`net_nmi`, `net/net.inc`) is one of three things:

- **a lag**: the NMI came anywhere but the idle loop (or the reset's wait
  for a frame), or the idle loop has a task to run (one RUNNING, WAITING
  or CREATED). The NMI does what the game does when it finds the
  scheduler busy, the scroll and the screen's splits, and the task goes
  on where it was.
- **a tick**: every task asleep, and both players' buttons for this tick
  are here. The NMI is the game's, with the buttons the session gives it.
- **a stall**: every task asleep, and the other console's are not here.
  The tasks are not run, and nor are the controllers read or the numbers
  stepped.

So the game's state depends on the ticks and on nothing else. Getting
there needed more than the three cases:

- **The PPU's writes are the game's state too**: the tasks wait for the
  buffer of writes to be empty, and a column of the field drawn in an
  NMI takes the place of the buffer's writes in it. So the PPU has them
  once between two ticks, at the first NMI after a tick that is not a lag
  (`net_owed`), and the NMIs of a stall after that write only the sprites.
- **The exchange runs where the game's read was**, in the NMI, and the
  NMI's stack is the idle loop's 14 bytes at $01F2-$01FF, which the game's
  own NMI fits in; the first task's stack is below. So the exchange keeps
  the 40 bytes below it and `LOCAL_1` to `LOCAL_8`, in the save RAM at
  $6EFE, which the checksum leaves out, and puts them back.
- **A tick clears `TASK_BUSY_FLAG`.** Its low bits are what the idle loop
  has shifted out of it, once each time round, and the last of them is
  the carry a task wakes with (`UPDATE_CURRENT_TASK`'s LSR). How many
  times round the loop went depends on the frames.
- **The digest** the consoles swap every 256 ticks is of zero page $46-$EF
  and the sprites' page: not the library's zero page, nor the sound
  engine's ($F0-$FF).

**The line** is at 14 cycles a bit (`NET_RATE`): the game plays samples
(drums, and "hut" and "touchdown"), whose fetches made 10 too fast for
Jackal. The session's read of the controller reads twice while a sample
plays.

## The simulation

`tests/console.py` is River City Ransom's console on py65, with the save
RAM's $A001 as the MMC3 has it and a scheduler that leaves the NMI with no
RTI. `tests/netplay.py` is two of them, each with nesp32's firmware, and a
network between; `Table.to_game` plays from a session's start to the
kickoff of a preseason game, MAN VS MAN, Buffalo against Cleveland.

The two consoles' states are compared at the start of each tick, where
the game's NMI goes on into its tasks (`NMI_UPDATE_RANDOM_NUMS`), once the
exchange has put back what it borrowed. Left out (`UNKEPT`): the
library's zero page, the sound engine's memory, the interrupts' saves of
the registers and how far down the screen's splits the IRQ has got
($0300-$0306), the idle loop's stack, and in each task's stack what is
below the pointer it saved when it went to sleep.

`tests/test_lockstep.py`: from a session's start through the menus and
1500 frames of play at random, the same game at every tick, at 5 and 20 ms
each way.

## To do

In order. Each step is tested in the simulation before the next.

1. **The menu** (`net/menu.inc`, now a stub). Jackal's and RCR's lobby
   (HOST GAME, JOIN GAME by a room's code or an address, LOCAL GAME), in
   bank 31 at $8000 with the library at $A000. Select at the title opens
   it (`net_title_press`); the title's task sleeps, and the NMI is the
   menu's (`net_menu_nmi`). It ends with a reset, by a session or not, so
   it may use the game's RAM: $0500 on (not $0300, where the NMI saves the
   registers), and the sprites' page at $0200. The menu has to turn off the
   MMC3's IRQ and set the CHR banks for the title's letters (ASCII tiles).
   Tests: `test_menu.py` after RCR's.
2. **The save RAM the same on both consoles.** A session's two consoles
   must start with the same save RAM: the game reads its season, the
   playbooks, the starters, the teams' control and the seed of its random
   numbers from it. The tests pass now only because both simulated
   consoles start with the same, empty one. Decision 1, below.
3. **The rest of the game in a session**: the season (and its schedule,
   SKP mode, the playoffs), the Pro Bowl, TEAM DATA's changes, a game
   played to its end and the screens after it, the pause (timeouts), and
   both players' Start at the title. Each with a lockstep test. Check that
   the game never picks a bank above 29 (`tests/test_console.py`, as RCR's).
4. **The frame rate.** The exchange costs some 2000 cycles at 14, and the
   stack and zero page it keeps some 1000 more, in each tick's NMI, which
   is time the tasks lose: measure the lags in a session against the
   original's 1%, with a bench like Jackal's (`make bench`).
5. **For players**: `make bps` and `dist/tsb_net.bps`, `tests/test_patch.py`,
   the hello's version, and every document that lists the games (the
   `nes-netplay-port` skill's "Shipping a change").
6. **Hardware**: two consoles and two nesp32s, by a room's code. Watch the
   screen's splits while an exchange holds the IRQ off (the play-call
   screen has them), and the samples against the line at 14.

## Decisions to make

1. **What save RAM a session starts from** (for To do 2). The link
   carries about two bytes a frame, and the save RAM the game reads is
   6-8 KB.
   - *The host's, copied to the guest* (proposed): the two compare a
     checksum at the session's start and copy only if they differ, run
     long, so a season early on (mostly zeros) takes seconds and a full
     one under a minute. Both play the host's season. The guest's save
     (of the netplay ROM, which a flash cartridge keeps apart from its
     Tecmo Super Bowl) becomes a copy of the host's.
   - *Always the game's defaults*: simpler, but a season cannot go on
     from one session to the next.
   - Also to settle with it: which of the save RAM is copied. The season
     ($66C0-$7F71, under the checksum) for certain; of $6000-$66BF, the
     teams' control (`TEAM_TYPE_SEASON`), the CPU boosts, the playbooks
     and the random seed (`SAVED_RANDOM_1`-`3`), but not the menus'
     scratch.
2. **Where a session begins.** Now at the reset, so the players see the
   intro and the title and press Start, as alone. Straight to the main
   menu would save a few seconds.
3. **LOCAL GAME and B in the menu** reset the console now (the menu uses
   the game's RAM), which shows the intro again. A mark through the reset
   could go straight back to the title instead.

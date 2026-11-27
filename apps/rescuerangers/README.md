# Chip 'n Dale Rescue Rangers for two consoles

Capcom's Chip 'n Dale Rescue Rangers (NES, 1990) is a game for two
played at once, on one screen. This is the start of its netplay ROM for
nesp32: each player on a console of their own, each console with a
nesp32 on controller port 2.

**There is no session yet.** What is here builds the original game from
source made from the ROM, byte for byte, and the game on the netplay ROM's
cartridge, an MMC3, which plays the same game as the original. All of it
was tried only in the simulation (py65); nothing here has been on a real
NES or in Mesen.

## Building

You need your own copy of the US release, as `baserom.nes` here. It is
not in the repository (`*.nes` is ignored).

```sh
make && make verify     # build/rescuerangers.nes, and its SHA-512 checked;
                        # build/rescuerangers_net.nes, on the MMC3
make test               # the simulation's tests
make trace              # tools/entries.txt again (some 5 minutes)
```

The ROM's SHA-512 is in the Makefile (`SHA512_ORIGINAL`); its SHA-1 is
`39a5fdb7efd4425a8769fd3073b00dd85f6cd574`.

There is no disassembly of the game to start from, so the build makes one,
as Bubble Bobble's and River City Ransom's do. `tools/trace.py` runs the
game on the simulated console and notes every instruction it runs
(`tools/entries.txt`); `tools/convert.py` follows the code from there and
from the names in `tools/game.map`, and writes ca65 source of the whole
ROM to `build/gen`, every byte from `baserom.nes`. None of the game is in
the repository: only addresses, names and comments. So far the trace has
played only the first level, for one player and for two, and has seen
6948 instructions: some 18 KB of the 128 KB of PRG ROM is known to be
code. The rest is written as bytes, which rebuild the ROM all the same.

## The cartridge

An MMC1 with 128 KB of PRG ROM in eight banks of 16 KB and 128 KB of CHR
ROM in 4 KB banks. The game keeps the last bank fixed at $C000 and
switches the others at $8000 (`SET_PRG`); the CHR banks by `SET_CHR0` and
`SET_CHR1`, or from the NMI. Each bank ends with the same reset stub at
$BFE0 and the vectors. It has no PRG RAM, and never touches $6000-$7FFF.

Free in the ROM: next to nothing. The runs of $00 of 64 bytes or more come
to some 1.6 KB, spread over banks 0 to 6, and none is in the fixed bank,
which has 48 bytes at $FFB0 that nothing seen runs or reads. Bubble
Bobble's netplay is some 5.2 KB.

So the netplay ROM is on another board: an MMC3 (mapper 4) with 256 KB of
PRG ROM, the game's 128 KB of CHR ROM, and 8 KB of PRG RAM, which its NES
2.0 header asks for (`net/cart.inc`, `net/rescuerangers_net.cfg`). An
MMC1 could not have taken more PRG ROM: with CHR ROM in 4 KB banks, the
bit that would pick the second 256 KB is the CHR bank's.

- **The banks.** The game's banks 0 to 6 are the MMC3's 8 KB banks two by
  two, R6 at $8000 and R7 at $A000, and its fixed bank 7 is the MMC3's
  last two, at $C000 and $E000: the last in the file. Banks 8 to 15 are
  new, between them. The game's CHR bank at $0000 is R0 and R1, and the
  one at $1000 is R2 to R5.
- **Netplay's code runs from the PRG RAM**, which the reset copies from
  the start of bank 8 before the game's own reset (`net_cart_start`, in
  the reset vector). The fixed bank has no room for it: `SET_PRG`,
  `SET_CHR0`, `SET_CHR1` and the NMI's switches are now a few bytes each
  that jump there, and `net_cart_start` is in the room `SET_PRG`'s MMC1
  writes left. Every change to the fixed bank is the length of what it
  replaces, so none of the game moves.
- **An NMI in the middle of a switch.** A write to an MMC3 register is
  two, a register picked at $8000 and its bank at $8001, and the NMI
  switches banks of its own: the CHR banks when the game asks, and bank 3
  for the sound engine. Each pick is kept in `net_select`, and the NMI
  (`net_nmi`, `net_nmi_leave`) puts back the one it found, so the switch
  it broke into goes on to the right register. `tests/test_cart.py`
  breaks into each of the three switches before each of its
  instructions. As in the original, `SET_PRG` keeps the NMI off bank 3
  while it switches and runs the sound engine after.
- **The reset's stub** at $FFE0 wrote to $FFE1 (an MMC1 reset); on the
  MMC3 that turns the scanline counter's IRQ on, so the netplay ROM's
  reads it instead. The game never lets an IRQ in (no CLI), and the
  simulation counts writes that would turn it on. One routine
  (`$D3E7`) writes to `$FFE8,y` and `$FFEA,y` with Y from $18 up, which
  wraps round to the RAM; a Y below $18 would write to the MMC3's IRQ
  registers.

With no session, the netplay ROM plays the same game as the original, tick
for tick, from power-on through a level for two (`tests/test_cart.py`),
but for `FRAME_COUNT`: the MMC3's switches take longer, and as the story's
screen comes up the netplay ROM takes one frame more, which leaves the
NMI's count of frames one ahead. Nothing seen so far reads it.

## The game, as far as it has been read

- **Tasks.** The game runs as up to four coroutines (`TASKS`, $80-$8F),
  each on its own stack in page 1. `SCHEDULE` runs the first that is
  ready; a task gives way by sleeping a number of frames (`TASK_YIELD`),
  and the NMI counts the sleeps down. In a level only task 0 was seen,
  sleeping a frame at a time.
- **The controllers** are read in one place, `CTRL_READ` ($C162), which
  `SCHEDULE` calls as it goes back to task 0: once a frame. It reads D0
  and D1 of both ports (a Famicom's expansion pads), into `PAD_HELD` and
  `PAD_PRESSED`. Each controller is read once.
- **No samples.** The reset writes 0 to $4010, and the sound engine only
  ever writes $0F to $4015: the sample channel is never on, so the
  "phantom Right" (`docs/PHANTOM-RIGHT.md`) cannot happen.
- **The NMI** ($C000) makes the PPU's writes and the OAM's DMA unless the
  picture is off, and then, in every NMI: counts `FRAME_COUNT`, counts
  down the tasks' sleeps, and runs the sound engine in bank 3. A bank
  switch under way when it comes leaves the sound engine to `SET_PRG`.
  No sprite 0 waits, no IRQ: the screen is not split.
- **The sound engine** keeps $C0-$D8 and $0700-$077F, and takes its
  orders from `SOUND_QUEUE` ($DB-$E3).
- **Random numbers**, it seems, at $E4-$E7: they change every frame, the
  pause's too.
- **The title**: Select moves the cursor between 1 PLAYER and 2 PLAYERS,
  Start picks and shows the story, Start again skips it to the first
  level. In a level, Start pauses.

On the simulated console, a level for two keeps the game busy for some
18000 to 20000 cycles of a frame's 29780 with the players standing still,
and a median of some 16000 with them moving at random; fewer than 1 frame
in 100 overruns. The link's exchange takes some 2500 to 4000 cycles
(`docs/MULTIPLAYER.md`), which leaves room.

## Not done

1. **`make ines`**, the netplay ROM with an iNES header for a cartridge
   that takes no NES 2.0, as Contra's.
2. **More of the game traced**: the zone map, the later zones, the
   bosses, a game over, the continue and the end, by poking in a zone as
   Bubble Bobble's trace pokes in a round.
3. **Where each task's stack is**, so the digest (`state()` in
   `tests/console.py`) can keep the live part of page 1 and leave out
   only the dead bytes. For now it leaves out the whole page.
4. **The session**: the exchange in the NMI after the PPU's writes, and
   `CTRL_READ` taking both players' buttons from the session. A tick is
   an NMI that finds the game idle in `SCHEDULE`. An NMI that finds a task
   at work must not count `FRAME_COUNT` or the sleeps down, or the game
   would depend on where the frames fell (the cartridge alone already
   moves `FRAME_COUNT`, above). The music goes on in every NMI.
5. **The menu** (the lobby) before the title, the digest and the dump of
   the RAM when the digests differ, and the hello's name and version.
6. **The tests** of two consoles in lockstep (`tests/netplay.py`, as
   Bubble Bobble's), `make bps`, and the documents that list the games
   (the nes-netplay-port skill, "Shipping a change").
7. **Hardware**: two consoles, each with a nesp32.

# Tecmo Super Bowl, two consoles

A netplay build of Tecmo Super Bowl (US, NES), in progress: a two-player
game on two consoles, each with a [nesp32](../..) on controller port 2.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
netplay games share.

**Where it stands.** The game builds from its disassembly with ca65, and
the original matches the ROM byte for byte. The netplay ROM's session is
done and tested in the simulation: two consoles, each with nesp32's
firmware, play the same game tick by tick from a session's start at the
main menu through all of the game: a preseason game played to its end in
each of the six ways to play, the timeouts, the season (TEAM CONTROL, a
season game for two, a week of the CPU's games skipped through, the
standings and the playoffs), the Pro Bowl and TEAM DATA, with the two
consoles' saves alike after each. The menu (NETWORK GAME at the title) hosts and
joins a game by a room's code or an address, and makes the two consoles'
saves the same, player 1's copied to player 2's when player 2 says yes,
all in the simulation. On hardware (November 2026, two consoles): the save's
copy and the season kept across a power-off work; the top of the screen
broke up in play and the music slowed with the lags, both put right since
in the simulation and not yet tried again ("What has been learned"). "To do", at the
end, is where to pick it up.

**The game is not in this repository.** Whoever builds puts a copy of
it, the US release, in this directory as `baserom.nes` (or says where it
is with `BASEROM=`); `make verify` checks what is built against its
SHA-512.

```sh
git submodule update --init third_party/Tecmo_Super_Bowl_NES_Disassembly
make            # build/tsb.nes, the original, build/tsb_net.nes, and
                # build/tsb_net_slow.nes, the netplay ROM with the game's
                # own routines where it has quicker ones ("Quicker routines")
make verify     # the original matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make bench      # the original's frames against a session's ("The frame rate")
make patches    # patches/ again, from what has been changed in build/src
make import     # tools/game.map again, from the disassembly (needs asm6f)
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
tests run the ROM against nesp32's firmware built for this computer. Each
test is a minute or more; with the repository's `.venv`, which has
pytest-xdist, they run on every core, the 32 of them in about 12 minutes:
`make test PYTHON=../../.venv/bin/python` here, or from the top of nesp32
`make test-apps APPS=superbowl`. They need the firmware of this branch,
whose PEER has the save's ops.

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
about 2% of its frames (`make bench`, "The frame rate"), mostly the
sprites' sorting (task $25) and the players' update ($20).

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
and the game was never seen to write, and the intro's mark is the byte
before them (`net_skip`, $067C). The library's zero page is the game's
`LOCAL_1` to `LOCAL_8` ($3E-$45), which a task keeps on its own stack
while it sleeps. Its frames, a reply of 64 bytes and a request of 66, are
in the save RAM the game leaves empty at $6EFE, past the stack the NMI's
exchange keeps there ($6F1E on).

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
  the 24 bytes below it and `LOCAL_1` to `LOCAL_8`, in the save RAM at
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

## The menu

`net/menu.inc` is River City Ransom's lobby (HOST GAME, and JOIN GAME by
a room's code or an address), in bank 31 at $8000 with the library at
$A000. The title has LOCAL GAME and NETWORK GAME in place of START GAME
(`net/title.inc`): its scene's script calls a subscript of ours for the
two lines (rows 18 and 20: above row 18 the title's last split has the
logo's CHR, and the stars' tiles are other pictures there), Up, Down and
Select move its stars between them through the game's PPU buffer, and
Start or A on NETWORK GAME opens the menu (`net_title_pick`); Start on
LOCAL GAME flashes it, where the game flashed START GAME. The title's loop
waits on, and the NMI is the menu's (`net_menu_nmi`), which the game's
tasks do not run in. Its question before a save is copied is CONTINUE:
the game's font has no question mark. Its first screen also says why
the last session was given up, if it was: LAST: GAMES DIFFERED (the
digests), OTHER STOPPED (`SILENT_FRAMES` with no tick) or OTHER LEFT (the
nesp32 says so). Before GAMES DIFFERED's reset, with the screen off, each
console sends its 2 KB of RAM to its nesp32 (`net_differ`, PEER's DUMP),
whose log has it in 32 lines: the first try waits out the nesp32's
return to the link's rate. Each console keeps it in the save RAM (`net_why`, with
the tick), and a session's start clears it: a console that stops on its
own keeps none. Below that, in hex, is where the last session NMI found
the console (row 27, `net_crumb`), and above it what the last two resets found
in the RAM before the game's reset cleared it (`net_resets`, To do 3). It
ends with a reset, by a session or not,
so it uses the game's RAM: $0500 on (not $0300, where the NMI saves the
registers) and the sprites' page at $0200. It turns off the MMC3's IRQ,
which splits the title's screen, and turns on the save RAM's writes, for
the library's memory. Its NMI is off while each of its frames is at work
(below, "The save"). B on its first screen goes back to the title.

Its letters are the game's: the font of its menus, CHR bank $20 at $0000,
has its letters, digits and full stop at their ASCII codes, and the menus'
borders, which the menu uses for its dash and for the mark under a letter
being edited. The cursor is the game's menu arrow, tile 0 of bank $0F at
$1000.

**Past the intro.** The menu leaves by a reset, and a reset plays the
intro. So a reset of the netplay's own (`net_drop`: the menu's B, a
session lost, a session's start) leaves a mark in the save RAM
(`net_skip_mark`), which `net_reset` takes into `net_skip`, in the
console's RAM, and clears. The intro's first wait for a frame
(`net_intro`, in the fixed bank) goes from there to the title, as the
intro's Start does, or, for a session, which both consoles begin from the
title, to the main menu, some 30 frames after the reset. A reset of the
console's, or a power-on, finds no mark, and the intro plays.

## The save

A session's two consoles must have the same save RAM: the game reads its
season, playbooks, starters, the teams' control and the seed of its random
numbers from it. The save (`SAVE_START` to `SAVE_END`, `net/net_ram.inc`)
is $6403 (`SAVED_RANDOM_1`) to the end of the season ($7F71), 6,763 bytes
but for the 260 the game leaves empty at $6EFE, which are the netplay's.
Before it, $6000-$6402 is the scratch of the game's scenes and sprites,
which is not compared or copied, and which a session's start clears on
both consoles.

When the nesp32s are connected, each console works out a CRC of its save
(some frames, with the NMI off) and sends it with PEER's SAVE (nesp32's
`docs/PROTOCOL.md`, "A game's save"). The same: the session begins. Not:
player 2's screen says that its save will be replaced by player 1's, YES
or NO, and player 1's says it is waiting for player 2. Meanwhile player 1
sends its save to the other nesp32, 64 bytes a frame (SAVE_PUT, about two
seconds at the link's rate), which keeps it. YES: player 2's console waits
until all of it is at its nesp32, and copies it into its save RAM, with
the NMI off (SAVE_GET, 64 bytes an exchange, about a second), says so
(SAVE_DONE), and both begin the session. NO, or B: player 2 hangs up, and
both are back at the menu's first screen.

The menu's NMI is off while a frame of it is at work (`menu_nmi_on`): the
game's NMI keeps the registers it saves in memory, and one that broke into
a frame of the menu that ran long (a SAVE_PUT and a SAVE in one) gave the
main thread back the wrong ones.

Between the nesp32s the save goes ahead of the session's ticks, on a
stream that now keeps a window of 2 KB in flight: some 0.2-0.5 s for the
save across a network with no loss, in nesp32's `tests/test_arq.py`.

## The simulation

`tests/console.py` is River City Ransom's console on py65, with the save
RAM's $A001 as the MMC3 has it and a scheduler that leaves the NMI with no
RTI. `tests/netplay.py` is two of them, each with nesp32's firmware, and a
network between; `Table.to_game` plays from a session's start to the
kickoff of a preseason game, MAN VS MAN, Buffalo against Cleveland. A test
may change both consoles' memory alike at a tick (`Table.at_tick`), or at
every tick from the next one neither console has taken
(`Table.every_tick`), as a change the game made itself would be.

The two consoles' states are compared at the start of each tick, where
the game's NMI goes on into its tasks (`NMI_UPDATE_RANDOM_NUMS`), once the
exchange has put back what it borrowed. Left out (`UNKEPT`): the
library's zero page, the sound engine's memory, the interrupts' saves of
the registers and how far down the screen's splits the IRQ has got
($0300-$0306), the idle loop's stack, and in each task's stack what is
below the pointer it saved when it went to sleep; and in the save RAM,
the netplay's own, and $6203-$621E, where the game's save of its state for
a scene keeps a copy of one task's stack, $0150-$016B, with whatever the
interrupts left below its pointer.

`tests/test_lockstep.py`: from a session's start through the menus and
1500 frames of play at random, the same game at every tick, at 5 and 20 ms
each way. `tests/test_menu.py`: the menu's screens and what it asks the
nesp32, and HOST GAME and JOIN GAME, by an address and by a room's code,
into a session that plays the same game on both; the same saves, and
different ones, with player 2's YES (its save becomes player 1's, and the
session is one game) and its NO. `tests/test_fast.py`: the netplay ROM's
quicker routines against `tsb_net_slow.nes` ("Quicker routines").
`tests/test_frame.py`: in a session's play, the screen's splits taken on
time, with replies misheard too, and the music in every NMI.

`tests/test_game.py`: a preseason game, MAN VS MAN, played to the fourth
quarter's whistle, its statistics, and A back to the main menu; a timeout
taken by each player from the play-call screen's menu; the preseason's
five other ways to play (MAN VS COM, MAN VS COA, COA VS COM, COA VS COA,
COM VS COM); the Pro Bowl; and TEAM DATA, the AFC's all stars' playbooks
changed at random, which the game writes to the save. `tests/test_season.py`:
TEAM CONTROL's change of a team, and a season game for two played to its
end, its result in the season; SCHEDULE's autoskip and a week of the
CPU's games played out with no buttons; and the season's last game into
the standings and the first playoff game. Each from a session's start at
the main menu, the same game at every tick, the two saves alike at the
end, and in the longer ones every bank the game picks one of its 30 (the
netplay's are 30 and 31; `game_banks`).

Some of the game would take too long in the simulation, some 19 frames a
second for the two consoles and their nesp32s, and the tests make it
shorter, the same on both consoles:

- **A game** is some 15 minutes of play. Each quarter's clock is 0:10
  once it starts (`short_quarters`), and player 1 is given a touchdown, or
  a tie goes on to overtime: a game is then some 5500 frames. Setting the
  quarter instead does not end it: the game's quarters are a task's
  calls one after another, and `QUARTER` only a count.
- **A season** is 17 weeks. A test that needs it further on sets the week
  and game in the save (`CURRENT_WEEK_IN_SEASON`, `CURRENT_GAME_IN_WEEK`)
  at the main menu and makes its checksum right (`fix_checksum`), which
  the game checks only at the power-on.
- **A timeout** is taken only while the clock runs between plays, after a
  tackle in bounds, which plays at random seldom end with: the clock runs
  between plays while the test tries (`clock_runs`).

## The frame rate

`make bench` (`tools/bench.py`) plays a preseason game for two, MAN VS
MAN, Buffalo against Cleveland, from its kickoff: on the original by its
own menus, and in a session of two consoles with nesp32's firmware, 10 ms
apart. Then 1,500 frames of both players' buttons at random, the same for
each seed on both. Each NMI is a lag (it found a task at work), a tick (it
ran the tasks) or a stall (in a session, the other's buttons not there);
a tick is timed from its vblank to every task asleep again. The two are
not the same game, so it compares four seeds of each, not tick for tick.
At 14 cycles a bit:

| | NMI off | lags | ticks a second | NMI to the tasks | a tick | over a frame |
|---|---|---|---|---|---|---|
| the original | 0.9% | 2.2% | 58.2 | 2,375 | 22,068 | 2.2% |
| a session, 2026-11-15 | 0.9% | 14.2% | 51.0 | 6,817 | 26,329 | 16.8% |
| a session, the stack kept unrolled (2026-11-16) | 1.1% | 10.4% | 53.2 | 5,763 | 25,282 | 11.8% |
| a session, the sprites' flicker quicker (2026-11-16) | 0.9% | 6.5% | 55.6 | 5,470 | 24,326 | 7.2% |
| a session, and the collision checks quicker (2026-11-16) | 0.9% | 3.9% | 57.2 | 5,470 | 23,293 | 4.3% |

(Cycles are medians; a frame is 29,780.) The game's tick is long: the
median is three quarters of a frame, so what the session adds to the NMI
puts many ticks over. In the original a lag costs the game nothing but
where it falls (the NMI goes on into the tasks, which count their frames
as before); in a session it is a frame the game stands still, so the game
plays at 57.2 ticks a second, 1.7% slower than the original (53.2, 9%,
before the quicker routines). No stalls at 10 ms: the delay covers
the trip. Each 1,000 cycles off a tick of play takes some three of the
lags in a hundred frames away: the busy stretches' ticks are close to a
frame, and the session's work tips them over.

What the session's NMI adds, from its read (`net_nmi_read`) to the tasks,
where the game's own read is some 700 cycles. The stack and the locals
were kept in loops of a byte at a time, 40 bytes of stack; now 24, and
unrolled (`STACK_KEEP`, `net/net_ram.inc`, which says why 24):

| | loops, 40 bytes | unrolled, 24 |
|---|---|---|
| the save RAM on, the stack below and `LOCAL_1` to `LOCAL_8` kept | 890 | 327 |
| this console's buttons read and stored | 363 | 363 |
| the exchange, PEER's TICKS at 14 | 2,598 | 2,593 |
| both players' buttons taken, the stack and the locals put back | 1,027 | 434 |
| in all | 5,102 | 3,748 |

### Quicker routines

The game's own routines are the larger part of a tick. In play (a
profile of the original's ticks, by routine): the players' movement
(`UPDATE_PLAYER_LOCATION_START` and the loop round it, in the fixed bank)
some 6,700 cycles a tick, the checks of each offensive player against the
defense (`CHECK_OFF_PLAYER_VS_ALL_DEF_LOOP`) 1,600, the sprites' flicker
1,900, the task switches 2,300, the music 1,500. The netplay ROM has
quicker ways through some of them, and `build/tsb_net_slow.nes` is the
same ROM with the game's own (built with `NET_SLOW`): `tests/test_fast.py`
holds the one to the other, each routine from memory at random (its
memory, registers, flags and the MMC3's banks after), and a session's
whole game, its buttons the same at each tick, the same at every tick.
That is a session's game: alone, the game's NMI breaks into its tasks
wherever a frame ends, and a quicker routine makes a different game.

- **The sprites' flicker** (`net/flicker.inc`): each frame the flicker
  task counts the sprites in each band of 16 lines and puts the ninth and
  later off the screen, over some 48 sprites, at some 45 cycles each.
  Written out a sprite at a time, with the band from a table, 16 of them
  for the offsets the game cycles through, it is some 27. Its bank, 33,
  goes in at $A000 for the count from bank 22's empty bytes
  (`net_flicker`), which keeps the game's shadows of the banks as they
  were; the registers and flags it leaves are the game's loop's, which the
  task's next sleep keeps on its stack (the first thing the whole game's
  test found). Lags from 10.4% to 6.5%.
- **The collision checks** (`net/coll.inc`): each frame the collision
  task checks two of the offense's players against each of the defense's
  11, some 70 to 90 cycles a pair, most of it the loop's tables, pointer
  and counting. Written out, a defender at a time, with its byte and bit
  of the pair's status as constants and its RAM at a fixed address, in a
  copy for each team on defense, a pair that may not collide takes some
  20 and one too far up or down 34. In a bank of its own, 34, put in by
  `net_coll` in bank 22's empty bytes as the flicker's is. It leaves the
  loop's pointer, counter, last pair's byte and bit, registers and flags
  as the game's. Lags from 6.5% to 3.9%.
- **The players' movement** is next by its size, but its loop is as tight
  as the game's way of reaching each player's 32 bytes, through a
  pointer, allows; X-indexed it would save some 1,000 cycles a tick, in
  the fixed bank, which has no room, with the players' bytes across four
  pages.

## What has been learned

- **The game's NMI keeps the registers it saves in memory** (`NMI_A`,
  `NMI_X`, `NMI_Y`), not on the stack. An NMI that breaks into another,
  as one into a frame of the menu that ran long did, gives the main thread
  back the wrong registers, and the idle loop takes X for a task's index
  and crashes. Anything of the netplay's that may run past a frame does so
  with the NMI off.
  And the NMI goes on again only at the RTI (`net_menu_nmi`): the menu
  turned it on at the end of its frame's work, before the way out restored
  the registers, and a vblank that came in those few instructions brought
  an NMI that saved its own over them. The idle loop then took X = $C9 for
  a task, ran into a stale stack, and from there into BRKs at $24A7; on
  player 1 the save's copy stopped (player 2 kept its own past byte 2088)
  or ran on with the IRQ left on. It came in about one run in four of
  `test_menu.py`'s different saves. The tests now fail any task the
  scheduler takes up that is none of the eight (`guard_tasks`).
- **The game puts much of its save right at the power-on.** A save RAM of
  zeros becomes a new save; in one the game had made, a change to the
  seed (`SAVED_RANDOM_1`), the CPU's boost or the playbooks was undone by
  the next power-on, and a change to a team's control (`TEAM_TYPE_SEASON`)
  was kept. So two consoles whose saves are not the game's own end up
  alike, and a test of different saves needs one the game made, with a
  change it keeps (`test_menu.py`'s `hosts_save`).
- **The game's IRQ splits the title's screen**, and its handler is in the
  fixed bank: a hang with the PC in $C2C2-$C378 is the IRQ, running when
  it should not.
- **The game's tasks keep their stacks in page 1, and it copies one into
  the save RAM** for a scene ($0150-$016B to $6203, bank 19's $A07B),
  with what an interrupt pushed below the stack's pointer. Two consoles
  differ there, and in nothing that counts: a season game for two
  differed in three such bytes. The save the two must share begins at
  $6403, past it.
- **On the play-call screen, A alone is the menu** (CANCEL, TIMEOUT, and
  the offense's PUNT KICK, FIELD GOAL and CHANGE), not Start, and it takes
  some frames to open; its text stays in the nametable after it closes,
  so a test looks at its arrow's sprite ($0200 for player 1, $0204 for
  player 2, at Y $38 beside CANCEL). A timeout is refused while the clock
  is stopped.
- **The main menu is PRESEASON, SEASON GAME, PRO BOWL and TEAM DATA**, in
  that order; the season's is TEAM CONTROL, SCHEDULE, GAME START, the
  standings, rankings and leaders, and TEAM DATA. A season starts with
  every team SKP (TEAM_TYPE_SEASON 3), and GAME START plays each game of
  the week out with its scoreboard and statistics, some 900 frames a game
  with A to go on; each A in TEAM CONTROL makes a team's control the next
  (MAN 0, COA 1, COM 2, SKP 3).
- **`SOFT_PPU_CTRL`'s nametable bits ($31) are where the frame fell**:
  each of the screen's splits sets them for its own, in the NMI and the
  IRQ, so at a tick they are the last split's to have run. A quicker NMI
  made two consoles differ there; the tests leave the two bits out
  (`UNKEPT_BITS`). The game only writes them to the PPU.
- **The simulation is the same every run** now that the rendezvous's
  rooms are made with a seed (`ROOMS_SEED`, `tests/netplay.py`; `Rooms`'s
  `rng`, nesp32's `host/rendezvous.py`). Each room's code and session were
  drawn from the system's random numbers, and the code is drawn on the
  menu and crosses the link: frames after it took a little more or less
  time each run, which let the menu's NMI bug pass some runs and fail
  others. The other games' tests still make their rooms at random.
- **The exchange must be over before the screen's first split** (seen on
  hardware, November 2026: the top quarter of the screen broke up in play
  and in many scenes, the fans on the sidelines among them). The game
  splits the screen with the MMC3's IRQ, the first some 5,000 cycles into
  the frame in play, near line 24; the exchange holds the IRQ off for
  some 2,600 cycles, and came after the sound engine, from some 3,300. In
  the simulation 15% of the splits were taken a line or more late, by up
  to 21 lines. Now the read and the exchange come before the sound
  (`net_sound_hook`, in place of the NMI's CLI and call of the sound
  engine) and end some 4,300 cycles in; and the digest, some 5,000
  cycles once in 256 ticks, is taken with the IRQ on, leaving out the two
  bytes the IRQ writes ($49-$4A). No split late in 1,500 frames
  (`tests/test_frame.py`).
- **A misheard reply is asked again only if there is room before the next
  split** (seen on hardware, November 2026: with the splits fixed, the top
  of the screen still broke up now and again, with the voice's samples).
  A sample's fetches can spoil a reply, and `net_ask` asked again at
  once: a second exchange, which ended some 6,800 cycles in where the
  first split is at line 32 (some 6,000 cycles), as it is in most of
  play. In the simulation, with one reply in seven made to fail its
  check, 20 splits in 641 were late, by up to 21 lines. Now it asks again
  in the same NMI only if the next split is at line 64 or below, or there
  is none, and otherwise at the next NMI. No split late; the ticks taken
  went from 876 to 860 in 300 frames at that rate of mishearing (hardware
  has been some 0.6%). `tests/test_frame.py`.
- **An NMI that comes in another's own work is let be** (seen on
  hardware, November 2026: both consoles stopped in the second quarter,
  on an interception, the screen black and a note held). A session's NMI
  does its own work before the game's tasks: the PPU's writes, the
  exchange and the music. If that runs past the next vblank, the next NMI
  comes in the middle of it. That NMI went as a lag: it put the banks back
  from the game's shadows (`RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS`,
  since the lag's music came in) and returned into the netplay's code
  with another bank at $A000. In the simulation, an exchange made to take
  a frame and more crashed the console at the second, running from
  $0000. The exchange waits up to 4.15 ms for a reply, and asked again
  after one that did not come: with a nesp32 that did not answer, the
  NMI's own work was some 22,700 cycles of the frame's 29,780, and a slow
  frame's PPU writes or the digest would take it past. 720 interceptions
  forced in the simulation, with and without a nesp32 that went quiet,
  never crashed: the interception was where it happened, not why. Now
  the NMI marks its own work (`net_nmi_busy`, until `net_read_hook`), an
  NMI that comes in it gives back the registers and nothing else
  (`net_nmi_check`), and the NMI it came in returns to the start of the
  idle loop, as the registers it kept for the loop are the second's. A
  reply that does not come is no longer asked for again in the same NMI
  (one misheard still is). `tests/test_frame.py` stretches an exchange
  past the vblank once in 37 frames: the session goes on, the same game
  on both.
- **A lag's music takes no sound waiting to be played.** The game asks
  for a sound by `SOUND_ID_TO_PLAY`, which the sound engine clears as it
  takes it, and `PLAY_SOUND` waits a tick while it is not clear. With the
  music in a lag's NMI, the engine took a request in the middle of a
  tick, and the lags come where they will on each console: in a whole
  game with one console's lags moved, the two took requests at different
  places 24 and 8 times. A task that asked for a second sound in that
  tick would have waited on one console and not the other. Now a lag's
  NMI runs the music only with no request waiting (nor the song after an
  interception, which the engine moves into it): requests are taken in a
  tick's NMI or a stall's, between ticks, on both. Not seen to split two
  games in the simulation; the one hardware stop since (November 2026,
  one console black at the start of the third quarter, the other at the
  menus) is not explained by anything found yet.
- **The music runs in every NMI** (seen on hardware too: it slowed down
  with the lags). The game's NMI runs the sound engine whenever its
  scheduler is not in the middle of a switch, a task at work or not; a
  session's lag ran only the splits. Now it runs the music too
  (`net_lag_sound`), from the fixed bank: the sound engine changes the
  bank at $A000, and called from the netplay's bank it came back into
  another (the game's reset, which counts its save's checksum with the
  NMI on, hung on it). The game's own busy NMI still has none, as in the
  original: some 0.7% of a session's frames.
- **A test's ticks are counted from `Table.begun()`**, which now clears
  what was traced before it: one console's session may begin some frames
  before the other's (player 2 copying a save), and ticks taken before it
  were named from the table's start.
- **The exchange made ahead, in the idle loop, gained little** (tried
  and taken out, 2026-11-16). Once a tick's tasks were asleep, the
  scheduler's idle loop read the controller for the next tick and made
  its exchange, so that the NMI had only to take the buttons; an NMI that
  came first gave it up and put back what it had changed. The NMI's part
  went from 5,770 cycles to 3,238, but lags only from 10.4% to 9.2% (53.2
  to 54.0 ticks a second, `make bench`'s four seeds), and the NMI cut off
  some 30% of them. After a tick there are some 4,100 cycles to the next
  vblank (the median), and the exchange ahead took some 3,600 with the
  read and the stack and locals kept; in the busy stretches of play,
  where the lags are, there are fewer. Moving the session's work about
  the frame does not help where the frame has no room: a tick has to cost
  less in all. Each exchange cut off left half a request on the line.

## To do

In order. Each step is tested in the simulation before the next.

1. **The frame rate**: measured ("The frame rate"), a session lags in 10%
   of its frames where the original does in 2%. What the NMI adds before
   the tasks is mostly the exchange now, 2,600 cycles of 3,750: a faster
   line (10 was misheard on Jackal), or fewer bytes in TICKS, would save
   200-300 of them. Moving the exchange to the idle loop gained little
   ("What has been learned"). The game's own routines are the larger
   part of a tick ("Quicker routines"): the flicker's count and the
   collision checks are done (lags 10.4% to 3.9%, the original's 2.2%);
   next, of what is left, the check for players near each other
   (`PLAYER_NEARBY_CHECK`), the music, or the players' movement if room
   can be found for it. Each against `tsb_net_slow.nes` in
   `tests/test_fast.py`, then `make bench` again.
2. **For players**: the netplay ROM named `superbowl.nes`, not
   `tsb_net.nes`, so that it says what it is (and its `_slow` twin, its
   `.dbg` and `.map`, and the patch to match: the Makefile, the README and
   `tests/conftest.py` and `test_fast.py` name it today). Then `make bps`
   and the patch in `dist/`, `tests/test_patch.py`,
   the hello's version, and every document that lists the games (the
   `nes-netplay-port` skill's "Shipping a change"), with `TSBO` in
   `VERSIONS` (`host/peer_player.py`), which `tests/test_peer_player.py`
   fails without (the one failure of nesp32's `make test` on this branch).
   The save needs the firmware with PEER's SAVE ops (in `CHANGELOG.md`
   under Unreleased): the patch's entry in `PATCHES` names the release that
   brings them, and a nesp32 with older firmware should be told to update
   (its SAVE answers `NO_OP`; the menu now gives the session up after
   `SAVE_TRIES` instead).
3. **Hardware**: two consoles and two nesp32s, by a room's code, each
   nesp32 flashed with this branch's firmware. Tried in November 2026 (a
   MiSTer; the N8 clone multicart showed a gray screen, which may be its
   SD card's loading, the ROM's 512 KB, or its battery's NES 2.0 header):
   the save's dialogue, its copy and a season kept work; the screen's
   splits broke up and the music slowed. Then the music was right and the
   splits broke up only now and again, with the samples: the misheard
   reply's second exchange, put right since in the simulation. Then the
   splits and the music were right and the game played well, but both
   consoles stopped in the second quarter, on an interception: an NMI in
   another's own work ("What has been learned"), put right since in the
   simulation, with LOCAL GAME and NETWORK GAME at the title. Then twice
   more (the third quarter, then the first): one console's screen black
   at once, silent the first time and a tone held the second, and the
   other at the title at once. That is not `SILENT_FRAMES` (4 seconds):
   either both gave up at a check of the digests and the black one's
   reset went no further, or the black one stopped and its nesp32 told
   the other. Neither is seen in the simulation, nor a reset after a
   drop going wrong (forced at 15 places in a game). The menu then said
   why each gave up (above), and after the next the black one (the host)
   said OTHER STOPPED and the other nothing: the joining console went to
   the title by no drop of the session's, a reset (its own, or a crash
   into the reset), and the host gave up 4 seconds later and its own
   reset after the drop went no further. In the simulation both of those
   go as they should (`test_a_reset_in_play_is_kept_for_the_menu`). So
   the menu's first screen now also shows, in hex on rows 25 and 26,
   what the last two resets found before the game's reset cleared the
   RAM (`net_reset_keep`, `net_resets`): the stack pointer, net_mode,
   net_tick, net_silent, TASK_BUSY_FLAG, net_nmi_busy, the two banks'
   shadows and the stack's top four bytes. Then (the MiSTer the host,
   the multicart's console the other) the multicart's went black and the
   MiSTer gave up after 4 seconds, its reset to the title as it should
   be (`F9 80 1C F0`: in a session, tick $1C, 240 silent NMIs). The
   multicart's had no reset between the session's start and its button
   (whose loader clears the RAM, but not the save RAM): it stopped dead
   at tick $1B, in place. Every time, the multicart's console is the
   one that stopped, black or at the title. So row 27 is now where the
   last session NMI found the console (`net_crumb`): the stack pointer,
   the tick, the banks' shadows and the stack's top eight bytes, which
   hold the main thread's place. That console's nesp32 turned out to
   reach only 178,977 bps from the console; with it fixed (both at
   298,296 both ways), a game went to the third quarter and both
   consoles gave the session up together, LAST: GAMES DIFFERED, each
   reset as it should be (`F9 80 FF 00`: in a session, at the digests'
   tick): the first desync on hardware, where whole games in the
   simulation have none. So a console whose digest differs now sends its
   RAM to its nesp32's log before it gives up (`net_differ`, PEER's
   DUMP, as Bubble Bobble's does), and the two logs say which bytes
   differ. Two whole games after it, with the nesp32s' logs watched, had
   none. The simulation then played whole season games at full-length
   quarters with each console's main thread stalled at random, so that
   the two lag on different frames as on hardware: of nine, six ended
   alike; one (in the fourth quarter) found a sound engine byte in a
   sleeping task's X (STOP_CURRENTLY_PLAYING_SOUND loads
   ON_FIELD_SONG_TO_PLAY_AFTER_INT, which the interception's music clears
   when it ends, by the frames and not the ticks; the code after does not
   use X); and two failed after the final whistle, the scheduler taking
   up a task at X = $00. That was an NMI that came in the IRQ's handler,
   which keeps the main thread's registers in IRQ_A, X and Y as the NMI
   does in NMI_A, X and Y: a lag's music turns the IRQ on, and the next
   split's IRQ saved its own over them. A lag's NMI that comes with the
   IRQ off now keeps it off and has no music
   (`test_an_nmi_in_the_irqs_handler_lets_no_irq_in`). It needs an IRQ
   some 4 lines above the vblank held back by 350 cycles or so, so it is
   rare on hardware. Next: the nesp32s' logs of the next desync; then a
   whole game again, the title's choice, the samples against the line at
   14, how the lags feel against a game on one console, and the save's
   time across the Internet. The copy is at the link's rate; PEER's RATE
   could make it some twice as fast.
4. **River City Ransom's menu** is the same as this one's but for the
   save: check whether its frames can run past an NMI, and whether its
   game's NMI keeps its registers where a nested one would spoil them.

## Decisions made

1. **What save RAM a session starts from**. *Decided
   2026-11-14: the host's, copied to the guest*, and only when the two
   differ (they compare a checksum at the session's start). Before the
   copy, the screen says that player 2's save will be replaced by
   player 1's. Both then play the host's season, and the guest's save (of
   the netplay ROM, which a flash cartridge keeps apart from its Tecmo
   Super Bowl) becomes a copy of the host's. The notice is a yes/no
   dialogue in the lobby menu's style, on both screens; only player 2's
   buttons answer it, and no leaves the session.
   Done: "The save", above.
2. **Where a session begins.** *Decided 2026-11-14: at the main menu*
   when the intro and title have already been shown before the session
   was made (as they have been when it is made from the lobby, which is
   opened at the title). Done ("The menu", Past the intro).
3. **LOCAL GAME and B in the menu** reset the console (the menu uses the
   game's RAM). *Decided 2026-11-14: they go back to the title*, past the
   intro, by a mark in the save RAM that the reset finds (the same mark
   decision 2's session start uses). A power-on or the console's Reset
   clears it, and the intro plays as ever. Done, and B on the menu's
   first screen goes back to the title too. Since November 2026 the menu
   has no LOCAL GAME: B is the way back, and LOCAL GAME is at the title.

---
name: nes-netplay-port
description: How a two-player NES game is made a nesp32 netplay ROM in this repo, and how one already made is changed, tested, measured and shipped. Use when starting a new game's port under apps/, changing an existing port (Contra, Dr. Mario, Tetris, TMNT II, Bubble Bobble, Jackal, River City Ransom), chasing a desync between two consoles, measuring frame time, or rebuilding a game's BPS patch.
---

# A game for two consoles, on nesp32

Read `docs/MULTIPLAYER.md` first: what a tick, a stall and a lag are, where
the exchange goes, the music, the digest. Then the nearest port's README,
which says what was that game's own. Jackal's (`apps/jackal/README.md`) is
the most complete, with "What has been learned". RCR and Bubble Bobble
had no disassembly to start from: their builds make one from the ROM
(`tools/trace.py` notes where the game runs, in `entries.txt`;
`tools/game.map` has the names; `tools/convert.py` makes ca65 source that
rebuilds the ROM byte for byte). Start a game with no disassembly from
theirs.

## The layout of a port

```
apps/<game>/
  Makefile            all, verify, test, patches, bps, clean (bench in some)
  baserom.nes         the player's own copy; never committed (gitignored)
  net/                our code: net.inc (the session), menu.inc, ram.inc,
                      <game>_net.cfg (the netplay ROM's map), cart.inc
  patches/            our lines in the game's source, as diffs with no context
  tools/              convert.py (a disassembly to ca65), bench.py, game.map
  tests/              console.py (the game on py65), drive.py, netplay.py
                      (two consoles, two nesp32s, a network), test_*.py
  dist/<game>_net.bps the netplay ROM for players
third_party/<disassembly>   a submodule, kept at one commit; never written to
nes/lib/              nesp.inc and the link, shared by every ROM
```

The game is not in the repo. The build copies the disassembly (or
converts it, into `build/gen`) to `build/src`, applies `patches/`, and
builds three ROMs: the original (which `make verify` holds to the
release's SHA-512), the netplay ROM, and a `_slow` netplay ROM with the
game's own routines, which is the same game as the netplay ROM and is
what it is measured against.

## Building, and changing the game's source

```sh
git submodule update --init third_party/<disassembly>
make && make verify && make test
```

- Edit the copies in `build/src`, never the submodule. Then `make patches`
  writes `patches/` from them.
- **Run `make` after each `make patches`, before editing `build/src`
  again.** `make patches` can remake the copy from the old patches and
  lose what was edited.
- Each patch is under `.ifdef NETPLAY` and the same length as what it
  replaces, or a label alone: none of the game moves, and the original
  still verifies.
- A netplay ROM may need a bigger cartridge than the game's for the
  session's code and the menu: Contra's and Jackal's are on an MMC3
  (mapper 4) with PRG RAM where the games are UxROM. Each README's "The
  cartridge" says what its port did.

## What every port has had to get right

- **The exchange goes where the game reads its controllers**, after the
  NMI's PPU writes and before the frame's work. Later costs a tick of delay.
- **The music runs in every NMI** (tick, stall or lag), not once a tick,
  or it speeds up and slows down on real consoles. Leave the sound
  engine's memory out of the digest and the tests' comparisons.
- **A session starts from a console just switched on.** Clear all 2 KB of
  RAM at the start of a session (Bubble Bobble desynced until it did),
  keeping only what is meant to carry over (a mark like Contra's
  `net_boot`, which a reset keeps on purpose).
- **The digest** covers the game's state and leaves out what may differ
  without the game differing: the link's bytes, the sound engine's, scratch,
  shadows of the PPU and banks. Rotate then EOR: no rotate through the
  carry with ADC, which lost early bytes.
- **Drum samples (the DMC) can spoil a controller read** on a real NES:
  the "phantom Right" (`docs/PHANTOM-RIGHT.md`). If the game plays
  samples, the session's read must read twice and compare, as the game's
  own routine usually does and Dr. Mario's `session_read_pad` now does.
  Contra does not have the problem.
- **A new build that changes the game is a new version in the hello**, so
  two different builds never join.
- **Some games depend on PPU timing** that py65 does not model (Contra
  Force's logic depends on when its second buffer reaches the PPU, on the
  `contraforce` branch). Check those in Mesen (below), and on hardware.

## Testing

- `make test` in the app: the ROM on py65 (`tests/console.py`), two
  consoles against the firmware built for this computer (`make host` at the
  top), with a simulated network. A lockstep test compares the two
  consoles' state tick by tick.
- Tests need `pytest`; on this Mac it is in `/usr/bin/python3`, not pyenv's:
  `make test PYTHON=/usr/bin/python3`, or a `.venv`, which the Makefiles prefer.
- **In Mesen, with no window** (`host/mesen/README.md`):
  ```sh
  python3 tools/mesen_run.py apps/<game>/build/<game>_net.nes \
      --press 260:start:3 --press 700:right:400 --shot 1100 --ram 1100
  python3 tools/png_diff.py a.png b.png --out diff.png
  ```
  Use it for the picture, sprites, mapper IRQs and anything py65 leaves
  out. Contra's netplay ROM with no session is the original 3 frames
  later (its boot), so compare shots at an offset. Mesen's "Uninitialized
  memory read" lines are worth one look each; most are on purpose.
- The two-console PEER session is not in the Mesen bridge yet: sessions
  are tested in the simulation and on hardware.

## Measuring frame time

`make bench` (`tools/bench.py`, in the apps that have one, Jackal's the
model): the same seeds on both ROMs, only ticks of
play (not menus or level loads), a level poked in where the game keeps it
before it loads, and the boot offset allowed for. Compare the netplay ROM
with the `_slow` one only: netplay and original are different games once
a session's exchange is in. The session line's speed (`NET_RATE` in
the Makefile, CPU cycles a bit: 21 is the link's own, 14 is faster) is
opt-in per game and needs trying on hardware; 10 was
misheard 12% of the time.

## Shipping a change

1. `make verify && make test`, and the tests at the top (`make test`).
2. `make bps` and commit `dist/<game>_net.bps`; `tests/test_patch.py`
   fails while it is out of date. A new game also needs its entry in
   `PATCHES` in `tools/gen_web.py` and a card on `web/patches/index.html`.
3. A line under Unreleased in `CHANGELOG.md` if a player would notice.
4. **Every document that lists the supported programs**, for a new game,
   or a changed name, cartridge, firmware need or status:
   - `web/product/index.html` (the product page's list of games)
   - `README.md` (the Games row, the build commands, the ROMs table, the
     games that need a `baserom.nes`, the docs table's line for
     `docs/MULTIPLAYER.md`)
   - `docs/MULTIPLAYER.md` (the opening list, the table of READMEs, the
     title's choice and hello, the digest table, "Known limits", "To do")
   - `docs/USER_GUIDE.md` (the games not on the cartridge, the patches
     table with each release's size and CRC32, firmware needed, which need
     an MMC3, how each game's menu is reached)
   - `docs/DEVELOPMENT.md` (how each is built, which patch a copy of the
     converted source, which `make bps` covers)
   - `web/patches/index.html` and `PATCHES` in `tools/gen_web.py`
   - `VERSIONS` (and `TICKS_PER_S` if a tick is not a frame) in
     `host/peer_player.py`; `tests/test_peer_player.py` holds them to the
     apps' sources
   - this skill's description and opening list

   Search for an existing game's name (`rg -i 'river city ransom|\bRCR\b'
   --glob '!apps/rcr/**' --glob '!third_party/**'`) to catch any list
   added since.
5. Hardware: two consoles, each with a nesp32, a session by room code.
   Say in the README what was tried on hardware and what only in the
   simulation.

## Writing the docs

Match the READMEs as they are: plain sentences, what the player sees
first, figures with what they were measured on. Call the product nesp32;
"Stick" is only the M5 board itself.

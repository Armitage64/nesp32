# Contra, two consoles

A netplay build of Contra (US, NES): a two-player game on two consoles,
each with a [nesp32](../..) on controller port 2, each player on
controller 1 of their own console, the nesp32s joined over the network.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
three netplay games share: the menu, the nesp32, how the two games are
kept the same, and the limits. [docs/Netplay.md](docs/Netplay.md) has what
is Contra's own, what has been played on hardware and the figures.

The netplay ROM is on another cartridge than the game's: an MMC3 (mapper
4) with 8 KB of PRG RAM and 8 KB of CHR RAM, where the game's own is a
UxROM, so that netplay's code can run from the RAM (docs/Netplay.md, "The
cartridge"). A flash cartridge or an emulator has to take that, as for
TMNT II; `make ines` writes it with an iNES header for one that takes no
NES 2.0.

**The game is not in this repository.** What is here is the netplay code,
its tests, and a few lines to be put into the game's own code. The build
takes the rest from two places:

- [nes-contra-us](https://github.com/vermiceli/nes-contra-us), vermiceli's
  disassembly of the game, a submodule at `third_party/nes-contra-us`. Its
  README and `docs/` are the place to read about the game itself.
- `baserom.nes`, a copy of the game, which whoever builds puts in this
  directory (or says where it is with `BASEROM=`). The graphics and the
  sound are cut out of it, as the disassembly's own build does. It is the
  US release: `make verify` checks what is built against its SHA-512.

```sh
git submodule update --init third_party/nes-contra-us
make            # build/contra.nes (the original), build/contra_net.nes, and
                # build/contra_net_slow.nes, with the game's passes, for the tests
make verify     # the original still matches its SHA-512
make bps        # dist/contra_net.bps again, for players ("The patch", below)
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
link's library for the console is nesp32's, and the tests build its
firmware's link and services for this computer.

## The patch, for players

To play, there is no need to build anything. `dist/contra_net.bps` is the
netplay ROM as a patch to the US release: apply it to your own copy of the game
with any BPS patcher (Floating IPS, or RomPatcher.js in a browser), and
put the ROM it makes on a flash cartridge. A BPS patch knows the ROM it is
for, and a patcher refuses any other: the US release with its iNES header,
131088 bytes, CRC32 `C50A8304`, as `make verify` knows it. The ROM it makes has an NES 2.0 header; for a cartridge that will not
take one, build it (`make ines`).

The patch holds none of the game. The netplay's lines in the game's own
code move what comes after them, so the patch copies the game's bytes
from wherever they are in the player's own ROM, and carries only the
netplay's code, its header, and the game's instructions the move has
changed (an address, a branch). There is no IPS patch, which cannot copy.
`tools/gen_patch.py` (at the top of this repository) refuses to write a
patch that carries sixteen bytes in a row that are found anywhere in the
game; and `tests/test_patch.py` holds the patch in `dist/` to the ROM this
tree builds: after a change to the netplay, `make bps` writes it again.

## What is where

| Path | Purpose |
|---|---|
| `net/` | the netplay code: the session, the menu, the cartridge, the sprite pass and the bullets' test, their memory, and where the linker puts them |
| `patches/` | the lines that call it, for five of the disassembly's files. All are under `.ifdef NETPLAY` |
| `tools/extract_assets.py` | cuts the graphics and the sound out of `baserom.nes` |
| `tests/` | a console on py65, and two of them with their nesp32s and a network between |
| `docs/Netplay.md` | the design, the figures, and what has been learned |
| `dist/contra_net.bps` | the netplay ROM as a patch to the game, for players (`make bps`) |

## Changing the game's code

Edit the copies in `build/src`, then `make patches`. nesp32's
[`docs/DEVELOPMENT.md`](../../docs/DEVELOPMENT.md), "Changing a borrowed
program's code", has how the patches are kept.

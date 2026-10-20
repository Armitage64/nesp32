# Contra, two consoles

A netplay build of Contra (US, NES): a two-player game on two consoles,
each with a [nesp32](../..) on controller port 2, each player on
controller 1 of their own console, the nesp32s joined over the network.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
three netplay games share: the menu, the nesp32, how the two games are
kept the same, and the limits. [docs/Netplay.md](docs/Netplay.md) has what
is Contra's own, what has been played on hardware and the figures.

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
make            # build/contra.nes (the original) and build/contra_net.nes
make verify     # the original still matches its SHA-512
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
link's library for the console is nesp32's, and the tests build its
firmware's link and services for this computer.

## What is where

| Path | Purpose |
|---|---|
| `net/` | the netplay code: the session, the menu, their memory, and where the linker puts them |
| `patches/` | the lines that call it, for three of the disassembly's files. All are under `.ifdef NETPLAY` |
| `tools/extract_assets.py` | cuts the graphics and the sound out of `baserom.nes` |
| `tests/` | a console on py65, and two of them with their nesp32s and a network between |
| `docs/Netplay.md` | the design, the figures, and what has been learned |

## Changing the game's code

Edit the copies in `build/src`, then `make patches`. nesp32's
[`docs/DEVELOPMENT.md`](../../docs/DEVELOPMENT.md), "Changing a borrowed
program's code", has how the patches are kept.

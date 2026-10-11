# NES Radar, on a nesp32

[NES Radar](https://github.com/k6lcm/nes-radar), k6lcm's air traffic scope
for the NES, with a [nesp32](../..) on controller port 2 in place of a
computer and a serial cable. Four letters typed on the controller name an
airport, and the aircraft within nine nautical miles of it are on the
scope, from [adsb.fi](https://adsb.fi). The nesp32 fetches them itself,
over Wi-Fi, and asks [Wikidata](https://www.wikidata.org) where the
airport is.

**The program is not in this repository.** What is here is the code that
puts it on nesp32's link, its tests, and a few lines to be put into the
ROM's own source. The build takes the rest from
[nes-radar](https://github.com/k6lcm/nes-radar), a submodule at
`third_party/nes-radar`: its README is the place to read about the scope
itself and what is on it.

```sh
git submodule update --init third_party/nes-radar
make            # build/nes_radar.nes (the original) and build/nes_radar_link.nes
make verify     # the original still matches its SHA-256, and passes nes-radar's own checks
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
link's library for the console is nesp32's, and the tests build its
firmware's link and services for this computer.

`build/nes_radar_link.nes` is the ROM for a nesp32. It says hello to
nesp32's firmware as `RADR` and asks for the RADAR service. Like the
original it is a CN-ROM (mapper 3) with 32 KB of PRG and 32 KB of CHR.
`build/nes_radar.nes` is nes-radar's own ROM, for its own server and
cable, built here only to show that the patch leaves it alone.

**Not yet run on hardware.** It is tested on a simulated console against
nesp32's own RADAR service, over a cycle-exact line.

## Using it

Flash nesp32's firmware ([its README](../../firmware/README.md)) and put
the nesp32 on Wi-Fi with [Setup](../setup). Then, as with nes-radar's own
ROM: Up and Down change a letter, Left and Right move along the four,
Start asks for the airport. On the scope the direction buttons choose
among the aircraft, and Select is the editor again. The editor begins at
the last airport the nesp32 found, which it keeps when it is switched
off; with none kept, or no nesp32, at nes-radar's `KSBA`.

| The editor says | |
|---|---|
| `REQUESTING` | the nesp32 is being asked, and is asking where the airport is: a second or two |
| `INVALID AIRPORT` | Wikidata knows no airport with those letters as its ICAO code |
| `LOOKUP FAILED` | Wikidata did not answer. Start asks again |
| `NO NESP32 ANSWER` | no nesp32 is there, or it is running something else |
| `NESP32 NO WI-FI` | Setup has not been run, or the network is out of reach |
| `UPDATE NESP32` | its firmware is older than this ROM, and has no RADAR |

| The scope's `LINK` says | |
|---|---|
| `IDLE` | the scene on the screen is the newest the nesp32 has, and it is good |
| `WAITING` | nothing has come of the aircraft yet, or for ten seconds, or for thirty from adsb.fi |
| `ERROR` | the nesp32's last fetch from adsb.fi failed. The last scene stays |
| `ERROR 1` | the nesp32 has stopped answering. The last scene stays |
| `ERROR 4` | the nesp32 sent an aircraft or a name that cannot be shown |

nes-radar's `RECEIVING`, and its `ERROR 2`, `3` and `5`, are not seen:
they are about its own packets on its own line.

## What is changed, and what is not

Everything on the screen is nes-radar's, and so is every check of what
goes there: the editor, the scope and its sprites, the selected aircraft,
the table, the validation of a record. The nine bytes of an aircraft and
the twenty-five of its names are nes-radar's, byte for byte, and nesp32's
tests hold the service's to the ones nes-radar's own server makes of the
same reply from adsb.fi.

What is replaced is the line and everything that was there because of it.
nes-radar's host streams packets at 9600 baud whenever it likes, so its
ROM has a receiver calibrated by hand, chunks with gaps to draw in, a
window in which the host promises to keep quiet, a heartbeat to keep the
sprites turning, and a request to pause before the editor may be shown.
On nesp32's link the console asks and the nesp32 answers, at 85227 baud,
so none of that is needed:

- **The scope is a loop that goes round once a frame**, and makes at most
  one exchange each time: twice a second it asks for the scene, by the
  serial of the one it has, and is sent the aircraft only if they are
  others. The pad is read every frame and the targets take their turns in
  front every frame, whatever the link is doing.
- **Names are fetched before the scene they belong to**, a slot a frame,
  and only when a scene's reply says they have changed.
- **Select is the editor at once.** There is nobody to ask.
- **A nesp32 switched off and on** is told who is on the console and
  which airport again, and the scope goes on.
- **The nesp32 has no table of airports.** nes-radar's server has ten
  thousand of them in a file; the nesp32 asks for the one it is given,
  and keeps the last in its flash, letters and place, so that the same
  airport next time needs no asking and the editor begins at it. Wikidata has most of nes-radar's and not all: of
  60 taken at random it had 55, the rest small fields. It also puts some
  a little way from where nes-radar has them, so the same aircraft can be
  a point or two away on the two scopes.

The ROM keeps its NMI off but for the moment it waits for a vblank to
write in, as nes-radar does. Every exchange is made with it off, just
after such a write, and the receiver gives up by counting (nesp32's
`gen_link.py --timeout`). The tests hold the ROM to nothing being written
to the PPU outside a vblank, and to the line never being listened to with
the NMI on.

[`docs/PROTOCOL.md`](../../docs/PROTOCOL.md) has the RADAR service.

## What is where

| Path | Purpose |
|---|---|
| `nes/radar_link.inc` | the link's code: the hello, the airport, the scope's loop and its exchanges |
| `nes/cnrom256_link.cfg` | nes-radar's linker configuration, with a place for the serial routines |
| `patches/` | the lines that call it, for nes-radar's one source file. All are under `.ifdef NESP32` |
| `tests/` | a console on py65, a nesp32 and the line between them, and the test in place of Wikidata and adsb.fi |

## Changing nes-radar's code

The build copies nes-radar's ROM directory to `build/src` and applies
`patches/` there; the submodule is never written to. To change what the
link adds to nes-radar's own file, edit the copy in `build/src/nes`, then

```sh
make patches    # patches/ again, from build/src
```

A patch is made with no context, so it holds our lines and where they go
and none of nes-radar's. That is why the submodule is kept at one commit
(`RADAR_COMMIT` in the Makefile): the patch is line numbers in that
commit's file. `make clean` will not delete a `build/src` that has changes
`patches/` has not.

## Not done

- A real NES, the MiSTer, any hardware at all.
- A place on [the cartridge](../../docs/DEVELOPMENT.md): it has two
  pictures' worth of CHR, and the cartridge gives a program one.
- PAL consoles.

## Licence

nes-radar is k6lcm's, under the
[GPL-3.0](https://github.com/k6lcm/nes-radar/blob/main/LICENSE). The ROM
built here is nes-radar's with these changes, and so is under it too; the
files in this directory are offered under the same licence. nesp32's
RADAR service is written from nes-radar's documents of its records
(`nes_radar/PROTOCOL.md`), not from its server's code, which the tests
only run beside it. The aircraft are adsb.fi's, from its open data API,
and where an airport is comes from Wikidata, whose data is
[CC0](https://creativecommons.org/publicdomain/zero/1.0/).

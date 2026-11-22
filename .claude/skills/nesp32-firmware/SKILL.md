---
name: nesp32-firmware
description: How the nesp32's firmware (ESP-IDF, firmware/) is built, flashed, watched and tested, which build goes on which board, and how a firmware change is shipped and released. Use when changing anything under firmware/ or nesp_core/nesp_services, flashing a StickS3, StickC Plus2 or generic ESP32-S3, reading a board's log, or cutting a release.
---

# The nesp32's firmware

`firmware/README.md` is the reference: what each file does, how it keeps
time, the jukebox, the keyboard, the radio, two consoles. `docs/PROTOCOL.md`
is the link and every service. This is the working order.

## Three builds, one per kind of board

| Board | Build directory | Target | Port on this Mac |
|---|---|---|---|
| M5StickS3 on the hat | `build-esp32s3` | `esp32s3` | `/dev/cu.usbmodem*` |
| M5StickC Plus2 on the hat | `build-esp32` | `esp32` | `/dev/cu.usbserial*` |
| ESP32-S3 dev board, three resistors (link not inverted) | `build-esp32s3-generic` | `esp32s3` + `sdkconfig.defaults.generic` | `/dev/cu.usbmodem*`, same as a StickS3 |

- The generic build is the StickS3's with `CONFIG_NESP_LINK_INVERTED` off,
  on the same pins (G1, G8), and needs 8 MB flash and 8 MB octal PSRAM.
  A dev board's port looks like a StickS3's, so say `--generic`.
- The Plus2 is low priority: a retired board, kept building. It shares
  the S3 hat, TX on G0 and RX on G36 (`main/board.h`).
- **NTSC and PAL are one firmware**: the nesp32 tells the console's clock
  from the line (`docs/PAL.md`). Never add a region build or make a ROM
  know its region.

## Building and flashing

```sh
firmware/deploy.sh build            # all three; errors from build-*/deploy.log
firmware/deploy.sh                  # build and flash whatever is on USB
firmware/deploy.sh --generic        # an ESP32-S3 dev board, not a StickS3
firmware/deploy.sh watch            # every board's log, without restarting it
```

`deploy.sh` sources ESP-IDF's `export.sh` itself, from `IDF_PATH`, else
`~/esp/esp-idf`, else the latest `~/.espressif/v*/esp-idf`; `idf.py` is not on the PATH otherwise. For one board by hand, the
`idf.py -B build-<x> -D SDKCONFIG=build-<x>/sdkconfig -D IDF_TARGET=<t>`
lines are at the top of `firmware/README.md`.

**The Plus2 needs an ESP-IDF older than 6.1.1.** The firmware needs 6.0
or later; the releases build the StickS3's and the generic image with
6.1.1 and the Plus2's with 6.0.3, since M5GFX doesn't build for the
`esp32` target with 6.1.1 (m5stack/M5GFX#425). `deploy.sh` builds every
board with the one ESP-IDF it finds, and with two in `~/.espressif` it
takes the newer. With 6.1.1, `deploy.sh build` builds the StickS3's and
stops at the Plus2's, so the generic image is not built, and flashing a
Plus2 fails the same way. Either set `IDF_PATH` to a 6.0.3, which builds
all three with it, or build the Plus2's alone with 6.0.3 by the `idf.py`
line in `firmware/README.md`. Delete a `build-<x>` that the other ESP-IDF
configured first: each has its own Python, and `idf.py` will not use a
build directory set up with another (it says to run `idf.py fullclean`).

- **Flashing replaces what is on the Stick** (UIFlow included). A StickS3
  flashed the first time needs boot mode: hold the side button until the
  green light flashes.
- **Ask before flashing.** A board on USB may be one the user is playing
  or measuring on; `watch` is safe, `flash` restarts it.
- Read a log with `deploy.sh watch` under the Monitor tool, not with
  `idf.py monitor` (which restarts the board and wants a terminal).

## Traps already met

- **M5Unified and M5GFX are pinned together** in
  `main/idf_component.yml`. Move them together and build both Sticks: M5GFX
  0.3.0 broke the S3 build, and M5GFX alone pulled M5Unified back to one
  whose StickS3 crashed. After a change, delete `build-*/esp-idf/m5stack__*`.
- A StickS3 build directory from before Bluetooth has it off in its
  `sdkconfig`; the build says to delete `build-esp32s3/sdkconfig`.
- The image fills about 80% of the StickS3's 2 MiB app slot, built with
  ESP-IDF 6.1.1 (`firmware/README.md` has the figures); watch the size when
  adding a service.
- Build directories are per checkout and gitignored: an agent worktree
  has none until it builds, and clangd/Serena find no C symbols there
  until then (`firmware/.clangd` points at `build-esp32s3`).

## Testing without a board

The services and the link core are plain C, also built for this computer:

```sh
make host     # build/libnesp_host.dylib, from firmware/components
make test         # tests/: test_core, test_link, test_peer, ... on every core
make test-apps APPS="jackal contra"   # those apps' own tests
```

Every app's tests run its ROM against that same library, so a change to
`nesp_services` can break an app's tests: run the apps it touches too.
pyenv's Python on this Mac has no pytest: the Makefile uses the `.venv`,
which has it and `pytest-xdist` (`requirements-dev.txt`); another Python
without `pytest-xdist` runs the tests one at a time. `tools/mesen_run.py
--bridge` runs a ROM in Mesen against the library (`host/mesen/README.md`).
`tools/lcd.py out` draws the Stick's screens, to try a layout before
flashing.

## On hardware

`firmware/README.md`, "Bringing it up": no hat, then the hat (a black
screen with it on means something reaches G0), the setup ROM (`NES:
SETP v1`), its link test (nothing but GOOD, slowest reply under 500 µs),
Wi-Fi from the controller. Real NES and the MiSTer with SNAC differ
electrically: a result on one is not a result on the other.

## Shipping

1. A pull request that changes what a player or a ROM sees adds one line
   under **Unreleased** in `CHANGELOG.md` (Firmware, Cartridge, Protocol
   or Games), with its number: what changed for them, not how.
2. A protocol change is a minor version; fixes are a patch version.
   A ROM that needs new firmware has its minimum raised in the release
   that brings it, and its patch's entry in `PATCHES` (`tools/gen_web.py`)
   names that release.
3. Releases (`docs/RELEASING.md`): `tools/release.py 0.x.0` from an
   up-to-date main makes `release-0.x.0`; merging its PR tags, builds the
   three firmwares and the cartridge, makes the GitHub release, and puts
   them on the site, whose flash page offers the hat's manifest and, from
   releases that have it, the generic one. Ask the user before cutting one.
4. Firmware on main reaches players only in a release; web pages and
   game patches go up when they merge.

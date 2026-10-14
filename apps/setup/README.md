# nesp32 Setup

A [nesp32](../..) has no keyboard. This ROM is its setup: plug the nesp32
into controller port 2, run the ROM, and use controller 1. It shows what
the nesp32 is and how it is doing, puts it on a Wi-Fi network, tests the
link, and lends a StickS3's files to a computer as a USB drive.

![The status screen](docs/status.png) ![Choosing a network](docs/list.png)
![Typing a password](docs/password.png) ![The link test](docs/test.png)
![The USB drive](docs/usb.png)

It is also the first user of nesp32's link, and the ROM that the tests of
the link are run on. It is one of the programs on
[the cartridge](../../docs/DEVELOPMENT.md#the-cartridge).

## Status

**It works on hardware.** With a StickS3 on the MiSTer's NES core,
through a SNAC adapter, it found the nesp32, joined a Wi-Fi network from
the controller, and the nesp32 joined it again by itself after a power
cycle. The link test ran 6000 requests with every one good, and the
nesp32's slowest reply was 215 microseconds
([the firmware's README](../../firmware/README.md), "On hardware"). It has
also run from the cartridge on a real NES, and with a StickC Plus2; no
figures were taken from those runs.

The USB drive works on hardware too: a StickS3's files lent to a
computer, and music copied to it.

## Using it

| Screen | Buttons |
|---|---|
| Status: the nesp32, its firmware, its Wi-Fi, address, signal, battery, and a menu: Wi-Fi setup, test interface, enable USB drive | Up, Down. A: choose |
| Networks, strongest first, with a lock on those that want a password | Up, Down. A: choose. Select: look again. B: back |
| Keyboard, for a password (or the name of a network that hides it) | D-pad. A: type. B: delete. Select: `abc`, `ABC`, `#+=`. Start: join |
| Link test: a checked request every frame, and the nesp32's time to reply | B: back |
| USB drive: a StickS3's files lent to a computer, for music to be copied to | B: back, and the nesp32 restarts |

Every printable character can be typed, and a password may be the full 63.
The nesp32 saves the network and joins it by itself from then on. The
password goes to the nesp32 and is never sent back.

The USB drive is how the jukebox's music gets onto a StickS3:
[nes-jukebox](../jukebox/README.md#music-on-a-nesp32) has what to copy and
where.

## Building

```sh
make            # build/setup.nes
make verify     # its size and header
make test       # needs nesp32's requirements-dev.txt, at the top
make preview    # the pictures above, from the ROM itself
```

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`) and Python 3.
`build/setup.nes` is NROM-256 (mapper 0). `make rom` at the top of the
repository builds the same ROM into the build directory there, for the
tests and for the cartridge.

## What is where

| Path | Purpose |
|---|---|
| `nes/setup.s` | reset, the NMI, and the screens' common code |
| `nes/status.inc`, `nes/wifi.inc`, `nes/keys.inc`, `nes/test.inc`, `nes/usb.inc` | each screen: status, networks, the keyboard, the link test, the USB drive |
| `nes/nrom256.cfg` | where the linker puts it |
| `tools/gen_screen.py` | the tiles, the header and the layout's numbers. The cartridge's menu has its tiles from here too |
| `tools/preview.py` | the pictures in `docs/` |

The link is nesp32's: [`docs/PROTOCOL.md`](../../docs/PROTOCOL.md) has the
line, the frames and the services this ROM asks for (SYS, NET and DIAG),
and `nes/lib/nesp.inc` at the top is the library it includes.

## Tests

The tests are among nesp32's own, in `tests/` at the top, because they
share its simulated console: `test_setup.py` works every screen with the
controller, to a network joined with a password of every character.
`test_link.py` and `test_link_timing.py` run this ROM too, as the console's
end of the link, and a second build of it (`make timeout-rom`) on the
library's other receiver.

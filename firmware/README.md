# The Stick's firmware

ESP-IDF 5.x and M5Unified, for an M5StickC Plus2 (`esp32`) or an M5StickS3
(`esp32s3`). One image serves every ROM: the ROM says which services it
needs (`../docs/PROTOCOL.md`).

**Status: working on a StickS3**, on the MiSTer's NES core through a SNAC
adapter ("On hardware", below). A real NES, a run of any length, and the
StickC Plus2 build have not been tried.

With ESP-IDF 5.5.5 the image is about 0.9 MB of the 2 MB slot, with no
warnings from this project's code.

Each board has its own build directory, since the two have different chips:

```sh
. ~/esp/esp-idf/export.sh
# a StickC Plus2
idf.py -B build-esp32 -D SDKCONFIG=build-esp32/sdkconfig -D IDF_TARGET=esp32 build
idf.py -B build-esp32 -p /dev/cu.usbserial-XXXX flash monitor
# a StickS3
idf.py -B build-esp32s3 -D SDKCONFIG=build-esp32s3/sdkconfig -D IDF_TARGET=esp32s3 build
```

Flashing replaces whatever is on the Stick, UIFlow included; M5Burner
brings UIFlow back.

M5Unified is fetched by the component manager on the first build
(`main/idf_component.yml`).

| Path | Purpose |
|---|---|
| `components/nesp_core` | frames, the CRC, the services' registry, who is asked what. No hardware; also built for the tests |
| `components/nesp_services` | SYS, NET (Wi-Fi) and DIAG, and `nesp_hal_t`, what they ask of the hardware |
| `main/link.c` | the UART and the one task that answers the console, on a core of its own |
| `main/radio.c` | Wi-Fi, its worker task, and the hardware as the services see it |
| `main/main.cpp` | M5Unified: the screen, the buttons, the battery, power off |
| `main/board.h` | the link's pins on each board |
| `partitions.csv` | two slots for the firmware, and the rest for files |

## How it keeps time

The console listens for a reply only until its next vblank, so the reply
has to begin within a few milliseconds of the request, every time.

- The link task is the only thing on core 1 at its priority. It sleeps on
  the UART driver's queue, with the receive interrupt set to fire on every
  byte, and wakes when a request's last byte is in.
- Services never wait. A scan or a join is an order left for the worker
  task in `radio.c`; what the services read is a snapshot kept under a
  spinlock.
- A reply goes out no sooner than 50 microseconds after the request, which
  is how long the console takes to turn from sending to listening.
- The time from the last byte to the reply is measured for every request,
  and the setup ROM's link test shows the last and the slowest.

## Bringing it up

In the order nes-jukebox's Stick was, each step isolating one thing:

1. **Build and flash**, with no hat on. The screen should say `NESP32`,
   `NES: waiting`, and `Wi-Fi: not set up`.
2. **Boot check with the hat on** and the console on: power-cycle the
   Stick. A black screen with the hat on and a normal start with it off
   means something reaches G0.
3. **The setup ROM** (`build/setup.nes`, from `make` at the top) on the
   console. Its status screen should go from `NOT FOUND` to `CONNECTED`
   within a second, and the Stick's to `NES: SETP v1`.
4. **The link test** (B on the status screen). Record after a minute:
   REQUESTS against GOOD, NO REPLY, WRONG, and the Stick's reply times. The
   target is a slowest reply under 500 microseconds and nothing but GOOD.
5. **Wi-Fi from the controller** (A on the status screen), with no USB
   cable on the Stick. Then power-cycle the Stick and see that it joins by
   itself.

## On hardware

A StickS3 with the NPN hat (TX on G8, RX on G1), on controller port 2 of a
MiSTer's NES core through a SNAC adapter, with firmware 0.1.0 and the setup
ROM:

| | |
|---|---|
| The Stick is found, and its status shown | yes |
| A network joined from the controller | yes |
| Joined again by itself after a power cycle, with no USB | yes |
| Link test | 6000 requests, 6000 good, none unanswered, none wrong |
| The Stick's time to reply | 74 microseconds for the last, 215 for the slowest |

The slowest reply is under half of the 500 microsecond target, and a
twenty-fifth of the 5.75 ms the setup ROM's longest exchange allows
(`../docs/PROTOCOL.md`, "Timing"). Against the 0.9 ms average and 3.9 ms
worst that the MicroPython firmware of nes-jukebox measured on a Plus2, an
application has about 3.5 ms more of every frame for its reply, which at
this rate is some 27 bytes.

What this run does not show: a real NES, whose port is electrically not the
SNAC adapter's (nes-radar's README has what differed before); more than a
couple of minutes; replies while the Stick is busy with a TLS handshake,
which nothing asks of it yet.

## Not done

- A real NES, a long run, and the StickC Plus2.
- Leaving UIFlow: a Stick that ships with UIFlow has to be flashed once
  over USB. M5Burner brings UIFlow back.
- Updates over Wi-Fi. The partitions are laid out for them.
- The `storage` partition is not mounted yet; the jukebox will want it.

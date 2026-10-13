# The Stick's firmware

ESP-IDF 5.x and M5Unified, for an M5StickC Plus2 (`esp32`) or an M5StickS3
(`esp32s3`). One image serves every ROM: the ROM says which services it
needs (`../docs/PROTOCOL.md`).

**Status: working on a StickS3**, on the MiSTer's NES core through a SNAC
adapter ("On hardware", below). It works on a StickC Plus2 as well, and
both boards on a real NES: the cartridge (`../docs/DEVELOPMENT.md`), its menu and
every program on it, has been run on each board with each console. No
figures were taken from those runs, and none has been of any length. The
jukebox runs on the same
Stick and core ("The jukebox", below). PEER, for two consoles playing one
game, has played a network game of nes-drmario's netplay ROM ("Two
consoles", below).

With ESP-IDF 5.5.5 the image is about 1.19 MB of the 2 MB slot, with no
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

`firmware/deploy.sh` does both for whichever boards are on this computer's
USB, telling a StickS3 from a StickC Plus2 by the name of its port, and
`firmware/deploy.sh watch` prints their logs without restarting them.

Flashing replaces whatever is on the Stick, UIFlow included; M5Burner
brings UIFlow back.

M5Unified, and for a StickS3 TinyUSB (`espressif/esp_tinyusb`), are fetched
by the component manager on the first build (`main/idf_component.yml`).

| Path | Purpose |
|---|---|
| `components/nesp_core` | frames, the CRC, the services' registry, who is asked what. No hardware; also built for the tests |
| `components/nesp_services` | SYS, NET (Wi-Fi), DIAG, WIKI, RAW, JUKE, PEER, RADAR, TUNER and WEATHER, the text code, the MP3 decoder (`mp3.c`, which is minimp3 from `../third_party`), and `nesp_hal_t`, what they ask of the hardware |
| `main/link.c` | the UART and the one task that answers the console, on a core of its own; the UART with framing off, for RAW |
| `main/store.c` | the files: LittleFS in the `storage` partition, and the jukebox's tracks in it |
| `main/radio.c` | Wi-Fi, its worker task, and the hardware as the services see it |
| `main/fetch.c` | one HTTPS GET at a time, in a task of its own, handed to a service as it arrives |
| `main/spike.c` | not part of the firmware: a measurement of decoding a radio station, built with `-D NESP_SPIKE=1` ("The radio", below) |
| `main/conn.c` | one connection to another nesp32, as datagrams, in a task of its own: PEER's, for two consoles |
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
  task in `radio.c`, and a fetch one left for the task in `fetch.c`, which
  makes the TLS connection and reads the reply on the other core. What the
  services read is kept under a spinlock, held for a few instructions.
  The connection to another nesp32 is the task's in `conn.c`: the link
  task leaves it bytes to send and takes the bytes that have come.
- What takes time and is the link task's own to do is done after the
  reply has gone: the services' `tick`. The jukebox reads its files there,
  a few dozen bytes at a time, when the console cannot ask again before
  its next vblank; a run of RAW's is fed from there every 2 ms.
- Nothing is logged between a request and its reply. Every ten seconds the
  main task logs the link's counters, what the link and fetch tasks have
  ever had left of their stacks, and the free memory.
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

NESpedia's ROM (`../apps/wiki`) has since run on the same Stick and
adapter: a search is fetched from Wikipedia over HTTPS, with the server's
certificate checked, and the article read from the 8 MB of PSRAM the board
reports. No figures were taken from that run.

What these runs do not show: figures from a real NES, whose port is
electrically not the SNAC adapter's ([`docs/WIRING.md`](../docs/WIRING.md) has what differed
before), though the cartridge has since worked on one; more than a few
minutes; how long the Stick's replies took while it was making a TLS
connection, which the log's report every ten seconds would say.

## The jukebox

On the same StickS3 and MiSTer, with nes-jukebox's link ROM and tracks put
there by `tools/put_files.py`:

| | |
|---|---|
| Tracks written over USB are found and played | yes |
| Music: three tracks, changed from the controller and from the Stick, and following one another | sounded right |
| Sampled sound, at 20338 samples a second (223722 baud) | sounded right; it ended by itself, and the next track followed |
| A button on the Stick during a sound | ends it and changes the track |
| Requests | about 15000, none answered twice; the console's buffer never ran dry |
| The Stick's time to reply | about 70 microseconds, 474 for the slowest |
| The link task's stack | 9124 bytes of 12288 never used |

So the file reads do not land on the way to a reply, and the UART's change
of rate and back works with the driver installed. Not tried: the five
slower rates of sound, and a long run.

RAW's runs of the test pattern have since run there, with nes-throughput's
test ROM: 298296 baud to the console, the last rate its CPU can
do, and 223722 from it. The first try heard 194 of every 256 bytes from
the console, at any rate. The UART's stop bits are one setting for both
ways, two for what the console is sent, and the StickS3's receiver then
waits for two, where a run from the console has one and nothing after it.
The UART is now set for one while such a run is heard (`link_line_hear`).

The steps it was brought up by, for another board or after a change, each
isolating one thing:

1. **The files.** Flash this firmware; its log should say `store: 0
   tracks` (the first start formats the partition, which takes a few
   seconds). Then `tools/put_files.py` with a directory of tracks, from
   the top of the tree (nes-jukebox's `tools/deploy.py` makes one and calls
   it). The log should then count them. If it says 0, or the partition is
   formatted again at every start, the image is not one this firmware's
   FAT and wear levelling mount. (The files were in LittleFS when this was
   done on hardware; with FAT it is still to do.)
2. **Music.** nes-jukebox's `build/jukebox_link.nes` on the console. The
   nesp32's screen should say `NES: JUKE v2`, the track, and `STOPPED`; the
   console's, `PRESS START`. Start, or the nesp32's button A, plays. On
   the nesp32's screen `again` counts replies it had to send twice and
   `dry` frames the console had nothing to play: both should stay at 0,
   and the reply times where the setup ROM's link test had them. The file
   reads are what is new here: a slowest reply of more than a millisecond
   or two would be one of them landing where it should not.
3. **Sound.** A playlist with a `.pcm` track. The nesp32's screen says
   `SOUND` while it plays. What this leans on: `uart_set_baudrate` to the
   sound's rate and back with the driver installed, the transmit buffer's
   free size as the pump reads it (`link_line_write`), and
   `uart_wait_tx_done` as the sign that the last sample has left
   (`link_line_idle`). A sound that drags is the pump not keeping up; one
   after which the console says `WAITING FOR LINK` is the rate not having
   gone back.
4. **The buttons**, the nesp32's and the controller's, during music and
   during a sound.

## The radio

TUNER plays a radio station on the console ([NPR](../apps/npr)'s ROM): the
fetch task decodes the station's MP3 as it arrives, which is the first
thing this firmware does that is heavy and never stops. **It works on a StickS3**: the station played, with clear speech, and the
ring neither ran dry nor dropped anything in a first minute; no longer
run has been made. With it the StickS3's image is 1.30 MB, 29 KB more than
before: 20 KB of that is the decoder. The fetch task's stack went from 12
to 32 KB, since the decoder keeps 16 KB there while it works, and the
ring of samples is 256 KB of PSRAM.

Whether a nesp32 decodes fast enough can be measured with no console and
no hat:

```sh
idf.py -B build-spike -D SDKCONFIG=build-spike/sdkconfig -D IDF_TARGET=esp32s3 \
       -D NESP_SPIKE=1 build
idf.py -B build-spike -p /dev/cu.usbmodemXXXX flash monitor
```

Once the nesp32 has joined its network it fetches the station, decodes
it, throws the samples away, and logs every ten seconds: how much sound
came in how long, the share of a core the decoding took, the slowest
piece, and what the fetch task's stack has left.

On a StickS3, over 70 seconds of NPR's stream (32 kHz, two channels, 96
kbps), with the CPU at its default 160 MHz and the decoder's memory in
PSRAM:

| | |
|---|---|
| Decoding | 11.5% of a core: a second of sound in 115 ms |
| The slowest piece of the stream (1 KB, two or three frames) | 15.3 ms |
| The fetch task's stack | 14952 bytes of 32768 never used |
| On connecting | 14 seconds of sound in the first 10: the station sends some four seconds at once |
| Frames decoded, and bytes that were no frame's | 2074, and none |
| Free memory | 113 KB internal, 8.3 MB of PSRAM |

## Two consoles

Network games of nes-drmario's netplay ROM have been hosted, joined and
played on hardware with this firmware, a StickS3 on the console that
hosted and a StickC Plus2 on the one that joined, one of them for 35
minutes. That ROM's README has what the logs counted: a delay of 1 tick
for most of every game, about one frame in a hundred waiting for buttons,
and next to no reply misheard. Under the tests the service runs
against that ROM on two simulated consoles; `conn.c` runs only on a
nesp32. What to look for, with that ROM (`../apps/drmario`,
`build/drmario_net.nes`) on each console:

1. **One console, no other.** A computer on the cable in place of a
   nesp32, `host/serial_host.py <port> --idle`: HOST GAME starts a game at
   once against an opponent who never presses a button. This tries the ROM
   and the link, and nothing of `conn.c`.
2. **One nesp32.** Its screen should say `NES: DRMA v2` once the ROM's
   menu is open (2 PLAYER GAME on the title), and the menu the nesp32's
   address. HOST GAME: the nesp32's screen says `Waiting for player 2` and
   the address again. The log says if it could not listen.
3. **Two ends.** The other console with a nesp32, or with a computer on
   the cable (`host/serial_host.py <port> --game`): JOIN GAME there, the
   first one's address, Start. Both screens say which player they are,
   and the game starts on both. In play `waiting` on a nesp32's screen
   counts frames in which its console brought it no new buttons, which is
   a game standing still for a frame; on one network it should grow
   slowly, and the reply times stay where the setup ROM's link test had
   them.
4. **One end switched off**, and the other console back at its title
   within a few seconds.

What `conn.c` leans on: lwIP's sockets from a task on the Wi-Fi's core, a
non-blocking `connect` waited for with `select`, and a look for received
bytes once a millisecond.

## Not done

- A long run, and figures from a real NES and from the StickC Plus2.
- Figures from PEER on hardware (above).
- Leaving UIFlow: a Stick that ships with UIFlow has to be flashed once
  over USB. M5Burner brings UIFlow back.
- Updates over Wi-Fi. The partitions are laid out for them.
- A way to put files on a nesp32 without a cable. A StickS3 is a USB drive
  when the setup ROM asks (`main/usb.c`), and `tools/put_files.py` writes
  the whole `storage` partition over USB.
- The FAT files, the rips converted at start, and the USB drive on
  hardware: all three build and are tested as far as a computer can.

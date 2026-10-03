# NES Jukebox on an M5Stack Stick

The jukebox's host: a Stick on M5Stack's **UIFlow 2.0** firmware (MicroPython)
that holds the music as `.jbs` files and answers the NES's requests over the
controller-port link. The same firmware runs on two boards and picks its pins
by asking UIFlow which one it is on:

| Board | Role | TX | RX |
|---|---|---|---|
| M5StickS3 | the product | G8 (hat slot 5) | G1 (hat slot 4) |
| M5StickC Plus2 | stand-in for testing until an S3 is on hand | G26 (hat slot 3) | G36 (hat slot 4) |

This is a proof of concept. **It has played music on a real NES from a
StickC Plus2**: about two minutes with no resends and no errors counted by
the console, and the buttons start, stop and change tracks at once. It has not run on a StickS3 yet, and has had no long run on
either. The protocol and playlist code is also tested byte for byte against
the desktop host and against the simulated NES (`tests/test_stick.py`).

## The hat

The level shifter is nes-radar's two-transistor NPN hat, unchanged; see
[its README](../../../nes-radar/firmware/stick_s3/README.md) for the circuit
and the reasons. Only the slot the TX wire lands on differs between boards:

| Hat slot | StickS3 | StickC Plus2 |
|---|---|---|
| 1 | GND | GND |
| 2 | EXT_5V, not connected | 5V OUT, not connected |
| 3 | **G0: nothing may touch it** | G26: **TX**, to the TX base resistor |
| 4 | G1: **RX**, from the RX collector | G36/G25: **RX**, from the RX collector |
| 5 | G8: **TX**, to the TX base resistor | **G0: nothing may touch it** |
| 6 | BAT, not connected | BAT, not connected |
| 7 | 3V3_L2: RX pull-up | 3V3: RX pull-up |
| 8 | 5V_IN, not connected | 5V IN, not connected |

G0 is the boot-mode pin on both boards. A hat wired for the S3 has its TX
base resistor on slot 5, which is G0 on a Plus2: the resistor holds G0 near
1.2 V through the transistor, and the Plus2 may start in download mode
instead of running anything. So **on a Plus2 the TX wire goes to slot 3**,
and it moves back to slot 5 for the S3 (nes-radar's "Converting a Plus2
hat"). RX stays on slot 4 for both.

The jukebox runs the link at 38400 baud, four times nes-radar's rate, so the
RX stage's base resistor matters more here. The Plus2 hat design used 10 kΩ;
the S3 design uses 100 kΩ so a MiSTer SNAC adapter's strobe still works,
which slows the stage's edges. Either should work at 38400 on a real NES;
`tools/link_monitor.py` is the test.

## Setup

1. **UIFlow 2.0** on the Stick. If it shows the UIFlow launcher at power-on,
   it is there. Otherwise flash *UIFlow2.0 StickC Plus2* (or *StickS3*) with
   [M5Burner](https://docs.m5stack.com/en/uiflow2/m5burner/intro). Save a
   Wi-Fi network in M5Burner's configure step even though the jukebox never
   uses it: UIFlow's own `boot.py` stops with a blank screen when none is
   saved. nes-radar's `tools/set_wifi.py` does the same job from a terminal.
2. **Deploy**, with the Stick on USB:

   ```sh
   pip install mpremote
   tools/deploy.sh                      # everything in ../../music
   tools/deploy.sh -p /dev/cu.usbserial-XXXX music/a.vgz music/b.vgz
   ```

   It converts the music to `.jbs` on this computer, copies it and the
   firmware to `/flash`, and sets UIFlow to start the jukebox at power-on.
   Name the port when the FTDI test cable is plugged in too.
   `tools/restore_uiflow.sh` brings the UIFlow launcher back.
3. **Optional `config.json`** next to `config.example.json`: `board` (`"s3"`
   or `"plus2"`) if the screen says `unknown board`, `tx` and `rx` pin
   numbers for a hat wired some other way, `invert` (`false` for a
   non-inverting shifter), `loops`, and `repeat`.

## Using it

Plug the hat into controller port 2 and start `build/jukebox_link.nes` on the
console. The order of powering up does not matter.

Nothing plays until you press a button. The Stick starts stopped, shows
`STOPPED` once it hears the console, and answers the console's
requests with nothing to play.

| Button | What it does |
|---|---|
| **A** (front) | pause, resume. From stopped (as at power-up), play the track shown from its start |
| **B** (side) | previous track, and play it |
| **Power**, tapped | next track, and play it |
| **B**, held 2 s | power off |

The NES's controller 1 does the same through the link: **Start** or **A**
is the Stick's A, **Left** its B and **Right** its power button. The
Stick's screen follows.

- A pause is heard within a few frames and keeps what the NES has
  buffered, so the music goes on from the same place.
- Track changes are heard at once, and the music starts again
  after about half a second: the Stick tells the NES to drop the few
  seconds it has buffered.
- Resetting the NES while a track plays starts that track again. Resetting
  it while stopped leaves it stopped.
- The power button is read as UIFlow's `M5.BtnPWR`. It works on the StickC
  Plus2; the StickS3's has not been tried, and a build without one has no
  next-track button (the NES's controller still has one).

The screen shows the track being sent, and once a second:

| Row | Meaning |
|---|---|
| TIME | position in the track and its length. The NES does not report its position: the Stick works it out from when the NES's buffer filled, so it can be a moment off, and rests at 0:00 for the few seconds before a track that follows another by itself is heard |
| STATE | `PLAYING`, `PAUSED` or `STOPPED` while requests arrive, `WAITING FOR NES` otherwise |
| LINK | bursts sent, and the share of requests that were repeats. A repeat is a burst the NES missed |
| REPLY | the average and slowest reply in the last second, in ms: the firmware's own time from bytes in to handing the burst to the UART. Then bytes that were not part of a request |

The console's own counters (cut-offs, timeouts, rejects, CRC errors,
underruns) are no longer on the screen; they are in the USB log line.

The NES row says *why* bursts were resent. Cut-offs mean replies are
arriving too late in the frame, timeouts mean they are not arriving at all,
and rejects or CRC errors mean bytes are damaged on the wire. They are
totals since the Stick first heard from the console, or since the console
was switched on if that came later, so nothing from an earlier test shows.

Every 5 s it also prints a line over USB (`mpremote` shows it) with the same
counters by name, and the longest pauses: `write` (handing a burst to the
UART), `chore` (buttons, battery and screen), `log` (printing this line) and
`gc` (garbage collection).

## Bring-up on hardware

Do these in order; each isolates one thing.

1. **The NES side alone**, with the desktop host and the FTDI cable
   (`host/jukebox.py`, see the top-level README). If music plays there, the
   ROM and the console are good, and anything wrong later is on the Stick's
   side.
2. **Boot check.** With the hat on and the NES on, power-cycle the Stick. It
   must start the jukebox and show `WAITING FOR NES` or `PLAYING`. A black
   screen with the hat on, and a normal start with it off, means something
   reaches G0.
3. **NES to Stick only:** `mpremote run tools/link_monitor.py`, then start
   the link ROM. Expect `HELLO`, then `DATA seq 0 credit 24`, and a data
   count that climbs by about 13 a second with the noise count standing
   still. The `NES:` line should show `timeouts` climbing and nothing else,
   since nothing is answering. The Stick's screen says `LINK MONITOR`; the
   output is on USB. This proves OUT0, the RX stage and the baud rate without the Stick
   sending anything. Run `mpremote reset` afterwards.
4. **Play.** Reset the NES. Record from
   the screen after a minute: the resend share, the reply times, and the
   NES row. On the FTDI cable the same ROM ran 625 requests with no resends
   and no counter moving, so that is the mark to compare against. Under 5.5 ms of total reply time the
   link runs at full rate with no resends; a few percent of resends is
   harmless (see docs/PROTOCOL.md, Timing).

On a StickC Plus2 this gave 1433 bursts with no resends, replies of 0.9 ms
on average and 3.9 ms at worst, and every NES counter at zero. No longer
run has been done.

## Files

| Path | Purpose |
|---|---|
| `nesjuke/protocol.py` | requests, bursts and resends; a port of `host/protocol.py` |
| `nesjuke/tracks.py` | `.jbs` files and the playlist stream; a port of `host/playlist.py` |
| `nesjuke/player.py` | the reply loop |
| `nesjuke/board.py`, `ui.py`, `device.py` | pins and UART per board, the screen, and the main loop (UIFlow only) |
| `tools/deploy.sh`, `tools/pack_tracks.py` | convert music and copy everything to the Stick |
| `tools/link_monitor.py` | bench helper for step 3 |
| `tools/stick_repl.py`, `tools/restore_uiflow.sh` | from nes-radar: run code without a soft reset; go back to the UIFlow launcher |

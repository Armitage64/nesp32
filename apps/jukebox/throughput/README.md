# Link throughput test

How fast can the controller-port link go on the hardware in front of you?
The jukebox runs it at 38400 baud both ways. This test finds the fastest
rate that is stable in each direction, for whichever Stick, hat and cable are
plugged in, so the margin over 38400 is a number.

It is a ROM for the console and a script for the Stick, and is kept apart
from the jukebox: none of the jukebox's code changed to make it, and nothing
here is part of the player.

**Status: run on a StickC Plus2 and a real NES**, where it reached 298296
baud to the NES, the last rate the console's CPU can do, and 223722 baud
coming back. See "Hardware results" and "What the runs taught". The build
here differs from the one last run in one way: the fast receiver now also
takes the rates below 162707 baud.

## What it measures

| Name here | Direction | On the wire |
|---|---|---|
| RX, "to NES" | Stick to console, D0 | 8N2, as the jukebox's bursts |
| TX, "to Stick" | console to Stick, OUT0 | 8N1, as its requests |

A rate is a whole number of NES CPU cycles per bit, so the console's
bit-banged routines hit every bit exactly; the Stick's UART is set to the
nearest baud rate. Both directions share 14 rates from 186 cycles (9622
baud) to 13 (137675 baud). 47 cycles is 38080 baud, the jukebox's rate to
within 1%. Above those each direction goes as far as its routines can:

| Direction | Extra rates | Why it ends there |
|---|---|---|
| to NES | 12, 11, 10, 9 and 8 cycles (223722 baud) with the fast receiver; 7 and 6 (298296 baud) with the tracking one | a sample takes 6 cycles: shift, XOR the port in. Then 5 cycles (357955 baud), which is there to fail |
| to Stick | 12, 11, 10, 8 and 6 cycles (298296 baud) | a bit takes 6 cycles: write, shift |

**Two receivers, neither of them the jukebox's.** The jukebox takes 11
cycles to sample a bit and hunts for the start bit with a loop that looks
every 9. An earlier build of this test used that receiver up to 149148
baud, where it passed on hardware; it is gone, since a faster one covers
every rate it did.

The fast receiver keeps the byte in A and folds each read into it (shift
left, XOR the port: 6 cycles), and it hunts by comparing the port with what
it reads at a start bit (6 cycles a look). It leaves every byte
bit-reversed, inverted and with the port's other bits mixed in, and the
console puts the block right from a table once it has all arrived. It
takes every rate down to 8 cycles a bit.

At 8 cycles a bit that hunt is nearly a bit long, so at 7 and 6 the
tracking receiver does not hunt. Once a byte it looks at the line at the moment the
start bit should fall. If the line is already low it is late, and takes a
cycle less to reach its first sample; if still high it is early, and takes
a cycle more. That holds its samples within 2.5 cycles of the middle of a
bit, and follows a Stick whose clock is up to about 1% off. At 6 cycles a
bit nothing in its loop is padding, so this is the last rate there is. It
finds a block's first byte by hunting and is up to 6 cycles out at first,
so the first 8 bytes of its blocks are `$FF` for it to settle on, and are
not checked: a block there carries 248 bytes of data.

**One rate too many.** The last rate to the NES is 5 cycles a bit, 357955
baud. The console has no routine for it and runs its 6-cycle one, which
needs 66 cycles for a byte that lasts 55. It is on the ladder to be seen
failing, as a check on the CPU figure: it shows 120%, and nearly every
byte of its first block is wrong.

Both count on the unused bits of `$4017` reading the same every time: `$40`
with the line at rest. Before a run the Stick asks the console what its
port reads. On any other answer nothing can be received, so it runs no
rates to the NES and says so in the log.

**Two senders.** Down to 8 cycles a bit the console loads the next byte
during the start bit, and needs 11 cycles between bytes. At 6 there is no
room for that, so it loads the byte first and needs 13. Either way the
stop bit is then longer than the data bits, which a UART does not mind, and
the bytes a second allow for it.

One direction is tested at a time, in blocks of 256 pseudo-random bytes sent
back to back. A trial is 4 blocks, 1024 bytes, and is clean when no byte in
it is wrong. The test tries each rate once, from the slowest up, until a
trial fails, and backs off to the rate before it. No rate is tried twice.

The result for each direction is the fastest rate that passed, with the
payload rate it gives in bytes a second.

A whole run takes about 35 seconds in simulation when every rate passes;
expect a little more on a Stick.

## Running it

Needs what the jukebox needs: cc65 to build, and a Stick already set up by
`../firmware/stick/tools/deploy.sh`.

```sh
make                      # build/linktest.nes
stick/run.sh              # or: stick/run.sh -p /dev/cu.usbserial-XXXX
```

1. Start `build/linktest.nes` on the console, with the hat in controller
   port 2. The screen says `WAITING`.
2. Run `stick/run.sh` with the Stick on USB. It copies `stick/linktest` to
   `/flash/linktest` and starts it; the log comes back on the terminal.
3. When the console says `PRESS START`, press Start on controller 1 or
   button A on the Stick. Nothing is tested until then.
4. When it says `DONE`, either button runs it again. Ctrl-C stops
   it, and `mpremote reset` puts the Stick back in the jukebox.

The order does not matter, and either side can be restarted in the middle.

The console's screen has the jukebox's header, the name in its big letters
over what this is and the credit line, then the Stick-to-NES test and under it the
NES-to-Stick test. Each half shows the trial that is running.
This is a run on a simulated line with slow edges, partway through the
second direction:

```text
        N - E S P - 3 2
         THROUGHPUT TEST
        RETRO BITS (2026)

  TESTING

  STICK TO NES
   STATUS  DONE
   SPEED   85227 BPS
   SENT    1024 BYTES
   BAD     0 BYTES
   CPU     30%
   FASTEST 7747 BYTES/S

  NES TO STICK
   STATUS  CLIMBING
   SPEED   52640 BPS
   SENT    512 BYTES
   BAD     0 BYTES
   CPU     20%
   FASTEST
```

| Row | Meaning |
|---|---|
| STATUS | `WAITING`, `CLIMBING`, then `DONE` |
| SPEED | the rate of the trial that is running, in bits a second on the wire (the baud rate) |
| SENT | bytes sent in this trial so far; it counts up a block at a time |
| BAD | bytes of those that arrived wrong. A trial stops at its first bad block |
| CPU | the share of the console's CPU the rate takes, below |
| FASTEST | once the direction is done: the payload rate, in bytes a second, of the fastest rate that held |

When a direction is done its half goes back to the rate that held, with
that trial's figures, and stays up. The trial that failed is on the screen
only while it runs; its line stays in the Stick's log.

**CPU** is the share of the cycles in a byte that the console's routine
spends on instructions it needs; the rest is padding between bits and
waiting for the next start bit. It is worked out from the routines, not
measured, and is the same on every run. Near 100% there is no rate left to
gain whatever the wire does. The CPU is busy for the whole of a block
either way, since the routines count cycles.

| | 9622 baud | 38080 | 137675 | 149148 | 162707 | 223722 | 255682 | 298296 | 357955 |
|---|---|---|---|---|---|---|---|---|---|
| to NES | 3% | 13% | 48% | 48% | 53% | 73% | 86% | 100% | 120% |
| to Stick | 4% | 14% | 52% | 55% | 61% | 81% | | 97% | |

The figure rises all the way up each ladder. The run on hardware bears it
out at the top: 298296 baud to the NES, at 100%, was the last rate to pass.

The Stick's screen shows the two results, what it is doing, and the last
trial. The terminal gets a line for every trial:

```text
RX  85227 bps: 0 of 1024 bytes bad, cpu 30%, 693 ms
RX  94199 bps: 73 of 256 bytes bad, cpu 33%, 210 ms
RX fastest stable: 85227 bps 7747 b/s
```

On a line with no limit of its own, the climb to the NES ends like this:

```text
RX 298296 bps: 0 of 1024 bytes bad, cpu 100%, 598 ms
RX 357955 bps: 247 of 256 bytes bad, cpu 120%, 191 ms
RX fastest stable: 298296 bps 27117 b/s
```

A trial stops at its first block with a bad byte, so a failed one is short.
The time is there to show that the rate is real: each block is some 30 to
70 ms of waiting, a draw for the screen's count, and its time on the wire,
which is 0.3 s at 9622 baud and under 0.02 s at the fastest rates, so the
trials get quicker all the way up.

The last line also counts commands that had to be repeated and blocks that
stalled (below). Both should be 0 on a line that works at 9622 baud.

## Reading the result

- This is the rate of the wire and the two bit-banged routines with nothing
  else going on. The jukebox gets less out of a rate than `B/S` says: its
  bursts stop for every vblank and wait for a reply.
- The console's receivers are the tighter side by design. The fast one
  finds a start bit with a loop, so its samples sit up to 3.5 cycles off
  the center of a bit. The sender has no such slack to lose. In simulation
  the baud error the fast receiver takes falls from 5.5% at 9622 baud to
  1.5% at 223722; the tracking one takes 1% at 255682 and 298296.
- A direction that ends on the last rate of its ladder passed everything
  there is. Its limit is then the console's routine, not the wire.
- A trial is 1024 bytes, so "stable" means no bad byte in about a
  thousand, and a rate that fails once in a few thousand bytes can pass.
  Raise `TRIAL_BLOCKS` in `stick/linktest/tester.py` to ask for more.

## Protocol

The Stick is in charge, the reverse of the jukebox's link: it sends a
command and the console answers. Commands and replies always travel at the
slowest rate, 9622 baud (nes-radar ran this wiring at 9600), whatever rate
is under test.

```text
command   $C5, SEQ, OP, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
reply     $9A, SEQ, OP, VALUE_LO, VALUE_HI, CRC_HI, CRC_LO
```

The CRC is the jukebox's CRC-16/CCITT-FALSE, over `SEQ` up to the CRC. A
command with a bad CRC gets no reply, and the Stick sends it again.

| OP | Name | Payload | The console |
|---|---|---|---|
| 1 | ping | none | replies with its number of rates to the Stick (high byte) and to the NES; the Stick refuses a ROM built from other ladders |
| 2 | draw | PPU address, high byte first, then up to 32 tiles | writes them at the next vblank; replies 0 |
| 3 | rx | rate (an index into that direction's ladder), seed (low, high) | receives a block at that rate; replies with the number of bytes that differ from the seed's pattern; at the tracking receiver's rates the first 8 bytes are `$FF` and are not counted |
| 4 | tx | rate, seed | sends the seed's pattern as a block at that rate; no reply |
| 5 | port | none | replies with what its `$4017` reads; the receivers need `$40` |
| 6 | pad | none | reads controller 1 and, 30 ms later, replies with its buttons (A in bit 7, Start `$10`); the Stick asks while it waits to be started |

A reply of `$FFFF` means the console could not do it (a rate it does not
have, a seed of 0).

The pattern is a 16-bit xorshift (7, 9, 8) started from the seed, one byte a
step, the same on both sides (`proto.pattern`, `prng_next`). The font has
each character at its ASCII code, so a draw's tiles are plain text and the
Stick lays out the whole screen.

**Changing rate.** After an rx or tx command the console waits 30 ms before
it listens or sends, and after an rx block it waits 30 ms again before it
replies. The Stick changes its UART's rate inside those waits, so whatever
that does to the line is never taken for a start bit.

**No interrupts, no timeouts.** Anything that takes cycles from a bit-banged
routine would count as a line error, so the test ROM never enables the NMI
and draws only when told to, waiting for vblank by polling. It cannot time
out either: a block that loses bytes leaves the console waiting for the
rest. The Stick sees no reply and sends *filler*, zero bytes at the control
rate, whose long lows the console takes for bytes at any rate until the
block is full. Such a block counts as bad and as a *stall*. A Stick that
starts up does the same until its ping is answered, which frees a console
left waiting by a run that was cut short.

## Files

| Path | Purpose |
|---|---|
| `nes/linktest.s`, `nes/linktest.cfg` | the test ROM: commands, replies, the screen |
| `tools/gen_rates.py` | writes the ROM's cycle-timed receive and send routines, one pair per rate |
| `tools/gen_screen.py` | the jukebox's font (at ASCII codes), palette and header, and the opening screen |
| `stick/linktest/rates.py` | the ladder of rates, shared by the ROM's generator and the Stick |
| `stick/linktest/proto.py` | frames, the CRC, the pattern |
| `stick/linktest/tester.py` | blocks, the search, and both screens' text; plain Python |
| `stick/linktest/device.py` | the Stick's UART, screen and button (UIFlow only) |
| `stick/run.sh` | copy to the Stick and run |
| `tests/` | pytest: every routine's timing on py65, and the Stick's code against the ROM over a simulated wire |

It borrows from the jukebox at build time: `../tools/gen_crc_table.py` and
the font in `../tools/gen_ui.py`.

```sh
make test                 # these tests only; the top-level `make test` runs them too
```

In simulation every routine reads and writes on the cycle it should at
every rate; a clean line passes every rate both ways but the one that is
there to fail, also with the Stick's clock 1% off; and lines with slow rising edges (which is what the
hat's transistors give) make the search stop where the blocks start to
fail. Damaged commands, a block with bytes missing, and a console left in
the middle of a block all recover.

## Hardware results

On a StickC Plus2 and a real NES, with 1024-byte trials:

| Direction | Fastest rate that passed | What stopped it |
|---|---|---|
| Stick to NES | 298296 baud, about 27000 bytes a second | nothing: it was the last rate the console's CPU can do, and the 357955-baud rate above it failed as it should. The port reads `$40` there |
| NES to Stick | 223722 baud, 21563 bytes a second | 298296 baud failed. The console's sender has no slack there, so this is the wire, the hat or the Stick's UART |

That run still had the jukebox's own receiver on the rates up to 149148
baud, which all passed.

## What the runs taught

- **To the NES, the limit is the console's CPU, not the wire.** The hat's
  TX stage, the cable and the port's buffer carried 298296 baud cleanly.
  The rate one step past it, which needs 120% of the CPU, failed, and the
  rate at 100% passed, so the CPU figures are right.
- **From the NES, the limit is on the Stick's side.** 223722 baud passed
  and 298296 failed. The console's sender is cycle-exact at both, so what
  gave out is the hat's RX stage, the wire or the UART.
- **The jukebox's kind of receiver is good to 149148 baud** on this hat,
  with two stop bits: the same sampling and start-bit hunt, timed for each
  rate. The jukebox runs at 38400, so its link has about four times the
  rate in hand, and 57600 is no risk on a Plus2.
- **Sampling can cost 6 cycles a bit, not 11**, by keeping the byte in A
  and XORing the port into it. The price is that it counts on bits 1 to 7
  of `$4017` always reading `$40`, which this console's do, and that bytes
  must be unscrambled afterwards.
- **Hunting for each start bit stops working near 8 cycles a bit**, where
  a look every 6 or 7 cycles is most of a bit. Past that the receiver has
  to predict the start bit and correct by a cycle a byte, which needs a
  few bytes to lock and a sender within about 1% of the right rate.
- **An ESP32 UART leaves a byte of junk in its receiver when its rate is
  changed** under MicroPython's `uart.init`. Its transmitter is clean
  across the change. Anything that changes rate and then counts bytes by
  position has to drop what is there first.
- **Each direction should be judged by itself.** The first design had one
  ladder for both, and both passed all of it; the real limits only showed
  once each had rates up to what its own routine could do.
- **What it does not show:** these are rates with the console doing
  nothing else and no interrupts. At 298296 baud the receive loop has no
  spare cycle, so nothing can be done with a byte until the block is in.

Still untried:

- **The fast receiver below 162707 baud**, where it has taken over from
  that one. It is the same sampling and hunt as the rates it passed at,
  with longer padding.
- **The StickS3.**
- **Changing the UART's rate** works on the Plus2, with one catch that the
  first run found: every changed rate from the console failed with nearly
  all 256 bytes bad. One junk byte ahead of a block does that, since bytes
  are compared by position, so the Stick now drops what its receiver holds
  10 ms after a change. A failed block from the console is logged with its
  length and first bytes.
- **`uart.flush()`** is used to wait for bytes to leave, with a sleep for
  the time they take as a floor.
- **OUT1 and OUT2.** The send routines write the whole byte to `$4016` and
  shift it, so bits 1 and 2 toggle OUT1 and OUT2 as well. Those reach only
  the expansion port on a stock console.
- **Vblank by polling `$2002`** can miss a vblank now and then. A draw then
  takes a frame longer, which the Stick's timeout allows for.

Nothing here runs over the FTDI cable. `tester.py` only needs a port with
six methods (see its header), so a pyserial one would be short to add.

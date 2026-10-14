# Link throughput test

How fast can the controller-port link go on the hardware in front of you?
nesp32's link runs at 85227 baud both ways. This test finds the fastest
rate that is stable in each direction, for whichever nesp32, hat and cable
are plugged in, so the margin over 85227 is a number.

It is a ROM for the console, and the nesp32 needs nothing but its
firmware: [nesp32](../..) is one firmware for every ROM, and this
one asks it for its RAW service, which carries a run of bytes at any rate
with framing off. Nothing is copied to the nesp32 and nothing is run on a
computer. The test began in the jukebox's tree and is a program of its
own now; it still has the jukebox's font and header.

**Status: run on a StickS3 with the MiSTer's NES core**, where it reached
298296 baud to the console, the last rate the console's CPU can do, and
223722 baud coming back. Those are the rates the test found on a real NES
before October 2026, when it was a ROM with the same receive and send
routines and a MicroPython script on a StickC Plus2; that script, its
protocol and its tests are in this repository's history. It has also run
on a real NES with a StickC Plus2 wired through a breadboard. See
"Hardware results" and "What the runs taught".

## What it measures

| Name here | Direction | On the wire |
|---|---|---|
| "nesp32 to NES" | nesp32 to console, D0 | 8N2, as the link's replies |
| "NES to nesp32" | console to nesp32, OUT0 | 8N1, as its requests |

A rate is a whole number of NES CPU cycles per bit, so the console's
bit-banged routines hit every bit exactly; the nesp32's UART is set to the
nearest baud rate. Both directions share 14 rates from 186 cycles (9622
baud) to 13 (137675 baud). 21 cycles is 85227 baud, the link's own rate.
Above those each direction goes as far as its routines can:

| Direction | Extra rates | Why it ends there |
|---|---|---|
| to NES | 12, 11, 10, 9 and 8 cycles (223722 baud) with the fast receiver; 7 and 6 (298296 baud) with the tracking one | a sample takes 6 cycles: shift, XOR the port in. Then 5 cycles (357955 baud), which is there to fail |
| to nesp32 | 12, 11, 10, 8 and 6 cycles (298296 baud) | a bit takes 6 cycles: write, shift |

**Two receivers, neither of them the link's.** The link takes 11 cycles to
sample a bit and hunts for the start bit with a loop that looks every 9.

The fast receiver keeps the byte in A and folds each read into it (shift
left, XOR the port: 6 cycles), and it hunts by comparing the port with what
it reads at a start bit (6 cycles a look). It leaves every byte
bit-reversed, inverted and with the port's other bits mixed in, and the
console puts the block right from a table once it has all arrived. It
takes every rate down to 8 cycles a bit.

At 8 cycles a bit that hunt is nearly a bit long, so at 7 and 6 the
tracking receiver does not hunt. Once a byte it looks at the line at the
moment the start bit should fall. If the line is already low it is late,
and takes a cycle less to reach its first sample; if still high it is
early, and takes a cycle more. That holds its samples within 2.5 cycles of
the middle of a bit, and follows a nesp32 whose clock is up to about 1%
off. At 6 cycles a bit nothing in its loop is padding, so this is the last
rate there is. It finds a block's first byte by hunting and is up to 6
cycles out at first, so the first 8 bytes of its blocks are `$FF` for it
to settle on, and are not checked: a block there carries 248 bytes of
data.

**One rate too many.** The last rate to the NES is 5 cycles a bit, 357955
baud. The console has no routine for it and runs its 6-cycle one, which
needs 66 cycles for a byte that lasts 55. It is on the ladder to be seen
failing, as a check on the CPU figure: it shows 120%, and nearly every
byte of its first block is wrong.

Both count on the unused bits of `$4017` reading the same every time: `$40`
with the line at rest. The console looks before a test. If its port reads
anything else nothing can be received, so it runs no rates to the NES and
says what it read.

**Two senders.** Down to 8 cycles a bit the console loads the next byte
during the start bit, and needs 11 cycles between bytes. At 6 there is no
room for that, so it loads the byte first and needs 13. Either way the
stop bit is then longer than the data bits, which a UART does not mind, and
the bytes a second allow for it.

One direction is tested at a time, in blocks of 256 pseudo-random bytes
sent back to back. A trial is 4 blocks, 1024 bytes, and is clean when no
byte in it is wrong. The test tries each rate once, from the slowest up,
until a trial fails, and backs off to the rate before it. No rate is tried
twice.

The result for each direction is the fastest rate that passed, with the
payload rate it gives in bytes a second.

A whole test takes about 55 seconds when every rate passes, by the
simulated console's clock. A block is a quarter of a second of agreeing
and waiting, and then its bytes.

## Running it

Needs cc65 to build, [nesp32](../..), the top of this
repository, and a nesp32 with that firmware on it.

```sh
make                      # build/linktest.nes
```

1. Start `build/linktest.nes` on the console, with the nesp32 in
   controller port 2. The screen says `WAITING FOR THE NESP32` until the
   nesp32 answers, and then `PRESS START`. `UPDATE THE NESP32` means its
   firmware has no RAW service.
2. Press Start on controller 1, or button A on the nesp32. Nothing is
   tested until then.
3. When it says `DONE. PRESS START`, either button runs it again.

A nesp32 that is plugged in late, or switched off and on between tests, is
found again by itself. One that loses its power in the middle of a block
to the NES leaves the console waiting for the rest of it: press Reset.

The console's screen has the jukebox's header, the name in its big letters
over what this is and the credit line, then the nesp32-to-NES test and
under it the NES-to-nesp32 test. Each half shows the trial that is
running. This is a test on a simulated line with slow edges, partway
through the second direction:

```text
          N E S P 3 2
         THROUGHPUT TEST
        RETRO BITS (2026)

  TESTING

  NESP32 TO NES
   STATUS  DONE
   SPEED   127841 BPS
   SENT    1024 BYTES
   BAD     0 BYTES
   CPU     45%
   FASTEST 11621 BYTES/S
   FAILED  137675 BPS, 43 BAD

  NES TO NESP32
   STATUS  CLIMBING
   SPEED   52640 BPS
   SENT    512 BYTES
   BAD     0 BYTES
   CPU     20%
   FASTEST
   FAILED
```

| Row | Meaning |
|---|---|
| STATUS | `WAITING`, `CLIMBING`, then `DONE` |
| SPEED | the rate of the trial that is running, in bits a second on the wire (the baud rate) |
| SENT | bytes sent in this trial so far; it counts up a block at a time |
| BAD | bytes of those that arrived wrong. A trial stops at its first bad block |
| CPU | the share of the console's CPU the rate takes, below |
| FASTEST | once the direction is done: the payload rate, in bytes a second, of the fastest rate that held |
| FAILED | once the direction is done: the rate that stopped the climb, and the bytes of its bad block that were wrong. Of a block from the console, those are the bytes the nesp32 heard wrong and the ones it never heard. `NONE` if every rate passed |

When a direction is done its half goes back to the rate that held, with
that trial's figures, and stays up; the trial that failed is left in the
FAILED row.

**CPU** is the share of the cycles in a byte that the console's routine
spends on instructions it needs; the rest is padding between bits and
waiting for the next start bit. It is worked out from the routines, not
measured, and is the same on every run. Near 100% there is no rate left to
gain whatever the wire does. The CPU is busy for the whole of a block
either way, since the routines count cycles.

| | 9622 baud | 38080 | 137675 | 149148 | 162707 | 223722 | 255682 | 298296 | 357955 |
|---|---|---|---|---|---|---|---|---|---|
| to NES | 3% | 13% | 48% | 48% | 53% | 73% | 86% | 100% | 120% |
| to nesp32 | 4% | 14% | 52% | 55% | 61% | 81% | | 97% | |

The figure rises all the way up each ladder. The run on hardware bore it
out at the top: 298296 baud to the NES, at 100%, was the last rate to pass.

On a line with no limit of its own, the upper half ends like this:

```text
   SPEED   298296 BPS
   SENT    1024 BYTES
   BAD     0 BYTES
   CPU     100%
   FASTEST 27117 BYTES/S
   FAILED  357955 BPS, 246 BAD
```

## Reading the result

- This is the rate of the wire and the two bit-banged routines with nothing
  else going on. A ROM gets less out of a rate than `BYTES/S` says: the
  link's frames stop for every vblank and wait for a reply.
- The console's receivers are the tighter side by design. The fast one
  finds a start bit with a loop, so its samples sit up to 3.5 cycles off
  the center of a bit. The sender has no such slack to lose. In simulation
  the baud error the fast receiver takes falls from 5.5% at 9622 baud to
  1.5% at 223722; the tracking one takes 1% at 255682 and 298296.
- A direction that ends on the last rate of its ladder passed everything
  there is. Its limit is then the console's routine, not the wire.
- A trial is 1024 bytes, so "stable" means no bad byte in about a
  thousand, and a rate that fails once in a few thousand bytes can pass.
  Raise `TRIAL_BLOCKS` in `nes/linktest.s` to ask for more.

## How a block goes

The console is in charge, as everywhere on nesp32's link: it asks in
frames at 85227 baud, and the nesp32 answers. The ROM says hello as `THRU`
and asks for the RAW service ([nesp32's protocol](../../docs/PROTOCOL.md),
"RAW"). A block is one run of RAW's:

| | The console asks | Then |
|---|---|---|
| to NES | RAW SEND: the rate, the seed, how many bytes | the nesp32 sends the pattern, the console receives a block and counts the bytes that differ |
| to nesp32 | RAW LISTEN: the rate, the seed, 256 bytes | the console sends the pattern, and the nesp32 counts |
| either | RAW RESULT, once the run is over | the nesp32 says that the run was done, at what rate, and what it heard |

The pattern is a 16-bit xorshift (7, 9, 8) started from the seed, one byte
a step, the same on both sides. Each block has a new seed.

**From the reply to the block, the line is silent.** The nesp32 listens for
100 ms after it agrees, in case the console did not hear and asks again,
and then changes its UART's rate. The console waits 150 ms from the reply
before it listens or sends, with its NMI off and its controller unread, and
the nesp32 sends from 175. After the block the console lets the rest of
the run and 30 ms more go by, and asks how it went.

**No interrupts in a block, and no timeouts.** Anything that takes cycles
from a bit-banged routine would count as a line error, so the NMI is off
for a block and the screen stands still. The receivers cannot time out
either. The tracking receiver goes by the clock and has its block whatever
the line did. The fast one waits for every start bit, and at a rate that
is failing it can lose its place and pass over two bytes of the line for
one of its own; it never passes over more, so a run to it is two blocks
long, 512 bytes, of which it checks the first 256 and lets the rest go by.
Only a line with nothing on it at all leaves the console waiting.

**The link itself is taken as given.** A request that gets no reply is
made again the next frame, and the nesp32 does nothing twice for that. If
none comes for a second and a half, or the nesp32 says it does not know
this ROM (it was switched off and on), the test is over, and the ROM goes
back to saying hello.

## Files

| Path | Purpose |
|---|---|
| `nes/linktest.s`, `nes/linktest.cfg` | the test ROM: the hello, the climb, the screen |
| `tools/rates.py` | the ladders of rates, and their figures |
| `tools/gen_rates.py` | writes the ROM's cycle-timed block routines, one pair per rate, and its tables |
| `tools/gen_screen.py` | the jukebox's font (at ASCII codes), palette and header, the screen the ROM comes up with, and where its figures go |
| `tests/thru_sim.py` | the ROM on py65, joined to nesp32's firmware by a cycle-exact line |
| `tests/` | pytest: every routine's timing, and whole tests against that firmware |

It borrows at build time: the font in `../jukebox/tools/gen_ui.py`, and from
nesp32 the link's library for the console (`nes/lib/`) and the numbers the
two ends share. The tests also build nesp32's link and services for this
computer, and join the ROM to them with the jukebox's line model
(`../jukebox/tests/wire.py`).

```sh
make test                 # these tests only; the top-level `make test` runs them too
```

In simulation every routine reads and writes on the cycle it should at
every rate. Against nesp32's firmware, a clean line passes every rate both
ways but the one that is there to fail, also with the nesp32's clock 1%
off; lines with slow rising edges (which is what the hat's transistors
give) make each direction stop where its blocks start to fail; every
exchange of a test is made once, and nothing else is on the line. A run
that loses bytes, a nesp32 that is not there, and one switched off and on
between blocks all recover.

## Hardware results

With the test as it was before nesp32 (a MicroPython script on the
nesp32's hardware in place of the firmware, and commands at 9622 baud), on
a StickC Plus2 and a real NES, with 1024-byte trials:

| Direction | Fastest rate that passed | What stopped it |
|---|---|---|
| to NES | 298296 baud, about 27000 bytes a second | nothing: it was the last rate the console's CPU can do, and the 357955-baud rate above it failed as it should. The port reads `$40` there |
| from NES | 223722 baud, 21563 bytes a second | 298296 baud failed. The console's sender has no slack there, so this is the wire, the hat or the UART |

That run still had the jukebox's own receiver of the time on the rates up
to 149148 baud, which all passed. The block routines are unchanged since.

With this ROM and nesp32's firmware, on a StickS3 and the MiSTer's NES
core through a SNAC adapter:

| Direction | Fastest rate that passed | What stopped it |
|---|---|---|
| to NES | 298296 baud | nothing, as on the real NES: 357955 baud failed as it should |
| from NES | 223722 baud, 21563 bytes a second | 298296 baud: 187 of a block's 256 bytes came |

With this ROM and nesp32's firmware, on a StickC Plus2 wired to a real NES
through a breadboard, with long runs of wire in place of the hat's board:

| Direction | Fastest rate that passed |
|---|---|
| to NES | 111861 baud |
| from NES | 178977 baud |

That was the breadboard: on the hat's board the same Plus2 plays sampled
sound at 223722 baud to a real NES, which failed on the breadboard.

The first run on the MiSTer passed nothing from the console: 194 of 256 bytes
came, at 9622 baud and at 85227 alike. The nesp32's UART was set for the
two stop bits it sends with, and a StickS3's receiver then waits for both,
where the console's blocks have one and nothing after it. nesp32's
firmware now sets it for one while it hears a run. Two builds told that
apart from other faults, and are still there: `make -B TX_FIRST=8` begins
the climb from the console at that rate of its ladder (8 is 85227 baud),
and `THRU_STOP_BITS=2 make -B` gives the console's blocks a stop bit of
two bits.

## What the runs taught

- **To the NES, the limit is the console's CPU, not the wire.** The hat's
  TX stage, the cable and the port's buffer carried 298296 baud cleanly.
  The rate one step past it, which needs 120% of the CPU, failed, and the
  rate at 100% passed, so the CPU figures are right.
- **From the NES, the limit is on the far side.** 223722 baud passed and
  298296 failed. The console's sender is cycle-exact at both, so what gave
  out is the hat's RX stage, the wire or the UART.
- **A receiver that samples in 11 cycles and hunts every 9 is good to
  149148 baud** on this hat, with two stop bits. nesp32's link is that
  receiver at 85227.
- **Sampling can cost 6 cycles a bit, not 11**, by keeping the byte in A
  and XORing the port into it. The price is that it counts on bits 1 to 7
  of `$4017` always reading `$40`, which this console's do, and that bytes
  must be unscrambled afterwards.
- **Hunting for each start bit stops working near 8 cycles a bit**, where
  a look every 6 or 7 cycles is most of a bit. Past that the receiver has
  to predict the start bit and correct by a cycle a byte, which needs a
  few bytes to lock and a sender within about 1% of the right rate.
- **An ESP32 UART leaves a byte of junk in its receiver when its rate is
  changed.** Its transmitter is clean across the change. Anything that
  changes rate and then counts bytes by position has to drop what is there
  first, which nesp32's RAW does.
- **Each direction should be judged by itself.** The first design had one
  ladder for both, and both passed all of it; the real limits only showed
  once each had rates up to what its own routine could do.
- **What it does not show:** these are rates with the console doing
  nothing else and no interrupts. At 298296 baud the receive loop has no
  spare cycle, so nothing can be done with a byte until the block is in.

Still untried:

- **This ROM on a real NES with the hat on its board**, with either Stick.
- **The fast receiver below 162707 baud**, where it has taken over from
  the one the first run used. It is the same sampling and hunt as the
  rates it passed at, with longer padding.
- **OUT1 and OUT2.** The send routines write the whole byte to `$4016` and
  shift it, so bits 1 and 2 toggle OUT1 and OUT2 as well. Those reach only
  the expansion port on a stock console.

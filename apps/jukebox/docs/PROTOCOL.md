# NES Jukebox stream format and link protocol

Status: the stream format (part 1) and the file container (part 2) are
implemented by `tools/jbs.py` and fixed for v1. The link protocol (part 3)
is implemented by `nes/serial_link.inc` and `host/protocol.py` and verified
in a cycle-exact simulation. Its timing still needs confirming on hardware
(phase 3b). Sampled sound (part 4) is implemented by the same two, with
`tools/pcm.py` for its file and its bytes. It has played on a real NES
from a StickC Plus2 at one of its six rates.

## 1. Stream format

A `.jbs` stream is a sequence of records. The NES decodes records until it
has advanced exactly one frame, once per NMI.

| First byte | Record | Frames advanced |
|---|---|---|
| `$00` | chain: the write record that follows does not advance | 0 |
| `$01`-`$7F` | wait *n* frames with no writes | *n* |
| `$80 cc ...` | control record | 0 (end of track: 1) |
| `$81`-`$FF` | write record | 1 |

### Write records

The header byte has bit 7 set. Bits 0-6 select register groups. The groups
follow in **apply order**, which is not bit order:

| Apply order | Header bit | Group | Registers | Submask |
|---|---|---|---|---|
| 1 | 5 | status | `$4015` | none |
| 2 | 0 | pulse 1 | `$4000 $4001 $4002 $4003` | bits 0-3 |
| 3 | 1 | pulse 2 | `$4004 $4005 $4006 $4007` | bits 0-3 |
| 4 | 2 | triangle | `$4008 $400A $400B` | bits 0-2 |
| 5 | 3 | noise | `$400C $400E $400F` | bits 0-2 |
| 6 | 4 | DMC | `$4010 $4011 $4012 $4013` | bits 0-3 |
| 7 | 6 | frame counter | `$4017` | none |

A group of more than one register starts with a submask byte, with bit *i*
selecting the group's *i*-th register as listed above. The values for the
selected registers follow in that order. A submask of zero, or one with bits
beyond the group's size, is invalid. Single-register groups carry only their
value.

Example: `$4015=$0F`, `$4000=$BF`, `$4003=$08`, `$400B=$10`, `$4017=$40`
encodes as

```text
E5  0F  09 BF 08  04 10  40
```

In v1 the DMC group carries only `$4011`, the DMC output level. With sample
playback off it is a plain latch, but it changes how loud the triangle and
noise channels mix, and games such as Super Mario Bros. set it every frame
for that reason. The converter drops `$4011` in frames with more than 4
writes to it, which is raw PCM, and clears `$4015` bit 4. `$4010`, `$4012`
and `$4013` are reserved for a later DPCM-capable player, which then needs
no format change.

### Control records

| Code | Meaning |
|---|---|
| `$00` | end of track: silence the APU (`$4015=0`) and end the frame. The NES stays silent until more stream arrives, then carries on, so a playlist can restart after its end |
| `$01` | APU init: `$4015=0`, `$4017=$40`, then the stream writes what it needs |
| `$02 n text` | track name: *n* characters (0-28) of printable ASCII for the console's screen |
| `$03 n text` | game name, in the same form, for the line above it |
| `$04 text` | track length: 5 characters as the screen shows them, `M:SS ` or `MM:SS`, or `-:-- ` for a track that never ends. It also starts the console's clock again from zero |
| `$05 r` | sound record: sampled sound is due here, at rate *r* (part 4). It silences the APU and ends the frame as `$00` does, and the console then asks the host for the sound. The link ROM only; to the standalone ROM it is invalid |

Other codes are invalid in v1, and so is a name longer than 28. The three
with text write nothing to the APU.

They are not part of a track's own stream: the converter never writes
them, and a `.jbs` file keeps its title in the header. The host puts all
three ahead of each track as it sends it (`jbs.intro`): game, track, then
length. They reach the screen as the track's first notes play, however
much of the previous track the console still had buffered, one line per
vblank. The converter's titles are "game - track", split at the first
` - `; a title without one is a track's name with no game. The length is
the time the playlist will play the track for, loops included. The
standalone ROM's song gets the same records from `tools/embed_song.py`.

The console's clock counts the frames it plays, 60 to the second, from the
length record on. It therefore shows what is being heard, stops while the
music is stopped, and needs nothing more from the host.

### Guarantees the converter makes

- Every track's stream starts with `$80 $01`.
- The first frame begins with `$4015=$0F`, before the rip's own writes. A
  rip often starts after the game enabled its channels and never writes
  `$4015` itself; VGM players start with the channels enabled, and without
  this such a rip is silent on the console.
- Every `$4017` value has bit 6 set, so the APU frame IRQ can never fire.
- Writes to `$4003`, `$4007`, `$400B` and `$400F` are never dropped as
  duplicates, because each one restarts the note.
- Within a frame, writes are merged and put in apply order only when the
  write-order model in `tools/apu_model.py` shows the result is the same.
  Otherwise the original order is kept, split into chained records.
- Frames are VGM's 735-sample (1/60 s) grid. The console plays them at
  60.0988 Hz, 0.16% fast.

## 2. File container (`.jbs`)

The host stores and reads this file. It is never sent to the NES.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic `JBS` `$1A` |
| 4 | 1 | version, 1 |
| 5 | 1 | flags: bit 0 loops, bit 1 PAL source |
| 6 | 2 | reserved, 0 |
| 8 | 4 | total frames (little-endian) |
| 12 | 4 | loop frame, `$FFFFFFFF` if none |
| 16 | 4 | loop offset: stream byte where the loop frame's records begin |
| 20 | 4 | stream length |
| 24 | 1 | title length *n* |
| 25 | *n* | title, printable ASCII |
| 25+*n* | | stream |

**Looping.** The host streams bytes up to the stream length, then continues
from the loop offset. The encoder forgets which register values the console
holds at the loop frame, so a repeat pass never relies on state from before
the loop. When the host decides to stop, it sends `$80 $00`.

## 3. Link protocol v1

Same wiring as nes-radar: D0 on controller port 2 for host to NES, OUT0 for
NES to host.

- **Host to NES:** 38400 baud, 8 data bits, no parity, **2 stop bits**. The
  second stop bit is the NES's time to store a byte and start hunting for
  the next start bit.
- **NES to host:** 38400 baud, 8N1, bit-banged on OUT0. OUT0 idles at mark.

The NES paces the link, and the host transmits only in reply to a request.

### Request (NES to host, 4 bytes)

```text
OP, SEQ, ARG, CHECK        CHECK = $A5 ^ OP ^ SEQ ^ ARG
```

| OP | Name | SEQ | ARG |
|---|---|---|---|
| `$4A` 'J' | data | burst the NES wants | most payload bytes it can take |
| `$48` 'H' | hello | 0 | 0; the host restarts the track and its sequence |
| `$42` 'B' | button | 0 | what controller 1 asked for: bit 0 next track, bit 1 previous, bit 2 play or pause; no reply |
| `$53` 'S' | stats | which counter | the counter's low byte; no reply |
| `$50` 'P' | sound | burst the NES wants | the rate of the sound record it has played, or `$FF` if it cannot play it (part 4) |

The NES sends hello once at boot, after holding OUT0 at mark for about
1.3 ms so the host's UART leaves break. After that it sends a data request
right after an NMI whenever at least 8 bytes of the ring are free, asking
for at most 24, and waits for the burst.

Every 16th frame a stats request takes the place of the data request. The
counters take turns, in this order: bursts cut off by an NMI (aborts),
waits that timed out, rejects (framing, length or sequence), CRC errors,
the current `request_delay`, underruns, and committed bursts. The console
has no screen for them, and they are how a host tells *why* bursts are
being asked for again. A report is a low byte of a count that began when
the console was switched on, so the hosts add up the steps between reports
and show totals for their own session.

A button request goes out when a button on controller 1 is pressed, in
place of that frame's data or stats request: Right is next, Left is
previous, and Start or A is play or pause. The host answers with what it
would do for its own buttons. A track change jumps at once and starts
playing, also from stopped or paused, and reaches the NES as a flush burst
in reply to its next data request. Play or pause toggles between playing
and paused (pause bursts, below); from stopped, or after the playlist has
ended, it plays the current track from its beginning. A button request that is lost on
the line is a press that did nothing, and is not sent again.

**The controller read is on the line too.** The NES reads controller 1 by
holding OUT0 low for the 8 reads, and OUT0 is the line to the host. It
rests at mark, which keeps the controller loading its buttons, so there is
no separate strobe pulse: each read is one low pulse of 94 CPU cycles, two
bit times at 38400 baud. A UART receives that as the byte `$FE`, once a
frame, at the start of the NMI. The read comes first in the NMI so that
the byte is finished (ten bit times) long before the request that follows;
in the simulation the gap is never under 12 bit times. The host's decoder
passes over a `$FE` where a request should start without counting it as
noise.

If a data request's `SEQ` equals the last burst sent, the host sends
**exactly the same burst** again. If it is one more, the last burst was
committed and the host moves on. This covers lost requests, lost or late
bursts and CRC failures without a separate NAK.

Resends must be identical. A slow host can have several copies of one burst
on the wire, and the NES commits whichever arrives intact first; if the
copies differed, the host could not know how much was committed. An
identical copy always fits, because the NES's credit for a repeated
sequence number never shrinks: nothing was committed, and playback only
frees space. (The simulation caught an earlier host that re-sliced resends
by the new credit, and duplicated stream bytes as a result.)

The host decoder scans for a valid 4-byte frame and resyncs one byte at a
time, so noise on OUT0 costs at most the frame it lands in.

### Burst (host to NES)

```text
$A5, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
```

The CRC is CRC-16/CCITT-FALSE (polynomial `$1021`, initial `$FFFF`) over
`SEQ` through the payload. The NES stores the payload straight into its
ring as it arrives. It drops a burst whose `LEN` is beyond the credit before
storing any of it, because that could run past the free space, and after
the last byte it checks `SEQ` and the CRC. Only then does it commit the
bytes. Bytes
before the `$A5` marker are ignored.

Once a track has ended, the host answers with empty bursts (`LEN` 0). The
NES takes an empty burst as the end of the track and starts playing
whatever it has, even if that is less than the 768-byte prefill.

### Flush burst (host to NES)

```text
$5A, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
```

The same as a burst, with a different marker, and with the CRC taken over
the marker as well (`$5A`, `SEQ`, `LEN`, payload), so a damaged ordinary
burst cannot pass for one. When the NES accepts it, it drops everything it
has buffered and not yet played, silences the APU (`$4015=0`), and stops
playing until the ring has refilled to the prefill. The burst's payload is
the first thing in the emptied ring. Sequence numbers and resends work as
for any burst.

The host uses it for everything that should be heard at once, where the NES
would otherwise first play out the few seconds it holds:

- **Changing or restarting a track:** the first burst of the new stream is
  a flush burst. The music starts again after the prefill, about half a
  second.
- **Stopped:** the host answers every request with an *empty* flush burst.
  The NES stays silent and keeps asking every frame, so nothing times out
  and the host can see that the console is there. Unlike an empty ordinary
  burst, this does not start playback.

A flush waits for the NES's next request, and the NES asks only when 8
bytes of its ring are free. In the middle of a long rest in the music that
can take as long as the rest.

### Pause burst (host to NES)

```text
$3C, SEQ, 0, CRC_HI, CRC_LO
```

An empty burst with its own marker, and the CRC taken over the marker as
for a flush burst. When the NES accepts one it holds the music where it
is: the NMI stops decoding, the APU is silenced (`$4015=0`), and
everything buffered is kept. A paused host answers every request with one.

Paused, the NES asks every frame whatever room its ring has, even none, so
the link stays up and the host has a request to answer when the pause
ends. The first burst that is not a pause burst ends it: the NES puts the
channel enables back and decodes on from the frame it stopped at. Notes
that were sounding are not restarted; each channel comes back with its next
note.

That first request after a pause can carry a credit of zero, and its
answer is then an empty ordinary burst. The NES takes that as it always
does ("the track has ended, play what you have"), which changes nothing
while it is already playing.

### Waiting, cut-offs and retries

- **Waiting for the marker spans NMIs.** An NMI that arrives while the NES
  is still waiting for `$A5` plays its frame and returns to the wait, so a
  reply that comes a frame or two late still gets through.
- **An NMI in the middle of a burst ends the receive.** Bytes that arrive
  during the NMI are lost, so the burst could not pass its CRC.
- **No marker for 4 frames ends the receive** (`HUNT_TIMEOUT_FRAMES`).
- After either, the NES requests the same `SEQ` again, and **moves its next
  request later** after the NMI: `request_delay` steps through 0-9 units of
  about 1.3 ms, three at a time, and keeps a value that works. Without this, a
  host with a steady reply time that always lands across the NMI would never
  get a burst through.
- **After a burst that came a frame late, the next request waits for the
  next NMI.** Such a burst ends partway through a frame, and a request sent
  from there would have its reply cut off by the NMI that follows. (Found on
  the simulation: before this, a host replying in 6-10 ms lost every other
  burst.)

### Timing

Measured in the cycle-exact simulation (`tests/test_link.py`,
`tests/test_serial_timing.py`), as the rate while the ring is filling:

| Host reply time | Result |
|---|---|
| up to 5.5 ms | a burst every frame (about 22 bytes per frame), no resends |
| 7-20 ms, steady to within a few ms | a burst every other frame (about 11 bytes per frame), about 1% resends |
| random across a whole frame (1-17 ms) | about 10 bytes per frame, about 40% resends |
| 30-40 ms | about 4 bytes per frame, about 30% resends; still correct, may underrun |

The music needs about 3-5 bytes per frame on average, so a host within
20 ms is comfortable, and within 5.5 ms is ideal. In every case the music is
frame-exact: faults can delay it (an underrun holds the notes for a frame),
never change it.

The first row was 6.5 ms before the console had a screen. Drawing it takes
about 1 ms of each NMI (the controller read, half of the bars, and working
out the next frame's bars), and the request cannot go out until the NMI is
over. If a host needs that millisecond back, lowering `CREDIT_MAX` from 24
to 20 in `nes/serial_link.inc` shortens every burst by more than it: the
simulation then runs clean up to 7 ms, with prefill taking 38 frames
where it took 32.

- **Sampling:** the NES samples within 0.12 bit of each bit's center for
  every start-bit phase, and receives correctly with host baud error from
  -4.25% to +6.5%. Its transmit writes land within 0.62 cycles of ideal and
  decode with 3% error.
- **Headroom, measured:** the throughput test (`throughput/README.md`) ran
  a receiver built the way this one is (the same sampling and start-bit
  hunt, timed for each rate) on a real NES from a StickC Plus2 at rates up
  to 149148 baud with no errors in its trials, and the wiring itself
  carried 298296 baud to the console and 223722 from it. 38400 is far
  inside what the link can do.
- **USB serial adapters** hold received bytes for a latency timer before
  passing them to the computer (16 ms by default on FTDI chips). That adds
  directly to the host's reply time, so set it low where the driver allows
  it (1 ms).
  The timer runs free of the requests, so replies start anywhere in a
  frame, and a burst that takes half a frame to send runs into the next NMI
  about half the time. Measured with the FTDI cable on a real NES at the
  default: 50-60% of requests were repeats, and the music still played
  correctly. `host/jukebox.py` asks the driver for 1 ms when it opens the
  port (`--latency-ms`; on macOS the driver takes milliseconds in one
  byte). At 1 ms the same cable ran 625 requests with no repeats and
  no errors counted by the NES.

## 4. Sampled sound

A playlist may hold sampled sound: a recording, played through `$4011`, the
7-bit DAC of the console's sample channel. It does not travel in the stream
or in bursts. The console writes each byte to `$4011` as it arrives, a byte
a sample, at a baud rate several times the link's, and nothing is stored.
That takes all of its CPU: for as long as a sound plays the NMI is off, the
screen stands still, and the controller is not read.

**Status: heard on a real NES at two rates.** A 30-second clip at rate 1
(10169 samples a second) and at rate 5 (20338), sent by a StickC Plus2,
sounded right. The other rates have only run in the simulation, as has the
desktop host's side; the
receive routines are the throughput test's fast receiver
(`throughput/README.md`), which passed on that console at every rate used
here.

### Rates

A rate is a whole number of CPU cycles a bit, so the console's bit-banged
receiver hits every bit. The host sends 8N2 as on the link, 11 bits a
byte, and its UART is the clock: the sample rate is the baud rate over 11.

| Rate | Cycles a bit | Baud | Samples a second | A minute is |
|---|---|---|---|---|
| 0 | 21 | 85227 | 7748 | 465 KB |
| 1 | 16 | 111861 | 10169 | 610 KB |
| 2 | 14 | 127841 | 11622 | 697 KB |
| 3 | 12 | 149148 | 13559 | 814 KB |
| 4 | 10 | 178977 | 16271 | 976 KB |
| 5 | 8 | 223722 | 20338 | 1220 KB |

### The bytes

The receiver keeps the byte in A and folds each read of the port into it
(shift left, XOR `$4017`), 6 cycles a sample where the link's takes 11. It
ends up with the byte's bits reversed and inverted, and with the `$40` that
the port's unused bits read left in from the last two reads. Nothing puts
that right on the console: the host sends each sample as the byte this
turns into its level (`pcm.sample_byte`).

Bit 7 of what the console ends up with says there is more, and `$4011`
ignores it. The stream ends at the first byte without it, which is also
written to `$4011`. A host ends a sound with `$FC`, which leaves the DAC at
0.

A sample comes out a fixed time after its start bit, plus the 0 to 7 cycles
by which the receiver's hunt for the start bit missed the edge, under 4
millionths of a second. If the host is late with a byte the DAC holds its
level and the hunt waits: a pause is not an error.

The routines count on the unused bits of `$4017` reading `$40` with the
line at rest. The console checks before it asks for a sound, and refuses
if they do not.

### From music to sound and back

```text
 stream:  ... the track before | names and length | $80 $05 r |   (nothing more)

 NES                                         host
 plays the sound record: APU silent
 draws the names, and SAMPLED SOUND
 P, SEQ, r, CHECK        ---------------->
                         <----------------   $C3, SEQ, 1, r, CRC   (go burst)
 NMI off; waits 150 ms                       listens 100 ms for another request
                                             changes its UART to the sound's rate
                         <----------------   samples, from 175 ms after the go burst
 writes each to $4011                        ...
                         <----------------   $FC
 waits 30 ms; NMI on                         changes its UART back to 38400
 J, SEQ+1, credit        ---------------->
                         <----------------   flush burst: the next track
```

- **The sound record** is the sound's place in the stream. The host sends
  the sound's names and length ahead of it, as for any track, and after it
  gives the NES nothing more, answering data requests with empty bursts.
  The NES plays out what it has buffered and comes to the record at the
  moment the sound should start.
- **The sound request** (`$50`) takes the place of the data request from
  then on, every frame, once the lines the record's frame changed are on
  the screen and the bars of the music before it, which the record brings
  down, are off it. Its `ARG` is the record's rate. A console that cannot play
  it (no routine for the rate, or a port that reads otherwise) sends `$FF`.
- **The go burst** is a burst with marker `$C3`, a payload of one byte, the
  rate, and the CRC taken over the marker as for a flush burst. When the
  NES accepts one that matches its request, it turns the NMI off, waits
  150 ms, and receives samples until the last.
- **The host cannot see that the NES took the go burst**, and must not send
  samples to one that did not. So it listens for 100 ms first. A console
  that missed the burst asks again, at the latest after its 4-frame
  timeout, and gets the same burst; one that took it is silent, since
  even its controller read has stopped. Only then does the host change its
  UART's rate, and it starts the samples 175 ms after the go burst.
- **Other answers to a sound request.** A stopped host answers with an
  empty flush burst and a paused one with a pause burst, as they answer a
  data request. A host with no sound to give (it was restarted, or the
  rate was `$FF`) answers with a flush burst that carries on with whatever
  is next. Any flush burst takes the console's sound away: it asks for
  data again.
- **A sound that was called off.** A button request or a hello in the
  100 ms means the NES is not waiting, and the host drops the sound. If
  the NES then repeats its sound request, it gets a new answer under the
  same sequence number, never the go burst again; that is safe because it
  committed nothing.
- **After the last sample** the NES waits 30 ms, turns the NMI back on and
  asks for data with the next sequence number. The host's answer is a
  flush burst, so the music after a sound starts from a full buffer.

### A console left in a sound

The receive routines have no timeout: an NMI would take cycles from them,
and there is nothing else to count with. A console whose host went away in
the middle of a sound waits for the rest until it is reset, or until a host
starts up: both hosts send four zero bytes at 38400 baud when they open
their UART. Those are long lows, which the routines take for last bytes at
any rate, and which the link at rest passes over as noise.

### File container (`.pcm`)

The host stores and reads this file. `tools/wav2pcm.py` and
`tools/mp32pcm.py` write it.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | magic `NPCM` |
| 4 | 1 | version, 1 |
| 5 | 1 | cycles a bit: 21, 16, 14, 12, 10 or 8 |
| 6 | 1 | title length *n* |
| 7 | 1 | reserved, 0 |
| 8 | *n* | title, printable ASCII, "game - track" as for a `.jbs` |
| 8+*n* | | the samples, each as the byte to send |

The converters pick each level through the DAC's curve, which is not a
straight line (the console's mixer squeezes the top of the range: level 127
gives 64% of 127 times level 1), and ramp to and from level 0 over 20 ms at
each end, so a sound neither starts nor ends with a click.

# NES Jukebox stream format, files and link

Status: the stream format (part 1) and the two file containers (parts 2
and 4) are implemented by `tools/jbs.py` and `tools/pcm.py` and fixed for
v1.

The link (part 3) is not the jukebox's own. The link ROM's host is a
nesp32, and [nesp32's `docs/PROTOCOL.md`](../../../docs/PROTOCOL.md)
is the protocol: the line, the frames, the hello, and the JUKE and RAW
services this ROM uses. Parts 3 and 4 here say only how this ROM uses
them. `nes/serial_link.inc` is all of it, on nesp32's library for the
console (`nes/lib/nesp.inc` there). It is tested against nesp32's own code
on a simulated console, and works with a StickS3 on the MiSTer's NES core.

Before October 2026 the jukebox had a link protocol and a MicroPython
firmware of its own, at 38400 baud, which played on a real NES. Both are
in this repository's history.

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
| `$05 r` | sound record: sampled sound is due here, at rate *r* (part 4). It silences the APU and ends the frame as `$00` does, and the console then asks the nesp32 for the sound. The link ROM only; to the standalone ROM it is invalid |

Other codes are invalid in v1, and so is a name longer than 28. The three
with text write nothing to the APU.

They are not part of a track's own stream: the converter never writes
them, and a `.jbs` file keeps its title in the header. The nesp32 puts all
three ahead of each track as it sends it (as `jbs.intro` builds them, which
the tests hold its firmware to): game, track, then length. They reach the
screen as the track's first notes play, however much of the previous track
the console still had buffered, one line per vblank. The converter's
titles are "game - track", split at the first ` - `; a title without one
is a track's name with no game. The length is the time the playlist will
play the track for, loops included. The standalone ROM's song gets the
same records from `tools/embed_song.py`.

The console's clock counts the frames it plays, 60 to the second, from the
length record on. It therefore shows what is being heard, stops while the
music is stopped, and needs nothing more from the nesp32.

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

The nesp32 stores and reads this file (`tools/deploy.py` puts it there).
It is never sent to the NES as it is.

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

**Looping.** The nesp32 sends bytes up to the stream length, then continues
from the loop offset, twice round in all, and then goes on to the next
track. The encoder forgets which register values the console holds at the
loop frame, so a repeat pass never relies on state from before the loop. A
playlist that ends, ends with `$80 $00`.

## 3. The link

Wiring, rate, frames and services are nesp32's; see its
`docs/PROTOCOL.md`. The line runs at 85227 baud both ways, and every use
of it is one exchange, a request and its reply, made right after the NMI.
An exchange that has not ended by the next vblank is dropped there, and
costs nothing but itself.

### What the ROM sends

One exchange a frame, the first of these that applies:

| When | Request |
|---|---|
| Before anything else, and again whenever the nesp32 says a service is not in use | SYS HELLO, as `JUKE` version 2, asking for the JUKE and RAW services and replies of up to 63 bytes |
| A button on controller 1 was pressed | JUKE BUTTON: Right is next, Left previous, Start or A play or pause. Sent again, unchanged, every frame until it is answered, for up to 30 frames |
| A sound record has played, and the screen has caught up with it | JUKE SOUND: the ring's epoch, and the record's rate, or `$FF` if this console cannot play it (part 4) |
| Otherwise, every frame | JUKE STREAM: the ring's epoch, how many of its bytes the ROM has taken, the room in the ring up to 56 bytes, and the low byte of its count of underruns |

**The stream is asked for by position.** The reply's bytes go into the
ring, and the ROM's count goes up by as many. A reply that was lost or
damaged, or cut off by the vblank, changes nothing: the next frame's
request says the same position, and the same bytes come. Nothing is ever
stored from a reply whose CRC was not good, nor more than was asked for.

**A reply from another epoch is a flush.** The ROM drops everything
buffered and not yet played, silences the APU (`$4015=0`), stops playing
until the ring has refilled to the 768-byte prefill, and takes the reply's
bytes as the first of the new epoch. The nesp32 begins a new epoch for
whatever should be heard at once: another track, play after stop, the
music after a sound. The first reply after a hello is taken the same way.

### What the reply's state does

| State | The ROM |
|---|---|
| STOPPED | `PRESS START`, or the clock flashing if a track's names are on the screen. It goes on asking every frame |
| PLAYING | plays once 768 bytes are buffered; `LOADING` until then |
| PLAYING with DRAIN | plays what it has, however little: no more is coming for now |
| PAUSED | the NMI stops decoding and the APU is silenced, with everything buffered kept. When the state is PLAYING again the channel enables are put back, and the music goes on from the frame it stopped at. Notes that were sounding are not restarted |
| NO_TRACKS | `NO MUSIC FOUND` |

### What can go wrong, and what the screen says

| What happened | The ROM |
|---|---|
| No reply, a damaged one, one for another request, or one cut off by the NMI | stores nothing and asks again next frame |
| 8 exchanges in a row with no reply | `WAITING FOR LINK`, and goes on asking; what is buffered plays on |
| The hello is refused: no JUKE or RAW service, or another protocol | `UPDATE NESP32` |
| A request is refused because the service is not in use: the nesp32 was switched off and on | says hello again; the next reply is a flush, and the music is stopped |
| The ring runs dry | the notes hold for that frame, and an underrun is counted; the nesp32 keeps the total, for its own screen |

**The controller read is on the line too.** The NES reads controller 1 by
holding OUT0 low for the 8 reads, and OUT0 is the line to the nesp32. It
rests at mark, which keeps the controller loading its buttons, so there is
no separate strobe pulse: each read is one low pulse of 94 CPU cycles,
which the nesp32's UART takes for a byte and its decoder passes over as
noise, once a frame. The read comes first in the NMI, so that the byte is
long over before the request that follows.

### Timing

Measured in the cycle-exact simulation (`tests/test_link.py`):

- A STREAM exchange is 11 bytes out and up to 65 back. With a reply that
  brings all 56 bytes it lands before the next vblank with the nesp32
  taking **up to 5.5 ms** to answer; nesp32's firmware's slowest on
  hardware, with another ROM, was 0.2.
- The 768-byte prefill comes in 14 frames, about a quarter of a second.
  The music needs 3 to 5 bytes a frame on average, so one reply in ten
  getting through would keep it fed.
- Faults can delay the music (an underrun holds the notes for a frame),
  never change it: with replies damaged, cut short, late or lost, and with
  requests damaged, every frame that plays is the stream's.
- The nesp32's clock may be 2% out either way.

## 4. Sampled sound

A playlist may hold sampled sound: a recording, played through `$4011`, the
7-bit DAC of the console's sample channel. It does not travel in the stream
or in frames. The console writes each byte to `$4011` as it arrives, a byte
a sample, at a baud rate several times the link's, and nothing is stored.
That takes all of its CPU: for as long as a sound plays the NMI is off, the
screen stands still, and of the controller only button A is looked at.

On the line a sound is a run of nesp32's RAW service, which JUKE's SOUND
sets up; nesp32's `docs/PROTOCOL.md` has both.

**Status: working on hardware.** From a nesp32, sound has played on a
real NES from a StickC Plus2 at rates 1, 2 and 5 (10169, 11622 and 20338
samples a second), and at rate 5 on the MiSTer's NES core from a StickS3;
pausing with A and playing on works there. All six rates play on the
simulated console. The receive routines are the throughput test's fast receiver
(`../../throughput/README.md`), which passed on that console at every rate used
here.

### Rates

A rate is a whole number of CPU cycles a bit, so the console's bit-banged
receiver hits every bit. The nesp32 sends 8N2 as on the link, 11 bits a
byte, and its UART is the clock: the sample rate is the baud rate over 11.

| Rate | Cycles a bit | Baud | Samples a second | A minute is |
|---|---|---|---|---|
| 0 | 21 | 85227 | 7748 | 465 KB |
| 1 | 16 | 111861 | 10169 | 610 KB |
| 2 | 14 | 127841 | 11622 | 697 KB |
| 3 | 12 | 149148 | 13559 | 814 KB |
| 4 | 10 | 178977 | 16271 | 976 KB |
| 5 | 8 | 223722 | 20338 | 1220 KB |

Rate 0 is the link's own rate.

### The bytes

The receiver keeps the byte in A and folds each read of the port into it
(shift left, XOR `$4017`), 6 cycles a sample where the link's takes 11. It
ends up with the byte's bits reversed and inverted, and with the `$40` that
the port's unused bits read left in from the last two reads. Nothing puts
that right on the console: a file holds each sample as the byte this turns
into its level (`pcm.sample_byte`), and the nesp32 sends the file as it is.

Bit 7 of what the console ends up with says there is more, and `$4011`
ignores it. The stream ends at the first byte without it, which is also
written to `$4011`. The nesp32 ends a sound with `$FC`, which leaves the
DAC at 0.

A sample comes out a fixed time after its start bit, plus the 0 to 7 cycles
by which the receiver's hunt for the start bit missed the edge, under 4
millionths of a second. If the nesp32 is late with a byte the DAC holds its
level and the hunt waits: a pause is not an error.

The routines count on the unused bits of `$4017` reading `$40` with the
line at rest. The console checks before it asks for a sound, and says it
cannot play one if they do not.

### From music to sound and back

```text
 stream:  ... the track before | names and length | $80 $05 r |   (nothing more: DRAIN)

 NES                                         nesp32
 plays the sound record: APU silent
 draws the names, and SAMPLED SOUND
 JUKE SOUND: epoch, r    ---------------->
                         <----------------   GO
 NMI off; waits 150 ms                       listens 100 ms for another request
                                             changes its UART to the sound's rate
                         <----------------   samples, from 175 ms after GO
 writes each to $4011                        ...
                         <----------------   $FC
 waits 30 ms; NMI on                         changes its UART back to 85227
 JUKE STREAM, old epoch  ---------------->
                         <----------------   a new epoch: the next track
```

- **The sound record** is the sound's place in the stream. The nesp32 sends
  the sound's names and length ahead of it, as for any track, and after it
  gives nothing more. The NES plays out what it has buffered and comes to
  the record at the moment the sound should start.
- **The sound request** takes the place of the stream request from then
  on, every frame, once the lines the record's frame changed are on the
  screen and the bars of the music before it, which the record brings
  down, are off it.
- **GO** means the samples follow, as a run of RAW's, with RAW's clock:
  the NES turns the NMI off, waits 150 ms, and receives samples until the
  last; the nesp32 listens for 100 ms in case the NES did not hear GO and
  asks again, and starts the samples at 175 ms (nesp32's
  `docs/PROTOCOL.md`, "RAW").
- **WAIT** means the music is paused: the NES asks again next frame.
- **GONE** means there is no sound to play: this console said it could not
  play it, or the track was changed, or the nesp32 was restarted. The NES
  asks for the stream again, which by then is in another epoch.
- **A button on controller 1** while the NES waits for an answer goes out
  first, as always, and calls the sound off: the NES is evidently not deaf.
- **After the last sample** the NES waits 30 ms, turns the NMI back on and
  asks for the stream. The answer is from a new epoch, so the music after
  a sound starts from a full buffer.
- **A button on the nesp32** during a sound ends it with `$FC` at once.
- **Button A on controller 1 pauses a sound.** The line to the nesp32 is
  at rest all through a sound, and at rest it keeps the controller loading
  its buttons, so a read of `$4016` gives A as it is at that moment, with
  nothing put on the line. Each routine looks once a byte, in the stop
  bits: `cpy $4016 / beq`, 6 cycles, 3 of which the three fastest routines
  did not have to spare, so their hunt for the next start bit begins 3
  cycles later, still before one can fall. The other buttons are behind
  the controller's shift register, which is clocked only with the line
  held low, and are not read.
- **A console that leaves a sound says so** as RAW has it, with 8 bytes
  of `$FF` at the link's rate, and the nesp32 ends the run and pauses
  (nesp32's `docs/PROTOCOL.md`, "RAW" and "JUKE"). The console meanwhile
  brings its DAC to rest a step at a time, over 20 ms, and waits for the
  line to be quiet. Then the NMI goes back on, with the sound still
  wanted.
- **Paused**, the console asks for the stream, which says the music is
  paused and brings nothing, and everything on the controller works: Start
  or A plays, and Left and Right change the track. Played, the console
  asks for the sound again, once A is up (a button held down would end the
  sound as it began), and the nesp32 sends it from where it was when the
  console left, rising from the DAC's rest over 20 ms.

### A console left in a sound

The receive routines have no timeout: an NMI would take cycles from them,
and there is nothing else to count with. A console whose nesp32 went away
in the middle of a sound waits for the rest until it is reset, or until a
nesp32 starts up: its firmware sends twelve zero bytes at the link's rate
when it opens its UART. Those are long lows, which the routines take for
last bytes at any rate, and which the link at rest passes over as noise.

### File container (`.pcm`)

The nesp32 stores and reads this file. `tools/wav2pcm.py` and
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

# NES Jukebox stream format and link protocol

Status: the stream format (part 1) and the file container (part 2) are
implemented by `tools/jbs.py` and fixed for v1. The link protocol (part 3)
is implemented by `nes/serial_link.inc` and `host/protocol.py` and verified
in a cycle-exact simulation. Its timing still needs confirming on hardware
(phase 3b).

## 1. Stream format

A `.jbs` stream is a sequence of records. The NES decodes records until it
has advanced exactly one frame, once per NMI.

| First byte | Record | Frames advanced |
|---|---|---|
| `$00` | chain: the write record that follows does not advance | 0 |
| `$01`-`$7F` | wait *n* frames with no writes | *n* |
| `$80 cc` | control record | 0 (end of track: 1) |
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

Other codes are invalid in v1.

### Guarantees the converter makes

- Every stream starts with `$80 $01`.
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
| `$42` 'B' | button | 0 | button bits: next, previous, pause (not yet sent) |
| `$53` 'S' | stats | which counter | the counter's low byte; no reply |

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
| up to 6 ms | a burst every frame (about 22 bytes per frame), no resends |
| 7-20 ms, steady to within a few ms | a burst every other frame (about 11 bytes per frame), about 1% resends |
| random across a whole frame (1-17 ms) | about 10 bytes per frame, about 40% resends |
| 30-40 ms | about 4 bytes per frame, about 30% resends; still correct, may underrun |

The music needs about 3-5 bytes per frame on average, so a host within
20 ms is comfortable, and within 6 ms is ideal. In every case the music is
frame-exact: faults can delay it (an underrun holds the notes for a frame),
never change it.

- **Sampling:** the NES samples within 0.12 bit of each bit's center for
  every start-bit phase, and receives correctly with host baud error from
  -4.25% to +6.5%. Its transmit writes land within 0.62 cycles of ideal and
  decode with 3% error.
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

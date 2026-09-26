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
| `$80 cc` | control record | 0 |
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
| `$00` | end of track: silence the APU (`$4015=0`) and stop consuming |
| `$01` | APU init: `$4015=0`, `$4017=$40`, then the stream writes what it needs |

Other codes are invalid in v1.

### Guarantees the converter makes

- Every stream starts with `$80 $01`.
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

The NES sends hello once at boot, after holding OUT0 at mark for about
1.3 ms so the host's UART leaves break. After that it sends one data request
per frame, right after the NMI, whenever at least 8 bytes of the ring are
free. It asks for at most 24.

If a data request's `SEQ` equals the last burst sent, the host sends the
same stream bytes again (fewer if `ARG` is smaller). If it is one more, the
last burst was committed and the host moves on. This covers lost requests,
lost or late bursts and CRC failures without a separate NAK.

The host decoder scans for a valid 4-byte frame and resyncs one byte at a
time, so noise on OUT0 costs at most the frame it lands in.

### Burst (host to NES)

```text
$A5, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
```

The CRC is CRC-16/CCITT-FALSE (polynomial `$1021`, initial `$FFFF`) over
`SEQ` through the payload. The NES stores the payload straight into its
ring as it arrives, and only after the last byte checks `SEQ`, that `LEN`
is within the credit, and the CRC. Only then does it commit the bytes. Bytes
before the `$A5` marker are ignored.

Once a track has ended, the host answers with empty bursts (`LEN` 0). The
NES takes an empty burst as the end of the track and starts playing
whatever it has, even if that is less than the 768-byte prefill.

### Timing

- **Budget:** a full 24-byte burst is 29 bytes, 8.3 ms at 8N2. With the
  request (1.0 ms) and the NMI, it lands before the next NMI when the host
  starts replying within **6.0 ms** of the request's last stop bit
  (measured in simulation, `test_turnaround_budget_is_reported`).
- **Late hosts:** if a burst is still arriving when the NMI comes, the NMI
  plays its frame on time and then abandons the receive. The next frame's
  request repeats the sequence number, and the host resends. The music is
  never affected unless the ring runs dry.
- **Sampling:** the NES samples within 0.12 bit of each bit's center for
  every start-bit phase, and receives correctly with host baud error from
  -4.25% to +6.5%. Its transmit writes land within 0.62 cycles of ideal and
  decode with 3% error. See `tests/test_serial_timing.py`.

# NES Jukebox stream format and link protocol

Status: the stream format (part 1) and the file container (part 2) are
implemented by `tools/jbs.py` and fixed for v1. The link protocol (part 3)
is a draft until the phase 3 hardware spike confirms its timing.

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

## 3. Link protocol v1 (draft)

Same wiring as nes-radar: D0 on controller port 2 for host to NES, OUT0 for
NES to host.

- **Host to NES:** 38400 baud, 8 data bits, no parity, **2 stop bits**.
- **NES to host:** 38400 baud, 8N1, bit-banged on OUT0. OUT0 idles at mark.

The NES paces the link, and the host transmits only in reply to a request.

### Request (NES to host, 4 bytes)

```text
OP, SEQ, ARG, CHECK        CHECK = $A5 ^ OP ^ SEQ ^ ARG
```

| OP | Name | SEQ | ARG |
|---|---|---|---|
| `$4A` 'J' | data | burst the NES wants | most payload bytes it can take |
| `$48` 'H' | hello | 0 | 0; the host resets its burst sequence and track position |
| `$42` 'B' | button | 0 | button bits: next, previous, pause |

If a data request's `SEQ` equals the last burst sent, the host resends it.
If it is one more, the host sends the next bytes of the stream. This
covers lost requests, lost bursts and CRC failures without a separate NAK.

The host decoder scans for a valid 4-byte frame and resyncs one byte at a
time. Controller reads in the NMI briefly drop OUT0 and can show up as
noise bytes.

### Burst (host to NES)

```text
$A5, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
```

`LEN` never exceeds the request's `ARG`. The CRC is CRC-16/CCITT-FALSE
(polynomial `$1021`, initial `$FFFF`) over `SEQ` through the payload. The
NES computes it after the last byte arrives, not between bytes, and commits
the payload to its ring buffer only if it matches.

### Timing (to be measured in phase 3)

- The host starts a burst within `T_turn` of the request's last stop bit.
- The NES requests only what fits before the next vblank. If a burst runs
  late, the NMI still plays the frame on time and abandons the receive.
  The burst then fails its CRC and is requested again.

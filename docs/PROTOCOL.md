# The nesp link protocol

How an NES talks to an M5Stack Stick on controller port 2, for every
application at once: one frame format, a set of numbered services, and a
hello by which a ROM says which of them it needs.

Status: version 1. The frames, the hello, and the services SYS, NET
(Wi-Fi), DIAG and WIKI are implemented by `firmware/components/` and
`nes/lib/`, and tested together on a simulated console over a cycle-exact
line (`tests/`), and have run on a StickS3 with the MiSTer's NES core
(`firmware/README.md`, "On hardware"). RAW and JUKE are implemented and
tested the same way, JUKE with nes-jukebox's ROM (its `tests/`), and run
on the same hardware with that ROM; of RAW, only a run to the console has.
The services marked *reserved* have a number and no ops.

Every number in this document comes from `proto/nesp.toml`, from which
`tools/gen_proto.py` writes a C header, a ca65 include and a Python module.

## 1. The line

The wiring is nes-radar's hat, unchanged: the Stick drives D0 (bit 0 of
`$4017`, inverted by the port's buffer) and reads OUT0 (bit 0 of `$4016`
writes), which rests at mark.

| | |
|---|---|
| Rate | 21 NES CPU cycles a bit, 85227 baud, both ways |
| Console to Stick | 8N1 |
| Stick to console | 8N2: the second stop bit is the console's time to store a byte |
| CRC | CRC-16/CCITT-FALSE (polynomial `$1021`, start `$FFFF`), high byte first |

The console bit-bangs both directions by counting CPU cycles
(`nes/lib/gen_link.py`). Once a frame it also reads its controller, which
holds OUT0 low for 94 cycles; the Stick's UART takes that for a byte, and
the Stick's decoder passes over it.

## 2. Frames

The console is in charge. The Stick sends only in answer to a request, and
answers every request it acts on with exactly one reply.

```text
request   $4E, SVC, OP,     SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO     console to Stick
reply     $A5, SVC, STATUS, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO     Stick to console
```

| Field | Meaning |
|---|---|
| `SVC` | the service asked (section 5). A reply repeats it |
| `OP` | what is asked of it |
| `SEQ` | the request's sequence number. A reply repeats it |
| `LEN` | bytes of payload, 0 to 127. Bit 7 is always 0 |
| `STATUS` | how it went (section 3) |
| CRC | over `SVC` through the last byte of the payload |

**A new request has a new `SEQ`.** The console's library counts it up by
one for each.

**The same request again gets the same reply again.** If a request has the
`OP`, `SEQ`, `LEN` and CRC of the last one the Stick answered for that
service, the Stick sends the bytes it sent then and does nothing else. So
a console that heard no reply sends the request again unchanged
(`nesp_again`), and nothing is done twice: a piece of a password is not
added twice, a stream does not skip. Two replies are never held for a
repeat: a hello's, and one whose status is busy.

**Only the newest request is acted on.** If the Stick finds several
requests waiting, it drops all but the last. The console listens only
just after it asks, so the older ones are past answering, and it will ask
again for anything it still wants.

**The Stick is never silent on purpose.** Whatever takes time (joining a
network, a scan, a fetch) is started by one request and asked after by
others. A request for something not ready is answered at once, with a
state or with busy.

**A reply that is not for the request is dropped.** The console checks the
marker, the service, the sequence number, the length against its buffer,
and the CRC. Anything else is the same as no reply.

The Stick's decoder looks for `$4E` and a good CRC, and passes over
anything else a byte at a time. A marker in the noise with a plausible
length does not hold up the request behind it.

### How the check was chosen

The first design had nes-drmario's two running sums in place of a CRC,
since they need no table. Measured on 60,000 damaged frames of each kind:

| What was wrong | Sums, mod 256 | Sums, mod 255 | CRC-16 |
|---|---|---|---|
| 1 bit | 0 | 0 | 0 |
| 2 bits | 407 | 0 | 0 |
| 3 bits | 91 | 40 | 0 |
| 4 bits | 37 | 7 | 5 |
| a byte turned to `$00` or `$FF` | 0 | 393 | 0 |
| a burst of up to 32 bits | 1 | 0 | 1 |

The figures are frames that passed their check. The sums let through two
wrong bits one time in 150, so the link has the CRC. The console works it
out in 39 bytes of code and 66 cycles a byte with no table, or in 35
cycles a byte with a 512-byte table if a ROM defines `NESP_CRC_TABLE`.

## 3. Status

| Value | Name | Meaning |
|---|---|---|
| `$00` | OK | |
| `$40` | ATTENTION | a flag, set on any reply: the Stick has an event waiting (SYS EVENT) |
| `$80` | NO_SERVICE | this firmware has no such service |
| `$81` | NO_OP | the service has no such op |
| `$82` | BAD_ARG | the payload is not what the op takes |
| `$83` | BUSY | not now: ask again, with a new `SEQ` |
| `$84` | INACTIVE | the service was not asked for in a hello |
| `$85` | NO_WIFI | |
| `$86` | NOT_FOUND | |
| `$87` | FAILED | |
| `$88` | VERSION | the hello speaks a protocol this firmware does not |

Bit 7 marks an error. The console's library takes the attention flag off
the status and keeps it apart (`nesp_attention`).

**INACTIVE tells a ROM that the Stick was switched off and on.** A Stick
that starts knows of no hello, so a ROM's first request to one of its
services is refused with it. The ROM says hello again.

## 4. Hello: which services a ROM needs

The first request a ROM makes after reset is SYS HELLO. It is how the
Stick knows what is on the console, with nothing chosen on the Stick.

```text
request payload   PROTOCOL, APP[4], APP_VERSION, REPLY_MAX, SERVICE, SERVICE, ...
reply payload     PROTOCOL, MAJOR, MINOR, PATCH, BOARD, REQUEST_MAX, MISSING, SERVICE, ...
```

| Field | Meaning |
|---|---|
| `PROTOCOL` | 1 |
| `APP` | four characters that name the ROM: `SETP` is the setup ROM |
| `REPLY_MAX` | the longest reply payload the ROM can take, 16 to 127. Until a hello the Stick sends no more than 32 |
| `SERVICE` ... | the services the ROM needs |
| `MAJOR`, `MINOR`, `PATCH` | the firmware's version |
| `BOARD` | 1 StickC Plus2, 2 StickS3, 3 a computer standing in |
| `REQUEST_MAX` | the longest request payload the Stick takes: 127 |
| `MISSING`, `SERVICE` ... | how many of the services asked for this firmware lacks, and which |

On a hello the Stick stops every service that was in use and starts the
ones named, each from nothing, forgets every reply it held, and shows the
application on its own screen. SYS is always in use and need not be named.

The status is NO_SERVICE if any service asked for is missing, and VERSION
if the protocol is not one the firmware speaks; the payload is the same
either way, so a ROM can say "update the Stick" and what for.

A reset of the console is a new hello, so changing cartridges needs
nothing done on the Stick.

## 5. Services

| `SVC` | Name | For | State |
|---|---|---|---|
| `$00` | SYS | hello, status, strings, the time, events | done |
| `$01` | NET | Wi-Fi setup; sockets later | Wi-Fi done |
| `$02` | RES | resources by name: fetch, lay out, read as a stream or as numbered records | reserved |
| `$03` | RAW | a run of bytes at a rate of its own with framing off: sampled sound, rate trials | done; sound works on hardware, the rest untried there |
| `$04` | PEER | a lobby and a lockstep relay of buttons for two consoles | reserved |
| `$05` | DIAG | the link's counters and test patterns | done |
| `$10` | JUKE | the jukebox: the playlist as a stream, the buttons, sampled sound | done |
| `$11` | WIKI | NESpedia: a search, and the article it finds as numbered lines | done |
| `$12` | RADAR | NES Radar: airport, scenes and identities | reserved |
| `$80`-`$FF` | | experiments and other people's | |

Multi-byte numbers are low byte first, except the CRC.

### SYS `$00`

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | HELLO | section 4 | section 4 |
| `$01` | STATUS | | `WIFI`, `SIGNAL`, `ADDRESS[4]`, `BATTERY`, `EVENTS` |
| `$02` | ECHO | anything | the same, cut to `REPLY_MAX` |
| `$03` | INFO | which string | its characters, cut to `REPLY_MAX` |
| `$04` | TIME | | `KNOWN`, `SECONDS[4]` since 1970 |
| `$05` | EVENT | | `CODE`, `ARG`: the oldest event waiting, or 0, 0 |

- `WIFI`: 0 none set up, 1 not joined, 2 joining, 3 joined, 4 the last
  join failed.
- `SIGNAL`: dBm, a signed byte; 0 when not joined.
- `BATTERY`: percent, or `$FF` if the Stick cannot tell.
- INFO's strings: 0 the firmware's version, 1 the board's name, 2 the
  saved network's name, 3 the application of the last hello.
- Events: 1 button A, 2 button B, 3 the power button. Eight are kept; more
  are dropped. A service in use may take a button for itself, and the
  console then hears nothing of it: JUKE takes all three.

### NET `$01`: Wi-Fi

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | WIFI_STATUS | | `WIFI`, `WHY`, `SIGNAL`, `ADDRESS[4]`, `NAME_LEN`, `NAME` |
| `$01` | SCAN_START | | status only; BUSY if it cannot scan now |
| `$02` | SCAN_STATUS | | `SCAN`, `COUNT` |
| `$03` | SCAN_RESULT | `INDEX` | `INDEX`, `SIGNAL`, `AUTH`, `CHANNEL`, `NAME_LEN`, `NAME` |
| `$04` | SET_NAME | `OFFSET`, bytes | the name's length so far |
| `$05` | SET_PASSWORD | `OFFSET`, bytes | the password's length so far |
| `$06` | JOIN | `NAME_LEN`, `PASSWORD_LEN` | status only |
| `$07` | FORGET | | status only |

- `WHY`, when `WIFI` is 4: 1 the network refused the password, 2 no
  network of that name was found, 3 anything else.
- `SCAN`: 0 none yet, 1 looking, 2 done, 3 failed. A scan keeps up to 20
  networks, strongest first. A result past the end is NOT_FOUND.
- `AUTH`: 0 open, 1 a password, 2 something this firmware cannot join.
- A name is up to 32 bytes and a password up to 63. Both are cut to fit
  `REPLY_MAX` where they are sent back, which the name is and the password
  never is.

**A name and a password go to the Stick in pieces.** A password of 63
characters is longer than a request that fits between two frames with its
reply. Each SET carries the offset its bytes go at. Offset 0 begins the
text again; any other must be where the text so far ends, or the reply is
BAD_ARG with the length the Stick has. JOIN repeats both lengths, and is
BAD_ARG unless they are what the Stick holds, so a piece that never came
is found out before anything is tried. An open network has a password of
no pieces but one empty SET at offset 0.

**JOIN saves the network and starts joining it.** The Stick keeps it over
power-off and joins it by itself at every start. How the join goes is
asked for with WIFI_STATUS. The staged name and password are wiped by JOIN
and by any hello.

**The password goes one way only.** No op of any service sends it back
(`tests/test_core.py` asks all of them).

### DIAG `$05`

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | STATS | | six 16-bit counts: requests, repeats, dropped, noise bytes, the last reply time and the slowest, in microseconds |
| `$01` | PATTERN | `SEED[2]`, `COUNT` | `COUNT` bytes of the pattern |
| `$02` | SINK | `SEED[2]`, bytes | how many of them differ from the pattern, and how many came |

The pattern is nes-jukebox's throughput test's: a 16-bit xorshift (7, 9,
8) from the seed, a byte a step, the same on both sides (`nesp_pattern` in
`nesp_core.c` and in `nes/lib/nesp.inc`). A seed of 0 is BAD_ARG. The
counts stop at 65535.

The reply time is the firmware's own measure, from the last byte of a
request arriving to its reply being handed to the UART.

### RAW `$03`: the line with framing off

A frame costs seven bytes and a wait for its reply, at one rate. A *run* is
the other way to use the wire: a stretch of bytes one way, with nothing
round them, at a rate of its own. Sampled sound is a run to the console of
a byte a sample; a rate trial is a run of the test pattern, either way.

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | SEND | `PERIOD`, `LEAD`, `SEED[2]`, `COUNT[2]` | status only: a run to the console is agreed |
| `$01` | LISTEN | `PERIOD`, `SEED[2]`, `COUNT[2]` | status only: a run from the console is agreed |
| `$02` | RESULT | | `STATE`, `PERIOD`, `COUNT[2]`, `BAD[2]` |

- `PERIOD`: the run's rate, in CPU cycles a bit, 5 or more. The nesp32's
  UART is set to the nearest baud rate, both ways; a run to the console is
  8N2 and one from it 8N1, as on the link.
- A run of SEND's is `LEAD` bytes of `$FF`, for a receiver that needs some
  to settle on, then `COUNT` bytes of DIAG's pattern from `SEED`. A run of
  LISTEN's is `COUNT` bytes of the pattern from the console.
- `STATE`: 0 no run yet, 1 agreed and not begun, 2 under way, 3 done, 4
  called off before it began. `COUNT` is the bytes sent, or heard; `BAD` is
  how many of those heard were not the pattern's. Both stop at 65535.

**A run is agreed in frames and then goes by the clock**, in milliseconds
from the reply that agreed to it:

| | The nesp32 | The console |
|---|---|---|
| to 100 | goes on listening at the link's rate | if it heard the reply: silent, not even its controller read. If it did not: asks again |
| at 100 | changes its UART's rate | |
| at 150 | | listens for the run, or begins to send it |
| at 175 | sends its first byte, if the run is its own | |
| at the end | puts its UART's rate back | waits 30 ms, then asks for whatever is next |

**The nesp32 cannot see that the console heard the reply**, and must not
change its rate under one that did not. So it listens first. A console that
missed the reply asks again a frame later, with the same request, and the
100 ms start again; one that asks for anything else has called the run
off. Only silence lets the run begin. For that the reply to SEND and to
LISTEN is never held for a repeat: the same request again is the console
saying it did not hear.

**A run to the console ends when its last byte has left.** How the console
knows the end is the run's own business: a count, for the pattern, or a
byte that says so, for sound. Its receivers have no timeout, so a console
whose nesp32 lost its power partway through a run waits for the rest. A
nesp32 that starts sends four zero bytes at the link's rate, long lows
that a receiver at any rate takes for bytes, and that the link at rest
passes over as noise.

**A run from the console ends** when `COUNT` bytes have come, or when 20 ms
pass with none after the first, or after a second with none at all. What
the nesp32's UART hears in the 20 ms after it changes rate is dropped: an
ESP32's leaves a byte of junk in its receiver then, which would put every
byte after it out of place. The console waits its 30 ms after its last
byte and asks for the RESULT; a nesp32 still listening for bytes that never
came does not answer until it has given up.

While a run has the line nothing on it is a request, and the nesp32
answers none.

Another service may have something to send as a run, and agrees to it
with a reply of its own in place of SEND's: JUKE's SOUND does. The clock
and the rules are the same, and the hello must have asked for RAW.

### JUKE `$10`: the jukebox

The jukebox's music, as a stream the console asks for by position.
nes-jukebox's ROM is the console's side, and its `docs/PROTOCOL.md` has
the stream's records and the two files (`.jbs`, a stream of writes to the
console's sound chip; `.pcm`, sampled sound). The nesp32 holds the tracks,
the files of `tracks` in its filing system, in the order of their names,
and the playlist is one stream: each track's names and length as control
records, then its bytes, round its loop twice, then the next track's, and
after the last the first again. The console holds a kilobyte of it in a
ring and plays a frame of it at every vblank.

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | STREAM | `EPOCH`, `POS`, `ROOM`, `UNDERRUNS` | `STATE`, `EPOCH`, then up to `ROOM` bytes of the stream from `POS` |
| `$01` | BUTTON | `BUTTONS` | `STATE` |
| `$02` | SOUND | `EPOCH`, `RATE` | `STATE`, `ANSWER` |

| `STATE` | Name | Meaning |
|---|---|---|
| `$00` | STOPPED | nothing plays, and the console should hold nothing. As after every hello |
| `$01` | PLAYING | |
| `$02` | PAUSED | held where it is: no bytes come, and the console keeps what it has |
| `$03` | NO_TRACKS | the nesp32 has no music it can read |
| `$40` | DRAIN | a flag, with PLAYING: no more is coming for now, so play what you have, however little. The playlist has ended, or a sound is due |

**STREAM is "I have this much, and room for that much more".** `POS` is
the count of the epoch's bytes the console has taken, less a multiple of
256, and the reply's bytes are the stream's from there, as many as `ROOM`
and the reply's length allow. The nesp32 keeps what it sent until a
request's `POS` has moved past it. So a reply that was lost is sent again
by the next request, which has the same `POS`; a request that was lost
changes nothing; and neither needs handling of its own. No reply to
STREAM is held for a repeat. The stream may be cut anywhere: the console
plays only whole frames.

**An epoch is a stretch of the stream with no jump in it.** Whatever
should be heard at once (another track, play after stop, the music after
a sound) begins a new one: its number is one more, and its positions start
again from 0. A console that sees a reply from another epoch than the one
its ring holds drops what the ring holds and takes the reply's bytes as
the first of the new one. Until it has, its requests still name the old
epoch, and are answered from the start of the new. A console that has
just said hello treats the next reply so whatever its epoch.

The console asks every frame, also with no room: the reply is how it
hears that the music was stopped, paused or changed. `UNDERRUNS` is the
low byte of its count of frames that found the ring empty; the nesp32
keeps the total for its own screen, which also shows how many replies it
had to send again.

A `POS` that claims more than the nesp32 sent means that one of the two
was switched off and on. The nesp32 begins the track again in a new
epoch.

**BUTTON is what the console's controller asked for**: bit 0 the next
track, bit 1 the previous, bit 2 play or pause. Next and previous change
the track and play it, also from stopped or paused. Play pauses and
resumes; from stopped, or once the playlist has ended, it plays the
current track from its beginning. The reply is held for a repeat, as any
is, so a console that hears no reply sends the request again unchanged
until it does, and the press is done once. The nesp32's own buttons do the
same: A is play or pause, B the previous track, the power button the next.

The track the buttons count from is the one being sent, which in the last
seconds of a track is already the next: the console plays a few seconds
behind what it has been sent.

**A `.pcm` track is not part of the stream.** Its place there is its names
and length and then a sound record with its rate, after which the stream
gives nothing more (DRAIN). The console plays what it has, comes to the
record, and asks with SOUND in place of STREAM, every frame, until the
answer is not WAIT.

| `ANSWER` | Name | Meaning |
|---|---|---|
| `$00` | WAIT | not now: the music is paused. Ask again |
| `$01` | GO | the samples follow, as a run of RAW's at the sound's rate |
| `$02` | GONE | there is no such sound to play: ask for the stream, which is in another epoch by now |

- `RATE` is the record's: 0 to 5, for 21, 16, 14, 12, 10 and 8 CPU cycles
  a bit, which are 7748 to 20338 samples a second. A console that cannot
  play it says `$FF`, and is told GONE; so is one whose hello did not ask
  for RAW. The nesp32 goes on to the next track.
- `EPOCH` is the console's. A sound asked for from before a jump is GONE,
  whatever is due in the epoch the nesp32 is in now.
- After GO the run is RAW's in every way: asked again within 100 ms, the
  nesp32 says GO again and starts the wait again. A sample is a byte, as
  its file holds it; the run ends with `$FC`, which the console's routines
  take for the last and which leaves its DAC at 0.
- The music after a sound is a new epoch.
- A button on the nesp32 during a sound ends it at once, with the last
  byte, and is then done: A stops (a sound cannot be paused, and A again
  plays it from its start), B and the power button change the track. One
  pressed in the 100 ms before a sound begins waits for it to begin,
  since the console may already be deaf.

In nes-jukebox's ROM a STREAM exchange is 11 bytes out and up to 65 back
(56 of the stream), made right after the NMI. On the simulated console it
lands with the nesp32 taking up to 5.5 ms; the 768 bytes the ROM wants
before it plays come in 14 frames.

### WIKI `$11`: NESpedia

An article from Wikipedia, laid out by the Stick in lines of exactly 28
characters, which the console asks for by number. The console never holds
the article: it has 2 KB of memory.

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | SEARCH | `ID`, then the words: 1 to 30 characters | `STATE`, `ID`, `TOTAL[2]`, and with an error 28 characters for the screen |
| `$01` | LINE | `NUMBER[2]` | `STATE`, `NUMBER[2]`, `TOTAL[2]`, `TEXT[28]`; with no such line, bit 7 of `STATE` is set and there is no `TEXT` |

| `STATE` | Name | Meaning |
|---|---|---|
| `$00` | IDLE | no article, and nothing being fetched |
| `$01` | NO_WIFI | the Stick is not on a network |
| `$02` | FETCHING | a search is under way |
| `$03` | READY | an article is held; `TOTAL` is its number of lines. With bit 6 (`$43`), more of it is still arriving |
| `$04` | NOT_FOUND | the last search found no article |
| `$05` | ERROR | the last search failed; the reply says how |

**SEARCH is both "search for this" and "how is it going".** The console
gives each search an id, one more than the last, and sends the same request
again every few frames until the search has ended one way or another. The
Stick starts fetching when the id or the words differ from the search it
has, and otherwise only answers with its state. So a lost request or a lost
reply needs no handling of its own, and an old article is never taken for
the answer to a new search. Neither op's reply is held for a repeat: the
same request again is a new question.

**An article is offered while it is still arriving.** Once its first 28
lines are laid out, the Stick answers READY with bit 6 set, and `TOTAL` is
the lines so far. The console starts reading, and takes the new `TOTAL`
from every reply. Lines already laid out never change.

`TEXT` is tile numbers, ready for the screen: ASCII, padded with spaces. On
a heading line every character has bit 7 set, which a ROM shows as the same
glyph in a second colour. What is not ASCII becomes the nearest thing that
is (accents to their letters, typographic quotes and dashes to plain ones),
and a run of characters with no likeness becomes one `?`.

The article's memory is the service's while it is in use: a quarter of a
megabyte where the board has it, about 9000 lines. An article too long for
it ends with a line that says it was cut. Every article ends with two lines
naming Wikipedia and its licence. A hello drops the article, so a console
that is reset fetches again.

The reply to a search that failed carries a line of words for the screen:
`THE SITE DID NOT ANSWER`, `THE SITE SAID 429`, `THE CONNECTION DROPPED`.
A reply that stops partway is still READY if a screenful of it had come.

In NESpedia, a line's exchange is 9 bytes out and 40 back, made after the
header's split, about 10600 cycles into the frame. On the simulated console
it lands with the Stick taking up to 4.25 ms.

## 6. Timing

Measured on the simulated console and line (`tests/test_link.py`,
`tests/test_link_timing.py`); a frame is 29780.5 CPU cycles.

- **The Stick answers no sooner than 50 microseconds** after a request's
  last byte. The console is still on its way from sending to listening: a
  reply that began under 20 microseconds after the stop bit was missed
  every time, and one at 20 or more never.
- **How late it may answer depends on the exchange.** A byte to the Stick
  is 210 cycles and a byte back 231, and the whole exchange has to end
  before the next vblank. The setup ROM's longest, 10 bytes out and 55
  back, was good with the Stick taking up to 5.75 ms and lost its longer
  replies from 6 ms.
- An exchange cut off by the vblank, or answered a whole frame late, is
  never taken for the answer to the next request: its sequence number is
  the old one.
- The console's samples fall within a quarter of a bit of mid-bit at every
  phase, and the Stick's clock may be 3% out either way. With the receiver
  that counts its own timeout (below) those are 0.35 of a bit and 2%.

## 7. The console's library

`nes/lib/nesp.inc`, with `link.inc` written for the rate by
`nes/lib/gen_link.py`. A ROM sets the longest reply it takes
(`NESP_RX_MASK`: `$1F`, `$3F` or `$7F`) and the longest request it sends,
puts a request's payload in `nesp_request`, and calls `nesp_call` with the
service, the op and the length. It comes back with carry clear and the
status, and the payload in `nesp_reply`, or with carry set.

There are two receivers, for the two places an exchange can be made:

| | Default | `--timeout` |
|---|---|---|
| Where the exchange is made | in the main loop, between two NMIs | inside the NMI |
| What ends a wait | the NMI: its handler ends with `nesp_nmi_hook`, which returns to the exchange's caller with carry set | a count: `NESP_TIMEOUT` passes of 1.86 ms |
| Start-bit hunt | 9 cycles a look | 13 cycles a look |
| From | nes-jukebox and nes-wiki | nes-drmario |

A reply's length is not known until its fifth byte. The receiver works out
where the frame ends as that byte arrives, cut to `NESP_RX_MASK`, so that
no reply, however damaged, is stored past the buffer.

## 8. Adding to it

- A new application takes a service number, lists its ops in
  `proto/nesp.toml`, and adds a C module with the interface in
  `nesp_core.h`: an id, `activate`, `deactivate` and a `handle` that never
  waits. Nothing in the frame changes. What takes time or goes by the
  clock is done in the service's `tick`, which is called once a reply has
  gone and every few milliseconds besides (JUKE reads its files there, and
  RAW runs its runs); a service that wants the nesp32's buttons takes them
  with `event`.
- A new op on a service is a new number. An op is never given a new
  meaning.
- A reply may grow at its end. A ROM reads the bytes it knows and passes
  over the rest.
- Anything that breaks those rules is a new `PROTOCOL`, which a hello
  finds out.

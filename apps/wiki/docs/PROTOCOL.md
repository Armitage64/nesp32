# NESpedia link protocol

How the console asks the Stick for an article and reads it, a line at a
time, over controller port 2. The wiring is nes-jukebox's: the Stick drives
D0 (bit 0 of `$4017`, inverted by the port's buffer) and reads OUT0 (bit 0
of `$4016` writes), which rests at mark.

The numbers both ends share are in `firmware/stick/neswiki/linkrate.py`.

## The line

| | |
|---|---|
| Rate | 21 NES CPU cycles a bit, 85227 baud, both ways, never changed |
| Console to Stick | 8N1 |
| Stick to console | 8N2: the second stop bit is the console's time to store a byte |
| CRC | CRC-16/CCITT-FALSE (polynomial `$1021`, start `$FFFF`), high byte first |

The console is in charge. The Stick sends only in answer to a request, and
answers every request it can read with exactly one reply.

## Requests, console to Stick

```text
$57, OP, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO        CRC over OP .. PAYLOAD
```

| OP | Name | Payload |
|---|---|---|
| `$01` | SEARCH | an id, then the words to search for: ASCII, 1 to 30 characters |
| `$02` | LINE | the line's number, low byte then high |

**SEARCH is both "search for this" and "how is it going".** The console
gives each search an id, one more than the last, and sends the same request
again every 8 frames until the search has ended one way or another. The
Stick starts fetching when the id or the words differ from the search it
has, and otherwise only answers with its state. So a lost request or a lost
reply needs no handling of its own, and neither side can take an old
article for the answer to a new search.

A console that is reset counts its ids from 1 again. If it then asks for
what the Stick already holds under that id, with the same words, the Stick
says READY at once and nothing is fetched.

Once a frame the console reads its controller, which holds OUT0 low for 94
cycles. The Stick's UART takes that for a byte. The Stick looks for `$57`
and a good CRC and passes over anything else, a byte at a time.

## Replies, Stick to console

Always 36 bytes, so the console has one receive routine with a fixed count:

```text
$A5, STATE, LINE_LO, LINE_HI, TOTAL_LO, TOTAL_HI, TEXT[28], CRC_HI, CRC_LO
                                                  CRC over STATE .. TEXT
```

| STATE | Name | Meaning |
|---|---|---|
| `$00` | IDLE | no article, and nothing being fetched |
| `$01` | NO_WIFI | the Stick is not on a network |
| `$02` | FETCHING | a search is under way |
| `$03` | READY | an article is held; `TOTAL` is its number of lines. With bit 6 (`$43`), more of it is still arriving |
| `$04` | NOT_FOUND | the last search found no article |
| `$05` | ERROR | the last search failed; `TEXT` says how |

| Reply to | `STATE` | `LINE` | `TOTAL` | `TEXT` |
|---|---|---|---|---|
| SEARCH | as above | `$FF`, and the search's id in the low byte | lines, if READY; else 0 | with ERROR, a message for the console's status line; else spaces |
| LINE, held | READY | the number asked for | lines | the line |
| LINE, not held | the state, with bit 7 set | the number asked for | lines, if READY; else 0 | spaces |

**An article is offered while it is still arriving.** Once its first 28
lines are laid out, the Stick answers READY with bit 6 of `STATE` set, and
`TOTAL` is the lines it has so far. The console starts reading, and takes
the new `TOTAL` from every reply. When it wants no line, it asks every 16
frames for the line after the last it knows of, which is answered "not
held" with the total, or with the line if it has come. Lines already laid
out never change. Bit 6 is clear once the whole article is in.

**The Stick lays an article out only a few pages ahead of the reader.** It
stops 44 lines, two pages, past the furthest line it has served, and starts
again when the console has been given a line within 22 of the end of what
is held. A
request for the line past the last is not counted as reading. Nothing in
the frames changes for this: the console just sees the total grow as it
reads on.

A line's number is never `$FFxx` (an article is at most 9362 lines), so the
two kinds of reply cannot be mistaken for each other, and a reply to an
older request is never taken for the line now wanted.

`TEXT` is 28 tile numbers, ready for the screen: ASCII, padded with spaces.
On a heading line every character has bit 7 set, which is the same glyph in
the heading colour.

The Stick answers only the last request it finds when it looks. The console
listens just after it asks and then no longer, so after a spell of not
looking (a TLS handshake) the older requests are past answering.

## Timing

- The Stick starts its reply as soon as it has the request. The console
  listens until its next vblank and no longer: its NMI cuts a late reply
  off, and the console asks again in a later frame.
- A request for a line goes out after the header's split and the frame's
  scrolling, about 10600 cycles into a frame of 29780. The request takes
  1470 cycles and the reply 8316, which leaves the Stick about 9300 cycles,
  5.2 ms, to turn round.
- The console asks for at most one line a frame, and scrolls at most 4
  pixels a frame, so it needs a line every other frame at most.
- A SEARCH goes out soon after the vblank, there being no split on the
  search screen. With all 30 characters it takes 7350 cycles, which leaves
  the Stick about 7 ms.
- While the Stick is busy (joining Wi-Fi, in a TLS handshake) it may not
  answer at all. The console keeps sending the search, and gives up with a
  message after about 30 seconds of silence.
- Measured on the simulated console and line (tests/test_link.py,
  tests/test_link_timing.py): a line's reply lands with the Stick taking up
  to 5.0 ms and is cut off at 5.25; the samples of a reply fall within a
  quarter of a bit of mid-bit at every phase; and the Stick's clock may be
  3% out either way.

## Failure

No reply, a wrong marker, a bad CRC, a `LINE` that is not the one asked for
and a reply cut off by the NMI are all handled the same way: nothing is
drawn and the request is made again. A row is only ever drawn from a reply
whose CRC was good, and the screen only scrolls onto rows that were drawn.

A reply that is cut off, or that the console began to receive partway
through, leaves the two sides out of step by some bytes. There is no
resynchronizing: the console takes 36 bytes, finds no marker or a bad CRC,
and the rest of that reply has gone by before the next frame's request.

If a good reply to LINE says the Stick is not READY, the Stick no longer
holds the article (it was switched off and on). The console goes back to
its search screen and says so.

# NESpedia's link

How the console asks the nesp32 for an article and reads it, a line at a
time, over controller port 2.

The link is not NESpedia's own. It is nesp32's, and
[nesp32's `docs/PROTOCOL.md`](../../../docs/PROTOCOL.md) is the
protocol: the line, the frames, the hello, and the WIKI service this ROM
uses. This file says only how this ROM uses it. `nes/serial_link.inc` is
all of it, on nesp32's library for the console (`nes/lib/nesp.inc` there).

Before October 2026 NESpedia had a protocol and a MicroPython firmware of
its own. Both are in this repository's history.

## What the ROM sends

| When | Request |
|---|---|
| Before the first search, and again if the nesp32 ever says the service is not in use | SYS HELLO, as `WIKI` version 2, asking for the WIKI service and replies of up to 63 bytes |
| Every 8 frames while a search is under way | WIKI SEARCH: the search's id and its words |
| When the reader wants a line, at most once a frame | WIKI LINE: the line's number |
| Every 16 frames while an article is still arriving and no line is wanted | WIKI LINE for the line after the last it knows of, which is answered with the article's new length |

A search's id is one more than the last one's. The nesp32 starts fetching
when the id or the words are new and otherwise says how the search is
going, so the same request is both "search for this" and "how is it going".

## What can go wrong, and what the screen says

| What happened | The ROM |
|---|---|
| No reply, a damaged one, one for another request, or one cut off by the NMI | draws nothing and asks again in a later frame |
| No reply to 225 polls of a search, 30 seconds | `NO ANSWER FROM THE NESP32` |
| The hello is refused: no WIKI service, or another protocol | `THE NESP32 NEEDS AN UPDATE` |
| The nesp32 is not on a network | `THE NESP32 HAS NO WI-FI` |
| The search found no article | `NO ARTICLE FOUND` |
| The fetch failed | the nesp32's own words: `THE SITE DID NOT ANSWER`, `THE SITE SAID 429`, `THE CONNECTION DROPPED` |
| A line is refused because the service is not in use: the nesp32 was switched off and on | back to the search screen, with `THE NESP32 LOST THE ARTICLE`; the next search says hello again |

A row is only ever drawn from a reply whose CRC was good and whose line
number is the one asked for, and the screen only scrolls onto rows that
were drawn.

A console that is reset says hello again, and the nesp32 then starts the
service from nothing: the article is fetched afresh.

## Timing

- A request for a line goes out after the header's split and the frame's
  scrolling, about 10600 cycles into a frame of 29780. The request is 9
  bytes, 1890 cycles, and the reply 40 bytes, 9240. The reply's CRC is
  checked from a table, 35 cycles a byte, after it has arrived.
- Measured on the simulated console and line (`tests/test_link.py`), a
  line's reply lands with the nesp32 taking up to 4.25 ms and is cut off at
  4.5. nesp32's firmware took 0.2 ms at worst on a StickS3.
- The console asks for at most one line a frame, and scrolls at most 4
  pixels a frame, so it needs a line every other frame at most.
- A SEARCH goes out soon after the vblank, there being no split on the
  search screen.
- The nesp32 answers while it is fetching: the connection to Wikipedia is
  another task's work there. The console gives up on a search only after
  30 seconds of silence.

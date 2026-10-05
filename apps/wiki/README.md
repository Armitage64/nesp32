# NESpedia

A Wikipedia reader for the Nintendo Entertainment System. Type a few words
on the console, and an M5Stack Stick on controller port 2 fetches the
article from Wikipedia and hands it over a line at a time, to be read with
smooth scrolling under a fixed header.

![The search screen](docs/search.png) ![The reader](docs/reader.png)

It uses the controller-port serial link and the level-shifter hat from
[nes-radar](../nes-radar) and [nes-jukebox](../nes-jukebox), and the
jukebox's measurements of that link decided how this one runs. See
[`PLAN.md`](PLAN.md) for the design and [`docs/PROTOCOL.md`](docs/PROTOCOL.md)
for the link.

A proof of concept, and work in progress.

## Status

**It works on a real NES with an M5StickC Plus2**: a search is fetched from
Wikipedia, the article opens a couple of seconds later, and it scrolls smoothly by
the line and by the page.

| Part | State |
|---|---|
| Text: an API reply to 28-column lines | done; checked against the live API |
| Reader ROM, search screen and keyboard | working on hardware; tested on py65 |
| Link: ROM and the Stick's server code | working on hardware at 85227 baud; tested together over a cycle-exact simulated line |
| Stick firmware: Wi-Fi, HTTPS, UART, screen | working on a StickC Plus2 |

Still untried: the StickS3, an emulator (the standalone ROM should run in
Mesen 2), a long session, and a television with heavy overscan, where the
sides of the box round the search field may be cut off.

What bringing it up on hardware found is in [`PLAN.md`](PLAN.md), phase 5.
The one that mattered most: on the Stick, `uart.read()` makes a new buffer
every time it is called, and the garbage from calling it in a loop had the
Stick collecting for half of every second.

## Building

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`) and Python 3.

```sh
make                         # build/nespedia.nes and build/nespedia_link.nes
make ARTICLE=some.txt        # the standalone ROM with another text built in
make preview                 # build/search.png and build/reader.png
```

- `build/nespedia.nes` has an article built in and needs nothing on the
  controller port, so it runs in an emulator (Mesen 2 recommended) and from
  a flash cart. Whatever is searched for, it finds that article.
- `build/nespedia_link.nes` asks a Stick for its articles.

Both are NROM-256 (mapper 0) with vertical mirroring.

## Using it

Controller 1:

| | Search screen | Reader |
|---|---|---|
| Up, Down | move over the keys | scroll by the pixel, while held |
| Left, Right | move over the keys | a page up, a page down |
| A | type the key | a page down |
| B | delete; while searching, give up | a page up |
| Select | small letters / capitals | back to the search screen |
| Start | search | top of the article |

The field holds 30 characters and starts as `Nintendo Entertainment System`.
The key under the cursor pulses from white through the logo's blues. A page
glides rather than jumps, and keeps two lines in view. The mark at the
right edge shows how far the window is through as much of the article as
has been fetched, so in a long article it runs ahead until the end is in.

To see what an article will look like without a console:

```sh
tools/wiki_preview.py "Famicom Disk System"
```

That runs the Stick's own text code on this computer.

## The Stick

```sh
firmware/stick/tools/deploy.sh
```

See [`firmware/stick/README.md`](firmware/stick/README.md) for the hat, the
setup, and the order to bring things up on hardware.

## How it works

- **The console never holds the article.** It has 2 KB of memory. The Stick
  wraps the text into lines of exactly 28 characters, and the console asks
  for them by number, at most one a frame.
- **The Stick does not hold all of it either, at first.** It offers an
  article as soon as a screenful is laid out, and then fetches only two
  pages ahead of where the console is reading, so that it is nearly always
  free to answer at once.
- **A nametable is the cache.** Nametable 0 is a ring of 30 lines: line *n*
  of the article lives in row *n* mod 30. 23 rows can be in view, and the 7
  out of sight hold the lines just beyond the window. A line is only ever
  drawn into a hidden row, and the window only moves onto rows that have
  been drawn, so a slow or lost answer makes the scroll wait and can never
  put the wrong text on the screen.
- **The header is a second nametable**, and each frame changes from it to
  the article at a sprite-0 hit: one pixel sitting on the credit line, in
  that line's own colour.
- **The link is one rate, 85227 baud, both ways**, bit-banged by counting
  CPU cycles. A request and its 36-byte reply fit in the part of a frame
  left after the header. The NMI cuts off an exchange that runs late, and
  it is asked for again.
- **Wikipedia does the stripping.** One API request searches and returns
  the best page as plain text. The Stick reads the reply as it arrives,
  never holding it whole, and maps what is not ASCII to something that is.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

The ROM tests build both ROMs and run them on py65, so they need cc65; they
skip without it. The full suite takes about two minutes, most of it the
link.

- `tests/console.py` is the simulated console: a frame clock with NMIs, the
  PPU's scroll registers and sprite-0 flag as the ROM uses them, and
  controller 1. Every reader test checks, frame by frame, that the rows in
  view are exactly the article's lines at the place the scroll says.
- `tests/wire.py` is the serial line, cycle by cycle, between the link ROM
  and the Stick's real `server.py`: late, lost, damaged and cut-off
  replies, a Stick whose clock is out, one that goes deaf, one that forgets
  the article.
- `tests/test_device.py` runs the Stick's main loop against stand-ins for
  UIFlow's modules.

## Not done

- The StickS3.
- A list of search results to choose from: the first result is taken.
- Links, tables and pictures, which Wikipedia's plain text leaves out.
- PAL consoles.
- A licence. Parts are adapted from nes-radar, which is GPL-3.0, and from
  nes-jukebox, which has none yet.

Wikipedia's text is its contributors', under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); every
article fetched ends with two lines saying so.

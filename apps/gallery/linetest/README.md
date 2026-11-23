# Line palettes: a test ROM

A test of changing one palette colour in the horizontal blank of a line,
which would let the Gallery's pictures have a set of four palettes for
each row of squares instead of four for the whole picture (measured in
`../README.md`, "To do": 8.35 against 9.06, about 8% nearer the
photographs). It is a test for hardware, by itself: no nesp32, no link.
NTSC only.

## Building

```sh
make PHOTOS="lake.jpg strawberry.jpg house.jpg"    # build/linetest.nes
```

Up to three photos; without `PHOTOS` it uses the synthetic picture in
`tests/fixtures`. The ROM is UNROM (mapper 2), 128 KB, with 8 KB of CHR RAM.
Its banks:

| Bank | Picture |
|---|---|
| 0 | the test pattern |
| 1, 3, 5 | each photo with palettes changed line by line |
| 2, 4, 6 | the same photo as the Gallery makes it today |

It starts on bank 1.

## Buttons

| Button | Does |
|---|---|
| Left, Right | the picture before or after (a beep, higher further on) |
| A | what the lines do: their changes; none at all; or rendering off and on in every line that could have a change, with nothing changed (the edges alone). A low, a middle and a high beep |
| Up, Down | the timing one CPU cycle (three dots) later or earlier; the beep is higher the later it is |
| Start | the timing back to where it was built for |

Each button leaves the timed loop: the picture goes dark for about half a
second while the ROM finds the PPU's timing again.

## How it works

There is no NMI and no sprite 0. At the start, and after each button, the
ROM finds the moment the PPU sets its vblank flag to within a cycle (it
reads PPUSTATUS once a frame, each read 2/3 of a cycle earlier than the
last, until one comes before the flag). From then on every frame is timed
to the cycle: two frames take 59561 cycles with rendering on, so the loop
is one frame of 29781 cycles and one of 29780. In each line that has a
change, at dot 245 (`OFF_DOT`):

```
stx PPUMASK     rendering off; X is the next line's low address byte
sty PPUADDR     $3F00 + the entry ($3F was written earlier in the line)
sta PPUDATA     the colour
lda #hi
sta PPUADDR     the next line's address
stx PPUADDR
lda #$08
sta PPUMASK     rendering on, 24 cycles (72 dots) after it went off
```

- Only lines whose fine Y is 0 to 3 can have a change: two writes to
  PPUADDR cannot set fine Y's top bit, and the four writes that can do
  not fit in the blank. Line 120 has the write to PPUCTRL for the second
  pattern table instead.
- Rendering must be back on before the PPU moves to the line's second
  tile (dot 328). The line's first tile is fetched wrong; PPUMASK hides
  the left column, so every picture here is 248 pixels wide.
- The pixels from dot 245 to the line's end are black on a line with a
  change: up to the last 11 of the picture, the edges alone mode shows
  them.

`gen_linetest.py` makes the timed code (`build/timed.s`), counting every
instruction's cycles, a branch's with its page crossing, and makes the
pictures' banks. `lines3.c` is the converter of the experiment: the
Gallery's `picture.c`, patched by `bands.py` and `lines_patch.py`, with
palettes for each row of squares, their colours changed one a line on
the lines that can have one.

## Tried

In Mesen 2, on this Mac (not yet on hardware):

- Each photo's picture is pixel for pixel the converter's, from x = 8 to
  247, in both frames of the two, but for the last 2 to 6 pixels of a line
  with a change.
- Later by 3 cycles (Up three times), the lines' tiles move: rendering
  came back too late. Up twice is the latest that still works, so the ROM
  starts 2 cycles before it. Earlier only takes 3 more pixels off the
  right end of a changed line each cycle.

## On hardware

What to look for, on a real NES and on the MiSTer (they differ):

1. The test pattern (Left from the start): the diagonals should run on
   unbroken across the whole screen, and the stripes change colour line
   by line. A broken or shifted diagonal is a line restored wrong.
2. The left 8 pixels black, and the right end of the changed lines dark
   (the dark ticks in the edges alone mode). Anything else at the edges
   (coloured specks, flicker) is new.
3. If the pictures are broken, press Down a few times (earlier is safer),
   then Up one at a time to find where it breaks: the number of presses
   tells how far this console is from Mesen.
4. Each photo against today's (Right): whether the per-line one looks
   better, and whether its seams show.

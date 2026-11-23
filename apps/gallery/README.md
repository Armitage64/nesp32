# Gallery

Pictures from [Wikimedia Commons](https://commons.wikimedia.org) on the
Nintendo Entertainment System. Type a few words on the console, and a
[nesp32](../..) on controller port 2 finds pictures for them, makes each
one into the NES's tiles and colours, and sends it over to be shown full
screen.

The Gallery is this ROM and nesp32's COMMONS service
([`docs/PROTOCOL.md`](../../docs/PROTOCOL.md)); there is no firmware of
its own.

![The search screen](docs/search.png) ![A picture's info page](docs/info.png)
![A picture](docs/picture.png)

The last is a test picture (`tests/fixtures/commons_tower.jpg` at the top
of nesp32, made for the tests), as the nesp32's own code makes it and the
NES draws it.

**A prototype.** It runs on a simulated console against the firmware's
code, with the tests in place of Commons. It has not run on hardware, nor
in an emulator, and the firmware with COMMONS has been built but not run
on a nesp32.

## Using it

Controller 1:

| | Search screen | Info page | Picture |
|---|---|---|---|
| D-pad | move over the keys | Left, Right: the picture before or after | the same |
| A | type the key; on ⇧, small letters / capitals | | |
| B | delete; while searching, give up | back to the search | back to the search |
| Start | search | | |
| Select | on nesp32's cartridge, back to its menu; by itself, nothing | the same | the same |

A Bluetooth keyboard paired with the nesp32 works too: letters, Backspace
and Enter on the search screen, as in NESpedia; the arrows, Escape (B) and
Ctrl and Escape (Select) everywhere.

A search finds up to 20 pictures. Each has an info page first, while the
nesp32 fetches and makes it: its name, who made it, and its licence, which
most licences on Commons ask to be shown. Then the screen goes dark for
about two and a half seconds while the picture comes in, and it is shown.

**Safe search.** Commons has none of its own. COMMONS keeps to the
pictures Commons's people have judged to be good photographs (Quality and
Featured pictures), rules out words that mark adult pictures in the search
itself, refuses a search with such a word (it finds nothing), and drops a
picture whose name has one. It is a filter of words: it keeps most such
pictures out, not every one.

## Building

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler,
Python 3, and [nesp32](../..), the top of this repository (or `NESP32=`).

```sh
make                         # build/gallery.nes
make test
make preview                 # build/search.png and build/info.png
make picture FILES=photo.jpg # photo.nes.png: the photo as the Gallery shows it
tools/quality.py photo.jpg --montage m.png   # how near the picture is to the photo
```

`tools/quality.py` scores the converter on photographs: each is made into
a picture by the nesp32's own code, and both are blurred a little and
compared, lower being better. `tools/quality.py --fetch dir` saves a dozen
of Commons's thumbnails to try it on. They are their authors', so they stay
out of the repository.

`build/gallery.nes` is mapper 0 (NROM-256) with 8 KB of CHR RAM, not CHR
ROM, and vertical mirroring: a picture brings its own tiles. Flash
cartridges and emulators generally run such a ROM; it has not been tried
on one. It is not on nesp32's cartridge, whose MMC1 has CHR ROM.

## How it works

- **The nesp32 does the picture.** COMMONS asks Commons's API for a
  search, keeps each picture's thumbnail address, name, author and
  licence, and when the console opens one, fetches the thumbnail (a JPEG
  330 pixels wide, made by Commons), decodes it and makes it into a
  picture: four palettes of three colours over black, chosen for it, one
  for each square of 16 x 16 pixels, the pixels dithered in them, and at
  most 511 different tiles. Where there are more, tiles alike as the eye
  sees them (by the average of each 2 x 2 of pixels) are merged, and then
  every place takes whichever tile left is nearest its part of the
  photograph. On this Mac that takes about 65 ms; on a nesp32 it has not
  been timed.
- **A picture has two pattern tables of tiles.** The top 15 rows of tiles
  come from the first and the bottom 15 from the second; the ROM changes
  table between them every frame (`nes/viewer.inc`, `split`), on the top
  half's last line, where sprite 0 is hit. Sprite 0 is one pixel the
  nesp32 put behind a pixel of the picture, in black, so it is not seen;
  the nesp32 also works out the delay from the hit to the write for where
  it is, so that the write lands in the hblank on an NTSC console and a
  PAL one.
- **The picture comes in with the screen dark.** It is 9256 bytes: the
  tiles, the nametable, the palettes and sprite 0. The ROM asks for 64
  bytes a frame over the link and writes them straight to the PPU, with
  rendering off, so there is no vblank to fit them in. The NMI stays on,
  since the link's library needs it, and keeps off the PPU meanwhile.
- **The font is in PRG ROM.** A picture fills the CHR RAM, so the font is
  copied back for the search screen and the info page.
- **The search screen is NESpedia's** ([`apps/wiki`](../wiki)): its
  keyboard (`nes/keyboard.inc`) and its screen generator
  (`tools/gen_screen.py`), copied and changed for the Gallery.

## To do

- Try it on hardware: a nesp32 with this firmware, on a real NES and on
  the MiSTer, with a flash cartridge that has CHR RAM; time the making of
  a picture on a StickS3 and on a StickC Plus2 (which has less memory to
  make it in).
- Load a picture faster: a run of RAW's (as the Jukebox's sound is) in
  place of 145 exchanges.
- Pictures that are not JPEGs: the decoder takes PNGs, but the search
  asks only for JPEGs.
- The palettes: squares whose palette differs from their neighbours' can
  still show as blocks, in skies, gradients and fruit. Giving a square its
  neighbours' palette where that costs it little was tried and did not
  look better, and nor did ordered dithering (Bayer 4 x 4 and 2 x 2,
  diagonal lines, and Bayer with half of Floyd-Steinberg's error): calmer
  in skies, coarser in fur and faces, and no help with the blocks. What
  other converters do for them is choose the palettes and the dithering
  together (Dithertron anneals both); but measured here, the dithering
  already makes what the palettes plan for, so that would not help. The
  blocks come from four palettes being too few for the picture, and from
  colours the NES has nothing near: a sky from blue to lavender to pink is
  27 off with the best palette there is for it alone. Starting the palette
  search again in part (restarts) gained 0.4%, and was not kept. Making
  the image livelier before converting it, as the best conversions by hand
  do, was tried on the 12 test photographs, in the simulation, by eye.
  Stretching contrast to the darkest and lightest 0.5% blew out light
  skies and faces. Colour 1.2 times stronger brought back a lamp's orange
  and a parrot's yellow but made a portrait's beige ochre; 1.1 times was
  between the two. Sharpening (an unsharp mask of luma, half strength) made
  windows and eyes a little crisper. Each changed a picture by about as much
  as the palette search's own swings, so none was kept. Not tried:
  dithering for colours mixed in linear light, which is how the eye mixes
  them up and down (a composite signal mixes them across before the
  television's gamma).
- More palettes: tried, and not kept. The PPU's palettes can be written
  again partway down the screen, with rendering off for a moment. Measured
  in the converter alone, before the tiles are cut down (the 12 test
  photographs, 8.38 today): a second set of four for the bottom half, 8.01
  (4.4% nearer); a set for each row of squares, 7.48 (10.8%); MMC5's
  palette for each 8 x 8 tile, 7.91. A set for each row can be had by
  changing one colour in a line's horizontal blank, but only on lines whose
  fine Y is 0 to 3 (two writes to PPUADDR cannot set its top bit, and four
  do not fit); with the changes kept to those, the finished picture scored
  8.35 against 9.06 (7.8% nearer). A test ROM of it (commit 8cdef3c,
  `apps/gallery/linetest`, since removed: a sync to the PPU to within a
  cycle, a frame loop timed to the cycle with no NMI, and three photos made
  both ways) matched the converter pixel for pixel in Mesen, and worked on
  a real NES; there the pictures were better by only a little, and the
  black at the left (PPUMASK's hidden column) and at the right end of
  each changed line (rendering off from dot 245) stood out. Not worth the
  timed display it needs.
- On nesp32's cartridge, once it has CHR RAM.

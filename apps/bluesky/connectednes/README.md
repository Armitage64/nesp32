# From ConnectedNES

These files are from Rachel Simone Weil's
[ConnectedNES](https://github.com/hxlnt/connectedNES) (commit `2185afb`,
`NES-ROM/`), under the MIT licence in `LICENSE` here. ConnectedNES put
tweets on a NES in 2016, through a Particle Photon on the second
controller port; this ROM is the same idea on a nesp32, with Bluesky.

| File | What it is |
|---|---|
| `loadingscreen1.nam` to `4.nam` | the splash screen's nametable, a quarter each |
| `test.atr` | its attributes |
| `test.pal` | its palettes, the background's and the sprites' |
| `ascii.chr` | the first 8 KB of her tiles: the sprites' page, then the background's |

They are as she made them. `tools/gen_screen.py` takes the background's
page and the nametable, and writes this ROM's own lines of text over hers
(the last two on her blue ground, where she had one) in her font, whose characters are their ASCII codes with the bits in the
other order.

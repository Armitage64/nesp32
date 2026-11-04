# Changelog

What changed in each release of the nesp32's firmware and cartridge, for
the people who play with one and the people who write ROMs for one. A
release's firmware and cartridge go together. The games' ROM patches and
the web site change on their own: a release names only the games whose
patches it brings in, since the patches need its firmware.

Each pull request that changes something a player or a ROM sees adds a
line under *Unreleased*, with its number. `tools/release.py` makes that
section the release's. [docs/RELEASING.md](docs/RELEASING.md) has the rest.

## Unreleased

## 0.2.0 — 2026-11-04

The first numbered release.

### Firmware
- Each release has its own number, shown on the Stick's screen and in
  Setup; a build that is not a release says `-dev` after it (#35, #7)
- Joins the strongest access point when several share the network's name (#47)
- Bluetooth keyboards (StickS3): pairing, and typing into the cartridge's
  programs (#26, #34)
- Meets the other player across the Internet by room code, with no port
  to forward (#14)
- SAVE and LOAD for Family BASIC, to files in `basic/` on the nesp32's USB
  drive (#54)
- Holding a key repeats it only as fast as the console takes the keys (#54)

### Cartridge
- Setup: type the Wi-Fi password on a Bluetooth keyboard (#55)
- The keyboard across the cartridge: as a controller, in the menu, and
  a badge when one is connected (#34)
- Every program works the buttons the same way (#21)
- NESradio: a station menu on a radio dial (#16)
- Bluesky: an account's posts (#4)

### Protocol
A ROM that uses any of these needs this release's firmware.
- KBD: the keys Start ($17) and Select ($18) (#34)
- KBD `KEYS_ALL` ($06): F1–F8, F12, Home, Insert, Delete, and Ctrl and Alt
  chords (#54)
- TAPE ($16): a ROM's files, saved to and read from the nesp32's flash (#54)

### Games
Not on the cartridge, so players get them as ROM patches from the web site.
Their own notes are in the patches' README.
- Family BASIC V3, typed on a Bluetooth keyboard (#54)
- TMNT II: The Arcade Game, online co-op (#22)
- Dr. Mario, Tetris and Contra online, as BPS patches (#56)

## 0.1.0

Everything before numbered releases. Every build said 0.1.0.

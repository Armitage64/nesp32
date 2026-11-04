# Changelog

What changed in each release of the nesp32's firmware and cartridge, for
the people who play with one and the people who write ROMs for one. A
release's firmware and cartridge go together. The games' ROM patches and
the web site change on their own, and are not listed here.

Each pull request that changes something a player or a ROM sees adds a
line under *Unreleased*, with its number. `tools/release.py` makes that
section the release's. [docs/RELEASING.md](docs/RELEASING.md) has the rest.

## Unreleased

### Firmware
- The version moves: each release has its own number, shown on the
  Stick's screen and in Setup, and a build that is not a release says
  `-dev` after it (#35, #7)
- Joins the strongest access point when several share the network's name (#47)
- Bluetooth keyboards (StickS3): pairing, and typing into the cartridge's
  programs (#26, #34)
- Meets the other player across the Internet by room code, with no port
  to forward (#14)

### Cartridge
- Setup: type the Wi-Fi password on a Bluetooth keyboard (#55)
- The keyboard across the cartridge: as a controller, in the menu, and
  a badge when one is connected (#34)
- Every program works the buttons the same way (#21)
- NESradio: a station menu on a radio dial (#16)
- Bluesky: an account's posts (#4)

### Protocol
- KBD: the keys Start ($17) and Select ($18) (#34). A ROM that uses them
  needs this release's firmware.

## 0.1.0

Everything before numbered releases. Every build said 0.1.0.

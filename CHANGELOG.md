# Changelog

## Unreleased

### Games
- River City Ransom online co-op added, running faster than the original's two-player game on one console (#76)
- Bubble Bobble online sessions no longer drop at the start or in round 2: each console's leftover RAM from before the session is cleared

### Cartridge
- The cartridge menu says, under its title, when the firmware or the cartridge needs an update: when the two are from different releases, or the web site has a newer one (#80)
- Throughput test: 298296 baud to the console no longer fails a whole block at random; the test lost count of a block's first byte, not the line (#98)

### Firmware
- The Stick's screen says "Firmware update available" in red, with no console running a program, when the web site has newer firmware
- Jukebox: sounds made for the two fastest rates (7 and 8 cycles a bit) start every time, where they often played noise or nothing (#98)

### Other
- The web site's ROM patches are a page instead of a zip: each game's patch to download, the release of the game it needs (size, CRC32 and SHA-1), and how to apply it
- Mesen emulator support for NESP32 added for local testing and development (#74)
- Mesen: `nesp32.lua` starts the bridge itself when none is running, and the bridge stops a few seconds after Mesen does
- NESP32 logo displayed on Stick LCD screen at boot (#75)
- The Stick's log says why each online session ended, and Bubble Bobble sends its RAM to the log when the two games differ
- `firmware/deploy.sh` says what is wrong when ESP-IDF is missing or not installed, instead of stopping without a word, and the README lists ESP-IDF among what building needs (#93)
- `firmware/deploy.sh` and the tests find ESP-IDF where Espressif's installer puts it, `~/.espressif/v<version>/esp-idf`, as well as in `~/esp/esp-idf`

## 0.3.0 — 2026-11-08

### Cartridge
- Setup, Weather, NESpedia, Radar, and Jukebox reduced to 16 KB ROMs, freeing up four banks for new programs (#5, #61, #62)

### Firmware
- Support for PAL consoles (#72)
- Support for generic ESP32-S3 boards wired with a non-inverting resistor network. The online update tool now provides multiple options (#70)
- Use faster link speed when a game requests it, reducing CPU overhead (#15)
- Bugfix for short requests that still passed validation check

### Games
- Bubble Bobble online co-op added (#64)
- Jackal online co-op added with optimizations and faster link speed (#66, #15)
- TMNT II and Contra run at faster link speed (#15, #67)

## 0.2.0 — 2026-11-04

Roll-up of features and bugfixes since the Retro Bits video went live.

### Firmware
- Firmware and cartridge release versioning implemented (#35, #7)
- Wi-Fi connection handling improvements (#47)
- Bluetooth keyboard support on StickS3 (#26, #34)
- Online games use room codes with UDP hole punch (#14)
- Support Family Basic V3 (#53, #54)

### Cartridge
- Setup: SSID and WiFi password entry using Bluetooth keyboard (#55)
- All: Bluetooth keyboard control for all apps and menus (#34)
- All: Unified button mapping and tooltips across apps, quit to main menu (#21)
- NESradio: additional stations added (#16)
- Bluesky: an account's posts (#4)
- All: Select quits back to menu (#34)

### Games
- Family BASIC V3 using the Bluetooth keyboard with save and load to flash storage (#54)
- TMNT II: The Arcade Game, online co-op (#22)
- Dr. Mario, Tetris and Contra BPS patches (#56)

### Other
- Added sample code snippets for developers (#43)

## 0.1.0

Everything before numbered releases. Every build said 0.1.0.

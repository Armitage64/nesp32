# Changelog

## Unreleased

### Games
- Tecmo Super Bowl online added: the whole game, season included, with player 2's save replaced by player 1's when the two differ. Needs this release's firmware (#106)
- River City Ransom online co-op added, running faster than the original's two-player game on one console (#76)
- Bubble Bobble online sessions no longer drop at the start or in round 2: each console's leftover RAM from before the session is cleared

### Cartridge
- Weather: the weather for a place anywhere in the world, typed as a city and its state or country ("PORTLAND, ME", "DUBLIN, IRELAND"), in place of a US zip code; in °C and km/h outside the United States. Needs this release's firmware (#101)
- The cartridge menu says, under its title, when the firmware or the cartridge needs an update: when the two are from different releases, or the web site has a newer one (#80)
- Throughput test: 298296 baud to the console no longer fails a whole block at random; the test lost count of a block's first byte, not the line (#98)

### Firmware
- The last crash dump from an online game whose consoles stopped matching is kept over power-off and printed again on the serial port when the nesp32 starts, so it can be collected later without ESP-IDF (#106)
- Weather finds a place by its name, anywhere in the world, and a zip code kept by an earlier release is kept as a place (#101)
- The Stick's screen says "Firmware update available" in red, with no console running a program, when the web site has newer firmware
- Jukebox: sounds made for the two fastest rates (7 and 8 cycles a bit) start every time, where they often played noise or nothing (#98)
- A game's save can be copied from the console that hosts to the other before an online session, for games whose two consoles must share one (PEER's SAVE ops); and large transfers between two nesp32s go many packets at a time (#106)

### Protocol
- WEATHER PLACE and LAST_PLACE: the weather at a place named as typed, and the last one found; ZIP and LAST still work. Needs this release's firmware (#101)

### Other
- The web site records a nesp32's log in Chrome, Edge or Opera, with no ESP-IDF: a game's crash dump, and the one the nesp32 kept from earlier, go into a GitHub issue with the log's end to paste (#105)
- The web site's ROM patches are a page instead of a zip: each game's patch to download, the release of the game it needs (size, CRC32 and SHA-1), and how to apply it
- Mesen emulator support for NESP32 added for local testing and development (#74)
- Mesen: `nesp32.lua` starts the bridge itself when none is running, and the bridge stops a few seconds after Mesen does (#100)
- Mesen: the games for two, hosted and joined through the bridge as a nesp32 on this computer's network, by address or by a room's code; two Mesens, a Mesen and a real NES, or a Mesen and an opponent who presses nothing (`--peer idle`) (#102)
- The computer's idle opponent (`serial_host.py --idle`, and the Mesen bridge's) no longer ends a game after about 4 seconds: it sends back the console's digest (#102)
- Mesen: a paired keyboard stays paired after Mesen restarts, and NES Radar's airport, Weather's place and Bluesky's favorites are kept as a nesp32 keeps them over power-off (#103)
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

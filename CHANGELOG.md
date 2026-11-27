# Changelog

## Unreleased

### Firmware
- Built with ESP-IDF 6 instead of 5.5.5: 6.1.1 for the StickS3 and the generic ESP32-S3, 6.0.3 for the StickC Plus2 (#92, #17)
- HTTPS servers are checked against Mozilla's current list of root certificates, kept with the firmware, instead of ESP-IDF's, which still trusted roots Mozilla has removed: an https address now verifies as it would in Firefox, and a server that still relies on one of those older roots is refused (#96)

## 0.4.0 — 2026-11-26

### Games
- Tecmo Super Bowl online VS added: the entire game with whole sesons, player 2's saved game gets replaced by player 1's when the two differ. Optimized for improved framerate. Requires firmware 0.4.0 (#106)
- River City Ransom online co-op added, optimized to run faster than the original's two-player local game (#76)
- Bubble Bobble bugfixes to prevent game desyncs (#82)

### Cartridge
- Weather: you can now search for a location anywhere in the world, not just US zip codes. Requires firmware 0.4.0 (#101)
- Cartridge menu now tells you when new firmware and/or ROM file are available for update (#80)
- Bugfix for throughput test and jukebox's highest bitrates (#98)

### Firmware
- When consoles desync, a crash dump is saved to ESP32 non-volatile storage and can be collected later on the website (#106)
- The LCD screen indicates when a new firmware update is available (#79)
- Implemented game save copy from one console to another for Techmo Super Bowl (#106)
- NESP32 logo displayed on Stick LCD screen at boot (#75)

### Other
- Mesen emulator support for NESP32 added for local testing and development (#74) with PEER support (#102)
- Mesen lua script starts and stops the NESP32 bridge automatically (#100)
- Mesen bridge now stores NESP32 saved settings like bluetooth keyboard, radar's airport, and weather's location (#103)
- firmware/deploy.sh no longer fails silently when ESP-IDF is missing (#93)

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

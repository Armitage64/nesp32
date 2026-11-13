# Changelog

## Unreleased

### Games
- River City Ransom online co-op added, running faster than the original's two-player game on one console (#76)

### Other
- Mesen emulator support for NESP32 added for local testing and development (#74)

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

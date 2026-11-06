# Changelog

## Unreleased

### Cartridge
- Setup, Weather, NESpedia and the Jukebox take 16 KB each, leaving four banks free for more programs (#5)
- NES Radar 0.7.1 takes 16 KB too, leaving five banks free (#5)

### Firmware
- PEER's RATE: a session's line at a faster rate when the console asks for it, for a shorter exchange each frame; a ROM that does not ask is not touched by it (#15)
- No short request is put together across a quiet line: one that had lost a byte could pass its check with the next request's first byte, and two consoles' games go apart

### Games
- Bubble Bobble, online co-op: a session lasts past a game over, and 2P CONTINUE goes on at the round the two reached; its busiest rounds kept at the game's own speed
- Jackal, online co-op: a new netplay game, on an MMC3; its sessions run the line at 14 cycles a bit (#15)
- Every netplay game: the session's check that both games are alike now sees any one byte that differs (it missed most before); each game's version goes up by one, so a new patch does not join an old one
- TMNT II and Contra: sessions run the line at 14 cycles a bit with a firmware that has PEER's RATE, for a shorter exchange each frame; TMNT II's busiest level drops fewer frames, and a misheard reply no longer puts its status bar's split out for a frame (#15)

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

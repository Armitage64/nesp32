NESP32 ROM patches
==================

These patches are from {date}.

The NESP32's online games and Family BASIC contain the original games,
so they can't be handed out ready-made. Instead, this zip has a patch
for each one. Apply a patch to your own copy of the game, and the
patcher makes the NESP32 version of it.

The patches hold none of the original games: only what the NESP32 adds.


What you need
-------------

- Your own copy of each game, as a .nes file (with its 16-byte iNES
  header). It must be exactly the release listed below.
- A BPS patcher:
    RomPatcher.js, in any web browser: https://www.marcrobledo.com/RomPatcher.js/
    Floating IPS (Flips), for Windows, macOS and Linux
- NESP32 firmware {firmware} or later. The Stick shows its version at the
  top of its screen, and Setup shows it as FIRMWARE. Install the latest
  from https://nesp32.retrobits.tv/flash/


The patches
-----------

drmario_net.bps    Dr. Mario, online VS
    Needs:   Dr. Mario (Japan, USA), the first release (PRG0)
             65552 bytes, CRC32 B1F7E3E9
             SHA-1 01de1e04c396298358e86468ba96148066688194
    Won't work with: the later revision (PRG1, "Rev A").

tetris_net.bps     Tetris, online VS
    Needs:   Tetris (USA), Nintendo's
             49168 bytes, CRC32 6D72C53A
             SHA-1 77747840541bfc62a28a5957692a98c550bd6b2b
    Won't work with: Tengen's Tetris, or the European release.

contra_net.bps     Contra, online co-op
    Needs:   Contra (USA)
             131088 bytes, CRC32 C50A8304
             SHA-1 c9ea66bb7cb30ad5343f1721b1d4d3219859319b
    Won't work with: Probotector (Europe), or the Japanese Contra.

tmnt2_net.bps      Teenage Mutant Ninja Turtles II: The Arcade Game, online co-op
    Needs:   Teenage Mutant Ninja Turtles II: The Arcade Game (USA)
             524304 bytes, CRC32 C9FFBBDB
             SHA-1 40ff068d2a7be1202d843c2a9dc1220f087a094a
    Won't work with: Teenage Mutant Hero Turtles II (Europe), or the
    Japanese release.

fbasic.bps         Family BASIC, typed on a Bluetooth keyboard
    Needs:   Family BASIC V3 (Japan)
             40976 bytes, CRC32 667F6EA6
             SHA-1 21620b454c8b1253afc720feb25be9c8132dbfbc
    Won't work with: Family BASIC V1 or V2.


How to patch
------------

RomPatcher.js: open it in a browser, choose your game's .nes file as the
ROM file and the .bps from this zip as the patch, then Apply patch. It
saves the patched ROM.

Floating IPS: Apply Patch, choose the .bps, then your game's .nes file,
then where to save the patched ROM.

Copy the patched ROM to your flash cartridge's SD card or your MiSTer, as
you would any NES game.

If the patcher says the ROM is wrong (a checksum or CRC mismatch), your
copy is a different release from the one listed above, or has no iNES
header. The patch isn't broken: find the right release.


Playing
-------

- Contra and TMNT II need a flash cartridge or emulator that supports
  MMC3. Contra's patched ROM has an NES 2.0 header.
- Family BASIC needs MMC1 with battery-backed memory, and a Bluetooth
  keyboard paired to the NESP32 (a StickS3).
- For the online games, both players need the same patched game.

The user guide tells you how to play each one:
https://github.com/Armitage64/nesp32/blob/main/docs/USER_GUIDE.md

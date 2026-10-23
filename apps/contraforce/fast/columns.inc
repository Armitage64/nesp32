; The writing of a metatile's tiles into the PPU's buffer as the screen
; scrolls, from the PRG RAM: the game's from $EC26 (loc_EC26) to the end of
; sub_ECE7, which loc_EC26 jumps here from. The game's calls a routine for
; each tile, some 30 a frame of the game in a stage that scrolls up; here
; that routine is in line where it is called. The code is the game's, made
; from the disassembly at build time by tools/columns.py
; (build/columns_game.inc), and leaves what the game's leaves.

fast_columns:
.include "columns_game.inc"

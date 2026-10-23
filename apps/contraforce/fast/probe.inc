; The background's test at a point, from the PRG RAM: the game's script 00
; (ofs_006_EE54_00, in the fixed bank), which sub_0x008FD0 asks for for the
; players' and the enemies' feet and sides, some ten times a frame of the
; game for two players.
;
; The game's runs through execute_script: the stage's pair of banks in,
; the test, and the caller's pair back, two switches round a test of some
; 400 cycles, for the one byte it reads from those banks, the tile in the
; stage's metatile. Here the stage's metatiles are in the PRG RAM, copied
; there at the first test of a stage, so no bank is switched; and the
; loop that multiplies the metatile by 16 is shifts in line.
;
; The test itself is the game's, made from the disassembly at build time
; by tools/probe.py (build/probe_game.inc), with fast_probe_tile in place
; of its reading of the bank. It leaves the RAM and the registers as
; execute_script would: the jump's address in ram_0037_t01_jmp, A 0 and Y
; the caller's pair times two (the last switch's), and every one of the
; test's own temporaries, the metatile's address in the bank among them. X
; is the object's, as it was.

FAST_METATILES  = $7000         ; the stage's metatiles, 16 tiles each
METATILE_PAGES  = 16            ; 256 of them; a stage has 127 to 255
.assert FAST_METATILES + METATILE_PAGES * $100 <= $8000, error, "the metatiles leave the PRG RAM"

; In place of the game's $EEF3-$EF27, with A the metatile under the point
; (ram_0000_t42): the metatile's address in the stage's bank, in
; ram_0010_t03_metatiles_data, with ram_0014_t09 the high byte of 16 times
; the metatile, as the game's loop leaves it; the tile's place in it, in Y
; and ram_000D_tFF_useless; and the tile, in A, from the copy.
.macro fast_probe_tile
.local tile
    lsr
    lsr
    lsr
    lsr
    sta ram_0014_t09
    ora #>FAST_METATILES
    sta tile + 2
    lda ram_0000_t42
    asl
    asl
    asl
    asl
    sta tile + 1
    ldy ram_x2_stage
    clc
    adc tbl_DA57_metatiles,y
    sta ram_0010_t03_metatiles_data
    lda tbl_DA57_metatiles + $01,y
    adc ram_0014_t09
    sta ram_0010_t03_metatiles_data + $01
    lda ram_0012_t09
    and #$03
    sta ram_0012_t09
    lda ram_0013_t10
    and #$0C
    ora ram_0012_t09
    tay
    sty ram_000D_tFF_useless
tile:
    lda FAST_METATILES,y
.endmacro

fast_probe_body:                ; the game's test, as tools/probe.py makes it
.include "probe_game.inc"

fast_probe:
    lda #<ofs_006_EE54_00
    sta ram_0037_t01_jmp
    lda #>ofs_006_EE54_00
    sta ram_0037_t01_jmp + $01
    lda ram_x2_stage
    cmp fast_metatiles_stage
    beq @copied
    jsr fast_copy_metatiles
@copied:
    jmp fast_probe_game::ofs_006_EE54_00

; What the switch back to the caller's pair would leave.
fast_probe_done:
    lda ram_prg_banks_pair
    asl
    tay
    lda #$00
    rts

; The stage's metatiles into the PRG RAM, from its pair of banks, as the
; game's script 00 would have them in: 16 pages from the stage's table,
; whatever its length. Then the caller's pair back. X is kept.
fast_copy_metatiles:
    sta fast_metatiles_stage
    txa
    pha
    lda ram_prg_banks_pair
    pha
    lda #con_prg_pair + $03
    jsr fast_bankswitch
    ldy fast_metatiles_stage
    lda tbl_DA57_metatiles,y
    sta @from + 1
    lda tbl_DA57_metatiles + $01,y
    sta @from + 2
    lda #>FAST_METATILES
    sta @to + 2
    ldx #METATILE_PAGES
    ldy #$00
@from:
    lda $FFFF,y
@to:
    sta FAST_METATILES,y
    iny
    bne @from
    inc @from + 2
    inc @to + 2
    dex
    bne @from
    pla
    jsr fast_bankswitch
    pla
    tax
    rts

; The stage whose metatiles are in the PRG RAM, as ram_x2_stage; none yet.
fast_metatiles_stage:
    .byte $FF

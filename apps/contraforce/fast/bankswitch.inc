; The game's bank switch, from the PRG RAM: sub_F34C_prg_bankswitch's and
; sub_F362_switch_prg_bank_pair's, each a JMP here from its first bytes.
;
; The game's own sets a flag, calls a routine to clear another, and calls
; another to write the MMC3's R6 and R7, some 107 cycles in all. This is
; the same in line, some 71. As the game's, it begins again if a lag
; frame's NMI broke into it: that NMI's sound engine switches banks too,
; and leaves the MMC3's $8000 at R7, and sets ram_nmi_flag_2 to say so.
; It leaves A, X, Y and the flags as the game's does: A 0, Y the pair
; times two. ram_007E_useless, which the game's sets while it switches and
; clears after, and nothing reads, is left at 0.

; A: the pair (con_prg_pair), 3 for the stage's own.
fast_bankswitch:
    cmp #con_prg_pair + $03
    bne @pair
    ldy ram_stage
    lda tbl_F389,y
@pair:
    sta ram_prg_banks_pair
@again:
    ldy #$00
    sty ram_nmi_flag_2
    asl
    tay
    lda #$06
    sta ram_for_8000
    sta MMC3_SELECT
    lda tbl_F393_prg_pairs,y
    sta MMC3_DATA
    lda #$07
    sta ram_for_8000
    sta MMC3_SELECT
    lda tbl_F393_prg_pairs + $01,y
    sta MMC3_DATA
    lda ram_nmi_flag_2
    bne @broken
    rts
@broken:
    lda ram_prg_banks_pair
    jmp @again

; The pair in ram_prg_banks_pair, as the sound engine puts it back.
fast_switch_pair:
    lda ram_prg_banks_pair
    asl
    tay
    lda #$06
    sta ram_for_8000
    sta MMC3_SELECT
    lda tbl_F393_prg_pairs,y
    sta MMC3_DATA
    lda #$07
    sta ram_for_8000
    sta MMC3_SELECT
    lda tbl_F393_prg_pairs + $01,y
    sta MMC3_DATA
    lda #$00
    rts

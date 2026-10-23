; Two of the game's loops, from the PRG RAM, each jumped to from its first
; bytes, and leaving what the game's leaves.

; sub_F994's clearing of the three bytes each of the 22 objects have for
; the boxes they touch, a loop of 20 cycles an object: here a run of
; stores, 12. Then back to the game's routine, which loads A and X again.
fast_clear_boxes:
    lda #$00
.repeat $16, object
    sta ram_0736_obj + object
    sta ram_074C_obj + object
    sta ram_0762_obj + object
.endrep
    jmp fast_boxes_cleared

; sub_DEBD's: A zeros into the PPU's second buffer from X, by a call for
; each to sub_DE24_write_A_to_buffer_and_INX, 22 cycles a byte; here 10.
; A is 0, Y 0 and X past the last, as the game's leaves them.
fast_zeros:
    tay
    lda #$00
@zero:
    sta ram_ppu_buffer_2,x
    inx
    dey
    bne @zero
    rts

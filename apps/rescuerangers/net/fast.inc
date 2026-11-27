; Faster ways through two of the game's busiest routines, for the frames
; that a session's exchange would push past the vblank (README.md, "The
; frame rate"). Each does what the game's own does, to the byte: the same
; memory written, scratch ($02-$09) and all, and the same registers and
; flags left; tests/test_fast.py holds them to rescuerangers_net_slow.nes,
; which is built with NET_SLOW and keeps the game's own.
;
; They run in the PRG RAM, beside net/cart.inc's code: the fixed bank
; has no room, and from the PRG RAM they are reached with no bank switch.

.ifndef NET_SLOW

.pushseg
.segment "NETCODE"

; Tables first, each on a page of its own, so that no read of one by an
; index crosses a page.
.align $100

; The sprites' slots from X on: where in fast_hide_from to begin, for X
; a multiple of 4 (the slot's first byte), as a word at X.
fast_hide_at:
.repeat 64, slot
    .word fast_hide_from + 3 * slot
    .word $0000
.endrepeat

; Of an X in the level: (X >> 4) & 1, and (X >> 5) & 7.
fast_x4:
.repeat 256, i
    .byte (i >> 4) & $01
.endrepeat
fast_x5:
.repeat 256, i
    .byte (i >> 5) & $07
.endrepeat
; Of a Y: (Y >> 2) & $38, and (Y >> 3) & $02.
fast_y38:
.repeat 256, i
    .byte (i >> 2) & $38
.endrepeat
fast_y2:
.repeat 256, i
    .byte (i >> 3) & $02
.endrepeat

; L7_C21E: every sprite's slot from $97 on hidden (Y $F8), and slot 0
; too when $97 is 4. The game's loop takes 16 cycles a slot; this goes
; into a run of stores at the slot, 4 a slot. A, X and the flags as the
; game's leaves them: A $F8, X 0, Z set, N clear, C from the CPX.
fast_hide_sprites:
    ldx $97
    lda fast_hide_at,x
    sta @into+1
    lda fast_hide_at+1,x
    sta @into+2
    cpx #$04
    bne :+
    lda #$F8
    sta $0200
:
    lda #$F8
@into:
    jmp fast_hide_from          ; the address is written above
fast_hide_from:
.repeat 64, slot
    sta $0200 + 4 * slot
.endrepeat
    ldx #$00
    rts

; L7_EB3B: what the level's collision map has at point Y of object X
; (the point's offsets from the object in L7_EC97 and L7_EBFA), in A, with
; the game's scratch as the game's leaves it. Its shifts are tables here,
; and two of its loads are not made twice.
fast_tile_at:
    lda #$00
    sta $02
    lda L7_EC97,y
    bpl :+
    dec $02
:
    clc
    adc $04F0,x
    sta $06
    lda $0500,x
    adc $02
    sta $03
    bmi @range                  ; as the game's: $04, $05, $07, $08 left as they were
    sty fast_point
    ldy $06
    lda fast_x4,y
    sta $04
    lda fast_x5,y
    sta $05
    ldy fast_point
    lda $0520,x
    sta $08
    lda L7_EBFA,y
    bmi @up
    clc
    adc $0510,x
    bcs @wrap
    cmp #$F0
    bcc @down
@wrap:
    adc #$0F
    inc $08
@down:
    sta $07
    jmp @range
@up:
    eor #$FF
    sta $09
    inc $09
    lda $0510,x
    sec
    sbc $09
    bcs :+
    sbc #$0F
    dec $08
:
    sta $07
@range:
    lda $07
    sec
    sbc SCROLL_Y
    lda $08
    sbc $FB
    beq @tile
    bcs @none
    cpx #$02
    bcs @none
    cpy #$06
    bcc @top
@none:
    lda #$00
    rts
@top:
    lda SCROLL_Y
    sta $07
    lda $FB
    sta $08
@tile:
    lda $03
    and #$01
    tay
    lda L7_ED34,y
    ldy $07
    ora fast_y38,y
    ora $05
    sta $05
    asl a
    sta $02
    lda fast_y2,y
    ora $04
    sta $04
    and #$01
    clc
    adc $02
    tay
    lda $0600,y
    sta $02
    ldy $04
    lda L7_ED36,y
    beq :+
    and $02
    rts
:
    lda $02
    lsr a
    lsr a
    lsr a
    lsr a
    rts

.popseg

.endif

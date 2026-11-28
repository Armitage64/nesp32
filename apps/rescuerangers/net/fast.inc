; Faster ways through three of the game's busiest routines, for the frames
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

; L5_8164 on (L5_802F's last part): an object's sprites into the sprites'
; slots from $97, each hidden (Y $F8) where it falls off the screen. The
; game adds each sprite's offset to the object's place and reads the offset
; again for its sign, to tell from the carry whether the sprite is off: off
; is the sum outside 0-255, which is the overflow of the same sum with the
; place's top bit flipped. So the places are kept here with it flipped,
; written into the loop's loads (it runs in the PRG RAM), and the sum's top
; bit flipped back: the same bytes in the slots, some 16 cycles a sprite
; fewer. $97 is written once, at the end, with what it would have been.
; The memory, X and Y are left as the game's leaves them; A and the flags
; are not, and are dead: both of L5_802F's calls (L5_800B, L5_8020) go on
; with INC $96 and LDX $96.
fast_sprites:
    lda $0450,x
    sta $13
    eor #$80
    sta @x+1
    lda $0440,x
    sta $12
    eor #$80
    sta @y+1
    ldy #$00
    lda ($02),y
    sta $04
    iny
    lda ($02),y
    clc
    adc $11
    pha
    lda $0400,x
    and #$20
    sta $11
    pla
    tax
    lda L5_B08E,x
    sec
    sbc #$02
    sta $05
    lda L5_B145,x
    sbc #$00
    sta $06
    ldx $97
    beq @done
@sprite:
    iny
    lda ($02),y
    sta $0201,x
@y:
    lda #$00                    ; the object's Y, its top bit flipped
    clc
    adc ($05),y
    eor #$80
    sta $0200,x
    bvs @off_y
    iny
    lda ($02),y
    eor $10
    ora $11
    sta $0202,x
@x:
    lda #$00                    ; the object's X, its top bit flipped
    clc
    adc ($05),y
    eor #$80
    sta $0203,x
    bvs @off
    inx
    inx
    inx
    inx
    beq @full
    dec $04
    bpl @sprite
    stx $97
@done:
    rts
@full:
    stx $97                     ; every slot taken: the game stops here too
    rts
@off_y:
    iny
@off:
    lda #$F8
    sta $0200,x
    dec $04
    bpl @sprite
    stx $97
    rts

.popseg

.endif

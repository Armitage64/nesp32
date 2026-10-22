; Netplay: the sprite pass, faster. net/net.asm includes it, unless
; NET_SLOW_SPRITES is defined; it is linked in bank 29 and runs from the
; PRG RAM, where net_reset copies it.
;
; The game builds an object's sprites from its data (SPRITE_CREATE_FROM_PTR):
; a count, then four bytes a tile, its Y, tile, attributes and X, put
; about the object's place and flipped with it. For each tile its loop
; works out again what is the same for the whole object: whether it is
; flipped either way, whether the tile is moved to the second player's
; sheet ($40 on), the palette, and which side of the screen a tile has to
; be on to be shown. In level 7 that is a third of the frame's time.
;
; Here all of that is worked out once an object, and written into the
; loop's own instructions: the place, the flip, the $40, the palette, the
; side, as immediates and as a branch. There is a loop for each way of
; flipping, as a flip is a subtraction in place of an addition; and each
; comes plain, for an object with no $40 and no palette of its own, which
; is nearly every tile, and full. The data is read through the banks at
; $8000 and $A000, wherever it is, which is why the loops run from the PRG
; RAM: it is in no bank that the data could be in, and it can be written
; to.
;
; Everything the game's loop leaves is left the same: the sprites, and
; TMP_00 (the last tile's attributes), TMP_03, TMP_04, TMP_09 and TMP_0F
; (test_sprites.py holds the two to it, object by object and frame by
; frame).

.segment "SPRITES"

; In place of SPRITE_CREATE_FROM_PTR, which jumps here: A is the high byte
; of the object's data, TMP_08 its low.
net_sprites:
    sta TMP_09
    ldy #$00
    lda (TMP_08),y
    bne :+
    rts                         ; no tiles
:
    sta TMP_03
    ; Plain: no $40 (_4C_UNK's bit 7, or none of the flags the game's loop
    ; looks at for it) and no palette.
    lda TMP_0C
    bne @full
    bit _4C_UNK
    bmi @plain
    lda TMP_12
    ora TMP_13
    ora TMP_0E
    bne @full

@plain:
    bit TMP_07                  ; the object's flips: N vertical, V horizontal
    bmi @plain_v
    bvs @plain_h
    jmp net_sprites_00

@plain_h:
    jmp net_sprites_01

@plain_v:
    bvs @plain_vh
    jmp net_sprites_10

@plain_vh:
    jmp net_sprites_11

@full:
    bit TMP_07
    bmi @full_v
    bvs @full_h
    jmp net_sprites_00_full

@full_h:
    jmp net_sprites_01_full

@full_v:
    bvs @full_vh
    jmp net_sprites_10_full

@full_vh:
    jmp net_sprites_11_full

; One object's tiles, flipped as vflip and hflip say; plain, or full.
.macro net_sprite_loop vflip, hflip, full
.local tile, ypos, add_skip, add, add_end, flip, pal_cmp, pal_branch, pal
.local attr_keep, attr_store, xpos, edge, edge_limit, next, out, invalid, last
.local tile_13, tile_0e, tile_none, tile_40, tile_set, pal_on, pal_beq, pal_set
.local edge_zero, edge_set

    ; Where the object is. A flipped tile is placed from the far side of
    ; its 8 by 16 pixels.
    lda TMP_01
.if vflip
    sec
    sbc #$10
.endif
    sta ypos+1
    lda TMP_02
.if hflip
    sec
    sbc #$08
.endif
    sta xpos+1
    lda TMP_07
    sta flip+1

.if full
    ; The second player's sheet: none (A 00), every tile (A $40, X 0), or
    ; those below $80 (X past the addition), as the game's loop decides it
    ; for each.
    ldx #$00
    lda #$00
    bit _4C_UNK
    bmi tile_set
    lda TMP_12                  ; player 2
    beq tile_13
    ldx #add_end - add_skip - 2
    bne tile_40

tile_13:
    lda TMP_13                  ; player 1's second slot, but in level 7
    beq tile_0e
    lda LEVEL_SCREEN_ON
    cmp #$07
    bne tile_40
    beq tile_none

tile_0e:
    lda TMP_0E                  ; objects $0A-$0C of the ones it marks
    beq tile_set
    lda TMP_0B
    cmp #$0A
    bcc tile_none
    cmp #$0D
    bcc tile_40

tile_none:
    lda #$00
    beq tile_set

tile_40:
    lda #$40

tile_set:
    sta add+1
    stx add_skip+1

    ; The palette: the data's (CMP #0, BCS: kept), the object's for every
    ; tile (CMP #4, BEQ: never kept), or for a player the object's but
    ; where the data has palette 2 (CMP #2, BEQ).
    lda TMP_0C
    bne pal_on
    ldx #$00
    lda #$B0                    ; BCS
    bne pal_set

pal_on:
    sta pal+1
    ldx #$04
    lda TMP_12
    ora TMP_13
    beq pal_beq
    ldx #$02

pal_beq:
    lda #$F0                    ; BEQ

pal_set:
    stx pal_cmp+1
    sta pal_branch
.endif

    ; Which X a tile is shown at, as X plus EDGE below EDGE_LIMIT: TMP_06
    ; 0, from the left of the screen to $BC, or from $40 for an object at
    ; the right; bit 0, from $C0; 2, below $3D.
    lda TMP_06
    beq edge_zero
    lsr a
    lda #$40
    ldx #$40
    bcs edge_set
    ldx #$03
    bne edge_set

edge_zero:
    ldx #$03
    lda #$C0
    bit TMP_02
    bpl edge_set
    ldx #$C0

edge_set:
    stx edge+1
    sta edge_limit+1

    ldx TMP_04
    ldy #$00

tile:
    iny
.if vflip
ypos:
    lda #$00
    sec
    sbc (TMP_08),y
.else
    lda (TMP_08),y
    clc
ypos:
    adc #$00
.endif
    sta SPRITE_PAGE,x
    iny
    lda (TMP_08),y
.if full
add_skip:
    bmi add_end
    clc
add:
    adc #$00
add_end:
.endif
    sta SPRITE_PAGE+1,x
    iny
    lda (TMP_08),y
flip:
    eor #$00
.if full
    sta TMP_00
    and #$03
pal_cmp:
    cmp #$00
pal_branch:
    beq attr_keep
    lda TMP_00
    and #$FC
pal:
    ora #$00
    sta TMP_00
    bne attr_store              ; a palette of the object's is not 0

attr_keep:
    lda TMP_00

attr_store:
.endif
    sta SPRITE_PAGE+2,x
    iny
.if hflip
xpos:
    lda #$00
    sec
    sbc (TMP_08),y
.else
    lda (TMP_08),y
    clc
xpos:
    adc #$00
.endif
    sta SPRITE_PAGE+3,x
    clc
edge:
    adc #$00
edge_limit:
    cmp #$00
    bcs invalid

next:
    inx
    inx
    inx
    inx
    beq out                     ; the page is full
    dec TMP_03
    bne tile
    stx TMP_04
.if full
    rts
.else
    beq last
.endif

out:
    inc TMP_0F
.if full
    rts
.else

    ; The last tile's attributes, as the game's loop leaves them in TMP_00.
last:
    dey
    lda (TMP_08),y
    eor TMP_07
    sta TMP_00
    rts
.endif

invalid:
    lda #$F4
    sta SPRITE_PAGE,x
    lda #$00
    sta SPRITE_PAGE+1,x
    sta SPRITE_PAGE+2,x
    sta SPRITE_PAGE+3,x
    beq next
.endmacro

net_sprites_00:
    net_sprite_loop 0, 0, 0
net_sprites_01:
    net_sprite_loop 0, 1, 0
net_sprites_10:
    net_sprite_loop 1, 0, 0
net_sprites_11:
    net_sprite_loop 1, 1, 0
net_sprites_00_full:
    net_sprite_loop 0, 0, 1
net_sprites_01_full:
    net_sprite_loop 0, 1, 1
net_sprites_10_full:
    net_sprite_loop 1, 0, 1
net_sprites_11_full:
    net_sprite_loop 1, 1, 1

; In place of the game's sort of the objects by their X, right to left
; (OBJ_PROCESS_DISPLAY_ORDER), which jumps here with Y the count less one,
; and goes on at MOD_ONE. Theirs is a bubble sort, every pass of it, so as
; many compares as the count squared; this is an insertion sort, in as few
; as the count when the order is the last frame's. Both are stable, so the
; order is the same. The positions (TMP_00 on) are overwritten after, so
; only TMP_14 is left as the game's leaves it: 0, or for none $FF.
net_sort:
    tya
    beq @done                   ; one
    bmi @done                   ; none
    ldx #$01

@next:
    lda TMP_00,x
    sta net_sort_key
    lda SPRITE_ORDERING_ARR_OBJ_INDEXES,x
    sta net_sort_obj
    txa
    tay

@shift:
    dey
    bmi @place
    lda a:TMP_00,y
    cmp net_sort_key
    bcs @place                  ; not to the right of the one put in
    sta a:TMP_00+1,y
    lda a:SPRITE_ORDERING_ARR_OBJ_INDEXES,y
    sta a:SPRITE_ORDERING_ARR_OBJ_INDEXES+1,y
    bcc @shift

@place:
    iny
    lda net_sort_key
    sta a:TMP_00,y
    lda net_sort_obj
    sta a:SPRITE_ORDERING_ARR_OBJ_INDEXES,y
    inx
    cpx TMP_15
    bcc @next
    lda #$00
    sta TMP_14

@done:
    jmp MOD_ONE

.segment "CODE"

SPRITES_PAGES = 8

; From the reset: the loop to the PRG RAM.
net_sprites_copy:
    ldx #$00
@page:
    .repeat SPRITES_PAGES, page
    lda __SPRITES_LOAD__ + page * $100,x
    sta __SPRITES_RUN__ + page * $100,x
    .endrep
    inx
    bne @page
    rts

.import __SPRITES_LOAD__, __SPRITES_RUN__, __SPRITES_SIZE__
.assert __SPRITES_SIZE__ <= SPRITES_PAGES * $100, error, "net_sprites_copy copies too little"
.assert __SPRITES_LOAD__ + SPRITES_PAGES * $100 <= $C000, error, "net_sprites_copy reads past bank 29"

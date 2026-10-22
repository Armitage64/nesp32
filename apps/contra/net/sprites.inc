; Netplay: the sprite pass, faster. net/net.inc includes it, unless
; NET_SLOW is defined; it runs from the PRG RAM with the rest of
; netplay's code. draw_sprites (bank 1) jumps here, with bank 1 in, and
; the sprites' data and the HUD's are read from there.
;
; The game builds the sprites of each slot of CPU_SPRITE_BUFFER from their
; data (load_sprite_to_cpu_mem): a count, then four bytes a tile, its Y,
; tile, attributes and X, put about the sprite's place and flipped with
; it. For each tile it works out again what is the same for the whole
; sprite: whether it is flipped either way, the recoil's pixel, and the
; attributes' mask. Here that is worked out once a sprite and written into
; the loop's own instructions, as immediates. There is a loop for each way
; of flipping, as a flip is a subtraction in place of an addition.
;
; The HUD's medals are the game's own loop (draw_hud_sprites), with the
; step to the next place in line where the game calls for it.
;
; Then the game hides every place in the OAM buffer that no tile took, most
; of its 64 in most frames, a loop of 18 cycles a place. Here that is a
; run of stores, one for each place in the order the game visits them, 4
; cycles each, entered where the first is and ended where the last is.
;
; Everything the game's pass leaves is left the same: the OAM buffer, $00
; to $0D, and X and Y (test_sprites.py holds the two to it, on any memory
; and in the game tick by tick).

.import sprite_ptr_tbl_0, sprite_ptr_tbl_1, hud_sprites, sprite_medal_x_offset

; In place of draw_sprites.
net_sprites:
    lda OAMDMA_CPU_BUFFER_OFFSET
    clc
    adc #$4c                    ; the game's sprites from another place each frame
    sta OAMDMA_CPU_BUFFER_OFFSET
    sta $04
    ldy #$3f                    ; places left in the OAM buffer, less one
    sty $07
    lda SPRITE_LOAD_TYPE
    beq @slots
    jsr net_hud

@slots:
    ldx #$19

@slot:
    lda CPU_SPRITE_BUFFER,x
    beq @next_slot              ; none in this slot
    stx $05
    ldy SPRITE_ATTR,x
    sty $00
    ldy SPRITE_Y_POS,x
    sty $01
    ldy SPRITE_X_POS,x
    sty $02
    jsr net_sprite
    ldy $07
    bmi @full                   ; the OAM buffer is full
    ldx $05

@next_slot:
    dex
    bpl @slot
    inx
    stx $05                     ; the last slot, 0
    ldy $07
    ldx $04
    jmp net_hide

@full:
    rts

; The medals, or GAME OVER, of each player: draw_hud_sprites.
net_hud:
    lda PLAYER_MODE
    ldy DEMO_MODE
    beq @first
    lda #$01                    ; player 2 first, but in the demo

@first:
    sta $00
    ldx $04

@player:
    ldy #$04                    ; GAME OVER
    lda DEMO_MODE
    bne @four
    ldy $00
    lda P1_GAME_OVER_STATUS,y
    ldy #$04
    lsr
    bcs @four
    ldy $00
    lda P1_NUM_LIVES,y
    ldy #$00                    ; medals, one a life
    cmp #$04
    bcc @count

@four:
    lda #$04

@count:
    sta $01

@medal:
    dec $01
    bmi @next_player
    lda #$10
    sta OAMDMA_CPU_BUFFER,x
    lda hud_sprites,y
    sta OAMDMA_CPU_BUFFER+1,x
    lda $00
    sta OAMDMA_CPU_BUFFER+2,x
    lsr
    lda sprite_medal_x_offset,y
    bcc @shown
    adc #$af                    ; player 2's, at the right

@shown:
    sta OAMDMA_CPU_BUFFER+3,x
    dec $07
    txa
    clc
    adc #$c4
    tax
    iny
    bne @medal                  ; always

@next_player:
    dec $00
    bpl @player
    stx $04
    rts

; One slot's sprite, in place of load_sprite_to_cpu_mem: A its code, $00
; its attributes, $01 its Y and $02 its X.
net_sprite:
    asl
    tay
    bcs @second
    lda sprite_ptr_tbl_0-2,y
    sta $08
    lda sprite_ptr_tbl_0-1,y
    bcc @have                   ; always

@second:
    lda sprite_ptr_tbl_1,y
    sta $08
    lda sprite_ptr_tbl_1+1,y

@have:
    sta $09
    ldy #$00
    lda ($08),y
    beq @none                   ; no tiles
    iny
    cmp #$fe
    bne @regular
    jmp net_sprite_small

@none:
    rts

@regular:
    sta $03
    lda $00
    and #$c8                    ; the flips, and the recoil's pixel
    sta $0b
    lda $00
    lsr
    lsr
    lsr
    ldx #$fc                    ; the palette the sprite's own, or the tiles'
    lda #$23
    bcs @attributes
    ldx #$ff
    lda #$20

@attributes:
    and $00
    sta $00
    stx $0d
    ldx $04
    bit $0b                     ; N vertical, V horizontal
    bmi @v
    bvs @h
    jmp net_tiles_00

@h:
    jmp net_tiles_01

@v:
    bvs @vh
    jmp net_tiles_10

@vh:
    jmp net_tiles_11

; One sprite's tiles, flipped as vflip and hflip say. X is the place in
; the OAM buffer, Y the tile's first byte.
.macro net_tile_loop vflip, hflip
.local tile, have_y, ypos, attr_and, attr_or, attr_eor, xpos, next, left, xneg, shared
.local no_recoil, kept

    lda $0d
    sta attr_and+1
    lda $00
    sta attr_or+1
    lda $0b
    sta attr_eor+1
    lda $02
    sta xpos+1
    sta xneg+1
    ; A tile's Y is the sprite's, plus its own, plus the recoil's pixel; or
    ; flipped, $F0 less its own and the pixel.
    lda $0b
    and #$08
    beq no_recoil
    lda #$01

no_recoil:
.if vflip
    eor #$ff
    sec
    adc #$f0
.endif
    clc
    adc $01
    sta ypos+1

tile:
    lda ($08),y
    cmp #$80
    beq shared                  ; the rest of the tiles are elsewhere

have_y:
.if !hflip
    sta $0c                     ; as the game's loop leaves it, but for the pixel
.endif
.if vflip
    eor #$ff
    sec
.else
    clc
.endif
ypos:
    adc #$00
    sta OAMDMA_CPU_BUFFER,x
    iny
    lda ($08),y
    sta OAMDMA_CPU_BUFFER+1,x
    iny
    lda ($08),y
attr_and:
    and #$00
attr_or:
    ora #$00
attr_eor:
    eor #$00
    sta OAMDMA_CPU_BUFFER+2,x
    iny
    lda ($08),y
.if hflip
    sta $0c
    eor #$ff
    sec
    adc #$f8
.endif
    ; Shown if the sprite's X and the tile's, signed, are on the screen.
    bmi left
    clc
xpos:
    adc #$00
    bcs next
    sta OAMDMA_CPU_BUFFER+3,x
    dec $07
    txa
    adc #$c4
    tax

next:
    iny
    dec $03
    bne tile
    stx $04
.if !hflip
    lda $0b
    and #$08
    beq kept
    inc $0c                     ; the pixel, as the game's loop adds it
kept:
.endif
    rts

left:
    clc
xneg:
    adc #$00
    bcc next
    sta OAMDMA_CPU_BUFFER+3,x
    dec $07
    txa
    adc #$c3                    ; and the carry
    tax
    jmp next

    ; A tile of $80 says where the rest are, and that they have no
    ; recoil's pixel.
shared:
    lda $0b
    and #$f7
    sta $0b
    sta attr_eor+1
    iny
    lda ($08),y
    sta $06
    iny
    lda ($08),y
    sta $09
    lda $06
    sta $08
    lda $01
.if vflip
    clc
    adc #$f0
.endif
    sta ypos+1
    ldy #$00
    lda ($08),y
    jmp have_y
.endmacro

net_tiles_00:
    net_tile_loop 0, 0
net_tiles_01:
    net_tile_loop 0, 1
net_tiles_10:
    net_tile_loop 1, 0
net_tiles_11:
    net_tile_loop 1, 1

; A small sprite, of one tile, as the game's: Y is 1.
net_sprite_small:
    ldx $04
    lda #$f8
    clc
    adc $01
    sta OAMDMA_CPU_BUFFER,x
    lda ($08),y
    sta OAMDMA_CPU_BUFFER+1,x
    iny
    lda ($08),y
    ora $00
    sta OAMDMA_CPU_BUFFER+2,x
    lda $02
    sec
    sbc #$04
    bcc @exit                   ; off the left of the screen
    sta OAMDMA_CPU_BUFFER+3,x
    dec $07
    txa
    clc
    adc #$c4
    tax
    stx $04

@exit:
    iny
    rts

; The game's next place after one is $C4 on, which visits the 64 in the
; order net_hide_order gives, place K being the order's (17 * K) mod 64th.
; X is where the first place to hide is and Y one less than how many: the
; game stores $F4 as the Y of each. It leaves X at the place after the
; last, A the same, and Y $FF.
NET_HIDE_STEP   = $c4 / 4       ; 49, whose inverse mod 64 is 17
.assert (NET_HIDE_STEP * 17) .mod 64 = 1, error

net_hide:
    txa
    lsr
    lsr
    tax
    lda net_hide_first,x        ; where in the run the place is
    tax
    lda net_hide_low,x
    sta @enter+1
    lda net_hide_high,x
    sta @enter+2
    stx net_hide_from
    tya
    sec
    adc net_hide_from           ; and where the run is to end
    tax
    lda net_hide_low,x
    sta @end+1
    sta @back+1
    lda net_hide_high,x
    sta @end+2
    sta @back+2
    lda #$60                    ; RTS
@end:
    sta $ffff
    lda #$f4
@enter:
    jsr $ffff
    lda #$8d                    ; STA, as it was
@back:
    sta $ffff
    lda net_hide_order,x
    tax
    ldy #$ff
    rts

net_hide_from:
    .byte $00

; Two rounds of the 64 places, so that any 64 in a row are in it.
net_hide_run:
.repeat 128, step
    sta OAMDMA_CPU_BUFFER + 4 * ((NET_HIDE_STEP * step) .mod 64)
.endrep
    rts

net_hide_order:
.repeat 128, step
    .byte 4 * ((NET_HIDE_STEP * step) .mod 64)
.endrep

net_hide_first:
.repeat 64, place
    .byte (17 * place) .mod 64
.endrep

net_hide_low:
.repeat 128, step
    .byte <(net_hide_run + 3 * step)
.endrep

net_hide_high:
.repeat 128, step
    .byte >(net_hide_run + 3 * step)
.endrep

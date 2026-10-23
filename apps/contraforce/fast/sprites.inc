; The sprite pass, from the PRG RAM: sub_D2D1, which jumps here from its
; first bytes. The pause's sprites are still the game's
; (fast_sprites_paused, in the fixed bank).
;
; The game's walks the 26 objects from one that changes each frame, for
; each with an animation calls sub_D35B to find its sprite's data, and for
; each of the sprite's tiles calls a routine for its X and another for its
; tile and Y, working out again for every tile what is the same for all of
; them: the object's X and Y, whether the tile's X is flipped, the
; attributes, and whether the tile is on the screen, from the high byte of
; its X. Then it hides the places in the OAM buffer that no tile took, 23
; cycles each. Here the object's are worked out once and written into the
; tile loop's own instructions, as immediates; the test of the high byte
; is a branch on the carry, which of BCC or BCS written in too. A flip is
; another loop, and so are the players' tiles, which the game renumbers.
; The empty objects are passed in two runs, from the first to the 26th and
; from the 1st round to the first, and the unused places are hidden by a
; run of stores (fast_hide), 4 cycles each.
;
; Everything the game's pass leaves is left the same: the OAM buffer, its
; temporaries ($00-$03, $08, $0A, $0E, $10-$14 and $18-$1F) and
; ram_base_oam_offset. Its registers are not: nothing after reads them.

FAST_OBJECTS    = $1A           ; objects with sprites, 0-$19
OP_BCC          = $90
OP_BCS          = $B0

fast_sprites:
    lda ram_base_oam_offset
    clc
    adc #$4C                    ; the game's sprites from another place each frame
    sta ram_base_oam_offset
    tax
    stx fast_oam_x
    lda #$40
    sta ram_0001_t37_sprites_counter
    lda ram_pause_flag
    beq @play
    jmp fast_sprites_paused

@play:
    lda ram_frm_cnt
    and #$0F
    tay
    lda tbl_D55B,y
    sta ram_0008_t11_object_index
    sta fast_first_object
    tay
    ; From the first to the last, then from 0 to the first.
    lda #FAST_OBJECTS
    sta @end_run + 1
@object:
    lda ram_obj_animation_lo,y
    bne @sprite
@next_object:
    iny
@end_run:
    cpy #FAST_OBJECTS
    bne @object
    lda @end_run + 1
    cmp fast_first_object
    beq @all                    ; both runs done
    lda fast_first_object
    sta @end_run + 1
    ldy #$00
    cpy fast_first_object
    bne @object
@all:
    ; As the game's leaves them: the first object again, and no more to do.
    lda fast_first_object
    sta ram_0008_t11_object_index
    lda #$00
    sta ram_000A_t15_loop_counter
    lda ram_0001_t37_sprites_counter
    beq @rts
    jmp fast_hide

@sprite:
    sty ram_0008_t11_object_index
    jsr fast_object
    ldy ram_0008_t11_object_index
    lda ram_0001_t37_sprites_counter
    bne @next_object
    ; The buffer is full: the game's loop stops with this object's index
    ; and the objects it had still to look at, this one among them.
    tya
    sec
    sbc fast_first_object
    bcs @counted
    adc #FAST_OBJECTS
@counted:
    eor #$FF
    sec
    adc #FAST_OBJECTS
    sta ram_000A_t15_loop_counter
@rts:
    rts

fast_first_object:
    .byte $00

; One object's sprite: sub_D35B's, as the game's but for the tiles. A is
; the object's animation, ram_0008_t11_object_index the object.
fast_object:
    sta ram_0010_t09_animation_id
    ldy ram_0008_t11_object_index
    lda ram_0600_obj,y
    lsr
    lsr
    lsr
    and #$1E
    tay
    lda tbl_D53B,y
    sta ram_0013_t04_pos_X_hi
    lda tbl_D53C,y
    beq @shown
    rts                         ; not on the screen

@shown:
    sta ram_0014_tFF_useless
    ldy ram_0008_t11_object_index
    lda ram_obj_animation_hi,y
    and #$3C
    lsr
    jsr sub_FBF0                ; the sprites' bank
    tay
    lda ram_0010_t09_animation_id
    asl
    bcc @low
    clc
    adc tbl_0x000011_spr_data,y
    sta ram_0010_t02_data
    lda tbl_0x000011_spr_data + $01,y
    adc #$01
    bne @have                   ; always
@low:
    clc
    adc tbl_0x000011_spr_data,y
    sta ram_0010_t02_data
    lda tbl_0x000011_spr_data + $01,y
    adc #$00
@have:
    sta ram_0010_t02_data + $01
    ldy #$00
    lda (ram_0010_t02_data),y
    sta ram_0002_t04_data
    iny
    lda (ram_0010_t02_data),y
    sta ram_0002_t04_data + $01
    ldy ram_0008_t11_object_index
    lda ram_obj_pos_X,y
    sta ram_0011_t02_pos_X_lo
    lda ram_obj_pos_Y,y
    sta ram_0010_t08_spr_Y
    lda #$C3
    sta ram_0018_t16
    lda ram_obj_animation_hi,y
    bpl @front
    and #$03
    ora #$20                    ; behind the background
    bne @attributes             ; always
@front:
    and #$03
@attributes:
    sta ram_0012_t04_spr_A
    and #$03
    beq @mask
    lda #$C0
    sta ram_0018_t16
@mask:
    ; Which of BCC and BCS skips a tile off the screen: its X's high byte
    ; is the object's, plus the carry, less one if the tile's X is
    ; negative, and the tile is shown if that is even.
    lda ram_0013_t04_pos_X_hi
    lsr
    lda #OP_BCS
    ldx #OP_BCC
    bcc @parity
    lda #OP_BCC
    ldx #OP_BCS
@parity:
    sta fast_skip_pos
    stx fast_skip_neg
    lda ram_0008_t11_object_index
    cmp #$02
    bcs @enemy
    ; A player: the tiles from ram_001D_t10 on, below $C0, are moved down
    ; by ram_001E_t13, by the character and the stage.
    lda ram_00C0_combined_players_id
    asl
    clc
    adc ram_0008_t11_object_index
    tay
    lda ram_stage
    and #$01
    bne @odd_stage
    lda tbl_D4C4,y
    sta ram_001E_t13
    lda tbl_D4E2,y
    sta ram_001D_t10
    jmp @player
@odd_stage:
    lda tbl_D500,y
    sta ram_001E_t13
    lda tbl_D51D,y
    sta ram_001D_t10
@player:
    lda #$01
    bne @kind                   ; always
@enemy:
    lda #$00
@kind:
    sta fast_player
    ldy #$00                    ; sub_D4A7: not flipped
    sty ram_001B_t02_hi
    sty ram_001C_t10_spr_A_flip
    sty ram_001F_t14
    jmp fast_group

; Where the next tile goes in the OAM buffer: the game's X, kept here
; between the tile loops.
fast_oam_x:
    .byte $00
fast_player:
    .byte $00
fast_skip_pos:
    .byte $00
fast_skip_neg:
    .byte $00

; A group of tiles: sub_D459's. A first byte of $FF says that this and the
; object's groups after it are flipped, and where they are.
fast_group:
    lda #$FF
    cmp (ram_0002_t04_data),y
    bne @header
    sta ram_001B_t02_hi
    lda #$08
    sta ram_001F_t14
    lda #$40
    sta ram_001C_t10_spr_A_flip
    iny
    lda (ram_0002_t04_data),y
    pha
    iny
    lda (ram_0002_t04_data),y
    sta ram_0002_t04_data + $01
    pla
    sta ram_0002_t04_data
    ldy #$00
@header:
    lda (ram_0002_t04_data),y
    sta ram_001A_t08_lo
    and #$7F
    sta ram_0000_t6F_loop_counter
    iny
    lda (ram_0002_t04_data),y
    and ram_0018_t16
    ora ram_0012_t04_spr_A
    sta ram_0019_t02_spr_A
    iny
    eor ram_001C_t10_spr_A_flip
    ldx ram_001B_t02_hi
    beq @straight
    ldx fast_player
    bne @player_flipped
    jmp fast_tiles_flipped
@player_flipped:
    jmp fast_tiles_player_flipped
@straight:
    ldx fast_player
    bne @player_straight
    jmp fast_tiles
@player_straight:
    jmp fast_tiles_player

; One group's tiles: A the attributes, Y the first tile's first byte, X
; (from fast_oam_x) the place in the OAM buffer. Each tile is its X, its
; tile and its Y.
.macro fast_tile_loop flipped, player
.local tile, neg, xpos, xneg, skip_pos, skip_neg, show, attr, kept, below, ypos
.local next, skip, full, done
    sta attr + 1
    lda ram_0011_t02_pos_X_lo
    sta xpos + 1
    sta xneg + 1
    lda ram_0010_t08_spr_Y
    sta ypos + 1
    lda fast_skip_pos
    sta skip_pos
    lda fast_skip_neg
    sta skip_neg
.if player
    lda ram_001D_t10
    sta below + 1
    lda ram_001E_t13
    sta kept - 1
.endif
    ldx fast_oam_x

tile:
    lda (ram_0002_t04_data),y
.if flipped
    eor #$FF
    sec
    sbc #$08
.endif
    bmi neg
    clc
xpos:
    adc #$00
    sta ram_spr_X,x
    iny
skip_pos:
    bcs skip                    ; BCC or BCS, by the object's high byte
show:
attr:
    lda #$00
    sta ram_spr_A,x
    lda (ram_0002_t04_data),y
.if player
below:
    cmp #$00
    bcc kept
    cmp #$C0
    bcs kept
    sec
    sbc #$00
kept:
.endif
    sta ram_spr_T,x
    iny
    lda (ram_0002_t04_data),y
    clc
ypos:
    adc #$00
    sta ram_spr_Y,x
    txa
    clc
    adc #$C4
    tax
    dec ram_0001_t37_sprites_counter
    beq full

next:
    iny
    dec ram_0000_t6F_loop_counter
    bne tile
    stx fast_oam_x
    dey                         ; the last tile's X, for ram_000E_t05
    dey
    dey
    jsr fast_sign
    iny
    iny
    iny
    lda ram_001A_t08_lo
    bpl done
    jmp fast_group
done:
    rts

neg:
    clc
xneg:
    adc #$00
    sta ram_spr_X,x
    iny
skip_neg:
    bcc skip                    ; BCC or BCS, the other of skip_pos's
    jmp show

skip:
    iny
    jmp next

full:
    stx fast_oam_x
    dey                         ; the tile's X
    dey
    jmp fast_sign
.endmacro

fast_tiles:
    fast_tile_loop 0, 0
fast_tiles_flipped:
    fast_tile_loop 1, 0
fast_tiles_player:
    fast_tile_loop 0, 1
fast_tiles_player_flipped:
    fast_tile_loop 1, 1

; ram_000E_t05 as the game's tile leaves it: $FF if the tile's X, flipped
; as the group is, is negative, else 0. Y is where the tile's X is; A, the
; carry and the others are kept but for the flags.
fast_sign:
    pha
    lda (ram_0002_t04_data),y
    eor ram_001B_t02_hi
    sec
    sbc ram_001F_t14
    asl                         ; the sign into the carry
    lda #$00
    adc #$FF
    eor #$FF
    sta ram_000E_t05
    pla
    rts

; The places no tile took, from fast_oam_x on, ram_0001_t37_sprites_counter
; of them (1 to 64): the game stores $F4 as the Y of each, the next place
; $C4 on, which goes round all 64 in the order fast_hide_order gives, place
; K being the order's (17 * K) mod 64th. Here that is a run of stores,
; entered at the first and ended with an RTS written after the last (as
; nes-contra's net_hide). The counter is left at 0, as the game's loop
; leaves it.
FAST_HIDE_STEP  = $C4 / 4       ; 49, whose inverse mod 64 is 17
.assert (FAST_HIDE_STEP * 17) .mod 64 = 1, error

fast_hide:
    lda fast_oam_x
    lsr
    lsr
    tax
    lda fast_hide_first,x       ; where in the run the place is
    tax
    lda fast_hide_low,x
    sta @enter + 1
    lda fast_hide_high,x
    sta @enter + 2
    txa
    clc
    adc ram_0001_t37_sprites_counter    ; and where the run is to end
    tax
    lda fast_hide_low,x
    sta @end + 1
    sta @back + 1
    lda fast_hide_high,x
    sta @end + 2
    sta @back + 2
    lda #$60                    ; RTS
@end:
    sta $FFFF
    lda #$F4
@enter:
    jsr $FFFF
    lda #$8D                    ; STA, as it was
@back:
    sta $FFFF
    lda #$00
    sta ram_0001_t37_sprites_counter
    rts

; Two rounds of the 64 places, so that any 64 in a row are in it.
fast_hide_run:
.repeat 128, step
    sta ram_spr_Y + 4 * ((FAST_HIDE_STEP * step) .mod 64)
.endrep
    rts

fast_hide_first:
.repeat 64, place
    .byte (17 * place) .mod 64
.endrep

fast_hide_low:
.repeat 129, step
    .byte <(fast_hide_run + 3 * step)
.endrep

fast_hide_high:
.repeat 129, step
    .byte >(fast_hide_run + 3 * step)
.endrep

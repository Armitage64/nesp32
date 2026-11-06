; Netplay: a faster way through the busiest of the game's routines, from
; the PRG RAM (net/net.inc includes it, unless NET_SLOW is defined). The
; game's NMI calls it in place of its own (patches/bank7.patch), and it does
; what the game's does: the same memory written, and the same registers
; and flags when it returns, for the game's work after it takes them as
; they are. tests/test_fast.py holds the two alike.
;
; The sprites (bank 1's subProcessSpriteUpdates, with subDrawObjectSprites
; in line): every object's tiles into the OAM's copy, each at its place
; from the object's, in the order that turns $C4 slots at a time, then the
; score and the lives, and every slot left hidden. The game's own looks at
; the object's flips again for each tile, calls a routine for each object,
; and steps to the next slot with an addition; this one picks one of four
; loops by the flips, has the drawing in line, and steps by a table. A tile
; takes some 96 cycles in place of 113.
;
; bank 1 is in while it runs: the objects' tables of tiles are there.

.segment "NETCODE"

; What the game's drawing leaves in A when the OAM is full: it returns from
; subProcessSpriteUpdates at once, with the address its own call pushed
; taken off the stack, the high byte last (net_sprites_draw_return is past
; that call, patches/bank1.patch).
NET_DRAW_RETURN_HI = >(net_sprites_draw_return - 1)

net_sprites:
    lda #$40
    sta $17                     ; the OAM's slots
    lda #$1F
    sta $05                     ; the objects, from the last
    lda SpriteSlotRotation
    clc
    adc #$44
    sta SpriteSlotRotation
    sta $04

net_sprites_object:
    ldx $05
    lda SpriteTypeIndex,x
    beq net_sprites_drawn
net_sprites_found:
    lda SpriteState,x
    bmi net_sprites_drawn
    lda SpriteAttributes,x
    sta $10
    lda SpriteGraphicsAttributes,x
    sta $00
    lda SpriteVertScreenPosition,x
    sta $01
    lda SpriteHorizScreenPosition,x
    sta $02
    lda SpriteTypeIndex,x
    asl
    tay
    bcc @low
    lda tblSpriteConstructionHeaderAddress2,y
    sta $08
    lda tblSpriteConstructionHeaderAddress2 + 1,y
    jmp @pointer

@low:
    lda tblSpriteConstructionHeaderAddress,y
    sta $08
    lda tblSpriteConstructionHeaderAddress + 1,y

@pointer:
    sta $09
    ; subDrawObjectSprites, in line.
    ldy #$00
    lda ($08),y
    beq net_sprites_drawn       ; no tiles
    iny
    sta $03
    ldx $04
    bit $10                     ; the flips: N up and down, V left and right
    bmi @flipped_v
    bvs @to_h
    jmp net_tiles
@to_h:
    jmp net_tiles_h
@flipped_v:
    bvs @to_vh
    jmp net_tiles_v
@to_vh:
    jmp net_tiles_vh

; The next object, from the loops with this one drawn, or with nothing of
; it to draw. The empty slots are passed over in X alone, and $05 has the
; slot of the next object to draw by the time it is drawn, and $FF at the
; end, as the game's loop leaves it; it is read by nothing between.
net_sprites_drawn:
    ldx $05
@scan:
    dex
    bmi @done
    lda SpriteTypeIndex,x
    beq @scan
    stx $05
    jmp net_sprites_found

@done:
    stx $05
    jmp net_sprites_rest

.macro net_tile_loop name, flip_v, flip_h
; The tiles of one object, flipped as the macro's arguments say. Y is at
; the first, X the OAM's slot, $03 how many.
name:
@tile:
    lda ($08),y                 ; up and down from the object
.if flip_v
    eor #$FF                    ; the game's: (-d) - $10
    clc
    adc #$F1
.endif
    bpl @down
    clc
    adc $01
    bcc @off3
    bcs @on
@down:
    clc
    adc $01
    bcs @off3
@on:
    sta OAMDMA_Y,x
    iny
    lda ($08),y
    sta OAMDMA_PatternTableTileIndex,x
    iny
    lda ($08),y
    eor $10
    ora $00
    sta OAMDMA_Attributes,x
    iny
    lda ($08),y                 ; left and right
.if flip_h
    eor #$FF                    ; the game's: (-d) - 8
    clc
    adc #$F9
.endif
    bpl @right
    clc
    adc $02
    bcc @off
    bcs @shown
@right:
    clc
    adc $02
    bcs @off
@shown:
    sta OAMDMA_X,x
    dec $17
    beq @full
    lda net_oam_next,x
    tax
@off:
    iny
    dec $03
    bne @tile
    stx $04
    jmp net_sprites_drawn

@off3:
    iny
    iny
    iny
    jmp @off

; The OAM is full: the game's drawing returns from subProcessSpriteUpdates
; at once, with the last of the address it took off the stack in A.
@full:
    lda #NET_DRAW_RETURN_HI
    rts
.endmacro

net_tile_loop net_tiles, 0, 0
net_tile_loop net_tiles_v, 1, 0
net_tile_loop net_tiles_h, 0, 1
net_tile_loop net_tiles_vh, 1, 1

; The score and the lives, and the rest of the OAM hidden: the game's own.
net_sprites_rest:
    ldx $04
    lda GameControlState
    cmp #$05
    bne @hide
    lda GamePlayMode
    cmp #$03
    beq @score
@hide:
    jmp net_sprites_hide

@score:
    lda #$01
    ldy Player2Active
    bne @two
    lda #$00
    beq @which
@two:
    lda RNG_INCEveryFrame
    and #$80
    clc
    rol
    rol
@which:
    sta $08
    asl
    tay
    lda tblScoreDisplayCoordinates,y
    sta $09
    lda tblScoreDisplayCoordinates + 1,y
    sta $0C
    lda #$03
    sta $0B
    ldy #$00
    lda $08
    asl
    asl
    tax
@digits:
    lda JeepScore,x
    and #$0F
    asl
    clc
    adc #$02
    sta $D8,y
    iny
    lda Jeep1Score,x
    and #$F0
    lsr
    lsr
    lsr
    clc
    adc #$02
    sta $D8,y
    inx
    iny
    dec $0B
    bne @digits
    lda #$20
    sta $D8,y
    iny
    lda #$04
    sta $D8,y
    lda $08
    beq :+
    lda #$06
    sta $D8,y
:
    lda #$08
    sta $0A
    ldx $04
    ldy #$07
@put:
    lda $0C
    sta OAMDMA_Y,x
    lda $D8,y
    sta OAMDMA_PatternTableTileIndex,x
    dey
    lda #$00
    sta OAMDMA_Attributes,x
    lda $09
    sta OAMDMA_X,x
    clc
    adc #$08
    sta $09
    lda $0A
    cmp #$07
    bne :+
    lda $09
    clc
    adc #$08
    sta $09
:
    txa
    clc
    adc #$C4
    tax
    dec $17
    beq @done
    dec $0A
    bne @put
    ldy $08
    lda JeepLifeCount,y
    beq net_sprites_hide
    lda $09
    sec
    sbc #$2C
    sta $09
    lda $0C
    clc
    adc #$10
    sta $0C
    sta OAMDMA_Y,x
    lda #$20
    sta OAMDMA_PatternTableTileIndex,x
    lda $08
    sta OAMDMA_Attributes,x
    lda $09
    sta OAMDMA_X,x
    txa
    clc
    adc #$C4
    tax
    dec $17
    beq @done
    lda $0C
    sta $0200,x
    ldy $08
    lda JeepLifeCount,y
    sec
    sbc #$01
    and #$0F
    asl
    clc
    adc #$02
    sta OAMDMA_PatternTableTileIndex,x
    lda #$00
    sta OAMDMA_Attributes,x
    lda $09
    clc
    adc #$0A
    sta OAMDMA_X,x
    txa
    clc
    adc #$C4
    tax
    dec $17
    bne net_sprites_hide

@done:
    rts

; Every slot left hidden: the game's own steps from slot to slot, $C4 at a
; time, $17 of them (1 to 64), and puts each below the picture. The slots
; are all different, so the order they are written in does not matter:
; here they are written by a run of stores, one for each place in that
; order, entered at the first slot's place and ended, $17 places on, by an
; RTS put in for the time it runs. What the game's loop leaves after it is
; put as it would be: X the slot after the last, A the same, the carry and
; the overflow of the last step, $17 zero, and Y as it was.
net_sprites_hide:
    sty net_fast_y
    txa
    and #$03                    ; X's place within a slot, which the steps keep
    sta net_fast_r
    txa
    lsr
    lsr
    tay
    lda net_oam_place,y         ; the first slot's place in the order
    sta net_fast_j
    clc
    adc $17
    tay                         ; where the run ends, 64 at the most past it
    lda net_hide_lo,y
    sta @stop + 1
    sta @put_back + 1
    lda net_hide_hi,y
    sta @stop + 2
    sta @put_back + 2
@stop:
    lda $FFFF                   ; the store there, an RTS for the time the run takes
    sta net_fast_op
    lda #$60
    jsr @poke
    ldy net_fast_j
    lda net_hide_lo,y
    sta @run + 1
    lda net_hide_hi,y
    sta @run + 2
    ldy net_fast_r
    lda #$F4
    jsr @run
    lda net_fast_op
    jsr @poke
    ; The slot the game's loop wrote last, and its step past it.
    lda net_fast_j
    clc
    adc $17
    tay
    lda net_oam_order - 1,y
    ora net_fast_r
    ldy net_fast_y
    pha
    lda #$01
    sta $17
    pla
    clc
    adc #$C4
    tax
    dec $17                     ; Z set and N clear, as the loop's end leaves them
    rts

@run:
    jmp $FFFF

@poke:
@put_back:
    sta $FFFF
    rts

; The run: a store for each place in the order of the slots, twice round,
; so that any 64 in a row are in it.
net_hide_run:
.repeat 128, place
    sta OAMDMA_Y + ((place * $C4) & $FF),y
.endrep
    rts

; The background's collisions (fctGetCollisionTypeFromRAM300_4FF, and the
; two ways into its second half): the kind of 8x8 tile under a point, from
; the map of collisions at $0300-$04FF. The game's works out the place of
; the point's 32x32 tile in its row, and the 8x8 tile's in that, by shifts;
; this one looks both up, and is the game's otherwise. A is the point's
; height from the game's way in, $00 its place across.
net_collision_tail:
    sec
    sbc $0A
    clc
    adc $17
    and #$F8
    clc
    adc $4F
    clc
    adc #$08
    sta $01
    ldx $00
    lda net_div32,x             ; the 32x32 tile across: (A & $E0) / 32
    clc
    adc $01
    tay
    lda ($08),y
    sta $02
    ldy net_column,x            ; the 8x8 tile in it: (A & $1F) / 8
    ldx $0F
    lda tblSprite_BG_CollisionMask,y
    and $02
    dey
    bmi @first
    dey
    bmi @second
    dey
    bmi @third
    lsr
    rol
    rts

@first:
    lsr
    lsr
@second:
    lsr
    lsr
@third:
    lsr
    lsr
    rts

; The slot after each, in the order the game fills them: $C4 on.
.pushseg
.segment "RODATA"
net_oam_next:
.repeat 256, slot
    .byte (slot + $C4) & $FF
.endrep
; The slot at each place in that order, from slot 0, twice round; the
; place of each slot (by its number, a fourth of its offset); and where
; each place's store is in net_hide_run.
net_oam_order:
.repeat 128, place
    .byte (place * $C4) & $FF
.endrep
net_oam_place:
.repeat 64, slot
    .byte (slot * 17) & $3F     ; a step is 49 slots, and 49 * 17 is 1 past 64 * 13
.endrep
net_div32:
.repeat 256, value
    .byte (value & $E0) >> 5
.endrep
net_column:
.repeat 256, value
    .byte (value & $1F) >> 3
.endrep
net_hide_lo:
.repeat 128, place
    .byte <(net_hide_run + 3 * place)
.endrep
net_hide_hi:
.repeat 128, place
    .byte >(net_hide_run + 3 * place)
.endrep
.popseg
.assert <net_oam_next = 0, error, "net_oam_next on a page of its own, for no page crossed"

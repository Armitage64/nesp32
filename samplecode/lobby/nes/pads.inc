; The game: both players' controllers, with the buttons that are down lit.
;
; This is where your game goes. It runs once a tick, from the main loop,
; and has two bytes of input, game_buttons: player 1's and player 2's, as
; read on their own consoles, each bit a button (PAD_*). Both consoles run
; it with the same buttons at the same tick, so it must depend on nothing
; else: not on the frame count, not on which console it is on, not on
; memory that the session did not set. What it may not change, the
; session's digest catches (nes/session.inc).
;
; Here a tick only lights sprites. Each controller is in the session's
; screen, its buttons drawn in dark grey; each button has sprites of the
; same tiles over it, in red, at the places tools/gen_chr.py worked out
; (layout.inc). A button that is down has its sprites on the picture.

game_tick:
    inc game_ticks
    bne @draw
    inc game_ticks + 1
@draw:
    lda game_buttons
    ldx #0                      ; player 1's sprites from the first
    ldy #0
    jsr draw_pad
    lda game_buttons + 1
    ldx #4 * PAD_SPRITES        ; player 2's after them
    ldy #PAD2_DY
    ; fall through

; A player's sprites into oam from X: A is the player's buttons, Y how far
; below player 1's their controller is.
draw_pad:
    sta temp
    sty draw_dy
    ldy #0
@sprite:
    lda pad_mask,y
    and temp
    beq @up                     ; not down: off the picture
    lda pad_y,y
    clc
    adc draw_dy
    bne @place
@up:
    lda #SPRITE_HIDDEN
@place:
    sta oam,x
    lda pad_tile,y
    sta oam + 1,x
    lda #0                      ; the first sprite palette, in front
    sta oam + 2,x
    lda pad_x,y
    sta oam + 3,x
    inx
    inx
    inx
    inx
    iny
    cpy #PAD_SPRITES
    bne @sprite
    rts

.assert 8 * PAD_SPRITES <= 256, error, "two players' sprites fit in OAM"

.segment "BSS"
draw_dy:        .res 1
.segment "CODE"

; Netplay: the sprites' flicker, quicker.
;
; Every frame of play the game's flicker task (bank 22) counts the sprites
; in each band of 16 lines of the screen, (Y + sprite_y_offset) / 16, and
; puts the ninth and later of a band off the screen: two runs of the
; sprites' page each frame, in one of four orders by sprite_cycling_index
; (COUNT_SPR_FIRST_SUBSET_FORWARD and the rest). Its loops take some 45
; cycles a sprite, 1,900 a frame in play, much of it the loop's own
; counting and four shifts.
;
; Here each run is written out, a sprite at a time, and the band is looked
; up: 16 tables, one for each offset, of (Y + offset) / 16 as the game's
; ADC and four LSRs make it, wrapped at 256. Some 27 cycles a sprite. The
; tables and the runs are in a bank of their own (FLICKER_BANK), which
; net_flicker, in the 206 bytes bank 22 leaves empty (FREE_22_8F32), puts
; in at $A000 for the length of the count and takes out again. It changes
; nothing the game's own count would not: the counters, the sprites put off
; the screen, and the game's shadows of the banks as they were.
;
; sprite_y_offset is the task's LOCAL_8, which nothing sets before the task
; first adds to it: until the first time round it may be 16 or more, and
; then the game's own loops do the count (they are still there; the
; netplay ROM built with NET_SLOW has only them).

FLICKER_BANK    = 33            ; by its place in the file (net/superbowl_net.cfg)
FLICKER_OFFSETS = 16            ; sprite_y_offset is ANDed with $0F once round
net_band_ptr    = LOCAL_1       ; (and LOCAL_2) the offset's table: kept, and put back

.ifndef NET_SLOW

NET_FLICKER = 1                 ; the game's dispatch goes to net_flicker (patches/tsb.patch)
HAVE_FREE_22_8F32 = 1

.macro FILL_FREE_22_8F32
; In place of the dispatch on sprite_cycling_index, the counter just
; stepped (SET_SPRITES_OFFSCREEN_IF_NEEDED): the count, as the four orders
; make it, then on to CHANGE_SPR_Y_OFFSET in the second and fourth, as
; they go. With an offset the tables do not have, the game's own.
net_flicker:
    lda sprite_y_offset
    cmp #FLICKER_OFFSETS
    bcc @quick
    lda sprite_cycling_index
    and #max_cycle_types_bitmask
    jmp NET_FLICKER_ORDERS
@quick:
    ; The game's shadows first, then the MMC3: an interrupt that puts the
    ; banks back from the shadows on the way puts in the same.
    lda SOFT_BANK_SELECT
    pha
    lda SOFT_A000_BANK
    pha
    lda net_band_ptr
    pha
    lda net_band_ptr+1
    pha
    lda #FLICKER_BANK
    sta SOFT_A000_BANK
    lda SOFT_MODE_8000
    ora #SET_BANK_TO_A000_MMC3
    sta SOFT_BANK_SELECT
    sta BANK_SELECT_MMC3
    lda #FLICKER_BANK
    sta BANK_DATA_MMC3
    jsr flicker_count
    pla
    sta net_band_ptr+1
    pla
    sta net_band_ptr
    pla
    sta SOFT_A000_BANK
    lda SOFT_MODE_8000
    ora #SET_BANK_TO_A000_MMC3
    sta SOFT_BANK_SELECT
    sta BANK_SELECT_MMC3
    lda SOFT_A000_BANK
    sta BANK_DATA_MMC3
    pla
    sta SOFT_BANK_SELECT
    sta BANK_SELECT_MMC3
    ; And the registers and flags as the game's last loop leaves them (X,
    ; the last sprite's band, is flicker_count's): the task's next sleep
    ; keeps them on its stack. Y and A where the loop stopped, C and Z set
    ; by its last CPY, N and V clear.
    lda sprite_cycling_index
    and #max_cycle_types_bitmask
    beq @order_1
    cmp #$02
    beq @order_3
    cmp #$01
    beq @order_2
    ldy #<(SPRITE_SUBSET_START_2 - OFFSET_TO_NEXT_SPRITE)   ; the fourth: the second subset backward
    jmp CHANGE_SPR_Y_OFFSET
@order_2:
    ldy #<(SPRITE_SUBSET_START_3 - OFFSET_TO_NEXT_SPRITE)   ; the third subset backward
    jmp CHANGE_SPR_Y_OFFSET
@order_1:
    ldy #<(SPRITE_SUBSET_END_2 + OFFSET_TO_NEXT_SPRITE)     ; the second subset forward
    bne @stopped
@order_3:
    ldy #<(SPRITE_SUBSET_END_1 + OFFSET_TO_NEXT_SPRITE)     ; the first subset forward
@stopped:
    tya
    clv
    cpy #<(SPRITE_SUBSET_END_1 + OFFSET_TO_NEXT_SPRITE)     ; C and Z set: equal, as the loop's
    beq :+
    cpy #<(SPRITE_SUBSET_END_2 + OFFSET_TO_NEXT_SPRITE)
:
    rts
.endmacro

.pushseg
.segment "FLICKER"

; (Y + offset) / 16, wrapped, for each offset: the offset's table is
; the page FLICKER_BANDS + offset.
FLICKER_BANDS:
.repeat FLICKER_OFFSETS, offset
    .repeat 256, n
    .byte ((n + offset) & $FF) >> 4
    .endrepeat
.endrepeat

; A sprite counted in its band, and off the screen if it is the band's
; ninth or later: COUNT_SPR_*'s loop, once.
.macro FLICKER_SPRITE sprite_y
    .local counted
    ldy sprite_y
    lda (net_band_ptr),y
    tax
    inc SPRITE_PER_AREA_COUNTER_START,x
    lda SPRITE_PER_AREA_COUNTER_START,x
    cmp #MAX_SPRITES_PER_SCANLINE + 1
    bcc counted
    lda #SPRITE_OFFSCREEN
    sta sprite_y
counted:
.endmacro

; The count in the order sprite_cycling_index picks, as the game's
; CHECK_SPRITES_ORDER_1 to _4.
flicker_count:
    lda #$00
    sta net_band_ptr
    lda sprite_y_offset
    clc
    adc #>FLICKER_BANDS
    sta net_band_ptr+1
    lda sprite_cycling_index
    and #max_cycle_types_bitmask
    beq @order_1
    cmp #$01
    beq @order_2
    cmp #$02
    beq @order_3
    jsr flicker_third_backward
    jmp flicker_second_backward
@order_1:
    jsr flicker_first_forward
    jmp flicker_second_forward
@order_2:
    jsr flicker_second_backward
    jmp flicker_third_backward
@order_3:
    jsr flicker_second_forward
    jmp flicker_first_forward

; COUNT_SPR_FIRST_SUBSET_FORWARD: $0210 to $0274.
flicker_first_forward:
.repeat (SPRITE_SUBSET_END_1 - SPRITE_SUBSET_START_1) / OFFSET_TO_NEXT_SPRITE + 1, i
    FLICKER_SPRITE CUR_SPRITE_Y + <SPRITE_SUBSET_START_1 + i * OFFSET_TO_NEXT_SPRITE
.endrepeat
    rts

; COUNT_SPR_SECOND_SUBSET_FORWARD: $0278 to $02DC.
flicker_second_forward:
.repeat (SPRITE_SUBSET_END_2 - SPRITE_SUBSET_START_2) / OFFSET_TO_NEXT_SPRITE + 1, i
    FLICKER_SPRITE CUR_SPRITE_Y + <SPRITE_SUBSET_START_2 + i * OFFSET_TO_NEXT_SPRITE
.endrepeat
    rts

; COUNT_SPR_SECOND_SUBSET_BACKWARD: $02DC down to $0278.
flicker_second_backward:
.repeat (SPRITE_SUBSET_END_2 - SPRITE_SUBSET_START_2) / OFFSET_TO_NEXT_SPRITE + 1, i
    FLICKER_SPRITE CUR_SPRITE_Y + <SPRITE_SUBSET_END_2 - i * OFFSET_TO_NEXT_SPRITE
.endrepeat
    rts

; COUNT_SPR_THIRD_SUBSET_BACKWARD: $0274 down to $0230.
flicker_third_backward:
.repeat (SPRITE_SUBSET_END_1 - SPRITE_SUBSET_START_3) / OFFSET_TO_NEXT_SPRITE + 1, i
    FLICKER_SPRITE CUR_SPRITE_Y + <SPRITE_SUBSET_END_1 - i * OFFSET_TO_NEXT_SPRITE
.endrepeat
    rts

.popseg

.endif

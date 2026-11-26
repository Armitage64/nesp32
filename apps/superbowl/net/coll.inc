; Netplay: the collision checks, quicker.
;
; Every frame of play the game's collision task (bank 22) checks two of
; the offense's 11 players against each of the defense's 11
; (CHECK_OFF_PLAYER_VS_ALL_DEF_LOOP): may the two collide, are they within
; 6 pixels up or down and 8 across, and the bit for the pair in
; COLLIDED_STATUS_OFFENSE set or cleared, and both players' COLLIDING flag
; set when they first meet. Each pair takes some 70 to 90 cycles, most of
; it the loop's tables, pointer and counting: some 1,600 a frame.
;
; Here the 11 defenders are written out, each with its byte and bit of the
; pair's status as constants (DEFENDER_BYTE_TABLE and PLAYER_BITMASK_TABLE,
; by the defender's place) and its RAM at a fixed address, in two copies:
; player 1's team on defense, and player 2's. Some 20 cycles for a pair
; that may not collide, 34 for one too far up or down. In a bank of its
; own (COLL_BANK), which net_coll, in bank 22's empty bytes, puts in at
; $A000 for the 11 and takes out again, as net_flicker does.
;
; It leaves what the game's loop leaves: the defenders' pointer past the
; 11th, current_defender 0, offset_to_player_collision_byte and
; collision_bitmask the 11th's, and A, X, Y and the flags as the loop's
; last pass does (the task's next sleep keeps them on its stack). Until
; the end those two bytes, the task's own, hold the offense player's Y and
; X: an NMI that switches tasks in a game with no session keeps them.

COLL_BANK       = 34            ; by its place in the file (net/superbowl_net.cfg)
COLL_DEFENDERS  = INITIAL_DEF_POS_TO_CHECK
NET_COLL_DONE   = $9679         ; the loop's @check_if_done_coll_check (asserted there)
coll_off_y      = collision_bitmask             ; the offense player's Y, until the end
coll_off_x      = offset_to_player_collision_byte ; and X's low byte

.ifndef NET_SLOW

NET_COLL = 1                    ; the game's loop goes to net_coll (patches/tsb.patch)

; In bank 22's empty bytes (FILL_FREE_22_8F32, net/flicker.inc): in place
; of the loop over the defenders, with the offense player's pointer and the
; defenders' first set (SET_CUR_DEFENDER_RAM_ADDR). On to the loop's end.
.macro NET_COLL_HOOK
net_coll:
    lda SOFT_BANK_SELECT
    pha
    lda SOFT_A000_BANK
    pha
    lda #COLL_BANK
    sta SOFT_A000_BANK
    lda SOFT_MODE_8000
    ora #SET_BANK_TO_A000_MMC3
    sta SOFT_BANK_SELECT
    sta BANK_SELECT_MMC3
    lda #COLL_BANK
    sta BANK_DATA_MMC3
    jsr coll_defenders
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
    ; current_defender counted down to 0 by its DEC, A the pointer's high
    ; byte, and C and V as its ADC left them.
    clc
    clv
    lda #$01
    sta current_defender
    lda CURR_DEF_COLL_ADDR+1
    dec current_defender
    jmp NET_COLL_DONE
.endmacro

.pushseg
.segment "COLL"

; One defender, the k-th from the team's first, against the offense
; player: the loop's pass with current_defender 11 - k. X is the offense
; player's byte of the status (OFFSET_TO_COLL_BYTE_TABLE). In the last pass
; Y is left as the game's leaves it.
.macro COLL_DEFENDER base, k, last
    .local not_can, not_y, not_x, not_pair, far, left, collide, next
    .local def, byte, mask
    def = base + k * SIZE_OF_EACH_PLAYER_RAM
    byte = k >= 8                           ; DEFENDER_BYTE_TABLE[10 - k]
    mask = $80 >> (k - 8 * byte)            ; PLAYER_BITMASK_TABLE[10 - k]
    lda CAN_COLLIDE_STATUS_OFFENSE + byte,x
    and #mask
    beq not_can
    lda def + Y_POS + 1                     ; within 6 below?
    sec
    sbc #COLL_LIMIT_Y
    cmp coll_off_y
    bcs not_y
    adc #COLL_LIMIT_Y * 2                   ; and 6 above?
    cmp coll_off_y
    bcc not_y
    lda def + X_POS + 1                     ; the defender's X less the offense player's
    sbc coll_off_x
    pha
    ldy #X_POS + 2
    lda def + X_POS + 2
    sbc (CURR_OFF_COLL_ADDR),y
    bmi left
    bne far
    pla                                     ; to the right: within 8?
    cmp #COLL_LIMIT_X
    bcs not_x
    bcc collide
left:
    cmp #$FF
    bne far
    pla                                     ; to the left: within 8?
    clc
    adc #COLL_LIMIT_X
    bcc not_x
    bcs collide
far:
    pla
    jmp not_x
collide:
    lda COLLIDED_STATUS_OFFENSE + byte,x
    and #mask
    bne next                                ; met already
    lda COLLIDED_STATUS_OFFENSE + byte,x
    ora #mask
    sta COLLIDED_STATUS_OFFENSE + byte,x
    ldy #COLLISION_STATUS
    lda (CURR_OFF_COLL_ADDR),y
    ora #PLAYER_COLLIDING_BITFLAG
    sta (CURR_OFF_COLL_ADDR),y
    lda def + COLLISION_STATUS
    ora #PLAYER_COLLIDING_BITFLAG
    sta def + COLLISION_STATUS
    jmp next
not_can:
.if last
    ldy #COLL_DEFENDERS - k                 ; the game's: current_defender
    jmp not_pair
.endif
not_y:
.if last
    ldy #Y_POS + 1
.endif
not_x:
not_pair:
    lda COLLIDED_STATUS_OFFENSE + byte,x
    and #<~mask
    sta COLLIDED_STATUS_OFFENSE + byte,x
next:
.endmacro

; All 11 of a team, and the defenders' pointer past them, as the loop
; leaves it.
.macro COLL_TEAM base
.repeat COLL_DEFENDERS, k
    COLL_DEFENDER base, k, k = COLL_DEFENDERS - 1
.endrepeat
    lda #<(base + COLL_DEFENDERS * SIZE_OF_EACH_PLAYER_RAM)
    sta CURR_DEF_COLL_ADDR
    lda #>(base + COLL_DEFENDERS * SIZE_OF_EACH_PLAYER_RAM)
    sta CURR_DEF_COLL_ADDR+1
.endmacro

.assert >PLAYER_1_RAM_START <> >PLAYER_2_RAM_START, error

coll_defenders:
    ldy current_off_player
    ldx OFFSET_TO_COLL_BYTE_TABLE - 1,y     ; (bank 22, at $8000)
    ldy #Y_POS + 1
    lda (CURR_OFF_COLL_ADDR),y
    sta coll_off_y
    ldy #X_POS + 1
    lda (CURR_OFF_COLL_ADDR),y
    sta coll_off_x
    lda CURR_DEF_COLL_ADDR+1
    cmp #>PLAYER_1_RAM_START
    bne :+
    jmp coll_player_1
:
    COLL_TEAM PLAYER_2_RAM_START
    jmp coll_last
coll_player_1:
    COLL_TEAM PLAYER_1_RAM_START
coll_last:
    ; The 11th's byte and bit, as the loop leaves them.
    inx                                     ; DEFENDER_BYTE_TABLE[0] = 1
    stx offset_to_player_collision_byte
    lda #$20                                ; PLAYER_BITMASK_TABLE[0]
    sta collision_bitmask
    rts

.popseg

.endif

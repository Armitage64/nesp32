; Netplay: the test of the players' bullets against an enemy, faster.
; net/net.inc includes it, unless NET_SLOW is defined; it runs from the
; PRG RAM with the rest of netplay's code, and bullet_enemy_collision_test
; (bank 7) jumps here.
;
; The game tests each enemy against all 16 places for a bullet, from the
; last to the first, at 12 cycles for each empty one, and for each bullet
; it looks again at whether the level is outdoors. Here the 16 are in line,
; one copy of the test for each place, so that an empty one is a load and
; a branch, and there is a run of them for each way the level and the
; enemy decide it: outdoors, indoors and the bullet's age, indoors and its
; kind. The places are tested in the game's order, by the game's tests,
; and leave the registers, the flags and $08-$11 as its loop does.

; In place of bullet_enemy_collision_test: X is the enemy.
net_bullets:
    lda ENEMY_STATE_WIDTH,x
    and #$30                    ; the enemy's collision box code
    asl
    asl
    sta $10
    ldy #$04
    jsr set_enemy_collision_box ; for a bullet: $08 to $0B
    lda LEVEL_LOCATION_TYPE     ; the carry kept, as the game's loop finds it
    and #$01
    bne @indoor
    jmp net_bullets_outdoor

@indoor:
    lda $10
    bmi @kind
    jmp net_bullets_age

@kind:
    jmp net_bullets_kind

; One place K of the run of KIND, 0 outdoors, 1 indoors by the bullet's
; age, 2 indoors by its kind: what the game's loop does for it, with K for
; its X.
.macro net_bullet kind, k
.local next
    lda PLAYER_BULLET_SPRITE_CODE+k
    beq next                    ; no bullet
    lda PLAYER_BULLET_ROUTINE+k
    cmp #$01
    bne next                    ; not flying
.if kind = 0
    clc                         ; as the game's LSR of LEVEL_LOCATION_TYPE leaves it
.elseif kind = 1
    ldy $10
    lda PLAYER_BULLET_TIMER+k
    cmp #$02
    bcs next
.else
    ldy $10
    lda PLAYER_BULLET_SLOT+k
    bpl next
.endif
    lda PLAYER_BULLET_Y_POS+k   ; the carry as the game's test has it here
    sbc $08
    cmp $0a
    bcs next
    lda PLAYER_BULLET_X_POS+k
    sbc $09
    cmp $0b
    bcs next
    ldx #k
    jmp net_bullet_hit

next:
.endmacro

.macro net_bullet_run kind
.repeat 16, place
    net_bullet kind, 15 - place
.endrep
    ldx ENEMY_CURRENT_SLOT
    rts
.endmacro

net_bullets_outdoor:
    net_bullet_run 0
net_bullets_age:
    net_bullet_run 1
net_bullets_kind:
    net_bullet_run 2

; Bullet X is in the enemy's box: the game's @bullet_enemy_collision. If
; it is not near enough the enemy after all, the rest of the bullets are
; tested by the game's own loop, from the next one on.
net_bullet_hit:
    ldy ENEMY_CURRENT_SLOT
    lda ENEMY_X_POS,y
    sec
    sbc PLAYER_BULLET_X_POS,x
    bcs @apart
    eor #$ff
    adc #$01

@apart:
    cmp #$80
    bcs net_bullet_next
    lda PLAYER_BULLET_OWNER,x
    jsr bullet_collision_logic
    lda PLAYER_BULLET_SLOT,x
    cmp #$05
    bne @spent                  ; not a laser
    stx $08
    txa
    ldx #$00
    cmp #$0a
    bcc @laser
    ldx #$0a

@laser:
    lda PLAYER_BULLET_ROUTINE,x
    cmp #$01
    beq @spent
    inx
    cpx $08
    bne @laser

@spent:
    jsr set_bullet_routine_to_2
    ldx ENEMY_CURRENT_SLOT
    rts

; The game's loop, from its @next_bullet.
net_bullet_next:
    dex
    bpl @bullet
    ldx ENEMY_CURRENT_SLOT
    rts

@bullet:
    lda PLAYER_BULLET_SPRITE_CODE,x
    beq net_bullet_next
    lda PLAYER_BULLET_ROUTINE,x
    cmp #$01
    bne net_bullet_next
    lda LEVEL_LOCATION_TYPE
    lsr
    bcc @test
    ldy $10
    bpl @age
    lda PLAYER_BULLET_SLOT,x
    bmi @test
    bpl net_bullet_next

@age:
    lda PLAYER_BULLET_TIMER,x
    cmp #$02
    bcs net_bullet_next

@test:
    lda PLAYER_BULLET_Y_POS,x
    sbc $08
    cmp $0a
    bcs net_bullet_next
    lda PLAYER_BULLET_X_POS,x
    sbc $09
    cmp $0b
    bcs net_bullet_next
    jmp net_bullet_hit

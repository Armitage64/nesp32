; Netplay: faster ways through the game's busiest routines, so that the
; exchange costs a session no frames (README.md, "The frame rate"). In
; bank 6 with the rest; net/net.asm includes it. Each runs from the PRG
; RAM, where the reset copies it (net_fast_copy): the game calls them from
; the fixed bank with any bank in at $8000, and the PRG RAM is always
; there. The game's routine begins with a JMP to its faster way
; (patches/), and the rest of it is left as it was for whatever else jumps
; into it.
;
; Each does what the game's does: the same memory written, the same
; registers and flags left (tests/test_fast.py holds the two alike, from
; memory at random and through the game). With NET_SLOW defined the game
; keeps its own, for the tests.

.segment "FAST"

; --- the tile under a point -------------------------------------------------------
;
; TILE_AT ($D0BE): the tile of the playfield at Y = $21 and X = $22, in
; pixels, into A, with N and Z as its load leaves them. The game works
; out the playfield's address from the point with shifts and branches:
; $0500 + 32 * (Y / 8 - 4) + X / 8, the low byte's addition carrying
; nowhere, and $23 and $24 kept. A row above the playfield's or below it
; reads the bottom row's ($07E0 + X / 8, through $84 and $85, with carry
; set); one on it the playfield (carry clear). V is the last addition's,
; the column's to the row's low byte, as here. X is kept, in $25 as well.
net_tile:
    stx $25
    lda $21
    lsr a
    lsr a
    lsr a
    tax                         ; the row
    lda $22
    lsr a
    lsr a
    lsr a
    clc
    adc net_tile_lo,x           ; the game's last addition: the same carry and V
    sta $23
    lda net_tile_hi,x
    sta $24
    cmp #>$0800
    bcs @outside
    ldx #$00
    lda ($23,x)
    ldx $25
    ora #$00                    ; N and Z as the load left them
    rts

@outside:
    lda #>$0700
    sta $85
    lda $23
    and #$1F
    ora #<$07E0
    sta $84
    ldx #$00
    lda ($84,x)
    ldx $25
    ora #$00
    rts

; By the row, Y / 8: where the game's arithmetic puts it.
net_tile_lo:
.repeat 32, row
    .byte <(((row * 8 - $20) & $FF) << 2)
.endrep
net_tile_hi:
.repeat 32, row
    .byte >TILE_BASE + (((row * 8 - $20) & $FF) >> 6)
.endrep

TILE_BASE       = $0500         ; the playfield, at the game's L7_CFB5
.assert <TILE_BASE = 0, error, "net_tile_lo has no base's low byte"

; --- a bubble's or a monster's push away from the bubbles ------------------------
;
; The game's objects are 4 bytes each of the zero page, the players and the
; monsters at $68-$83 and the bubbles at $88-$C3, with two sprites each at
; $0200, 8 bytes, from $0210 and $0288. Its loops over them step with a call
; (STEP, $C39E: four INX, and 8 added to Y), and test a pair with another
; (NEAR, $C43E: A = how near, the point at $21 and $22 against the sprite at
; Y, with |dx| into $23 and A into $0467; carry clear if near in both).
; Here both are in line, each its own instructions as the game's are, so
; the flags each leaves are the same; only the calls are gone.

; The step to the next object, in line.
.macro STEP
    inx
    inx
    inx
    inx
    tya
    clc
    adc #$08
    tay
.endmacro

; NEAR in line, with how near as an immediate: to `far` if not near, on
; past if near. The same instructions as the game's, but for its JMP over
; the other way's subtraction, which is a BCS here that is always taken
; (the subtraction before it borrows nothing), and its compare with $0467,
; which is a compare with the same number.
.macro NEAR how, far
    lda #how
    sta $0467
    lda SPRITES+3,y
    cmp $22
    bcc :+
    sbc $22
    bcs :++
:
    sec
    lda $22
    sbc SPRITES+3,y
:
    sta $23
    cmp #how
    bcs far
    lda SPRITES,y
    cmp $21
    bcc :+
    sbc $21
    bcs :++
:
    sec
    lda $21
    sbc SPRITES,y
:
    cmp #how
    bcs far
.endmacro

; PUSH ($DAE4): now and then (a countdown at $0463, of 5 to 7 calls by
; IDLE_COUNT and the random number), whether the object X, its sprites at
; Y, is near any other bubble that is not one being blown (state 2 or 3, or
; bit 7), or any monster or player with bit 4 of its third byte; the first
; it is near, it is pushed away from (the game's own code, from $DB55).
net_push:
    dec $0463
    bne @exit
    lda #$05
    sta $0463
    lda IDLE_COUNT
    bmi :+
    inc $0463
:
    lda RNG
    bmi :+
    inc $0463
:
    stx $25
    sty $26
    lda SPRITES,y
    sta $21
    lda SPRITES+3,y
    sta $22
    ldx #$88
    ldy #$88
@bubbles:
    cpx $25
    beq @next_bubble
    lda $00,x
    bmi @bubble
    cmp #$02
    beq @bubble
    cmp #$03
    beq @bubble
@next_bubble:
    STEP
    cpx #$C4
    bne @bubbles
    ldx #$68
    ldy #$10
@others:
    cpx $25
    beq @next_other
    lda $00,x
    beq @next_other
    lda $02,x
    and #$10
    bne @other
@next_other:
    STEP
    cpx #$84
    bne @others
    ldx $25
    ldy $26
@exit:
    rts

@bubble:
    NEAR $0B, @next_bubble
    jmp L7_DB55

@other:
    NEAR $0B, @next_other
    jmp L7_DB55

.segment "CODE"

FAST_PAGES      = 2

; From the reset: the faster ways into the PRG RAM.
net_fast_copy:
    ldx #$00
@page:
    .repeat FAST_PAGES, page
    lda __FAST_LOAD__ + page * $100,x
    sta __FAST_RUN__ + page * $100,x
    .endrep
    inx
    bne @page
    rts

.import __FAST_LOAD__, __FAST_RUN__, __FAST_SIZE__
.assert __FAST_SIZE__ <= FAST_PAGES * $100, error, "net_fast_copy copies too little"
.assert __FAST_LOAD__ + FAST_PAGES * $100 <= $C000, error, "net_fast_copy reads past bank 6"

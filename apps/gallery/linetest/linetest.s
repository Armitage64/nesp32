; Line palettes: a test of changing a palette colour in the horizontal
; blank of a line, for the Gallery (README.md here).
;
; Bank 0 is a test pattern; the others pictures, each made two ways: with
; palettes changed line by line, and as the Gallery makes them today. The
; code that is timed to the cycle (the sync to the PPU, the frame loop and
; the line kernel) is made by gen_linetest.py, in timed.s; this is the rest:
; starting, loading a picture, and the buttons.
;
;   Left, Right   the picture before or after (a beep, higher further on)
;   A             what the lines do: their changes; none (the first line's
;                 palettes throughout, rendering never off); or rendering
;                 off and on in each line that could have a change, with
;                 nothing changed (the edges alone)
;   Up, Down      the timing one CPU cycle (three dots) later or earlier;
;                 the beep is higher the later it is
;   Start         the timing back to where it was made for
;
; Every button leaves the timed loop, so the picture goes dark for about
; half a second while the ROM finds the PPU's timing again.

.include "timed.s"
.include "banks.inc"

PAD_A     = $80
PAD_START = $10
PAD_UP    = $08
PAD_DOWN  = $04
PAD_LEFT  = $02
PAD_RIGHT = $01
MODES     = 3

.segment "HEADER"
    .byte "NES", $1A
    .byte 8                     ; 8 x 16 KB PRG
    .byte 0                     ; CHR RAM
    .byte $21                   ; mapper 2, vertical mirroring
    .byte $00
    .res 8, 0

.segment "ZEROPAGE"
    .res $18                    ; timed.s's, from $10
image:  .res 1
mode:   .res 1
offset: .res 1
src:    .res 2

.segment "BANK0"
    .incbin "bank0.bin"
.segment "BANK1"
    .incbin "bank1.bin"
.segment "BANK2"
    .incbin "bank2.bin"
.segment "BANK3"
    .incbin "bank3.bin"
.segment "BANK4"
    .incbin "bank4.bin"
.segment "BANK5"
    .incbin "bank5.bin"
.segment "BANK6"
    .incbin "bank6.bin"

.segment "CODE"

reset:
    sei
    cld
    ldx #$40
    stx $4017                   ; no frame IRQ
    ldx #$FF
    txs
    inx
    stx $2000                   ; no NMI
    stx $2001
    stx $4010
    bit $2002
:   bit $2002
    bpl :-
    txa
:   sta $00,x
    sta $0100,x
    sta $0200,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne :-
:   bit $2002
    bpl :-
    lda #$3F
    sta ZP_3F
    lda #$FF
    sta ZP_PREV                 ; a button held at power-on does nothing
    lda #LT_CENTRE
    sta offset
    lda #1
    cmp #BANKS
    bcc :+
    lda #0
:   sta image
    ; fall into load

; The picture `image` into the PPU, its lines' changes as `mode` has them,
; and back into the timed loop.
load:
    lda #0
    sta $2001
    ldx image
    lda bank_numbers,x
    sta bank_numbers,x          ; UNROM: the value written is the byte there
    bit $2002
    lda #$00
    sta $2006
    sta $2006
    sta src
    lda #$80
    sta src+1
    ldx #$20                    ; 8 KB of tiles
    jsr copy
    lda #$20
    sta $2006
    lda #$00
    sta $2006
    lda #$A0
    sta src+1
    ldx #$04                    ; the nametable and its attributes
    jsr copy
    ldx #0
@lines:
    lda mode
    beq @changes
    cmp #1
    beq @none
    lda #$00                    ; the backdrop, rewritten black
    sta RAM_LO,x
    lda #$0F
    sta RAM_COL,x
    jmp @next
@changes:
    lda BANK_LO,x
    sta RAM_LO,x
    lda BANK_COL,x
    sta RAM_COL,x
    jmp @next
@none:
    lda #$FF
    sta RAM_LO,x
@next:
    inx
    bne @lines
    ldx offset
    lda off_lo,x
    sta ZP_OFF_PTR
    lda off_hi,x
    sta ZP_OFF_PTR+1
    lda end_lo,x
    sta ZP_END_PTR
    lda end_hi,x
    sta ZP_END_PTR+1
    jmp sync

; X pages from (src) to PPUDATA.
copy:
    ldy #0
:   lda (src),y
    sta $2007
    iny
    bne :-
    inc src+1
    dex
    bne :-
    rts

; The timed loop comes here with A the buttons newly down.
action:
    ldx #0
    stx $2001
    tay
    and #PAD_RIGHT
    beq :+
    ldx image
    inx
    cpx #BANKS
    bcc @image
    ldx #0
@image:
    stx image
    txa
    asl a
    asl a
    asl a
    eor #$FF
    jsr beep
    jmp load
:   tya
    and #PAD_LEFT
    beq :+
    ldx image
    bne @down
    ldx #BANKS
@down:
    dex
    jmp @image
:   tya
    and #PAD_UP
    beq :+
    ldx offset
    cpx #LT_OFFSETS - 1
    bcs @beep_offset
    inc offset
    bne @beep_offset
:   tya
    and #PAD_DOWN
    beq :+
    lda offset
    beq @beep_offset
    dec offset
    jmp @beep_offset
:   tya
    and #PAD_START
    beq :+
    lda #LT_CENTRE
    sta offset
    jmp @beep_offset
:   tya
    and #PAD_A
    beq @load
    ldx mode
    inx
    cpx #MODES
    bcc :+
    ldx #0
:   stx mode
    lda mode_tones,x
    jsr beep
@load:
    jmp load
@beep_offset:
    lda offset
    asl a
    asl a
    asl a
    eor #$FF                    ; later: higher
    jsr beep
    jmp load

; A short beep of period A on the first pulse channel.
beep:
    ldx #$01
    stx $4015
    ldx #$9F                    ; half duty, the length counted, loudest
    stx $4000
    ldx #$00
    stx $4001
    sta $4002
    stx $4003                   ; ten frames
    rts

mode_tones:
    .byte $60, $C0, $F0

bank_numbers:
    .byte 0, 1, 2, 3, 4, 5, 6, 7

nothing:
    rti

.segment "VECTORS"
    .addr nothing, reset, nothing

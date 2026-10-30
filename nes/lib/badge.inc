; The Bluetooth keyboard's badge, at the top right of the screen: how the
; keyboard stands, by its colour (nes/lib/badge.py has its picture, tiles
; and colours). The cartridge's menu and the setup ROM both include this.
;
; None with no keyboard paired, or no nesp32 that has KBD; grey for one
; paired and not connected; flashing blue while it is connecting, Bluetooth
; starting or a pairing going on, and for BADGE_WAIT after that while the
; nesp32 waits for it, which is then grey (a key wakes it); blue while it
; is connected; yellow when the last pairing failed, or the nesp32 has
; stopped answering with a keyboard paired.
;
; Before including it, a ROM defines frame_count, BADGE_OAM (the first of
; four sprites of its OAM page, which the badge has to itself), and
; badge.py's constants (BADGE_X and so on), and includes nesp.inc. It sets
; badge_ok when a hello with KBD is answered, and badge_state and
; badge_paired from each KBD STATE (its KEYBOARD, and its NAME_LEN). It
; calls badge_init once, badge_show every frame, and puts badge_nmi in its
; NMI, after the OAM's DMA and before the scroll.

BADGE_ATTR = $01                ; sprite palette 1
BADGE_FLIP = $80                ; the bottom row is the top row upside down
BADGE_COLOR_ADDR = $3F15        ; sprite palette 1's colour 1
BADGE_WAIT = 150                ; 4-frame ticks of waiting that are connecting: 10 s
BADGE_FLASH = $10               ; frame_count's bit that flashes it
BADGE_HIDDEN_Y = $F0

; What it shows (badge_kind).
BADGE_SHOW_NONE   = 0
BADGE_SHOW_GREY   = 1
BADGE_SHOW_YELLOW = 2
BADGE_SHOW_FLASH  = 3
BADGE_SHOW_BLUE   = 4

.segment "BSS"
badge_ok:     .res 1            ; the nesp32's hello had KBD
badge_state:  .res 1            ; KBD STATE's KEYBOARD
badge_paired: .res 1            ; and its NAME_LEN: a keyboard is paired
badge_waited: .res 1            ; 4-frame ticks of NESP_KEYBOARD_WAITING
badge_color:  .res 1            ; its colour 1, which badge_nmi writes
.segment "CODE"

; Last in the NMI's writes to the PPU, before the scroll: the badge's
; colour. A is lost.
.macro badge_nmi
    bit $2002
    lda #>BADGE_COLOR_ADDR
    sta $2006
    lda #<BADGE_COLOR_ADDR
    sta $2006
    lda badge_color
    sta $2007
    lda #$3F                    ; off the palette, before the picture
    sta $2006
    lda #0
    sta $2006
    sta $2006
    sta $2006
.endmacro

; Its sprites' tiles, palette and places across, which do not change, and
; hidden until badge_show says otherwise.
.proc badge_init
    ldx #0
@sprite:
    lda badge_sprites + 1,x
    sta BADGE_OAM + 1,x
    lda badge_sprites + 2,x
    sta BADGE_OAM + 2,x
    lda badge_sprites + 3,x
    sta BADGE_OAM + 3,x
    lda #BADGE_HIDDEN_Y
    sta BADGE_OAM,x
    inx
    inx
    inx
    inx
    cpx #16
    bcc @sprite
    rts
.endproc

; Show it as the keyboard stands: its colour for the NMI, and its sprites
; shown or hidden. A not 0: the nesp32 has stopped answering.
.proc badge_show
    jsr badge_kind
    tax
    lda badge_colors,x
    cpx #BADGE_SHOW_FLASH       ; the dim blue every other stretch
    bne @color
    lda frame_count
    and #BADGE_FLASH
    beq @blue
    lda #BADGE_BLUE_DIM
    bne @color
@blue:
    lda #BADGE_BLUE
@color:
    sta badge_color
    lda #BADGE_HIDDEN_Y
    cpx #BADGE_SHOW_NONE
    beq @top
    lda #BADGE_Y - 1            ; a sprite shows a line below its Y
@top:
    sta BADGE_OAM
    sta BADGE_OAM + 4
    cmp #BADGE_HIDDEN_Y
    beq @bottom
    clc
    adc #8
@bottom:
    sta BADGE_OAM + 8
    sta BADGE_OAM + 12
    rts
.endproc

; BADGE_SHOW_* in A, A not 0 if the nesp32 has stopped answering; and the
; wait counted.
.proc badge_kind
    tay
    lda badge_state
    cmp #NESP_KEYBOARD_WAITING
    beq @waiting
    lda #0
    sta badge_waited
@counted:
    tya                         ; the nesp32 has stopped answering
    beq @answering
    lda badge_paired
    beq @none
    lda #BADGE_SHOW_YELLOW
    rts
@answering:
    lda badge_ok
    beq @none
    ldx badge_state
    cpx #NESP_KEYBOARD_FAILED + 1
    bcs @none
    cpx #NESP_KEYBOARD_WAITING
    beq @wait
    lda badge_kinds,x
    cpx #NESP_KEYBOARD_OFF      ; Bluetooth starting: only with one paired
    bne @done
    ldx badge_paired
    bne @done
@none:
    lda #BADGE_SHOW_NONE
@done:
    rts
@waiting:
    lda frame_count
    and #$03
    bne @counted
    lda badge_waited
    cmp #$FF
    beq @counted
    inc badge_waited
    bne @counted
@wait:
    lda badge_waited
    cmp #BADGE_WAIT
    lda #BADGE_SHOW_FLASH
    bcc @done
    lda #BADGE_SHOW_GREY
    rts
.endproc

.segment "RODATA"
; By KEYBOARD: none, off, unpaired, waiting (badge_kind's own), connected,
; scanning, scanned, pairing, failed.
badge_kinds:
    .byte BADGE_SHOW_NONE, BADGE_SHOW_FLASH, BADGE_SHOW_NONE, BADGE_SHOW_FLASH
    .byte BADGE_SHOW_BLUE, BADGE_SHOW_FLASH, BADGE_SHOW_FLASH, BADGE_SHOW_FLASH
    .byte BADGE_SHOW_YELLOW
.assert * - badge_kinds = NESP_KEYBOARD_FAILED + 1, error, "a badge for every state"
; By BADGE_SHOW_*: none (hidden), grey, yellow, flashing (badge_show's own)
; and blue.
badge_colors:
    .byte BADGE_BLUE, BADGE_GREY, BADGE_YELLOW, BADGE_BLUE, BADGE_BLUE
; Its four sprites as OAM has them, but for Y: top left, top right, and
; the bottom two, which are the top two upside down.
badge_sprites:
    .byte 0, BADGE_TILE_LEFT, BADGE_ATTR, BADGE_X
    .byte 0, BADGE_TILE_RIGHT, BADGE_ATTR, BADGE_X + 8
    .byte 0, BADGE_TILE_LEFT, BADGE_ATTR | BADGE_FLIP, BADGE_X
    .byte 0, BADGE_TILE_RIGHT, BADGE_ATTR | BADGE_FLIP, BADGE_X + 8
.segment "CODE"

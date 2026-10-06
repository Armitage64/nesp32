; nesp32 setup: the Stick's own screen and buttons, on the console.
;
; A Stick has no keyboard, and its user is not asked to plug it into a
; computer. This ROM is how it is set up: it shows what the Stick is and how
; it is, puts it on a Wi-Fi network chosen from a list with a password
; typed on the controller, and tests the link.
;
;   status.inc    the first screen: the Stick, its firmware, its Wi-Fi
;   wifi.inc      choosing a network, sending its name and password, joining
;   keys.inc      the keyboard a name or a password is typed on
;   test.inc      the link test
;
; Everything it knows comes over the link (nes/lib/nesp.inc,
; docs/PROTOCOL.md), a request at a time, at most one a frame.
;
; A frame: the NMI writes to the PPU and reads the controller. The main loop
; then runs the screen that is up, which makes its one exchange first, while
; most of the frame is left for the reply. Everything a screen wants drawn
; goes through one staging buffer, draw_buf, which the next NMI writes: up
; to 32 tiles in a row. Changing to another screen is the exception: it is
; written whole, with the picture and the NMI off for a frame.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
OAMADDR   = $2003
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
OAMDMA    = $4014
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

FRAME_IRQ_INHIBIT = $40
PPUCTRL_ON = $80                ; NMI on, nametable 0
PPUMASK_ON = $1E                ; background and sprites, left column included
PALETTE   = $3F00
ATTRIBUTES = $23C0
OUT0_MARK = $01

PAD_A      = $80
PAD_B      = $40
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04
PAD_LEFT   = $02
PAD_RIGHT  = $01
PAD_DIRECTIONS = PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
REPEAT_DELAY = 20               ; frames a direction is held before it repeats
REPEAT_EVERY = 5                ; and frames between repeats

; The screens. A state's number is its place in `screens`.
STATE_STATUS  = 0
STATE_SCAN    = 1
STATE_LIST    = 2
STATE_KEYS    = 3
STATE_SEND    = 4
STATE_JOINING = 5
STATE_FAILED  = 6
STATE_TEST    = 7

MISSES_MAX = 3                  ; requests in a row with no reply: the Stick is gone

; What this ROM asks of the link.
NESP_RX_MASK = $3F              ; replies of up to 63 bytes: a network's name is 32
NESP_TX_MAX  = 24
.ifdef TIMEOUT_BUILD            ; the tests' build of the library's other
NESP_TIMEOUT = 3                ; receiver and its other CRC (Makefile)
NESP_CRC_TABLE = 1
.endif
.define NESP_APP "SETP"
NESP_APP_VERSION = 1

oam = $0200                     ; sprites, copied to the PPU every NMI
SPRITE_HIDDEN = $F0

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $01, $00              ; mapper 0 (NROM), vertical mirroring
    .res 8, 0

.segment "RODATA"
.include "screen.inc"
header_data:
    .incbin "header.bin"

.segment "ZEROPAGE"
frame_count:  .res 1
served_frame: .res 1
state:        .res 1
mask:         .res 1            ; PPUMASK, written every NMI
ctrl:         .res 1            ; what PPUCTRL holds: 0 while the NMI is off
pad:          .res 1            ; controller 1 as the NMI read it
pad_seen:     .res 1
pad_new:      .res 1            ; buttons that went down, and directions repeating
pad_hold:     .res 1
draw_len:     .res 1            ; tiles staged in draw_buf; 0 for none
draw_addr:    .res 2
linked:       .res 1            ; the Stick has answered a hello
misses:       .res 1
message_ptr:  .res 2            ; the message line's text, if message_new
message_new:  .res 1
timer:        .res 2
tmp:          .res 2
ptr:          .res 2
width:        .res 1

.segment "BSS"
draw_buf:     .res 32

; --- macros --------------------------------------------------------------------

; draw_addr = the tile at a row and a column.
.macro at row, column
    lda #<($2000 + 32 * (row) + (column))
    sta draw_addr
    lda #>($2000 + 32 * (row) + (column))
    sta draw_addr + 1
.endmacro

; ptr = an address.
.macro point address
    lda #<(address)
    sta ptr
    lda #>(address)
    sta ptr + 1
.endmacro

; Show a text on the message line from the next frame on.
.macro say address
    lda #<(address)
    sta message_ptr
    lda #>(address)
    sta message_ptr + 1
    lda #1
    sta message_new
.endmacro

; A screen is a list of texts, each with its place, ended by a 0. text is
; white; label is the second colour.
.macro text row, column, string
    .byte >($2000 + 32 * (row) + (column)), <($2000 + 32 * (row) + (column))
    .byte .strlen(string), string
.endmacro

.macro label row, column, string
    .byte >($2000 + 32 * (row) + (column)), <($2000 + 32 * (row) + (column))
    .byte .strlen(string)
    .repeat .strlen(string), index
        .byte .strat(string, index) | ALT
    .endrepeat
.endmacro

.macro inc16 value
    inc value
    bne :+
    inc value + 1
:
.endmacro

.include "nesp.inc"
.include "status.inc"
.include "wifi.inc"
.include "keys.inc"
.include "test.inc"

.segment "RODATA"
screens_lo:
    .lobytes status_frame - 1, scan_frame - 1, list_frame - 1, keys_frame - 1
    .lobytes send_frame - 1, joining_frame - 1, failed_frame - 1, test_frame - 1
screens_hi:
    .hibytes status_frame - 1, scan_frame - 1, list_frame - 1, keys_frame - 1
    .hibytes send_frame - 1, joining_frame - 1, failed_frame - 1, test_frame - 1

empty_text:    .byte 0
no_answer_text: .byte "NO ANSWER FROM THE NESP32", 0

.segment "CODE"

.proc reset
    sei
    cld
    ldx #FRAME_IRQ_INHIBIT
    stx APU_FRAME
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx APU_DMC                 ; DMC IRQ off
    stx APU_STATUS
    lda #OUT0_MARK              ; the line to the Stick leaves break
    sta JOY1
    bit PPUSTATUS
@vblank1:
    bit PPUSTATUS
    bpl @vblank1

    txa
@clear:
    sta $0000,x
    sta $0100,x
    sta $0200,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @clear

@vblank2:
    bit PPUSTATUS
    bpl @vblank2

    jsr ppu_init                ; rendering is off; the first NMI turns it on
    lda #PPUMASK_ON
    sta mask
    jsr open_status             ; which turns the NMI on
    ; fall through
.endproc

; Once a frame, starting right after the NMI. The loop compares with the
; last frame it served rather than waiting for a change: an NMI that cuts
; off a receive has already counted the new frame, and that frame still
; needs its turn.
;
; The tests skip the clock ahead to the next NMI whenever the CPU sits at
; main_wait with frame_count equal to served_frame, so it is a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr read_input
    jsr run_screen
    jsr draw_message
    jmp main_loop

.proc run_screen
    ldx state
    lda screens_hi,x
    pha
    lda screens_lo,x
    pha
    rts
.endproc

; pad_new = the buttons that went down since the last frame, and any
; direction that has been held long enough to repeat.
.proc read_input
    lda pad
    tax
    eor pad_seen
    stx pad_seen
    and pad_seen
    sta pad_new
    txa
    and #PAD_DIRECTIONS
    beq @released
    bit pad_new                 ; a new press starts the count again
    bne @released
    inc pad_hold
    lda pad_hold
    cmp #REPEAT_DELAY
    bcc @done
    lda #REPEAT_DELAY - REPEAT_EVERY
    sta pad_hold
    txa
    and #PAD_DIRECTIONS
    ora pad_new
    sta pad_new
@done:
    rts
@released:
    lda #0
    sta pad_hold
    rts
.endproc

; --- the link ------------------------------------------------------------------

; nesp_call, and what every screen does about its answer. Carry set if
; there is nothing for the caller to use: no reply, or the Stick says the
; service is not in use, which means it has been switched off and on since
; this ROM's hello. Then the status screen is up, which says hello again.
.proc call
    jsr nesp_call
    ; fall through
.endproc

.proc called
    bcs @silent
    lda #0
    sta misses
    lda nesp_status
    cmp #NESP_ST_INACTIVE
    beq @lost
    clc
    rts
@silent:
    inc misses
    lda misses
    cmp #MISSES_MAX
    bcc @failed
    lda #0
    sta linked
    lda #MISSES_MAX
    sta misses
@failed:
    sec
    rts
@lost:
    lda #0
    sta linked
    jsr open_status
    sec
    rts
.endproc

; The last request again, byte for byte.
.proc call_again
    jsr nesp_again
    jmp called
.endproc

; --- drawing -------------------------------------------------------------------

; Fill draw_buf with spaces from X up to Y tiles, and stage Y tiles.
.proc stage_pad
    sty width
    lda #' '
@space:
    cpx width
    bcs @done
    sta draw_buf,x
    inx
    bne @space
@done:
    lda width
    sta draw_len
    rts
.endproc

; Add the text at ptr, which a 0 ends, to draw_buf at X. Leaves X after it.
.proc put_text
    ldy #0
@char:
    lda (ptr),y
    beq @done
    sta draw_buf,x
    inx
    iny
    bne @char
@done:
    rts
.endproc

; Add Y bytes at ptr to draw_buf at X as text: what is not a printable
; character is shown as a question mark. Leaves X after them.
.proc put_bytes
    sty tmp
    ldy #0
@char:
    cpy tmp
    beq @done
    lda (ptr),y
    cmp #' '
    bcc @other
    cmp #$7F
    bcc @put
@other:
    lda #'?'
@put:
    sta draw_buf,x
    inx
    iny
    bne @char
@done:
    rts
.endproc

; Add A in decimal to draw_buf at X. Leaves X after it.
.proc put_dec
    sta tmp
    lda #0
    sta tmp + 1
    ; fall through
.endproc

; Add the 16 bits at tmp in decimal to draw_buf at X. Destroys tmp.
.proc put_dec16
    ldy #0                      ; which power of ten
    sty width                   ; not 0 once a digit has been written
@power:
    lda #'0'
    sta draw_buf,x
@subtract:
    lda tmp
    sec
    sbc tens_lo,y
    pha
    lda tmp + 1
    sbc tens_hi,y
    bcc @under
    sta tmp + 1
    pla
    sta tmp
    inc draw_buf,x
    bne @subtract
@under:
    pla
    lda draw_buf,x
    cmp #'0'
    bne @keep
    lda width
    bne @keep
    cpy #4                      ; the last digit is written even if it is 0
    bne @next
@keep:
    inc width
    inx
@next:
    iny
    cpy #5
    bne @power
    rts
.endproc

.segment "RODATA"
tens_lo: .lobytes 10000, 1000, 100, 10, 1
tens_hi: .hibytes 10000, 1000, 100, 10, 1
.segment "CODE"

; The message line, when it has changed and nothing else is staged.
.proc draw_message
    lda message_new
    beq @done
    lda draw_len
    bne @done
    sta message_new
    lda message_ptr
    sta ptr
    lda message_ptr + 1
    sta ptr + 1
    at MESSAGE_ROW, LEFT
    ldx #0
    jsr put_text
    ldy #WIDTH
    jmp stage_pad
@done:
    rts
.endproc

; Sprite 0 is the cursor: tile A at X, Y on the screen.
.proc cursor_at
    sta oam + 1
    stx oam + 3
    dey                         ; a sprite shows a line below its Y
    sty oam
    lda #0
    sta oam + 2
    rts
.endproc

.proc cursor_off
    lda #SPRITE_HIDDEN
    sta oam
    rts
.endproc

; Change to the screen whose list of texts is at A (low) and X (high):
; everything under the header is cleared and the texts written. The picture
; and the NMI are off while that is done, so that nothing else writes to
; the PPU, and come back on with the next frame.
.proc show_screen
    sta ptr
    stx ptr + 1
    lda ctrl
    beq @off                    ; at reset the NMI is not on yet
    lda frame_count             ; a whole frame for it: wait for the next NMI
@wait:
    cmp frame_count
    beq @wait
@off:
    lda #0
    sta PPUCTRL
    sta ctrl
    sta PPUMASK
    sta draw_len
    sta message_new
    jsr cursor_off

    bit PPUSTATUS
    lda #>($2000 + 32 * HEADER_ROWS)
    sta PPUADDR
    lda #<($2000 + 32 * HEADER_ROWS)
    sta PPUADDR
    lda #0
    ldy #>(32 * (30 - HEADER_ROWS))
    ldx #<(32 * (30 - HEADER_ROWS))
    beq @whole
    iny                         ; a part of a page, then whole ones
@whole:
@blank:
    sta PPUDATA
    dex
    bne @blank
    dey
    bne @blank

@item:
    ldy #0
    lda (ptr),y
    beq @on
    sta PPUADDR
    iny
    lda (ptr),y
    sta PPUADDR
    iny
    lda (ptr),y
    tax
    iny
@char:
    lda (ptr),y
    sta PPUDATA
    iny
    dex
    bne @char
    tya
    clc
    adc ptr
    sta ptr
    bcc @item
    inc ptr + 1
    bne @item
@on:
    lda #PPUCTRL_ON
    sta ctrl
    sta PPUCTRL
    rts
.endproc

; Palettes, the header, and its palette over its rows. Rendering is off.
.proc ppu_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda palette_data,x
    sta PPUDATA
    inx
    cpx #32
    bne @palette

    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    tax
@header:
    lda header_data,x
    sta PPUDATA
    inx
    bne @header
    .assert HEADER_ROWS = 8, error, "the header is copied as one page"

    lda #>ATTRIBUTES
    sta PPUADDR
    lda #<ATTRIBUTES
    sta PPUADDR
    ldx #0
@attribute:
    lda #$FF                    ; the logo's palette, for the top 8 rows
    cpx #16
    bcc @put
    lda #$00
@put:
    sta PPUDATA
    inx
    cpx #64
    bne @attribute

    ldx #0
    lda #SPRITE_HIDDEN
@hide:
    sta oam,x
    inx
    bne @hide
    rts
.endproc

.proc nmi
    pha
    txa
    pha
    tya
    pha
    lda #0
    sta OAMADDR
    lda #>oam
    sta OAMDMA
    lda draw_len
    beq @scroll
    bit PPUSTATUS               ; reset the PPU's address latch
    lda draw_addr + 1
    sta PPUADDR
    lda draw_addr
    sta PPUADDR
    ldx #0
@tile:
    lda draw_buf,x
    sta PPUDATA
    inx
    cpx draw_len
    bne @tile
    lda #0
    sta draw_len
@scroll:
    bit PPUSTATUS
    lda #PPUCTRL_ON
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda mask
    sta PPUMASK

    ; Controller 1 shares its strobe with the line to the Stick: OUT0 must
    ; rest at mark, so the buttons are latched by dropping it, read, and it
    ; goes back up. The Stick sees one low pulse of 94 cycles a frame, which
    ; its UART takes for a byte and its decoder passes over.
    lda #0
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #OUT0_MARK
    sta JOY1

    inc frame_count
    nesp_nmi_hook
    pla
    tay
    pla
    tax
    pla
    rti
.endproc

.proc irq
    rti
.endproc

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

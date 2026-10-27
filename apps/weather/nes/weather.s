; Weather: the weather at a zip code, on one screen.
;
; A nesp32 on controller port 2 asks the Internet where a zip code is and
; what the weather is there, and lays the answer out as rows of tiles, the
; pictures among them; this ROM asks for the rows and draws them. It works
; nothing out. What is new is on the nesp32, its WEATHER service (nesp32's
; docs/PROTOCOL.md).
;
; There are two views. The form takes a zip code from the controller: Left
; and Right choose a digit, Up and Down change it, A or Start asks for its
; weather, and B, on nesp32's cartridge, is its menu again. The report is
; the nesp32's rows, but for the days' names, which the ROM moves half a
; tile to the left to center them over their pictures; B there is the form
; again. The nesp32 keeps the last
; zip code it found, over power-off too, so a console switched on asks it
; for that first (LAST), and the form comes up with those digits in it: A
; is all it takes.
;
; A Bluetooth keyboard on the nesp32 (its KBD) types a zip code too: a
; digit is the lit digit's and lights the next, Enter asks for the weather,
; Escape is B, and Backspace and the arrows move as the D-pad does. A digit
; typed over a report is the form's first, so that the next zip code can
; be typed at once.
;
; The digit that Up and Down change pulses, as the key under NESpedia's
; cursor does (../wiki/nes/keyboard.inc): its square of the screen has the
; cursor's palette, and the font's colour in that palette is changed every
; few frames.
;
; The link is nesp32's (its nes/lib/nesp.inc). Every use of it is one
; exchange, a request and its reply, made right after the NMI, at most one
; a frame, the first of these that applies:
;
;   SYS HELLO       until the nesp32 has answered it, and again whenever it
;                   says the service is not in use. It asks for KBD too, and
;                   a nesp32 without it is one to use all the same
;   WEATHER LAST    once: the zip code it keeps, if any
;   WEATHER ROW     a report is ready that is not on the screen: its next row
;   WEATHER ZIP     otherwise, while the report is the view: this zip code,
;                   and how it stands. Every frame until a report is on the
;                   screen, and about once a second after, in case there is
;                   a newer one
;   KBD KEYS        otherwise, every other frame, if the nesp32 has KBD:
;                   what has been typed on its keyboard
;
; The form asks nothing else.
;
; The NMI reads the controller and draws what the main loop has staged: the
; status line when it has changed, one row of the middle of the screen
; (row_buf), whether the form's or the report's, the palettes of the
; digits' squares, and the pulse's next colour. Nothing else writes to the
; PPU once the screen is on.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80
PPUMASK_BACKGROUND = $0A        ; background on, left column included
FRAME_IRQ_INHIBIT = $40
NAMETABLE = $2000
PALETTE   = $3F00

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

OUT0_MARK = $01

NESP_RX_MASK = $3F              ; replies of up to 63 bytes: a row, and what it is of
NESP_TX_MAX  = 9                ; the hello, with its two services
.define NESP_APP "WTHR"
NESP_APP_VERSION = 1

VIEW_FORM   = 0
VIEW_REPORT = 1

SKY_UNKNOWN = $FF               ; sky: the nesp32 has not said how it stands
PULSE_MASK = $07                ; frames between the pulse's colours, less one
; The cartridge's reset stub (nesp32's nes/cart/gen_cart.py) is at the same
; place in every program's bank: an `inc` of itself, which resets the
; mapper and puts the menu's bank at $C000, and a jump to the menu. Built by
; itself, this ROM has padding there. As Bluesky's Select does.
CART_STUB = $FFDA
CART_STUB_FIRST = $EE           ; inc absolute

POLL_MASK = $3F                 ; a report on the screen is asked after every 64 frames
MISSED_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is not there

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM), horizontal mirroring
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1
text_ptr:     .res 2            ; the status line's text, for the NMI
src_ptr:      .res 2            ; the main loop's: a row of the form, in the ROM
pad:          .res 1            ; A B Select Start Up Down Left Right
held:         .res 1            ; the NMI's: the directions that are down

.segment "BSS"
pad_prev:     .res 1
pad_new:      .res 1            ; buttons that went down, or repeated: the main loop's
repeat:       .res 1            ; frames until a direction held down counts again
presses:      .res 1            ; the main loop's copy of pad_new
status:       .res 1            ; STATUS_*: what the status line says
status_dirty: .res 1            ; and it is not on the screen yet
greeted:      .res 1            ; the nesp32 has answered this ROM's hello
typing:       .res 1            ; and has KBD: its keyboard's keys are asked for
key_at:       .res 1            ; ask_keys's: the key of the reply it is on,
key_count:    .res 1            ; of these
key_char:     .res 1            ; type_key's: the key
asked_last:   .res 1            ; and said what zip code it keeps
link_missed:  .res 1            ; exchanges in a row with no reply, up to MISSED_MAX
link_failed:  .res 2            ; every exchange with none, for a debugger's watch list
why_buf:      .res 28           ; the nesp32's words for what went wrong
why_len:      .res 1
view:         .res 1            ; VIEW_*
zip:          .res 5            ; the form's digits, as characters
zip_sent:     .res 5            ; the zip code last asked for,
zip_id:       .res 1            ; and its id: one more with every asking
cursor:       .res 1            ; the form's digit that Up and Down change
sky:          .res 1            ; NESP_SKY_*, as the nesp32 last said, or SKY_UNKNOWN
serial_have:  .res 1            ; the report on the screen: 0 for none
serial_want:  .res 1            ; the one being drawn
row_next:     .res 1            ; its next row to draw; PAINT_ROWS when it is all there
paint_at:     .res 1            ; the form's rows still to draw: from this one
paint_end:    .res 1            ; up to this one
row_buf:      .res 28           ; a row for the NMI to draw,
row_addr:     .res 2            ; where, high byte first,
row_dirty:    .res 1            ; and that it has not yet
attr_buf:     .res 4            ; the palettes of the digits' squares, likewise,
attr_dirty:   .res 1
pulse:        .res 1            ; where the lit digit's colour is in its round,
pulse_color:  .res 1            ; the colour, for the NMI,
pulse_dirty:  .res 1            ; and that it is not on the screen yet
on_cart:      .res 1            ; this is on nesp32's cartridge, which has a menu
day_at:       .res 1            ; center_days's: the day it is on

.include "screen.inc"
.include "nesp.inc"

.assert NESP_TX_MAX = NESP_HELLO_FIXED + 2, error, "the hello names two services"
.assert 1 + NESP_KBD_KEYS_MAX <= NESP_RX_MASK, error, "what is typed must fit a reply"
.assert NESP_TX_MAX >= 1 + NESP_WEATHER_ZIP_LEN, error, "a zip code must fit a request"
.assert 4 + NESP_WEATHER_COLUMNS <= NESP_RX_MASK, error, "a row must fit its buffer"
.assert ROWS = NESP_WEATHER_ROWS && COLUMNS = NESP_WEATHER_COLUMNS, error, "a report is the nesp32's"
.assert PICTURE_TILE = NESP_WEATHER_PICTURE && DEGREE_TILE = NESP_WEATHER_DEGREE, error, "and so are its tiles"
.assert STATUS_WIDTH = NESP_WEATHER_COLUMNS, error, "why_buf holds what the nesp32 may say"
.assert DIGIT_ATTRS <= 4, error, "attr_buf holds the digits' attribute bytes"

.segment "RODATA"
palette_data:
    .incbin "palette.bin"
screen_data:
    .incbin "screen.bin"

; The status line's text, by STATUS_*.
status_lo:
.repeat STATUS_WHY, index
    .byte <(status_text + index * STATUS_WIDTH)
.endrepeat
    .byte <why_buf
status_hi:
.repeat STATUS_WHY, index
    .byte >(status_text + index * STATUS_WIDTH)
.endrepeat
    .byte >why_buf

; What the status line says for each of the nesp32's states before READY.
sky_status:
    .byte STATUS_NONE, STATUS_NO_WIFI, STATUS_FINDING, STATUS_FETCHING
.assert NESP_SKY_IDLE = 0 && NESP_SKY_NO_WIFI = 1 && NESP_SKY_LOOKING = 2, error, "sky_status"
.assert NESP_SKY_FETCHING = 3 && NESP_SKY_READY = 4, error, "sky_status"

; The form's rows, in the ROM, and the column of each of its digits.
form_lo:
.repeat PAINT_ROWS, index
    .byte <(form_text + index * COLUMNS)
.endrepeat
form_hi:
.repeat PAINT_ROWS, index
    .byte >(form_text + index * COLUMNS)
.endrepeat
digit_column:
.repeat NESP_WEATHER_ZIP_LEN, index
    .byte FORM_DIGIT_COLUMN + index * FORM_DIGIT_STEP
.endrepeat

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

    lda CART_STUB
    cmp #CART_STUB_FIRST
    bne @alone
    inc on_cart
@alone:
    lda #$FF                    ; every button begins down, so that one held from
    sta pad_prev                ; before, as the cartridge's menu's A or Start is,
                                ; counts only once it has been let go
    jsr screen_init             ; rendering is off; the first NMI turns it on
    ldx #NESP_WEATHER_ZIP_LEN - 1
@zip:
    lda form_zip,x              ; what the form begins with, if nothing is kept
    sta zip,x
    dex
    bpl @zip
    lda #SKY_UNKNOWN
    sta sky
    sta status                  ; nothing is on the status line yet
    lda #PAINT_ROWS
    sta row_next
    lda #REPEAT_DELAY
    sta repeat
    lda #STATUS_WAITING
    jsr set_status
    lda #OUT0_MARK              ; the line rests at mark, which is also what keeps
    sta JOY1                    ; the controller loading its buttons
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through
.endproc

; A frame: the buttons, a row of the form if one is due, and one exchange,
; starting right after the NMI. The main loop compares against the last
; frame it served rather than waiting for the next change, because an NMI
; that cuts off a receive has already counted the new frame, and that frame
; still needs its request.
;
; The tests fast-forward the emulated clock to the next NMI whenever the
; CPU sits at main_wait with frame_count equal to served_frame, so keep it a
; plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr buttons
    jsr paint_form
    jsr pulse_step
    jsr link_service
    jmp main_loop

; Load the palette and the screen. Rendering must be off.
.proc screen_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda palette_data,x
    sta PPUDATA
    inx
    cpx #16
    bne @palette

    lda #>NAMETABLE
    sta PPUADDR
    lda #<NAMETABLE
    sta PPUADDR
    ldx #0
@page0:
    lda screen_data,x
    sta PPUDATA
    inx
    bne @page0
@page1:
    lda screen_data + $100,x
    sta PPUDATA
    inx
    bne @page1
@page2:
    lda screen_data + $200,x
    sta PPUDATA
    inx
    bne @page2
@page3:
    lda screen_data + $300,x
    sta PPUDATA
    inx
    bne @page3
    rts
.endproc

; The status line is to say A (STATUS_*). The NMI draws it; it is told only
; once the text's address is whole.
.proc set_status
    cmp status
    beq @done
    sta status
    tax
    lda #0
    sta status_dirty
    lda status_lo,x
    sta text_ptr
    lda status_hi,x
    sta text_ptr + 1
    lda #1
    sta status_dirty
@done:
    rts
.endproc

; row_buf is whole, and is row X of what is painted (the middle's rows,
; then the foot): the NMI is to draw it there.
.proc stage_row
    lda paint_hi,x
    sta row_addr
    lda paint_lo,x
    sta row_addr + 1
    lda #1
    sta row_dirty
    rts
.endproc

; --- the form ----------------------------------------------------------------------

; What the controller asked for since the last frame.
.proc buttons
    lda pad_new
    bne @some
@done:
    rts
@some:
    ldx #0
    stx pad_new
    tax
    and #PAD_SELECT             ; Select: back to the cartridge's menu, from
    beq @no_quit                ; either view, with a nesp32 or none
    lda on_cart
    beq @no_quit
    jmp quit
@no_quit:
    txa
    ldx asked_last              ; until the nesp32 has said what it keeps there
    beq @done                   ; is neither view to work
    jmp act
.endproc

; Buttons A pressed, on either view: from the controller, or a key typed.
.proc act
    sta presses
    lda view
    beq @form
    lda presses                 ; the report: B is the form
    and #PAD_B
    bne @back
@done:
    rts
@back:
    jmp back_to_form
@form:
    lda presses                 ; B: nothing to go back to, and never out of
    and #PAD_A | PAD_START      ; the program, so that B pressed again and
    beq @move                   ; again cannot leave it
    jmp submit
@move:
    lda presses
    and #PAD_DIRECTIONS
    beq @done
    ldx cursor
    lda presses
    and #PAD_LEFT
    beq @right
    dex
    bpl @right
    ldx #NESP_WEATHER_ZIP_LEN - 1
@right:
    lda presses
    and #PAD_RIGHT
    beq @up
    inx
    cpx #NESP_WEATHER_ZIP_LEN
    bne @up
    ldx #0
@up:
    stx cursor
    lda presses
    and #PAD_UP
    beq @down
    inc zip,x
    lda zip,x
    cmp #'9' + 1
    bne @down
    lda #'0'
    sta zip,x
@down:
    lda presses
    and #PAD_DOWN
    beq @touched
    dec zip,x
    lda zip,x
    cmp #'0' - 1
    bne @touched
    lda #'9'
    sta zip,x
@touched:
    jmp form_touch
.endproc

; One key typed on the nesp32's keyboard, A: a digit, or what a button
; would do. Anything else is no key of the form's.
.proc type_key
    cmp #'0'
    bcc @control
    cmp #'9' + 1
    bcs @done
    sta key_char
    lda view
    beq @digit
    jsr back_to_form            ; over a report: a new zip code, from its first digit
    lda #0
    sta cursor
@digit:
    ldx cursor
    lda key_char
    sta zip,x
    inx
    cpx #NESP_WEATHER_ZIP_LEN
    bcc @lit
    ldx #0                      ; after the last, the first: ready for the next zip code
@lit:
    stx cursor
    jmp form_touch
@control:
    cmp #NESP_KEY_BACKSPACE
    bne @find
    ldx cursor                  ; Backspace stops at the first digit
    beq @done
@find:
    ldx #KEY_BUTTONS - 1
@key:
    cmp key_codes,x
    beq @found
    dex
    bpl @key
@done:
    rts
@found:
    lda key_buttons,x
    jmp act
.endproc

.segment "RODATA"
key_codes:
    .byte NESP_KEY_ENTER, NESP_KEY_ESCAPE, NESP_KEY_BACKSPACE
    .byte NESP_KEY_UP, NESP_KEY_DOWN, NESP_KEY_LEFT, NESP_KEY_RIGHT
key_buttons:
    .byte PAD_A, PAD_B, PAD_LEFT
    .byte PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT
KEY_BUTTONS = * - key_buttons
.assert KEY_BUTTONS = key_buttons - key_codes, error, "a button for every key"

.segment "CODE"

; From the report: the form again, saying nothing.
.proc back_to_form
    lda #STATUS_NONE
    jsr set_status
    jmp show_form
.endproc

; The form is the view, and all of it is to be drawn.
.proc show_form
    lda #VIEW_FORM
    sta view
    lda #0
    sta paint_at
    lda #PAINT_ROWS
    sta paint_end
    jmp light
.endproc

; The form's digits, or which of them is lit, have changed: draw their
; row, and light the one. If the form is being drawn and has not got to
; that row, it will; if it is past it, it goes back.
.proc form_touch
    jsr light
    lda paint_at
    cmp paint_end
    beq @idle
    cmp #FORM_DIGITS_ROW + 1
    bcc @done
    bcs @from
@idle:
    lda #FORM_DIGITS_ROW + 1
    sta paint_end
@from:
    lda #FORM_DIGITS_ROW
    sta paint_at
@done:
    rts
.endproc

; The digits' squares of the screen have the text's palette, but for the
; one of the digit that Up and Down change, which has the cursor's. None
; has it while nothing can be changed. One attribute byte covers four
; squares, but only one digit is ever lit, so each byte is that digit's
; bits or nothing.
.proc light
    lda #0
    sta attr_dirty              ; the NMI is not to draw them half made
    ldx #DIGIT_ATTRS - 1
@clear:
    sta attr_buf,x
    dex
    bpl @clear
    lda view
    bne @stage
    ldy cursor
    ldx digit_attr,y
    lda digit_attr_on,y
    sta attr_buf,x
@stage:
    lda #1
    sta attr_dirty
    rts
.endproc

; The lit digit's colour, every few frames the next of its round.
.proc pulse_step
    lda view
    bne @done
    lda frame_count
    and #PULSE_MASK
    bne @done
    ldx pulse
    inx
    cpx #PULSE_STEPS
    bcc @color
    ldx #0
@color:
    stx pulse
    lda pulse_colors,x
    sta pulse_color
    lda #1
    sta pulse_dirty
@done:
    rts
.endproc

; The weather of the form's zip code is asked for: a new asking, whether or
; not the digits are new.
.proc submit
    ldx #NESP_WEATHER_ZIP_LEN - 1
@copy:
    lda zip,x
    sta zip_sent,x
    dex
    bpl @copy
    inc zip_id
    jsr await
    jmp form_touch              ; no digit is lit: nothing can be changed now
.endproc

; Back to the cartridge's menu, as reset would go: through its stub, with
; the NMI off first, since the stub's `inc` puts the menu's bank, and its
; NMI, under this. The menu says nothing to the nesp32; the next program's
; hello is what tells it this one has gone.
.proc quit
    lda #0
    sta PPUCTRL
    sta PPUMASK
    jmp CART_STUB
.endproc

; The report is the view, and none is on the screen: whatever the nesp32
; says of zip_sent is drawn from its first row.
.proc await
    lda #VIEW_REPORT
    sta view
    lda #SKY_UNKNOWN
    sta sky
    lda #0
    sta serial_have
    lda #PAINT_ROWS
    sta row_next
    rts
.endproc

; A row of the form for the NMI, if there is one to draw and the last has
; been drawn: its tiles from the ROM, with the digits on their row, and on
; the cartridge the foot that says Select is its menu.
.proc paint_form
    lda row_dirty
    bne @done
    ldx paint_at
    cpx paint_end
    beq @done
    lda form_lo,x
    sta src_ptr
    lda form_hi,x
    sta src_ptr + 1
    ldy #COLUMNS - 1
@copy:
    lda (src_ptr),y
    sta row_buf,y
    dey
    bpl @copy
    cpx #ROWS
    bne @digits
    lda on_cart
    beq @stage
    ldy #COLUMNS - 1
@cart:
    lda form_foot_cart,y
    sta row_buf,y
    dey
    bpl @cart
    bmi @stage
@digits:
    cpx #FORM_DIGITS_ROW
    bne @stage
    ldy #NESP_WEATHER_ZIP_LEN - 1
@digit:
    ldx digit_column,y
    lda zip,y
    sta row_buf,x
    dey
    bpl @digit
@stage:
    ldx paint_at
    jsr stage_row
    inc paint_at
@done:
    rts
.endproc

; --- the link ----------------------------------------------------------------------

; The frame's exchange, if it has one. An exchange that the next NMI cut
; off comes back here with carry set and frame_count moved on, so the main
; loop serves the new frame at once; one that ended inside its frame, good
; or not, leaves the next for the next NMI.
.proc link_service
    lda greeted
    bne @greeted
    jmp say_hello
@greeted:
    lda asked_last
    bne @asked
    jmp ask_last
@asked:
    lda view
    beq @keys                   ; the form asks only what is typed
    lda sky
    cmp #NESP_SKY_READY
    bne @zip
    lda row_next
    cmp #PAINT_ROWS
    beq @settled
    lda row_dirty               ; a row at a time,
    bne @idle
    lda paint_at                ; and none over a form that is still being drawn
    cmp paint_end
    bne @idle
    lda row_next
    cmp #ROWS
    beq @foot
    jmp ask_row
@foot:
    ldx #COLUMNS - 1            ; the last of it is the ROM's own: what B does
@copy:
    lda report_foot,x
    sta row_buf,x
    dex
    bpl @copy
    ldx row_next
    jsr stage_row
    inc row_next
    lda serial_want             ; and with that it is the report on the screen
    sta serial_have
@idle:
    rts
@settled:
    lda frame_count
    and #POLL_MASK
    bne @keys
@zip:
    jmp ask_zip
@keys:
    jmp ask_keys
.endproc

; Hello: this is Weather, and it needs WEATHER. A nesp32 that lacks it, or
; speaks another protocol, has older firmware than this ROM, and the screen
; says so.
.proc say_hello
    lda #NESP_SVC_WEATHER
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED + 1
    ldy #2
    jsr nesp_hello
    bcc @came
    jmp link_silent
@came:
    ldx #1
    cmp #NESP_ST_OK
    beq @greeted
    cmp #NESP_ST_NO_SERVICE     ; only KBD missing is a nesp32 to use, with no
    bne @old                    ; keyboard: one from before KBD
    lda nesp_reply + 6
    cmp #1
    bne @old
    lda nesp_reply + 7
    cmp #NESP_SVC_KBD
    bne @old
    ldx #0
@greeted:
    stx typing
    lda #1
    sta greeted
    lda view                    ; a nesp32 that was switched off and on has no
    beq @heard                  ; report: the one on the screen is asked for again
    jsr await
@heard:
    jmp link_heard
@old:
    lda #STATUS_OLD
    jsr set_status
    jmp link_heard
.endproc

; The zip code the nesp32 keeps, once: the form comes up with its digits,
; for A to ask for. If it keeps none, the form's digits are as they began.
.proc ask_last
    lda #NESP_SVC_WEATHER
    ldx #NESP_WEATHER_LAST
    ldy #0
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda #1
    sta asked_last
    lda nesp_reply_len
    cmp #NESP_WEATHER_ZIP_LEN
    bne @none
    ldx #NESP_WEATHER_ZIP_LEN - 1
@digit:
    lda nesp_reply,x
    sta zip,x
    dex
    bpl @digit
@none:
    lda #STATUS_NONE
    jsr set_status
    jsr show_form
    jmp link_heard
.endproc

; What has been typed on the nesp32's keyboard, every other frame, if it
; has one: each key as the form takes it. A reply after the nesp32 had
; gone quiet says it is back.
.proc ask_keys
    lda typing
    beq @none
    lda frame_count
    lsr a
    bcc @none
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda status
    cmp #STATUS_WAITING
    bne @count
    lda #STATUS_NONE
    jsr set_status
@count:
    lda nesp_reply
    cmp #NESP_KBD_KEYS_MAX + 1
    bcs @heard
    sta key_count
    lda #0
    sta key_at
@key:
    ldx key_at
    cpx key_count
    bcs @heard
    lda nesp_reply + 1,x
    jsr type_key
    inc key_at
    bne @key
@heard:
    jmp link_heard
@none:
    rts
.endproc

; This zip code, and how it stands with it: for the status line, and for
; what is asked next. One that cannot be had is the form's to put right.
.proc ask_zip
    lda zip_id
    sta nesp_request
    ldx #NESP_WEATHER_ZIP_LEN - 1
@digit:
    lda zip_sent,x
    sta nesp_request + 1,x
    dex
    bpl @digit
    lda #NESP_SVC_WEATHER
    ldx #NESP_WEATHER_ZIP
    ldy #1 + NESP_WEATHER_ZIP_LEN
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    cmp #3
    bcc @heard                  ; not a reply to this at all
    lda nesp_reply + 1
    cmp zip_id
    bne @heard
    lda nesp_reply
    sta sky
    cmp #NESP_SKY_READY
    beq @ready
    cmp #NESP_SKY_NOT_FOUND
    beq @none
    cmp #NESP_SKY_FAILED
    beq @failed
    bcs @heard                  ; a state this ROM has not heard of
    tax
    lda sky_status,x
    jsr set_status
@heard:
    jmp link_heard
@ready:
    lda #STATUS_NONE
    jsr set_status
    lda nesp_reply + 2
    cmp serial_have
    beq @heard                  ; it is the one on the screen
    sta serial_want
    lda #0
    sta row_next
    beq @heard
@none:
    lda #STATUS_NO_ZIP
    jsr set_status
    jmp @form
@failed:
    jsr take_why
@form:
    jsr show_form
    jmp link_heard
.endproc
.assert NESP_SKY_NOT_FOUND > NESP_SKY_READY && NESP_SKY_FAILED > NESP_SKY_READY, error, "ask_zip"

; The next row of the report, into row_buf. A row of a newer report than
; the one being drawn starts the drawing over, from that one's first.
.proc ask_row
    lda zip_id
    sta nesp_request
    lda row_next
    sta nesp_request + 1
    lda #NESP_SVC_WEATHER
    ldx #NESP_WEATHER_ROW
    ldy #2
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    cmp #4
    bcc @heard
    lda nesp_reply + 1
    cmp zip_id
    bne @heard
    lda nesp_reply + 3
    cmp row_next
    bne @heard
    lda nesp_reply
    cmp #NESP_SKY_READY
    beq @row
    sta sky                     ; no report after all: ZIP says how it stands
    jmp link_heard
@row:
    lda nesp_reply_len
    cmp #4 + COLUMNS
    bne @heard
    lda nesp_reply + 2
    cmp serial_want
    beq @same
    sta serial_want
    lda #0
    sta row_next
    beq @heard
@same:
    ldx #COLUMNS - 1
@copy:
    lda nesp_reply + 4,x
    sta row_buf,x
    dex
    bpl @copy
    lda row_next
    cmp #DAY_ROW
    bne @stage
    jsr center_days
@stage:
    ldx row_next
    jsr stage_row
    inc row_next
@heard:
    jmp link_heard
.endproc

; row_buf is the days' row: each name the ROM has tiles for is put in
; them, from the column before its own. A name it has none for is left.
.proc center_days
    lda #DAYS - 1
    sta day_at
@day:
    ldx day_at
    ldy day_column,x            ; Y: the name's column
    ldx #0                      ; X: a name's place in day_names, and its tiles' in day_tiles
@name:
    lda row_buf,y
    cmp day_names,x
    bne @next
    lda row_buf + 1,y
    cmp day_names + 1,x
    bne @next
    lda row_buf + 2,y
    cmp day_names + 2,x
    beq @found
@next:
    inx
    inx
    inx
    inx
    cpx #DAY_NAMES * DAY_TILES
    bne @name
    beq @done
@found:
    dey
.repeat ::DAY_TILES, index
    lda day_tiles + index,x
    sta row_buf + index,y
.endrepeat
@done:
    dec day_at
    bpl @day
    rts
.endproc
.assert DAY_TILES = 4, error, "center_days steps through day_names four at a time"

; The nesp32's words for what went wrong, in the middle of the status line.
.proc take_why
    lda #0
    sta status_dirty            ; the NMI is not to draw them half made
    lda #$FF
    sta status                  ; whatever the line said, it is to say these
    ldx #STATUS_WIDTH - 1
    lda #' '
@blank:
    sta why_buf,x
    dex
    bpl @blank
    lda nesp_reply_len
    sec
    sbc #3                      ; the words' length
    cmp #STATUS_WIDTH + 1
    bcc @fits
    lda #STATUS_WIDTH
@fits:
    sta why_len
    lda #STATUS_WIDTH
    sec
    sbc why_len
    lsr a
    tax                         ; where they begin
    ldy #0
@char:
    cpy why_len
    beq @copied
    lda nesp_reply + 3,y
    sta why_buf,x
    inx
    iny
    bne @char
@copied:
    lda #STATUS_WHY
    jmp set_status
.endproc

; A reply came. The next exchange waits for the next NMI: sent from here,
; partway through a frame, its reply could run into that NMI.
.proc link_heard
    lda #0
    sta link_missed
    lda frame_count
    sta served_frame
    rts
.endproc

; None came, or not a good one.
.proc link_silent
    inc link_failed
    bne @counted
    inc link_failed + 1
@counted:
    lda link_missed
    cmp #MISSED_MAX
    bcs @gone
    inc link_missed
    rts
@gone:
    lda #SKY_UNKNOWN
    sta sky
    lda #STATUS_WAITING
    jmp set_status
.endproc

; The nesp32 answered, and not with OK: it no longer has the service in
; use. Say hello again.
.proc link_refused
    lda #0
    sta greeted
    jmp link_heard
.endproc

; --- the NMI ------------------------------------------------------------------------

; The controller is read by taking OUT0 low for the 8 reads, and OUT0 is
; also the serial line to the nesp32. It rests at mark, which keeps the
; controller loading its buttons, so no strobe pulse is needed: the read is
; one low pulse, some four bits at the link's rate, which the nesp32's UART
; takes for a byte and its decoder passes over as noise. It comes first, so
; that the byte is long over before the main loop sends its request.
.proc nmi
    pha
    txa
    pha
    tya
    pha
    bit PPUSTATUS               ; reset the PPU's address latch
    lda #0
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #OUT0_MARK
    sta JOY1
    lda pad
    eor pad_prev
    and pad
    tax                         ; buttons that went down this frame
    ; A direction held down counts again after a while, and then often.
    lda pad
    and #PAD_DIRECTIONS
    beq @fresh
    sta held
    lda pad_prev
    and #PAD_DIRECTIONS
    cmp held
    bne @fresh
    dec repeat
    bne @counted
    lda #REPEAT_EVERY
    sta repeat
    txa
    ora held
    tax
    bne @counted
@fresh:
    lda #REPEAT_DELAY
    sta repeat
@counted:
    lda pad
    sta pad_prev
    txa
    ora pad_new
    sta pad_new

    lda status_dirty
    beq @row
    lda #>STATUS_ADDR
    sta PPUADDR
    lda #<STATUS_ADDR
    sta PPUADDR
    ldy #0
@char:
    lda (text_ptr),y
    sta PPUDATA
    iny
    cpy #STATUS_WIDTH
    bne @char
    lda #0
    sta status_dirty
@row:
    lda row_dirty
    beq @attrs
    lda row_addr
    sta PPUADDR
    lda row_addr + 1
    sta PPUADDR
    ldy #0
@tile:
    lda row_buf,y
    sta PPUDATA
    iny
    cpy #COLUMNS
    bne @tile
    lda #0
    sta row_dirty
@attrs:
    lda attr_dirty
    beq @pulse
    lda #>DIGIT_ATTR_ADDR
    sta PPUADDR
    lda #<DIGIT_ATTR_ADDR
    sta PPUADDR
    ldy #0
@attr:
    lda attr_buf,y
    sta PPUDATA
    iny
    cpy #DIGIT_ATTRS
    bne @attr
    lda #0
    sta attr_dirty
@pulse:
    lda pulse_dirty
    beq @done
    lda #>PULSE_ADDR
    sta PPUADDR
    lda #<PULSE_ADDR
    sta PPUADDR
    lda pulse_color
    sta PPUDATA
    lda #0
    sta pulse_dirty
@done:
    lda #PPUCTRL_NMI
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_BACKGROUND
    sta PPUMASK
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

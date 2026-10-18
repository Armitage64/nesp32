; The status screen: what the Stick is and how it is. The first screen, and
; the one every other comes back to.
;
;   Up, Down    move the arrow among what can be done from here
;   A           do it: set up Wi-Fi, test the link, lend the nesp32's
;               files to a computer as a USB drive, turn the nesp32's
;               screen the other way up, or, on the cartridge, go back to
;               its menu
;
; Every few frames it does one step of a round: say hello if the Stick has
; not been heard from, ask for something, and write the line that shows it.
; A Stick that stops answering is found out by the same round, and a Stick
; that is plugged in later is greeted by it.

STATUS_EVERY = $03              ; a step every 4 frames
STATUS_STEPS = 8

; The lines, down the screen.
LINE_STICK    = 0
LINE_FIRMWARE = 1
LINE_BOARD    = 2
LINE_WIFI     = 3
LINE_NETWORK  = 4
LINE_ADDRESS  = 5
LINE_SIGNAL   = 6
LINE_BATTERY  = 7

; The menu, under the lines.
MENU_ROW    = BODY_ROW + 9
MENU_COLUMN = LEFT + 2          ; after the arrow
MENU_FLIP   = 3
MENU_QUIT   = 4                 ; the last, and only on the cartridge

; The cartridge's reset stub (nes/cart/gen_cart.py) is at the same place in
; every program's bank: an `inc` of itself, which resets the mapper and puts
; the menu's bank at $C000, and a jump to the menu. Built by itself, this
; ROM has padding there.
CART_STUB   = $FFDA
CART_STUB_FIRST = $EE           ; inc absolute

.segment "ZEROPAGE"
menu_item:     .res 1           ; where the arrow is
menu_items:    .res 1           ; how many there are: Quit is on the cartridge alone
flipping:      .res 1           ; FLIP_*: how far turning the screen has got
status_step:   .res 1
hello_status:  .res 1           ; what the Stick said to the last hello
; SYS STATUS, as it came: Wi-Fi state, signal, address (4), battery, events.
stick_status:  .res 8
STICK_WIFI    = stick_status
STICK_SIGNAL  = stick_status + 1
STICK_ADDRESS = stick_status + 2
STICK_BATTERY = stick_status + 6

.segment "RODATA"
status_screen:
    text  HEADING_ROW, LEFT, "STATUS"
    label BODY_ROW + LINE_STICK, LEFT, "NESP32"
    label BODY_ROW + LINE_FIRMWARE, LEFT, "FIRMWARE"
    label BODY_ROW + LINE_BOARD, LEFT, "BOARD"
    label BODY_ROW + LINE_WIFI, LEFT, "WI-FI"
    label BODY_ROW + LINE_NETWORK, LEFT, "NETWORK"
    label BODY_ROW + LINE_ADDRESS, LEFT, "ADDRESS"
    label BODY_ROW + LINE_SIGNAL, LEFT, "SIGNAL"
    label BODY_ROW + LINE_BATTERY, LEFT, "BATTERY"
    text  MENU_ROW, MENU_COLUMN, "WI-FI SETUP"
    text  MENU_ROW + 1, MENU_COLUMN, "TEST INTERFACE"
    text  MENU_ROW + 2, MENU_COLUMN, "ENABLE USB DRIVE"
    text  MENU_ROW + MENU_FLIP, MENU_COLUMN, "FLIP LCD"
    text  HELP_ROW, LEFT, "UP/DOWN:MOVE  A:CHOOSE"
    .byte 0

; Which line each step of the round writes, and what works it out.
step_line:
    .byte LINE_STICK, LINE_WIFI, LINE_ADDRESS, LINE_SIGNAL
    .byte LINE_BATTERY, LINE_FIRMWARE, LINE_BOARD, LINE_NETWORK
step_lo:
    .lobytes step_hello - 1, step_wifi - 1, step_address - 1, step_signal - 1
    .lobytes step_battery - 1, step_firmware - 1, step_board - 1, step_network - 1
step_hi:
    .hibytes step_hello - 1, step_wifi - 1, step_address - 1, step_signal - 1
    .hibytes step_battery - 1, step_firmware - 1, step_board - 1, step_network - 1

value_lo:
.repeat 8, line
    .byte <($2000 + 32 * (BODY_ROW + line) + VALUE_COLUMN)
.endrepeat
value_hi:
.repeat 8, line
    .byte >($2000 + 32 * (BODY_ROW + line) + VALUE_COLUMN)
.endrepeat

stick_found:   .byte "CONNECTED", 0
stick_missing: .byte "NOT FOUND", 0
stick_old:     .byte "NEEDS AN UPDATE", 0
none_text:     .byte "-", 0
dbm_text:      .byte " DBM", 0

quit_text:     .byte "QUIT", 0

wifi_texts_lo: .lobytes wifi_none, wifi_idle, wifi_joining, wifi_joined, wifi_failed
wifi_texts_hi: .hibytes wifi_none, wifi_idle, wifi_joining, wifi_joined, wifi_failed
wifi_none:     .byte "NOT SET UP", 0
wifi_idle:     .byte "NOT JOINED", 0
wifi_joining:  .byte "JOINING...", 0
wifi_joined:   .byte "JOINED", 0
wifi_failed:   .byte "COULD NOT JOIN", 0

.segment "CODE"

.proc open_status
    lda #<status_screen
    ldx #>status_screen
    jsr show_screen
    lda #STATE_STATUS
    sta state
    lda #STATUS_STEPS - 1       ; the round begins with the hello
    sta status_step
    lda #0
    sta menu_item
    sta flipping
    lda #MENU_QUIT
    sta menu_items
    lda CART_STUB
    cmp #CART_STUB_FIRST
    bne menu_arrow
    inc menu_items              ; on the cartridge: Quit too, from the next frame
    point quit_text
    ldx #0
    jsr put_text
    at MENU_ROW + MENU_QUIT, MENU_COLUMN
    stx draw_len
    ; fall through
.endproc

; The arrow, at the menu's item.
.proc menu_arrow
    lda menu_item
    asl a
    asl a
    asl a
    clc
    adc #8 * MENU_ROW
    tay
    ldx #LIST_ARROW_X
    lda #TILE_ARROW
    jmp cursor_at
.endproc

.proc status_frame
    lda flipping                ; turning the screen has this frame's request
    beq @round
    jsr flip_step
    jmp @input
@round:
    lda frame_count
    and #STATUS_EVERY
    bne @input
    lda draw_len
    bne @input
    ldx status_step
    inx
    cpx #STATUS_STEPS
    bcc @step
    ldx #0
@step:
    stx status_step
    jsr do_step                 ; leaves X characters in draw_buf
    ldy status_step
    lda step_line,y
    tay
    lda value_lo,y
    sta draw_addr
    lda value_hi,y
    sta draw_addr + 1
    ldy #VALUE_WIDTH
    jsr stage_pad
@input:
    lda pad_new
    and #PAD_UP
    beq @down
    lda menu_item
    beq @down
    dec menu_item
    jsr menu_arrow
@down:
    lda pad_new
    and #PAD_DOWN
    beq @choose
    ldx menu_item
    inx
    cpx menu_items
    bcs @choose
    stx menu_item
    jsr menu_arrow
@choose:
    lda pad_new
    and #PAD_A
    beq @done
    ldx menu_item
    cpx #MENU_QUIT
    beq quit                    ; which needs no nesp32
    lda linked                  ; everything else does
    beq @done
    cpx #MENU_FLIP
    beq @flip
    txa
    beq @wifi
    dex
    beq @test
    jmp open_usb
@wifi:
    jmp open_scan
@test:
    jmp open_test
@flip:
    lda flipping                ; a press while one is under way is not another
    bne @done
    lda #FLIP_ASK
    sta flipping
@done:
    rts
.endproc

; Back to the cartridge's menu, as reset would go: through its stub, with
; the NMI off first, since the stub's `inc` puts the menu's bank, and its
; NMI, under this. The menu says nothing to the nesp32; the next program's
; hello is what tells it this one has gone.
.proc quit
    lda #0
    sta PPUCTRL
    sta ctrl
    jmp CART_STUB
.endproc

; Turning the nesp32's screen the other way up: a frame to ask which way up
; it is, and the next to turn it.
FLIP_NONE = 0
FLIP_ASK  = 1
FLIP_TURN = 2

.proc flip_step
    ldx #NESP_TURN_ASK
    lda flipping
    cmp #FLIP_ASK
    beq @ask
    ldx #NESP_TURN_FLIPPED
    lda nesp_reply
    cmp #NESP_SCREEN_FLIPPED
    bne @ask
    ldx #NESP_TURN_UPRIGHT
@ask:
    stx nesp_request
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_SCREEN
    ldy #1
    jsr call
    bcs @failed
    lda nesp_status
    and #NESP_ST_ERROR
    bne @over                   ; a firmware older than this op says NO_OP
    lda nesp_reply
    beq @over                   ; NESP_SCREEN_NONE: nothing to turn
    lda flipping
    cmp #FLIP_ASK
    bne @over                   ; turned: the nesp32's screen says so itself
    lda #FLIP_TURN
    sta flipping
    rts
@failed:
    lda linked
    beq @over                   ; the status lines say so
    say no_answer_text
@over:
    lda #FLIP_NONE
    sta flipping
    rts
.endproc

; One step: its line's text into draw_buf, X characters of it. Without a
; Stick every line but the first is a dash.
.proc do_step
    ldx status_step
    beq @go
    lda linked
    bne @go
    jmp put_none
@go:
    lda step_hi,x
    pha
    lda step_lo,x
    pha
    rts
.endproc

.proc put_none
    point none_text
    ldx #0
    jmp put_text
.endproc

; Say hello, if the Stick has not answered one. This ROM needs NET and DIAG.
.proc step_hello
    lda linked
    bne @found
    lda #NESP_SVC_NET
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_DIAG
    sta nesp_request + NESP_HELLO_FIXED + 1
    ldy #2
    jsr nesp_hello
    bcs @missing
    sta hello_status
    cmp #NESP_ST_OK
    bne @old
    lda #1
    sta linked
    lda #0
    sta misses
@found:
    point stick_found
    ldx #0
    jmp put_text
@old:                           ; another protocol, or a service it lacks
    point stick_old
    ldx #0
    jmp put_text
@missing:
    point stick_missing
    ldx #0
    jmp put_text
.endproc

; Ask how the Stick is, for this line and the three after it.
.proc step_wifi
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_STATUS
    ldy #0
    jsr call
    bcs @none
    ldx #7
@copy:
    lda nesp_reply,x
    sta stick_status,x
    dex
    bpl @copy
    ldx STICK_WIFI
    cpx #NESP_WIFI_FAILED + 1
    bcs @none
    lda wifi_texts_lo,x
    sta ptr
    lda wifi_texts_hi,x
    sta ptr + 1
    ldx #0
    jmp put_text
@none:
    jmp put_none
.endproc

.proc step_address
    lda STICK_WIFI
    cmp #NESP_WIFI_JOINED
    bne @none
    ldx #0
    ldy #0
@part:
    sty ptr                     ; put_dec uses Y
    lda STICK_ADDRESS,y
    jsr put_dec
    ldy ptr
    iny
    cpy #4
    beq @done
    lda #'.'
    sta draw_buf,x
    inx
    bne @part
@done:
    rts
@none:
    jmp put_none
.endproc

; The signal is a negative number of dBm.
.proc step_signal
    lda STICK_WIFI
    cmp #NESP_WIFI_JOINED
    bne @none
    lda STICK_SIGNAL
    bpl @none
    ldx #0
    lda #'-'
    sta draw_buf,x
    inx
    lda #0
    sec
    sbc STICK_SIGNAL
    jsr put_dec
    point dbm_text
    jmp put_text
@none:
    jmp put_none
.endproc

.proc step_battery
    lda STICK_BATTERY
    cmp #101
    bcs @none
    ldx #0
    jsr put_dec
    lda #'%'
    sta draw_buf,x
    inx
    rts
@none:
    jmp put_none
.endproc

.proc step_firmware
    lda #NESP_INFO_FIRMWARE
    jmp put_info
.endproc

.proc step_board
    lda #NESP_INFO_BOARD
    jmp put_info
.endproc

.proc step_network
    lda #NESP_INFO_NETWORK
    ; fall through
.endproc

; One of the Stick's strings, A, as the line's text.
.proc put_info
    sta nesp_request
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_INFO
    ldy #1
    jsr call
    bcs @none
    lda nesp_status
    bne @none
    ldy nesp_reply_len
    beq @none
    cpy #VALUE_WIDTH + 1
    bcc @fits
    ldy #VALUE_WIDTH
@fits:
    point nesp_reply
    ldx #0
    jmp put_bytes
@none:
    jmp put_none
.endproc

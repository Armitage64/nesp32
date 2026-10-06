; The status screen: what the Stick is and how it is. The first screen, and
; the one every other comes back to.
;
;   A    set up Wi-Fi
;   B    test the link
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

.segment "ZEROPAGE"
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
    label BODY_ROW + LINE_STICK, LEFT, "STICK"
    label BODY_ROW + LINE_FIRMWARE, LEFT, "FIRMWARE"
    label BODY_ROW + LINE_BOARD, LEFT, "BOARD"
    label BODY_ROW + LINE_WIFI, LEFT, "WI-FI"
    label BODY_ROW + LINE_NETWORK, LEFT, "NETWORK"
    label BODY_ROW + LINE_ADDRESS, LEFT, "ADDRESS"
    label BODY_ROW + LINE_SIGNAL, LEFT, "SIGNAL"
    label BODY_ROW + LINE_BATTERY, LEFT, "BATTERY"
    text  HELP_ROW, LEFT, "A:WI-FI SETUP   B:LINK TEST"
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
    rts
.endproc

.proc status_frame
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
    lda linked
    beq @done
    lda pad_new
    and #PAD_A
    beq @test
    jmp open_scan
@test:
    lda pad_new
    and #PAD_B
    beq @done
    jmp open_test
@done:
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

; The Bluetooth keyboard: pair one with the nesp32, forget it, and try it.
;
;   Up, Down move the arrow: pair a keyboard, or forget the one paired
;   A        do it; pairing looks for keyboards in their pairing mode and
;            lists them
;   B        back
;
; and on the list of what was found:
;
;   Up, Down move the arrow
;   A        pair with that one, in place of the one paired
;   B        back, pairing none
;
; Coming to this screen says hello with KBD besides NET and DIAG
; (docs/PROTOCOL.md), which turns the nesp32's Bluetooth on: the keyboard
; paired is connected when a key is pressed on it. Going back has the
; status screen say hello again without KBD, which turns Bluetooth off.
;
; Every 16th frame asks how the keyboard stands, and every other frame
; what has been typed on it, which the line under TRY IT shows: Backspace
; takes a character back, Enter and Escape clear the line.

KBD_HELLO_EVERY = $07           ; say hello every 8 frames until answered
KBD_STATE_EVERY = $0F           ; ask how the keyboard stands every 16 frames
KBD_UNKNOWN = $FF

KBD_GREETED = 1                 ; kbd_greeted: the hello was answered
KBD_OLD     = 2                 ; and the nesp32 has no KBD

ASK_SCAN   = 1                  ; kbd_asking: an order to send
ASK_FORGET = 2

; The menu, under the line of what is typed (KBD_MENU_ROW).
KBD_MENU_PAIR   = 0
KBD_MENU_FORGET = 1
KBD_MENU_ITEMS  = 2

DIRTY_NAME  = $01               ; kbd_dirty: what is to be drawn
DIRTY_STATE = $02
DIRTY_ECHO  = $04

.segment "BSS"
kbd_greeted: .res 1
kbd_state:   .res 1             ; what the nesp32 last said (enum KEYBOARD)
kbd_dirty:   .res 1
kbd_asking:  .res 1
kbd_looking: .res 1             ; a scan was asked for: the list comes when it is over
kbd_pairing: .res 1             ; a pairing was asked for: its end is said
kbd_count:   .res 1             ; keyboards the scan found
kbd_cur:     .res 1             ; the one the arrow is at
kbd_item:    .res 1             ; the menu's item the arrow is at
kbd_fill:    .res 1             ; the next line of the list to draw
kbd_picking: .res 1             ; A was pressed on the list: PAIR goes out
kbd_name_len: .res 1
kbd_name:    .res NESP_KBD_NAME_MAX
kbd_echo_len: .res 1
kbd_echo:    .res WIDTH - 1     ; what was typed, and room for the cursor after it

.segment "RODATA"
kbd_screen:
    text  HEADING_ROW, LEFT, "BLUETOOTH KEYBOARD"
    label BODY_ROW, LEFT, "KEYBOARD"
    label BODY_ROW + 1, LEFT, "STATUS"
    label KBD_ECHO_ROW - 1, LEFT, "TRY IT"
    text  KBD_MENU_ROW + KBD_MENU_PAIR, MENU_COLUMN, "PAIR A KEYBOARD"
    text  KBD_MENU_ROW + KBD_MENU_FORGET, MENU_COLUMN, "FORGET THE KEYBOARD"
    text  KBD_MENU_ROW + 3, LEFT, "PUT THE KEYBOARD IN ITS"
    text  KBD_MENU_ROW + 4, LEFT, "PAIRING MODE FIRST."
    text  HELP_ROW, LEFT, "A : CHOOSE   B : BACK"
    .byte 0

kbd_list_screen:
    text  HEADING_ROW, LEFT, "CHOOSE A KEYBOARD"
    text  HELP_ROW, LEFT, "A : PAIR   B : BACK"
    .byte 0

; How the keyboard stands, by the state (enum KEYBOARD).
kbd_texts_lo:
    .lobytes kbd_none, kbd_off, kbd_unpaired, kbd_waiting, kbd_connected
    .lobytes kbd_scanning, kbd_scanned, kbd_pairing_text, kbd_failed
kbd_texts_hi:
    .hibytes kbd_none, kbd_off, kbd_unpaired, kbd_waiting, kbd_connected
    .hibytes kbd_scanning, kbd_scanned, kbd_pairing_text, kbd_failed
KBD_TEXTS = * - kbd_texts_hi
.assert KBD_TEXTS = NESP_KEYBOARD_FAILED + 1, error, "a text for every state"
kbd_none:      .byte "NO BLUETOOTH", 0
kbd_off:       .byte "STARTING...", 0
kbd_unpaired:  .byte "NONE PAIRED", 0
kbd_waiting:   .byte "PRESS A KEY ON IT", 0
kbd_connected: .byte "CONNECTED", 0
kbd_scanning:  .byte "LOOKING...", 0
kbd_scanned:   .byte "LOOKED FOR ONE", 0
kbd_pairing_text: .byte "PAIRING...", 0
kbd_failed:    .byte "PAIRING FAILED", 0

kbd_update_text:  .byte "THE NESP32 NEEDS AN UPDATE", 0
kbd_no_bt_text:   .byte "THIS BOARD HAS NO BLUETOOTH", 0
kbd_looking_text: .byte "LOOKING FOR KEYBOARDS...", 0
kbd_none_found:   .byte "NO KEYBOARD FOUND", 0
kbd_paired_text:  .byte "THE KEYBOARD IS PAIRED", 0
kbd_refused_text: .byte "THE PAIRING FAILED", 0
kbd_forgot_text:  .byte "THE KEYBOARD IS FORGOTTEN", 0
kbd_nothing_text: .byte "NO KEYBOARD IS PAIRED", 0

.segment "CODE"

.proc open_kbd
    lda #0
    sta kbd_greeted
    sta kbd_echo_len
    sta kbd_name_len
    sta kbd_looking
    sta kbd_pairing
    sta kbd_item
    ; fall through
.endproc

; The keyboard's screen, from the list too: the hello is as it was.
.proc show_kbd
    lda #<kbd_screen
    ldx #>kbd_screen
    jsr show_screen
    lda #KBD_UNKNOWN
    sta kbd_state
    lda #DIRTY_NAME | DIRTY_STATE | DIRTY_ECHO
    sta kbd_dirty
    lda #0
    sta kbd_asking
    lda #STATE_KBD
    sta state
    ; fall through
.endproc

; The arrow, at the menu's item.
.proc kbd_arrow
    lda kbd_item
    asl a
    asl a
    asl a
    clc
    adc #8 * KBD_MENU_ROW
    tay
    ldx #LIST_ARROW_X
    lda #TILE_ARROW
    jmp cursor_at
.endproc

.proc kbd_frame
    lda pad_new
    and #PAD_B
    beq @greet
    lda #0                      ; the status screen's hello, without KBD
    sta linked
    jmp open_status
@greet:
    lda kbd_greeted
    bne @greeted
    lda frame_count
    and #KBD_HELLO_EVERY
    bne @draw
    jsr kbd_hello
    jmp @draw
@greeted:
    cmp #KBD_OLD
    beq @draw                   ; only B does anything
    jsr kbd_input
    jsr kbd_ask
    lda state                   ; the list, or the status screen if the Stick went
    cmp #STATE_KBD
    beq @draw
    rts
@draw:
    jmp kbd_draw
.endproc

; Hello, with KBD. A nesp32 without it says so, and is used for nothing
; here.
.proc kbd_hello
    lda #NESP_SVC_NET
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_DIAG
    sta nesp_request + NESP_HELLO_FIXED + 1
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED + 2
    ldy #3
    jsr nesp_hello
    bcs @silent
    cmp #NESP_ST_OK
    bne @old
    lda #KBD_GREETED
    sta kbd_greeted
    lda #0
    sta misses
@silent:
    rts
@old:
    lda #KBD_OLD
    sta kbd_greeted
    say kbd_update_text
    rts
.endproc

.proc kbd_input
    lda pad_new
    and #PAD_UP
    beq @down
    lda kbd_item
    beq @down
    dec kbd_item
    jsr kbd_arrow
@down:
    lda pad_new
    and #PAD_DOWN
    beq @choose
    ldx kbd_item
    inx
    cpx #KBD_MENU_ITEMS
    bcs @choose
    stx kbd_item
    jsr kbd_arrow
@choose:
    lda pad_new
    and #PAD_A
    beq @done
    lda kbd_state
    cmp #NESP_KEYBOARD_NONE
    beq @no_bt
    lda kbd_item
    cmp #KBD_MENU_FORGET
    beq @forget
    lda #ASK_SCAN
    sta kbd_asking
    say kbd_looking_text
@done:
    rts
@no_bt:
    say kbd_no_bt_text
    rts
@forget:
    lda kbd_name_len
    beq @nothing
    lda #ASK_FORGET
    sta kbd_asking
    rts
@nothing:
    say kbd_nothing_text
    rts
.endproc

; This frame's request: an order, if one is to go, and otherwise how the
; keyboard stands or what has been typed.
.proc kbd_ask
    lda kbd_asking
    beq @poll
    cmp #ASK_SCAN
    bne @forget
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_SCAN
    ldy #0
    jsr call
    bcs @done                   ; no answer: again next frame
    lda nesp_status
    cmp #NESP_ST_BUSY
    beq @done
    lda #0
    sta kbd_asking
    lda nesp_status
    bne @refused
    lda #1
    sta kbd_looking
    rts
@refused:                       ; a firmware with KBD and no Bluetooth
    say kbd_no_bt_text
    rts
@forget:
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_FORGET
    ldy #0
    jsr call
    bcs @done
    lda #0
    sta kbd_asking
    lda nesp_status
    bne @done
    say kbd_forgot_text
    rts
@poll:
    lda frame_count
    and #KBD_STATE_EVERY
    bne @keys
    jmp kbd_status
@keys:
    lda frame_count
    lsr a
    bcc @done
    jmp kbd_keys
@done:
    rts
.endproc

; How the keyboard stands, and the end of a scan or a pairing.
.proc kbd_status
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_STATE
    ldy #0
    jsr call
    bcs @silent
    lda nesp_status
    beq @heard
@silent:
    rts
@heard:
    ; The name, drawn again if it is not the one shown.
    ldy nesp_reply + 2
    cpy #NESP_KBD_NAME_MAX + 1
    bcc @fits
    ldy #NESP_KBD_NAME_MAX
@fits:
    sty tmp
    cpy kbd_name_len
    bne @new_name
@compare:
    dey
    bmi @name_done
    lda nesp_reply + 3,y
    cmp kbd_name,y
    beq @compare
@new_name:
    ldy tmp
    sty kbd_name_len
@copy:
    dey
    bmi @name_dirty
    lda nesp_reply + 3,y
    sta kbd_name,y
    jmp @copy
@name_dirty:
    lda kbd_dirty
    ora #DIRTY_NAME
    sta kbd_dirty
@name_done:
    lda nesp_reply
    cmp kbd_state
    beq @state_done
    sta kbd_state
    lda kbd_dirty
    ora #DIRTY_STATE
    sta kbd_dirty
@state_done:
    lda kbd_looking
    beq @pairing
    lda kbd_state
    cmp #NESP_KEYBOARD_SCANNED
    bne @done
    lda #0
    sta kbd_looking
    lda nesp_reply + 1
    bne @list
    say kbd_none_found
    rts
@list:
    cmp #NESP_KBD_FOUND_MAX + 1
    bcc @count
    lda #NESP_KBD_FOUND_MAX
@count:
    sta kbd_count
    jmp open_kbd_list
@pairing:
    lda kbd_pairing
    beq @done
    lda kbd_state
    cmp #NESP_KEYBOARD_CONNECTED
    beq @paired
    cmp #NESP_KEYBOARD_FAILED
    bne @done
    lda #0
    sta kbd_pairing
    say kbd_refused_text
    rts
@paired:
    lda #0
    sta kbd_pairing
    say kbd_paired_text
@done:
    rts
.endproc

; What has been typed, onto the line under TRY IT.
.proc kbd_keys
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr call
    bcs @done
    lda nesp_status
    bne @done
    ldx #0
@key:
    cpx nesp_reply
    bcs @done
    lda nesp_reply + 1,x
    jsr kbd_typed
    inx
    bne @key
@done:
    rts
.endproc

; One character typed, A. A printable one goes on the line, which moves
; left when it is full. Preserves X.
.proc kbd_typed
    cmp #NESP_KEY_BACKSPACE
    bne @clear
    lda kbd_echo_len
    beq @done
    dec kbd_echo_len
    jmp @dirty
@clear:
    cmp #NESP_KEY_ENTER
    beq @empty
    cmp #NESP_KEY_ESCAPE
    bne @char
@empty:
    lda #0
    sta kbd_echo_len
    beq @dirty
@char:
    cmp #' '
    bcc @done
    cmp #$7F
    bcs @done
    ldy kbd_echo_len
    cpy #WIDTH - 1
    bcc @put
    pha                         ; full: everything one place left
    ldy #0
@shift:
    lda kbd_echo + 1,y
    sta kbd_echo,y
    iny
    cpy #WIDTH - 2
    bcc @shift
    pla
@put:
    sta kbd_echo,y
    iny
    sty kbd_echo_len
@dirty:
    lda kbd_dirty
    ora #DIRTY_ECHO
    sta kbd_dirty
@done:
    rts
.endproc

; Stage the first of what is to be drawn, if nothing else is staged.
.proc kbd_draw
    lda draw_len
    bne @done
    lda kbd_dirty
    lsr a
    bcs @name
    lsr a
    bcs @state
    lsr a
    bcs @echo
@done:
    rts
@name:
    lda kbd_dirty
    and #<~DIRTY_NAME
    sta kbd_dirty
    at BODY_ROW, VALUE_COLUMN
    ldy kbd_name_len
    beq @none
    cpy #VALUE_WIDTH + 1
    bcc @name_fits
    ldy #VALUE_WIDTH
@name_fits:
    point kbd_name
    ldx #0
    jsr put_bytes
    ldy #VALUE_WIDTH
    jmp stage_pad
@none:
    point none_text
    ldx #0
    jsr put_text
    ldy #VALUE_WIDTH
    jmp stage_pad
@state:
    lda kbd_dirty
    and #<~DIRTY_STATE
    sta kbd_dirty
    at BODY_ROW + 1, VALUE_COLUMN
    ldx kbd_state
    cpx #KBD_TEXTS
    bcs @unknown
    lda kbd_texts_lo,x
    sta ptr
    lda kbd_texts_hi,x
    sta ptr + 1
    ldx #0
    jsr put_text
    ldy #VALUE_WIDTH
    jmp stage_pad
@unknown:
    point none_text
    ldx #0
    jsr put_text
    ldy #VALUE_WIDTH
    jmp stage_pad
@echo:
    lda kbd_dirty
    and #<~DIRTY_ECHO
    sta kbd_dirty
    at KBD_ECHO_ROW, LEFT
    point kbd_echo
    ldy kbd_echo_len
    ldx #0
    jsr put_bytes
    lda #CURSOR_CHAR
    sta draw_buf,x
    inx
    ldy #WIDTH
    jmp stage_pad
.endproc

; --- the list ----------------------------------------------------------------------

.proc open_kbd_list
    lda #<kbd_list_screen
    ldx #>kbd_list_screen
    jsr show_screen
    lda #0
    sta kbd_cur
    sta kbd_fill
    sta kbd_picking
    lda #STATE_KBD_LIST
    sta state
    rts
.endproc

.proc kbd_list_frame
    lda kbd_picking
    beq @fill
    jmp kbd_pick
@fill:
    lda kbd_fill                ; the link first, while the frame is young
    cmp kbd_count
    bcs @input
    lda draw_len
    bne @input
    jsr kbd_fill_line
    lda state                   ; the Stick may have gone
    cmp #STATE_KBD_LIST
    beq @input
    rts
@input:
    lda pad_new
    and #PAD_UP
    beq @down
    lda kbd_cur
    beq @down
    dec kbd_cur
@down:
    lda pad_new
    and #PAD_DOWN
    beq @choose
    ldx kbd_cur
    inx
    cpx kbd_count
    bcs @choose
    stx kbd_cur
@choose:
    lda pad_new
    and #PAD_A
    beq @back
    lda #1
    sta kbd_picking
@back:
    lda pad_new
    and #PAD_B
    beq @arrow
    jmp show_kbd
@arrow:
    lda kbd_cur
    asl a
    asl a
    asl a
    clc
    adc #8 * LIST_ROW
    tay
    ldx #LIST_ARROW_X
    lda #TILE_ARROW
    jmp cursor_at
.endproc

; Draw the list's next line: ask the Stick for the keyboard that goes
; there. A request that is not answered leaves the line for the next frame.
.proc kbd_fill_line
    lda kbd_fill
    sta nesp_request
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_FOUND
    ldy #1
    jsr call
    bcs @wait
    lda nesp_status
    bne @blank                  ; the Stick no longer has it
    lda nesp_reply
    cmp nesp_request
    bne @wait
    ldy nesp_reply + 2          ; the name, or as much as fits
    cpy #LIST_NAME + 1
    bcc @name
    ldy #LIST_NAME
@name:
    point nesp_reply + 3
    ldx #0
    jsr put_bytes
    lda #' '
@pad:
    cpx #LIST_WIDTH
    bcs @bars
    sta draw_buf,x
    inx
    bne @pad
@bars:
    lda nesp_reply + 1
    jsr signal_bars
    stx draw_buf + LIST_NAME + 3
    ldx #LIST_WIDTH
    bne @stage
@blank:
    ldx #0
@stage:
    ldy kbd_fill
    lda list_lo,y
    sta draw_addr
    lda list_hi,y
    sta draw_addr + 1
    ldy #LIST_WIDTH
    jsr stage_pad
    inc kbd_fill
@wait:
    rts
.endproc

; A was pressed on a keyboard: pair with it, and say how that goes on the
; keyboard's screen. A request that is not answered goes again next frame.
.proc kbd_pick
    lda kbd_cur
    sta nesp_request
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_PAIR
    ldy #1
    jsr call
    bcs @wait
    lda #0
    sta kbd_picking
    lda nesp_status
    pha
    jsr show_kbd
    pla
    bne @refused
    lda #1
    sta kbd_pairing
    say kbd_pairing_text
    rts
@refused:                       ; what the scan found is gone
    say kbd_refused_text
@wait:
    rts
.endproc

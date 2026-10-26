; The USB drive: the nesp32's files, lent to a computer for music to be
; copied to.
;
;   B    back: the nesp32 takes its files back, which it does by restarting
;
; Coming to this screen asks the nesp32 to become a drive (SYS DRIVE,
; docs/PROTOCOL.md), and every so often after that it is asked how that
; stands, which the message line says. The nesp32 stops being a drive by
; restarting, told to by B here or by the computer's ejecting it, and this
; ROM finds that out by its saying, once it is back, that it is no drive:
; the status screen comes back then, and says hello again.
;
; A nesp32 that does not answer is not taken to have gone. While a computer
; writes to it, it is deaf for as long as each piece of its flash takes to
; erase, and may miss several requests in a row.

USB_EVERY = $0F                 ; ask every 16 frames
USB_UNKNOWN = $FF

.segment "ZEROPAGE"
usb_lend:  .res 1               ; what is asked next: to start, and then only how it is
usb_state: .res 1               ; what the nesp32 last said

.segment "RODATA"
usb_screen:
    text  HEADING_ROW, LEFT, "USB DRIVE"
    text  BODY_ROW, LEFT, "CONNECT THE NESP32 TO A"
    text  BODY_ROW + 1, LEFT, "COMPUTER AND COPY VGM/VGZ"
    text  BODY_ROW + 2, LEFT, "AND PCM FILES INTO THE"
    text  BODY_ROW + 3, LEFT, "TRACKS DIR."
    text  BODY_ROW + 5, LEFT, "WHEN DONE, EJECT THE DRIVE."
    text  BODY_ROW + 6, LEFT, "THE NESP32 WILL RESTART AND"
    text  BODY_ROW + 7, LEFT, "CONVERT THE FILES INTO THE"
    text  BODY_ROW + 8, LEFT, "STREAMING FORMAT."
    text  HELP_ROW, LEFT, "B : BACK"
    .byte 0

; What the message line says of each state (enum DRIVE).
usb_texts_lo: .lobytes usb_none, usb_off, usb_waiting, usb_mounted, usb_ejected
usb_texts_hi: .hibytes usb_none, usb_off, usb_waiting, usb_mounted, usb_ejected
usb_none:    .byte "THIS BOARD CANNOT BE A DRIVE", 0
usb_off:     .byte "STARTING...", 0
usb_waiting: .byte "WAITING FOR A COMPUTER", 0
usb_mounted: .byte "THE USB DRIVE IS MOUNTED", 0
usb_ejected: .byte "EJECTED. RESTARTING...", 0

.segment "CODE"

.proc open_usb
    lda #<usb_screen
    ldx #>usb_screen
    jsr show_screen
    lda #NESP_LEND_START
    sta usb_lend
    lda #USB_UNKNOWN
    sta usb_state
    lda #STATE_USB
    sta state
    rts
.endproc

; SYS DRIVE, asking A of it. Carry and A as `call` leaves them.
.proc usb_ask
    sta nesp_request
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_DRIVE
    ldy #1
    jmp call
.endproc

.proc usb_frame
    lda pad_new
    and #PAD_B
    beq @poll
    lda #NESP_LEND_STOP         ; said once: heard or not, it is back to the status
    jsr usb_ask
    jmp open_status
@poll:
    lda frame_count
    and #USB_EVERY
    bne @done
    lda usb_lend
    jsr usb_ask
    bcs @silent
    ldx #NESP_DRIVE_NONE        ; a firmware from before there was such a thing
    lda nesp_status
    bne @known
    ldx nesp_reply
    cpx #NESP_DRIVE_EJECTED + 1
    bcs @done
@known:
    cpx #NESP_DRIVE_OFF
    bne @show
    lda usb_lend                ; off, and it had been started: it has restarted
    cmp #NESP_LEND_ASK
    beq @over
@show:
    lda #NESP_LEND_ASK
    sta usb_lend
    cpx usb_state
    beq @done
    stx usb_state
    lda usb_texts_lo,x
    sta message_ptr
    lda usb_texts_hi,x
    sta message_ptr + 1
    lda #1
    sta message_new
@done:
    rts
@silent:                        ; busy with its flash, or restarting: ask again
    rts
@over:
    jmp open_status
.endproc

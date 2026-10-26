; Wi-Fi setup: look for networks, choose one, type its password (keys.inc),
; hand both to the Stick, and wait to hear how the join went.
;
;   scan      the Stick is looking; this asks it how that is going
;   list      the networks it found, strongest first, and OTHER NETWORK for
;             one that does not say its name. Up and Down move, A chooses,
;             Start looks again, B goes back
;   send      the name and the password go to the Stick in pieces, then JOIN
;   joining   the Stick is trying; this asks it how that is going
;   failed    it did not work, and why. A tries another password, B another
;             network
;
; The console holds no list. A line is asked for when it is to be drawn,
; and the network chosen is asked for once more, for the whole of its name.

SCAN_EVERY   = $07              ; ask how a scan is going every 8 frames
SCAN_POLLS   = 150              ; and give up after 20 seconds
JOIN_EVERY   = $0F              ; ask how a join is going every 16 frames
JOIN_POLLS   = 170              ; and give up after 45 seconds
PIECE        = 16               ; bytes of a name or a password in one request
SEND_FAILS   = 120              ; frames with no answer before giving up
SEND_RESTARTS = 3
PICK_TRIES   = 30

SEND_NAME     = 0
SEND_PASSWORD = 1
SEND_JOIN     = 2

.segment "ZEROPAGE"
scan_started: .res 1
net_count:    .res 1            ; networks the scan found
list_top:     .res 1            ; the entry on the list's first line
list_cur:     .res 1            ; the entry the arrow is at; net_count is OTHER
list_fill:    .res 1            ; the next line to draw; LIST_ROWS when all are
picking:      .res 1            ; A was pressed: asking for the network's name
tries:        .res 1
net_name_len: .res 1
net_pass_len: .res 1
net_auth:     .res 1
send_phase:   .res 1
send_off:     .res 1
send_count:   .res 1            ; bytes in the piece that is out
send_retry:   .res 1            ; the last request got no answer: send it again
send_restarts: .res 1

.segment "BSS"
net_name:     .res NESP_NAME_MAX
net_pass:     .res NESP_PASSWORD_MAX

.segment "RODATA"
scan_screen:
    text  HEADING_ROW, LEFT, "CHOOSE A NETWORK"
    text  HELP_ROW, LEFT, "B : BACK"
    .byte 0

list_screen:
    text  HEADING_ROW, LEFT, "CHOOSE A NETWORK"
    text  HELP_ROW, LEFT, "A : CHOOSE   B : BACK"
    text  HELP_ROW + 1, LEFT, "START : LOOK AGAIN"
    .byte 0

join_screen:
    text  HEADING_ROW, LEFT, "JOINING"
    .byte 0

list_lo:
.repeat LIST_ROWS, line
    .byte <($2000 + 32 * (LIST_ROW + line) + LIST_COLUMN)
.endrepeat
list_hi:
.repeat LIST_ROWS, line
    .byte >($2000 + 32 * (LIST_ROW + line) + LIST_COLUMN)
.endrepeat

looking_text:   .byte "LOOKING FOR NETWORKS...", 0
other_text:     .byte "OTHER NETWORK...", 0
kind_text:      .byte "CANNOT JOIN THAT KIND", 0
sending_text:   .byte "TELLING THE NESP32...", 0
joining_text:   .byte "JOINING...", 0
refused_text:   .byte "THE NESP32 REFUSED IT", 0
password_text:  .byte "WRONG PASSWORD", 0
no_network_text: .byte "NETWORK NOT FOUND", 0
no_join_text:   .byte "COULD NOT JOIN", 0
failed_help:    .byte "A : TRY AGAIN   B : BACK", 0

.segment "CODE"

; --- scan ----------------------------------------------------------------------

.proc open_scan
    lda #<scan_screen
    ldx #>scan_screen
    jsr show_screen
    say looking_text
    lda #0
    sta scan_started
    sta timer
    lda #STATE_SCAN
    sta state
    rts
.endproc

.proc scan_frame
    lda pad_new
    and #PAD_B
    beq @poll
    jmp open_status
@poll:
    lda frame_count
    and #SCAN_EVERY
    bne @done
    inc timer
    lda timer
    cmp #SCAN_POLLS
    bcc @ask
    jsr open_status
    say no_answer_text
    rts
@ask:
    lda scan_started
    bne @status
    lda #NESP_SVC_NET
    ldx #NESP_NET_SCAN_START
    ldy #0
    jsr call
    bcs @done
    lda nesp_status
    bne @done                   ; busy: ask again
    inc scan_started
@done:
    rts
@status:
    lda #NESP_SVC_NET
    ldx #NESP_NET_SCAN_STATUS
    ldy #0
    jsr call
    bcs @done
    lda nesp_reply
    cmp #NESP_SCAN_RUNNING
    beq @done
    cmp #NESP_SCAN_DONE
    beq @found
    lda #0                      ; it failed, or the Stick forgot: start again
    sta scan_started
    rts
@found:
    lda nesp_reply + 1
    cmp #NESP_SCAN_MAX + 1
    bcc @count
    lda #NESP_SCAN_MAX
@count:
    sta net_count
    lda #0
    sta list_top
    sta list_cur
    ; fall through
.endproc

; The list, with the arrow where it was.
.proc open_list
    lda #<list_screen
    ldx #>list_screen
    jsr show_screen
    lda #0
    sta list_fill
    sta picking
    lda #STATE_LIST
    sta state
    rts
.endproc

; --- list ----------------------------------------------------------------------

.proc list_frame
    lda picking
    beq @fill
    jmp pick
@fill:
    lda list_fill               ; the link first, while the frame is young
    cmp #LIST_ROWS
    bcs @input
    lda draw_len
    bne @input
    jsr fill_line
    lda state                   ; the Stick may have gone
    cmp #STATE_LIST
    beq @input
    rts
@input:
    lda pad_new
    and #PAD_UP
    beq @down
    lda list_cur
    beq @down
    dec list_cur
    lda list_cur
    cmp list_top
    bcs @down
    sta list_top
    lda #0
    sta list_fill
@down:
    lda pad_new
    and #PAD_DOWN
    beq @choose
    lda list_cur
    cmp net_count               ; the last entry is OTHER, at net_count
    bcs @choose
    inc list_cur
    lda list_cur
    sec
    sbc list_top
    cmp #LIST_ROWS
    bcc @choose
    inc list_top
    lda #0
    sta list_fill
@choose:
    lda pad_new
    and #PAD_A
    beq @back
    lda #1
    sta picking
    lda #0
    sta tries
@back:
    lda pad_new
    and #PAD_B
    beq @again
    jmp open_status
@again:
    lda pad_new
    and #PAD_START
    beq @arrow
    jmp open_scan
@arrow:
    lda list_cur
    sec
    sbc list_top
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

; Draw the list's next line: ask the Stick for the network that goes there.
; A request that is not answered leaves the line for the next frame.
.proc fill_line
    lda list_top
    clc
    adc list_fill
    cmp net_count
    beq @other
    bcs @blank
    sta nesp_request
    lda #NESP_SVC_NET
    ldx #NESP_NET_SCAN_RESULT
    ldy #1
    jsr call
    bcs @wait
    lda nesp_status
    bne @blank                  ; the Stick no longer has it
    lda nesp_reply
    cmp nesp_request
    bne @wait
    ldy nesp_reply + 4          ; the name, or as much as fits
    cpy #LIST_NAME + 1
    bcc @name
    ldy #LIST_NAME
@name:
    point nesp_reply + 5
    ldx #0
    jsr put_bytes
    lda #' '
@pad:
    cpx #LIST_WIDTH
    bcs @marks
    sta draw_buf,x
    inx
    bne @pad
@marks:
    lda nesp_reply + 2
    beq @bars                   ; open: no lock
    lda #TILE_LOCK
    sta draw_buf + LIST_NAME + 1
@bars:
    lda nesp_reply + 1          ; dBm, a negative number
    ldx #TILE_BARS4
    cmp #256 - 55
    bcs @strength
    ldx #TILE_BARS3
    cmp #256 - 67
    bcs @strength
    ldx #TILE_BARS2
    cmp #256 - 78
    bcs @strength
    ldx #TILE_BARS1
@strength:
    stx draw_buf + LIST_NAME + 3
    ldx #LIST_WIDTH
    bne @stage
@other:
    point other_text
    ldx #0
    jsr put_text
    jmp @stage
@blank:
    ldx #0
@stage:
    ldy list_fill
    lda list_lo,y
    sta draw_addr
    lda list_hi,y
    sta draw_addr + 1
    ldy #LIST_WIDTH
    jsr stage_pad
    inc list_fill
@wait:
    rts
.endproc

; A was pressed on an entry. For a network, ask for it again: the list
; shows only as much of a name as fits, and the Stick wants all of it.
.proc pick
    lda list_cur
    cmp net_count
    bne @network
    lda #0                      ; OTHER: its name is typed too
    sta net_name_len
    sta net_pass_len
    sta picking
    lda #NESP_AUTH_PASSWORD
    sta net_auth
    lda #KEYS_NAME
    jmp open_keys
@network:
    sta nesp_request
    lda #NESP_SVC_NET
    ldx #NESP_NET_SCAN_RESULT
    ldy #1
    jsr call
    bcs @silent
    lda nesp_status
    bne @silent
    lda nesp_reply
    cmp nesp_request
    bne @silent
    lda nesp_reply + 2
    sta net_auth
    ldx nesp_reply + 4
    cpx #NESP_NAME_MAX + 1
    bcs @silent                 ; no name is that long
    stx net_name_len
    beq @named
@copy:
    lda nesp_reply + 4,x        ; the name follows its length
    sta net_name - 1,x
    dex
    bne @copy
@named:
    lda #0
    sta net_pass_len
    sta picking
    lda net_auth
    beq open_send               ; open: there is no password
    cmp #NESP_AUTH_PASSWORD
    bne @kind
    lda #KEYS_PASSWORD
    jmp open_keys
@kind:
    say kind_text
    rts
@silent:
    lda state                   ; the Stick has gone, and the status screen is up
    cmp #STATE_LIST
    bne @done
    inc tries
    lda tries
    cmp #PICK_TRIES
    bcc @done
    lda #0
    sta picking
    say no_answer_text
@done:
    rts
.endproc

; --- send ----------------------------------------------------------------------

; Hand the Stick net_name and net_pass, and tell it to join.
.proc open_send
    lda #<join_screen
    ldx #>join_screen
    jsr show_screen
    at BODY_ROW, LEFT           ; the network's name, under the heading
    point net_name
    ldx #0
    ldy net_name_len
    cpy #WIDTH + 1
    bcc @name
    ldy #WIDTH
@name:
    jsr put_bytes
    ldy #WIDTH
    jsr stage_pad
    say sending_text
    lda #0
    sta send_restarts
    sta tries
    lda #STATE_SEND
    sta state
    ; fall through
.endproc

.proc send_restart
    lda #SEND_NAME
    sta send_phase
    lda #0
    sta send_off
    sta send_retry
    rts
.endproc

; One request a frame: the next piece, or the last one again if nothing
; came back. The Stick answers a request it has seen with the reply it gave,
; so a piece sent twice is added once.
.proc send_frame
    lda send_retry
    beq @next
    jsr call_again
    jmp @answer
@next:
    lda send_phase
    cmp #SEND_JOIN
    bne @piece
    lda net_name_len
    sta nesp_request
    lda net_pass_len
    sta nesp_request + 1
    lda #NESP_SVC_NET
    ldx #NESP_NET_JOIN
    ldy #2
    jsr call
    jmp @answer
@piece:
    jsr piece
    lda #NESP_SVC_NET
    jsr call
@answer:
    bcc @heard
    lda state                   ; the Stick has gone, and the status screen is up
    cmp #STATE_SEND
    bne @done
    lda #1
    sta send_retry
    inc tries
    lda tries
    cmp #SEND_FAILS
    bcc @done
    jsr open_list
    say no_answer_text
@done:
    rts
@heard:
    lda #0
    sta send_retry
    sta tries
    lda nesp_status
    bne @refused
    lda send_phase
    cmp #SEND_JOIN
    bne @more
    jmp open_joining
@more:
    lda send_off                ; on to the next piece, or the next text
    clc
    adc send_count
    sta send_off
    ldx send_phase
    cmp net_name_len,x          ; the two lengths are next to each other
    bcc @done
    inc send_phase
    lda #0
    sta send_off
    rts
@refused:                       ; out of step: from the beginning
    inc send_restarts
    lda send_restarts
    cmp #SEND_RESTARTS
    bcs @give_up
    jmp send_restart
@give_up:
    jsr open_list
    say refused_text
    rts
.endproc
.assert net_pass_len = net_name_len + 1, error, "send_frame indexes the two lengths"

; The next piece of the name or the password into the request: its offset,
; then its bytes. Leaves the op in X and the payload's length in Y.
.proc piece
    lda send_phase
    bne @password
    point net_name
    lda net_name_len
    ldx #NESP_NET_SET_NAME
    bne @cut
@password:
    point net_pass
    lda net_pass_len
    ldx #NESP_NET_SET_PASSWORD
@cut:
    sec
    sbc send_off                ; what is left of it
    cmp #PIECE
    bcc @count
    lda #PIECE
@count:
    sta send_count
    lda send_off
    sta nesp_request
    clc
    adc ptr
    sta ptr
    bcc @copy
    inc ptr + 1
@copy:
    ldy #0
@byte:
    cpy send_count
    beq @done
    lda (ptr),y
    sta nesp_request + 1,y
    iny
    bne @byte
@done:
    iny                         ; and the offset
    rts
.endproc

; --- joining -------------------------------------------------------------------

.proc open_joining
    say joining_text
    lda #0
    sta timer
    lda #STATE_JOINING
    sta state
    rts
.endproc

.proc joining_frame
    lda frame_count
    and #JOIN_EVERY
    bne @done
    inc timer
    lda timer
    cmp #JOIN_POLLS
    bcc @ask
    say no_answer_text
    jmp fail
@ask:
    lda #NESP_SVC_NET
    ldx #NESP_NET_WIFI_STATUS
    ldy #0
    jsr call
    bcs @done
    lda nesp_reply
    cmp #NESP_WIFI_JOINED
    bne @failed
    jmp open_status
@failed:
    cmp #NESP_WIFI_FAILED
    bne @done                   ; still trying
    lda nesp_reply + 1
    cmp #NESP_WHY_PASSWORD
    bne @network
    say password_text
    jmp fail
@network:
    cmp #NESP_WHY_NO_NETWORK
    bne @other
    say no_network_text
    jmp fail
@other:
    say no_join_text
    jmp fail
@done:
    rts
.endproc

; The message line says why. The help line says what can be done.
.proc fail
    lda #STATE_FAILED
    sta state
    lda #0
    sta timer
    rts
.endproc

.proc failed_frame
    lda timer                   ; the help line once, after the message is out
    bne @input
    lda draw_len
    ora message_new
    bne @input
    inc timer
    at HELP_ROW, LEFT
    point failed_help
    ldx #0
    jsr put_text
    ldy #WIDTH
    jsr stage_pad
@input:
    lda pad_new
    and #PAD_A | PAD_START
    beq @back
    lda net_auth                ; another password, if the network takes one
    beq @list
    lda #KEYS_PASSWORD
    jmp open_keys
@back:
    lda pad_new
    and #PAD_B
    beq @done
@list:
    jmp open_scan
@done:
    rts
.endproc

; The lobby: from the hello to two nesp32s joined, as nesp32's netplay
; games have it (docs/MULTIPLAYER.md, "Playing").
;
;   HOST GAME   the nesp32 opens a room at the rendezvous, and waits in it
;               for the other. The screen shows the room's code, which
;               player 2 enters.
;   JOIN GAME   a room's code to enter (Left and Right to move, Up and Down
;               to change a letter), and Start joins that room.
;
; Select on either of those screens changes how the two meet: by a room's
; code, across the Internet with no port forwarded, or by an address, as
; on one network. By address HOST GAME shows this nesp32's address, and
; JOIN GAME has one to enter, which starts as the address last joined
; (PEER LAST). The way holds until the lobby is left. B goes back.
;
; Everything here is the PEER service's lobby (nesp32's docs/PROTOCOL.md,
; "PEER"). Two rules make it simple to get right:
;
; - An order is sent again until it is answered. An order the nesp32 is
;   already carrying out changes nothing, so sending one twice is safe.
; - The ROM acts on a state only once the order that should lead to it has
;   been answered: until then a STATUS may still say how things stood
;   before.
;
; The main loop decides what to ask (menu_link) and draws (menu_draw); the
; NMI makes the exchange (menu_nmi), one a frame at most.
;
; When the nesp32 says it is connected, as HOST (player 1) or GUEST
; (player 2), the lobby starts a session (start_session, nes/session.inc)
; with the delay the nesp32 advised in its replies.

LETTERS     = 32                ; of which a room's code is made
CODE_TILES  = NESP_PEER_CODE    ; K7QF
IP_TILES    = 15                ; 192.168.001.023
DIGITS      = 12
; What the nesp32 says of itself is one of NESP_LOBBY_*. The lobby's own:
STATE_NONE  = $FF               ; no nesp32 answers
STATE_OLD   = $FE               ; one answers, and its firmware has no PEER
MISSES      = 8                 ; requests in a row unanswered before STATE_NONE
HELLO       = $FF               ; in menu_sent: the last request was the hello

MODE_MAIN    = 0
MODE_HOSTING = 1
MODE_EDIT    = 2                ; the code or the address to join
MODE_JOINING = 3

; What is to be drawn, a bit each; menu_draw draws one a frame.
DIRTY_OWN    = $01              ; this nesp32's address, or why there is none
DIRTY_DIGITS = $02              ; the code or the address being entered
DIRTY_MARK   = $04              ; the dash under its letter or digit
DIRTY_STATUS = $08
DIRTY_CURSOR = $10
DIRTY_CODE   = $20              ; the room's code, on the host's screen
DIRTY_ENDED  = $40              ; why the last session ended

.segment "BSS"
menu_vars:
menu_mode:      .res 1          ; MODE_*
menu_count:     .res 1          ; frames
menu_pad_old:   .res 1
menu_press:     .res 1          ; buttons that went down this frame
menu_cursor:    .res 1          ; 0 HOST GAME, 1 JOIN GAME
menu_shown:     .res 1          ; where the cursor is drawn, $FF nowhere
menu_pos:       .res 1          ; the letter or digit being changed
menu_way:       .res 1          ; 0 by a room's code, 1 by an address
menu_want:      .res 1          ; an op of PEER's to send, 0 none
menu_sent:      .res 1          ; the op of the last request, or HELLO
menu_len:       .res 1          ; its payload's length
menu_pending:   .res 1          ; 1: the request is for the NMI to make
menu_result:    .res 1          ; 1 its reply came, $FF none did
menu_done:      .res 1          ; 1: the last op wanted has been answered
menu_linked:    .res 1          ; 1: the nesp32 has answered the hello
menu_misses:    .res 1
menu_state:     .res 1          ; the nesp32's, from its last reply
menu_delay:     .res 1          ; the delay it advises, for the session
menu_why:       .res 1          ; why a meeting failed: NESP_MEET_*
menu_dirty:     .res 1          ; DIRTY_*
menu_status:    .res 1          ; which of status_texts the status line shows
menu_filled:    .res 1          ; 1: the address to join has been set
menu_octets:    .res 4          ; an address, as it crosses the link
menu_digits:    .res DIGITS     ; the address to join, a digit a byte
menu_own:       .res DIGITS     ; this nesp32's
menu_code:      .res CODE_TILES ; the code to join, each a letter's number
menu_room:      .res CODE_TILES ; the room's code, in ASCII as the nesp32 gave it
MENU_VARS = * - menu_vars
menu_ended:     .res 1          ; why the last session ended: status_texts, 0 none

.assert menu_digits + DIGITS = menu_own, error, "octets_to_digits finds menu_own at menu_digits + 12"
.assert DIRTY_ENDED * 2 = 1 << DRAWERS, error, "a drawer for each of menu_dirty's bits"

.segment "CODE"



; The lobby from the start, its first screen, with a hello to come. A = why
; the last session ended (an offset in status_texts), or 0.
lobby_start:
    sta menu_ended
    lda #0
    ldx #MENU_VARS - 1
@clear:
    sta menu_vars,x
    dex
    bpl @clear
    sta mode
    lda #$FF                    ; buttons held as the lobby opens count
    sta menu_pad_old            ; only once let go
    lda #NET_DELAY              ; until the nesp32 advises one
    sta menu_delay
    lda #STATE_NONE
    sta menu_state
    jmp show_main

; The lobby's frame, from the main loop.
menu_frame:
    lda pad
    tay
    eor menu_pad_old
    and pad
    sta menu_press
    sty menu_pad_old
    inc menu_count
    jsr menu_link
    jsr menu_draw
    lda menu_mode
    asl a
    tax
    lda handlers + 1,x          ; each handler's rts is menu_frame's
    pha
    lda handlers,x
    pha
    rts

handlers:
    .word mode_main - 1, mode_hosting - 1, mode_edit - 1, mode_joining - 1

; The lobby's part of the NMI: the request menu_link staged, if any.
menu_nmi:
    lda menu_pending
    beq @rts
    jmp menu_exchange
@rts:
    rts



; --- the first screen ------------------------------------------------------------

mode_main:
    lda menu_press
    and #PAD_UP | PAD_DOWN
    beq @pick
    lda menu_cursor
    eor #1
    sta menu_cursor
    jsr cursor_moved
@pick:
    lda menu_press
    and #PAD_A | PAD_START
    beq @rts
    ; Both need a nesp32 that is on a network.
    ldx menu_state
    beq @rts                    ; NESP_LOBBY_NO_WIFI
    cpx #STATE_OLD
    bcs @rts                    ; or STATE_NONE
    lda menu_cursor
    bne join
    beq host
@rts:
    rts

; Wait for player 2, the way chosen.
host:
    lda #NESP_PEER_HOST
    ldx menu_way
    bne @host
    lda #NESP_PEER_HOST_ROOM
@host:
    jsr command
    jmp show_hosting

; The join screen, the way chosen. A code starts as the last one entered;
; an address as the last one joined, which the nesp32 keeps.
join:
    lda menu_way
    beq @edit
    lda menu_filled
    bne @edit
    lda #NESP_PEER_LAST
    jsr command
@edit:
    jmp show_join

; Select: the other way, on the screen it was pressed on.
other_way:
    lda menu_way
    eor #1
    sta menu_way
    lda #0                      ; a code has fewer places than an address
    sta menu_pos
    rts

cursor_moved:
    lda #DIRTY_CURSOR
    bne dirty

mark_moved:
    lda #DIRTY_MARK
    ; fall through

; Have A's things drawn.
dirty:
    ora menu_dirty
    sta menu_dirty
    rts

set_status:
    sta menu_status
    lda #DIRTY_STATUS
    bne dirty



; --- waiting for player 2 ------------------------------------------------------------

mode_hosting:
    lda menu_press
    and #PAD_SELECT
    beq @back
    jsr other_way
    jmp host                    ; which hangs up whatever there was
@back:
    lda menu_press
    and #PAD_B
    beq @state
    lda #NESP_PEER_LEAVE
    jsr command
    jmp show_main
@state:
    lda menu_done
    beq @rts
    lda menu_state
    cmp #NESP_LOBBY_HOST
    bne @room
    ldy #0                      ; this console is player 1
    jmp start_session
@room:
    ldx menu_way
    bne @rts
    jmp room_status
@rts:
    rts

; In a room, what the screen says of it: opening it, nothing while it
; waits (its code says enough), or why it could not be met in.
room_status:
    ldx #STATUS_OPENING
    cmp #NESP_LOBBY_MEETING
    beq @show
    ldx #STATUS_NONE
    cmp #NESP_LOBBY_HOSTING
    beq @show
    ldx #STATUS_CONNECTING
    cmp #NESP_LOBBY_CONNECTING
    beq @show
    cmp #NESP_LOBBY_FAILED
    bne @rts
    ldx menu_why
    cpx #WHY_TEXTS
    bcc @why
    ldx #0
@why:
    lda why_status,x
    tax
@show:
    cpx menu_status
    beq @rts
    txa
    jmp set_status
@rts:
    rts

why_status:
    .byte STATUS_FAILED, STATUS_NO_SERVER, STATUS_NO_ROOM, STATUS_MISMATCH
    .byte STATUS_FULL, STATUS_UNREACHABLE, STATUS_GONE
WHY_TEXTS = * - why_status
.assert WHY_TEXTS = NESP_MEET_GONE + 1, error, "a status for each NESP_MEET_*"



; --- the code or the address to join ---------------------------------------------------

mode_edit:
    lda menu_press
    and #PAD_SELECT
    beq @back
    jsr other_way
    jmp join
@back:
    lda menu_press
    and #PAD_B
    beq @move
    jmp show_main
@move:
    ; Left and Right move along the code's letters or the address's digits.
    ldx #CODE_TILES - 1
    lda menu_way
    beq @left
    ldx #DIGITS - 1
@left:
    stx temp                    ; the last place
    lda menu_press
    and #PAD_LEFT
    beq @right
    lda menu_pos
    beq @right
    dec menu_pos
    jsr mark_moved
@right:
    lda menu_press
    and #PAD_RIGHT
    beq @change
    lda menu_pos
    cmp temp
    beq @change
    inc menu_pos
    jsr mark_moved
@change:
    lda menu_way
    bne @digit
    jsr change_letter
    jmp @go
@digit:
    jsr change_digit
@go:
    lda menu_press
    and #PAD_A | PAD_START
    beq @rts
    lda #NESP_PEER_JOIN_ROOM
    ldx menu_way
    beq @join
    lda #NESP_PEER_JOIN
@join:
    jsr command
    lda #MODE_JOINING
    sta menu_mode
    lda #STATUS_CONNECTING
    jmp set_status
@rts:
    rts

; Up and Down: the next or the last of a code's 32 letters.
change_letter:
    ldx menu_pos
    lda menu_press
    and #PAD_UP
    beq @down
    inc menu_code,x
    bne @changed
@down:
    lda menu_press
    and #PAD_DOWN
    beq @rts
    dec menu_code,x
@changed:
    lda menu_code,x
    and #LETTERS - 1
    sta menu_code,x
    lda #DIRTY_DIGITS
    jmp dirty
@rts:
    rts

; Up and Down: the next or the last digit of an address, 0 to 9.
change_digit:
    ldx menu_pos
    lda menu_press
    and #PAD_UP
    beq @down
    inc menu_digits,x
    lda menu_digits,x
    cmp #10
    bcc @changed
    lda #0
    sta menu_digits,x
    beq @changed
@down:
    lda menu_press
    and #PAD_DOWN
    beq @rts
    dec menu_digits,x
    bpl @changed
    lda #9
    sta menu_digits,x
@changed:
    lda #1
    sta menu_filled
    lda #DIRTY_DIGITS
    jmp dirty
@rts:
    rts



mode_joining:
    lda menu_press
    and #PAD_B
    beq @state
    lda #NESP_PEER_LEAVE
    jsr command
    lda #STATUS_NONE
    jmp @status
@state:
    lda menu_done
    beq @rts
    lda menu_state
    cmp #NESP_LOBBY_CONNECTING
    beq @rts
    cmp #NESP_LOBBY_MEETING
    beq @rts
    cmp #NESP_LOBBY_GUEST
    bne @failed
    ldy #1                      ; this console is player 2
    jmp start_session
@failed:
    ldx menu_way
    bne @address
    jsr room_status             ; why the room could not be met in
    jmp @edit
@address:
    lda #STATUS_FAILED
@status:
    jsr set_status
@edit:
    lda #MODE_EDIT
    sta menu_mode
@rts:
    rts



; --- the nesp32 ------------------------------------------------------------------------

; Send op A of PEER's, in place of the next question about the nesp32's
; state, and again until it is answered.
command:
    sta menu_want
    lda #0
    sta menu_done
    rts

; Take the reply to the last request, if it has come or been given up, and
; stage the next request when it is time.
menu_link:
    lda menu_result
    bne @result
    jmp @send
@result:
    bpl @came
    jmp @missed
@came:
    lda menu_sent
    cmp #HELLO
    bne @reply
    jsr hello_answered
    jmp @clear
@reply:
    lda nesp_status
    beq @good
    cmp #NESP_ST_NO_OP
    bne @unlinked
    ; A firmware from before rooms: by address only, which the screen
    ; says, and Select is the way to.
    lda #0
    sta menu_want
    lda #1
    sta menu_done
    lda menu_mode
    cmp #MODE_JOINING
    bne @old
    lda #MODE_EDIT
    sta menu_mode
@old:
    lda #STATUS_OLD
    jsr set_status
    jmp @clear
@unlinked:
    ; PEER is not in use: the nesp32 was switched off and on, and knows of
    ; no hello.
    lda #0
    sta menu_linked
    jmp @missed
@good:
    lda #0
    sta menu_misses
    ldx #3
@address:
    lda nesp_reply + 1,x
    sta menu_octets,x
    dex
    bpl @address
    lda menu_sent
    cmp #NESP_PEER_LAST
    bne @state
    ; The address last joined, to start the edit from. With none, this
    ; nesp32's own: the other is most likely on the same network.
    lda menu_octets
    ora menu_octets + 1
    ora menu_octets + 2
    ora menu_octets + 3
    beq @own
    ldx #0
    jsr octets_to_digits
    jmp @filled
@own:
    ldx #DIGITS - 1
@copy:
    lda menu_own,x
    sta menu_digits,x
    dex
    bpl @copy
@filled:
    lda #1
    sta menu_filled
    lda #DIRTY_DIGITS
    jsr dirty
    jmp @answered
@state:
    lda nesp_reply
    jsr set_state
    ; The delay to begin a session with, if the nesp32 gives one: from
    ; how long the network took while the two nesp32s met.
    lda nesp_reply + 5
    beq @digits
    cmp #NET_DELAY_MAX + 1
    bcs @digits
    sta menu_delay
@digits:
    ldx #DIGITS                 ; menu_own
    jsr octets_to_digits
    lda #DIRTY_OWN
    jsr dirty
    ; A room's op: its code, and why a meeting failed.
    lda menu_sent
    cmp #NESP_PEER_HOST_ROOM
    bcc @answered
    ldx #CODE_TILES - 1
@code:
    lda nesp_reply + 6,x
    sta menu_room,x
    dex
    bpl @code
    lda nesp_reply + 6 + CODE_TILES
    sta menu_why
    lda #DIRTY_CODE
    jsr dirty
@answered:
    ; Is that the answer to the op the screen is waiting on?
    lda menu_sent
    beq @clear                  ; a question, not an op
    lda menu_want
    bne @clear                  ; another op is still to go
    lda #1
    sta menu_done
    bne @clear
@missed:
    ; No reply. An op is sent again; a hello is anyway, and a question is
    ; asked again in its time.
    lda menu_sent
    beq @count
    cmp #NESP_PEER_ROOM
    beq @count
    cmp #HELLO
    beq @count
    lda menu_want
    bne @count
    lda menu_sent
    sta menu_want
@count:
    inc menu_misses
    lda menu_misses
    cmp #MISSES
    bcc @clear
    dec menu_misses
    lda #0                      ; whatever answers next is asked who it is
    sta menu_linked
    lda #STATE_NONE
    jsr set_state
@clear:
    lda #0
    sta menu_result
@send:
    lda menu_pending
    bne @rts
    ; A request every fourth frame at most: with no nesp32 each one is a
    ; quarter of a frame spent waiting.
    lda menu_count
    and #$03
    bne @rts
    lda menu_linked
    bne @linked
    lda #HELLO
    sta menu_sent
    bne @go
@linked:
    lda menu_want
    bne @request
    ; With no op to send, how the nesp32 stands, every 16 frames: ROOM in a
    ; room, which says the room's code too.
    lda menu_count
    and #$0F
    bne @rts
    lda #NESP_PEER_STATUS
    ldx menu_way
    bne @request
    ldx menu_mode
    beq @request                ; MODE_MAIN
    lda #NESP_PEER_ROOM
@request:
    sta menu_sent
    ldy #0
    cmp #NESP_PEER_JOIN_ROOM
    beq @to_room
    cmp #NESP_PEER_JOIN
    bne @length
    jsr digits_to_octets
    ldx #3
@payload:
    lda menu_octets,x
    sta nesp_request,x
    dex
    bpl @payload
    ldy #4
    bne @length
@to_room:
    ldx #CODE_TILES - 1
@letter:
    ldy menu_code,x
    lda code_letters,y
    sta nesp_request,x
    dex
    bpl @letter
    ldy #CODE_TILES
@length:
    sty menu_len
    lda #0
    sta menu_want
@go:
    lda #1
    sta menu_pending
@rts:
    rts

.assert NESP_PEER_STATUS = 0, error, "menu_link takes NESP_PEER_STATUS for no op"
.assert NESP_PEER_JOIN_ROOM > NESP_PEER_HOST_ROOM && NESP_PEER_ROOM > NESP_PEER_HOST_ROOM, error
.assert NESP_PEER_LAST < NESP_PEER_HOST_ROOM && NESP_PEER_JOIN < NESP_PEER_HOST_ROOM, error

; The hello has been answered. With any status but OK the firmware has no
; PEER, or speaks another protocol: "UPDATE NESP32".
hello_answered:
    lda nesp_status
    beq @linked
    lda #STATE_OLD
    jmp set_state
@linked:
    lda #1
    sta menu_linked
    lda #0
    sta menu_misses
    lda #$0F                    ; the first question follows at once
    sta menu_count
    ; A nesp32 that was switched off and on has forgotten what it was told.
    lda menu_want
    bne @rts
    lda menu_mode
    cmp #MODE_HOSTING
    bne @joining
    lda #NESP_PEER_HOST
    bne @again
@joining:
    cmp #MODE_JOINING
    bne @rts
    lda #NESP_PEER_JOIN
@again:
    ; In a room, the room's op: the same but for its number.
    ldx menu_way
    bne @command
    clc
    adc #NESP_PEER_HOST_ROOM - NESP_PEER_HOST
@command:
    jmp command
@rts:
    rts

.assert NESP_PEER_JOIN_ROOM - NESP_PEER_JOIN = NESP_PEER_HOST_ROOM - NESP_PEER_HOST, error

; The nesp32's state is A, if that is news.
set_state:
    cmp menu_state
    beq @rts
    sta menu_state
    lda #DIRTY_OWN
    jmp dirty
@rts:
    rts

; The request menu_link staged, and its reply: from the NMI, as every
; exchange is.
menu_exchange:
    ldx menu_sent
    cpx #HELLO
    bne @op
    lda #NESP_SVC_PEER          ; the one service this ROM needs
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    jmp @result
@op:
    ldy menu_len
    lda #NESP_SVC_PEER
    jsr nesp_call               ; A = service, X = op, Y = the payload's length
@result:
    lda #0
    sta menu_pending
    lda #1
    bcc @store
    lda #$FF
@store:
    sta menu_result
    rts



; --- addresses ----------------------------------------------------------------------

; menu_octets as 12 digits at menu_digits + X (X = 12: menu_own).
octets_to_digits:
    ldy #0
@octet:
    sty temp
    lda menu_octets,y
    ldy #0
@hundreds:
    cmp #100
    bcc @tens
    sbc #100
    iny
    bne @hundreds
@tens:
    pha
    tya
    sta menu_digits,x
    pla
    ldy #0
@ten:
    cmp #10
    bcc @ones
    sbc #10
    iny
    bne @ten
@ones:
    sta menu_digits + 2,x
    tya
    sta menu_digits + 1,x
    inx
    inx
    inx
    ldy temp
    iny
    cpy #4
    bne @octet
    rts

; menu_digits as menu_octets. Three digits past 255 are 255.
digits_to_octets:
    ldx #0
    ldy #0
@octet:
    lda menu_digits,x           ; hundreds and tens: 0-99
    asl a
    sta temp
    asl a
    asl a
    clc
    adc temp
    adc menu_digits + 1,x
    cmp #26
    bcs @most
    asl a                       ; and ten times that: 0-250
    sta temp
    asl a
    asl a
    adc temp
    adc menu_digits + 2,x
    bcc @store
@most:
    lda #255
@store:
    sta menu_octets,y
    inx
    inx
    inx
    iny
    cpy #4
    bne @octet
    rts



; --- drawing -----------------------------------------------------------------------

; Stage one of the things that have changed, if the NMI has drawn the last.
menu_draw:
    lda draw_len
    bne @rts
    lda menu_dirty
    ldx #0
@find:
    lsr a
    bcs @draw
    inx
    cpx #DRAWERS
    bne @find
@rts:
    rts
@draw:
    txa
    asl a
    tax
    lda drawers + 1,x
    pha
    lda drawers,x
    pha
    rts

; By the bits of menu_dirty, from the lowest.
drawers:
    .word draw_own - 1, draw_digits - 1, draw_mark - 1, draw_status - 1
    .word draw_cursor - 1, draw_code - 1, draw_ended - 1
DRAWERS = (* - drawers) / 2

; Take A out of what is to be drawn.
drawn:
    eor #$FF
    and menu_dirty
    sta menu_dirty
    rts

; draw_line's first A tiles, to go at Y:X.
stage:
    stx draw_lo
    sty draw_hi
    sta draw_len
    rts

; This nesp32's address, or why it has none, on the first screen and on
; the screen of a host by address.
draw_own:
    lda #DIRTY_OWN
    jsr drawn
    lda menu_mode
    beq @row                    ; MODE_MAIN
    cmp #MODE_HOSTING
    bne @rts
    lda menu_way                ; a room's host shows its code instead
    beq @rts
@row:
    lda menu_state
    ldx #STATUS_NO_WIFI
    cmp #NESP_LOBBY_NO_WIFI
    beq @why
    ldx #STATUS_NO_NESP32
    cmp #STATE_NONE
    beq @why
    ldx #STATUS_OLD
    cmp #STATE_OLD
    beq @why
    ldx #DIGITS                 ; menu_own
    jsr digits_to_line
    jmp @at
@why:
    jsr text_to_line
@at:
    ldx #<($2000 + 20 * 32 + 8)
    ldy #>($2000 + 20 * 32 + 8)
    lda menu_mode
    beq @stage
    ldx #<($2000 + 14 * 32 + 8)
    ldy #>($2000 + 14 * 32 + 8)
@stage:
    lda #IP_TILES
    jmp stage
@rts:
    rts

; The code or the address being entered.
draw_digits:
    lda #DIRTY_DIGITS
    jsr drawn
    lda menu_mode
    cmp #MODE_EDIT
    bcc @rts                    ; MODE_EDIT and MODE_JOINING have it
    lda menu_way
    bne @address
    ldx #CODE_TILES - 1
@letter:
    ldy menu_code,x
    lda code_letters,y
    sta draw_line,x
    dex
    bpl @letter
    ldx #<($2000 + 12 * 32 + 14)
    ldy #>($2000 + 12 * 32 + 14)
    lda #CODE_TILES
    jmp stage
@address:
    ldx #0                      ; menu_digits
    jsr digits_to_line
    ldx #<($2000 + 12 * 32 + 8)
    ldy #>($2000 + 12 * 32 + 8)
    lda #IP_TILES
    jmp stage
@rts:
    rts

; A dash under the letter or the digit that Up and Down change.
draw_mark:
    lda #DIRTY_MARK
    jsr drawn
    lda menu_mode
    cmp #MODE_EDIT
    bcc @rts
    ldx #IP_TILES - 1
    lda #' '
@blank:
    sta draw_line,x
    dex
    bpl @blank
    lda menu_pos
    ldx menu_way
    beq @mark                   ; a code has no dots
    ; In an address the digit's place in the line is its number, and one
    ; more for each dot before it.
    ldx #0
    cmp #3
    bcc @place
    inx
    cmp #6
    bcc @place
    inx
    cmp #9
    bcc @place
    inx
@place:
    stx temp
    clc
    adc temp
@mark:
    tax
    lda #'-'
    sta draw_line,x
    ldx #<($2000 + 13 * 32 + 8)
    ldy #>($2000 + 13 * 32 + 8)
    lda menu_way
    bne @stage
    ldx #<($2000 + 13 * 32 + 14)
    ldy #>($2000 + 13 * 32 + 14)
@stage:
    lda #IP_TILES
    jmp stage
@rts:
    rts

; The status line: on the join screen, and on a room's host's.
draw_status:
    lda #DIRTY_STATUS
    jsr drawn
    lda menu_mode
    cmp #MODE_EDIT
    bcs @draw
    cmp #MODE_HOSTING
    bne @rts
    lda menu_way
    bne @rts
@draw:
    ldx menu_status
    jsr text_to_line
    ldx #<($2000 + 16 * 32 + 8)
    ldy #>($2000 + 16 * 32 + 8)
    lda #IP_TILES
    jmp stage
@rts:
    rts

; The cursor on the first screen: it goes from its old place, then comes
; at its new one, a frame each.
draw_cursor:
    lda menu_mode
    bne @done
    lda #' '
    ldx menu_shown
    bpl @one
    lda #'>'
    ldx menu_cursor
@one:
    sta draw_line
    cpx menu_shown
    bne @came
    lda #$FF                    ; gone: the next frame draws it where it is
    sta menu_shown
    bne @where
@came:
    stx menu_shown
    lda #DIRTY_CURSOR
    jsr drawn
@where:
    ldy #$21                    ; rows 9 and 11
    lda cursor_lo,x
    tax
    lda #1
    jmp stage
@done:
    lda #DIRTY_CURSOR
    jmp drawn

cursor_lo:
    .byte <($2000 + 9 * 32 + 9), <($2000 + 11 * 32 + 9)
.assert >($2000 + 9 * 32 + 9) = $21 && >($2000 + 11 * 32 + 9) = $21, error

; The room's code, on its host's screen, as the nesp32 gave it.
draw_code:
    lda #DIRTY_CODE
    jsr drawn
    lda menu_mode
    cmp #MODE_HOSTING
    bne @rts
    lda menu_way
    bne @rts
    ldx #CODE_TILES - 1
@letter:
    lda menu_room,x
    sta draw_line,x
    dex
    bpl @letter
    ldx #<($2000 + 14 * 32 + 14)
    ldy #>($2000 + 14 * 32 + 14)
    lda #CODE_TILES
    jmp stage
@rts:
    rts

; Why the last session ended, on the first screen.
draw_ended:
    lda #DIRTY_ENDED
    jsr drawn
    lda menu_mode
    bne @rts
    ldx menu_ended
    jsr text_to_line
    ldx #<($2000 + 15 * 32 + 8)
    ldy #>($2000 + 15 * 32 + 8)
    lda #IP_TILES
    jmp stage
@rts:
    rts

; A code's 32 letters, by number: no 0 or O, no 1 or I.
code_letters:
    .byte "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
.assert * - code_letters = LETTERS, error

; 12 digits at menu_digits + X into draw_line, with their dots.
digits_to_line:
    ldy #0
@digit:
    lda menu_digits,x
    ora #'0'
    sta draw_line,y
    inx
    iny
    tya
    and #$03
    cmp #$03
    bne @next
    lda #'.'
    sta draw_line,y
    iny
@next:
    cpy #IP_TILES + 1
    bcc @digit
    rts

; One of status_texts, at X, into draw_line.
text_to_line:
    ldy #0
@char:
    lda status_texts,x
    sta draw_line,y
    inx
    iny
    cpy #IP_TILES
    bne @char
    rts

status_texts:
STATUS_NONE = * - status_texts
    .byte "               "
STATUS_CONNECTING = * - status_texts
    .byte "CONNECTING     "
STATUS_FAILED = * - status_texts
    .byte "COULD NOT JOIN "
STATUS_NO_NESP32 = * - status_texts
    .byte "NO NESP32      "
STATUS_OLD = * - status_texts
    .byte "UPDATE NESP32  "
STATUS_NO_WIFI = * - status_texts
    .byte "NO WIFI        "
STATUS_OPENING = * - status_texts
    .byte "OPENING A ROOM "
STATUS_NO_SERVER = * - status_texts
    .byte "NO RENDEZVOUS  "
STATUS_NO_ROOM = * - status_texts
    .byte "NO SUCH ROOM   "
STATUS_MISMATCH = * - status_texts
    .byte "NOT THIS GAME  "
STATUS_FULL = * - status_texts
    .byte "ROOM IS FULL   "
STATUS_UNREACHABLE = * - status_texts
    .byte "CANNOT REACH IT"
STATUS_GONE = * - status_texts
    .byte "ROOM CLOSED    "
; Why a session ended (session_main).
STATUS_LEFT = * - status_texts
    .byte "THE OTHER LEFT "
STATUS_QUIET = * - status_texts
    .byte "THE LINK FAILED"
STATUS_DIFFER = * - status_texts
    .byte "GAMES DIFFERED "
.assert * - status_texts <= 256, error, "status_texts is indexed by X"



; --- the screens ------------------------------------------------------------------

; Each is drawn whole, with the picture off, and what changes on it is
; then drawn by menu_draw.
show_main:
    lda #MODE_MAIN
    ldx #<screen_main
    ldy #>screen_main
    jsr show
    lda #$FF
    sta menu_shown
    lda #DIRTY_OWN | DIRTY_CURSOR | DIRTY_ENDED
    sta menu_dirty
    rts

show_hosting:
    lda menu_way
    beq @room
    lda #MODE_HOSTING
    ldx #<screen_hosting
    ldy #>screen_hosting
    jsr show
    lda #DIRTY_OWN
    sta menu_dirty
    rts
@room:
    lda #' '                    ; no code until the room is open
    ldx #CODE_TILES - 1
@blank:
    sta menu_room,x
    dex
    bpl @blank
    lda #STATUS_OPENING
    sta menu_status
    lda #MODE_HOSTING
    ldx #<screen_room
    ldy #>screen_room
    jsr show
    lda #DIRTY_CODE | DIRTY_STATUS
    sta menu_dirty
    rts

show_join:
    lda #STATUS_NONE
    sta menu_status
    ldx #<screen_join
    ldy #>screen_join
    lda menu_way
    bne @show
    ldx #<screen_join_room
    ldy #>screen_join_room
@show:
    lda #MODE_EDIT
    jsr show
    lda #DIRTY_DIGITS | DIRTY_MARK | DIRTY_STATUS
    sta menu_dirty
    rts

; Mode A, and its screen's texts at Y:X on a blank screen.
show:
    sta menu_mode
    stx ptr
    sty ptr + 1
    jsr screen_off
    jsr draw_blank
    jsr draw_texts
    jmp screen_on

; 960 blank tiles, and 64 attributes of the one palette.
draw_blank:
    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #4
    ldy #0
@byte:
    sta PPUDATA
    iny
    bne @byte
    dex
    bne @byte
    rts

.segment "RODATA"
screen_main:
    text 4, 6, "NESP32 LOBBY SAMPLE"
    text 9, 11, "HOST GAME"
    text 11, 11, "JOIN GAME"
    text 18, 7, "THIS NESP32 IS AT"
    .byte 0

screen_hosting:
    text 4, 6, "NESP32 LOBBY SAMPLE"
    text 9, 6, "WAITING FOR PLAYER 2"
    text 12, 7, "PLAYER 2 JOINS AT"
    text 24, 12, "B - BACK"
    text 26, 5, "SELECT - BY ROOM CODE"
    .byte 0

screen_join:
    text 4, 6, "NESP32 LOBBY SAMPLE"
    text 9, 8, "JOIN THE GAME AT"
    text 22, 8, "START - CONNECT"
    text 24, 12, "B - BACK"
    text 26, 5, "SELECT - BY ROOM CODE"
    .byte 0

screen_room:
    text 4, 6, "NESP32 LOBBY SAMPLE"
    text 9, 6, "WAITING FOR PLAYER 2"
    text 12, 8, "THE ROOM CODE IS"
    text 24, 12, "B - BACK"
    text 26, 9, "SELECT - BY IP"
    .byte 0

screen_join_room:
    text 4, 6, "NESP32 LOBBY SAMPLE"
    text 9, 6, "JOIN THE ROOM OF CODE"
    text 22, 10, "START - JOIN"
    text 24, 12, "B - BACK"
    text 26, 9, "SELECT - BY IP"
    .byte 0
.segment "CODE"

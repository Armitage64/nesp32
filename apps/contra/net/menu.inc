; Netplay: the menu, in the space bank 5 leaves at its end. bank5.asm
; includes it when NETPLAY is defined. It is nes-drmario's (net/menu.s),
; made to run a frame at a time in the NMI, as all of this game does.
;
; Start at the title with 2 PLAYERS picked comes here (net_title_start,
; net.inc): from then the NMI is the menu's (net_menu_nmi, which brings this
; bank in and calls menu_frame), and the game's own handler does not run.
; The screens:
;
;   HOST GAME     the nesp32 opens a room at the rendezvous, and waits in it
;                 for the other. The screen shows the room's code, which
;                 player 2 has to enter.
;   JOIN GAME     a room's code to edit, and the nesp32 joins that room
;   LOCAL GAME    back to the game, for two controllers on this console
;
; Select on either of those screens changes how the two meet: by a room's
; code, across the Internet with no port forwarded, or by an address, as
; before rooms. By address, HOST GAME shows this nesp32's address and JOIN
; GAME has one to edit, which the nesp32 calls; that is for a network with
; no way to the Internet, and for a nesp32 whose firmware has no rooms.
; The way chosen holds until the menu is left.
;
; When the nesp32s are connected it starts a session (net_start_session),
; and does not come back. The delay it begins with is the nesp32's advice,
; from how long the network takes, which comes with the lobby's state.
;
; The nesp32 is spoken to through nesp32's library for the console, which
; is in the fixed bank: a hello as CNTR that asks for the PEER service, and
; then that service's lobby (nesp32's docs/PROTOCOL.md), one exchange an NMI
; at most, as a session's are. The hello is said again to a nesp32 that was
; switched off and on.
;
; The letters are the title's own, which are in the pattern table when the
; menu comes up and are ASCII by number. The two marks it has none for are
; put in two tiles the title leaves blank, and taken out again.
;
; The screens the menu draws are in bank 6 (menu_far.inc), which has room
; for them where this bank has not, and are drawn through net_far_draw.
;
; Nothing here may change the game's memory: LOCAL GAME goes on with it.
; The menu keeps its own in the game's buffer of writes for the PPU, which
; lies idle while the game's handler does not run.

.include "ram.inc"
.include "nesp_proto.inc"

.import net_far_call, net_far_hello, net_far_draw, net_start_session, net_menu_local
.importzp SCREEN_MAIN, SCREEN_HOSTING, SCREEN_JOIN, SCREEN_ROOM, SCREEN_JOIN_ROOM

nesp_request    = nesp_tx + NESP_HEADER
nesp_reply      = nesp_rx + NESP_HEADER

; Nothing follows this file in bank 5, so the map is left in force.
.charmap $20, $00               ; space
.charmap $2E, $40               ; .
TILE_BLANK      = $00
TILE_DOT        = $40
TILE_DASH       = $FE           ; the two the menu draws for itself
TILE_CURSOR     = $FF
MARKS           = $1000 + TILE_DASH * 16    ; where they are in the pattern table

BTN_RIGHT       = $01
BTN_LEFT        = $02
BTN_DOWN        = $04
BTN_UP          = $08
BTN_START       = $10
BTN_SELECT      = $20
BTN_B           = $40
BTN_A           = $80

IP_TILES        = 15            ; 192.168.001.023
CODE_TILES      = NESP_PEER_CODE    ; K7QF
LETTERS         = 32            ; that a code is made of
; What the nesp32 says of itself is one of NESP_LOBBY_*. The menu's own:
STATE_NONE      = $FF           ; no nesp32 answers
STATE_OLD       = $FE           ; one answers, and its firmware has no PEER
MISSES          = 8             ; requests in a row unanswered before STATE_NONE
HELLO           = $FF           ; in menu_sent: the last request was the hello

; The menu's memory.
menu_ptr        = nesp_ptr      ; 2 bytes of zero page, between exchanges
menu_tmp        = net_temp
menu_line       = CPU_GRAPHICS_BUFFER       ; 16: tiles to draw in the next NMI
menu_vars       = CPU_GRAPHICS_BUFFER + 16
menu_draw_len   = menu_vars + 0 ; how many of menu_line, 00 none
menu_draw_hi    = menu_vars + 1
menu_draw_lo    = menu_vars + 2
menu_busy       = menu_vars + 3 ; 01 while a frame of the menu is at work
menu_count      = menu_vars + 4 ; frames
menu_pad        = menu_vars + 5
menu_pad_old    = menu_vars + 6
menu_press      = menu_vars + 7 ; buttons that went down this frame
menu_mode       = menu_vars + 8
menu_cursor     = menu_vars + 9 ; 0-2 on the first screen
menu_shown      = menu_vars + 10    ; where its mark is drawn, FF nowhere
menu_pos        = menu_vars + 11    ; 0-11: the digit being edited
menu_want       = menu_vars + 12    ; an op of PEER's to send, 00 none
menu_sent       = menu_vars + 13    ; the op of the last request, or HELLO
menu_done       = menu_vars + 14    ; 01 the last op wanted has been answered
menu_misses     = menu_vars + 15
menu_state      = menu_vars + 16    ; the nesp32's, from its last reply
menu_dirty      = menu_vars + 17    ; what is to be drawn
menu_status     = menu_vars + 18    ; which of status_texts, on the join screen
menu_filled     = menu_vars + 19    ; 01 the address to join has been set
menu_octets     = menu_vars + 20    ; 4: an address, as it crosses the link
menu_digits     = menu_vars + 24    ; 12: the address to join
menu_own        = menu_vars + 36    ; 12: this nesp32's
menu_linked     = menu_vars + 48    ; 01 the nesp32 has answered a hello
menu_len        = menu_vars + 49    ; the payload's length, of the request to go out
menu_pending    = menu_vars + 50    ; 01: a request is to go out
menu_result     = menu_vars + 51    ; 01 its reply has come, FF none did
menu_delay      = menu_vars + 52    ; the delay the session is to begin with
menu_role       = menu_vars + 53    ; 00 player 1, 01 player 2: once connected
menu_way        = menu_vars + 54    ; 00 by a room's code, 01 by an address
menu_code       = menu_vars + 55    ; 4: the code to join, each a letter's number
menu_room       = menu_vars + 59    ; 4: the room's code, as the nesp32 gave it
menu_why        = menu_vars + 63    ; why a meeting failed: NESP_MEET_*
MENU_VARS       = 64

.assert menu_vars + MENU_VARS <= CPU_GRAPHICS_BUFFER + $50, error, "the menu's memory runs out of the buffer"

MODE_MAIN       = 0
MODE_HOSTING    = 1
MODE_EDIT       = 2
MODE_JOINING    = 3

DIRTY_OWN       = $01           ; this nesp32's address, or why there is none
DIRTY_DIGITS    = $02
DIRTY_MARK      = $04
DIRTY_STATUS    = $08
DIRTY_CURSOR    = $10
DIRTY_CODE      = $20           ; the room's code, on the host's screen


; One NMI of the menu. net_menu is 01 for the first, which sets it up.
menu_frame:
    lda net_menu
    cmp #$01
    bne @running
    jmp menu_enter

@running:
    lda menu_busy               ; an NMI that came as a screen was being drawn
    beq :+
    rts
:
    inc menu_busy
    ; What the last frame left to draw.
    lda menu_draw_len
    beq @picture
    lda PPUSTATUS
    lda menu_draw_hi
    sta PPUADDR
    lda menu_draw_lo
    sta PPUADDR
    ldx #$00

@tile:
    lda menu_line,x
    sta PPUDATA
    inx
    cpx menu_draw_len
    bne @tile
    lda #$00
    sta menu_draw_len

@picture:
    jsr menu_picture
    ; The controller. OUT0 rests at mark, as in the game.
    ldx #$00
    stx CONTROLLER_1
    ldy #$08

@button:
    lda CONTROLLER_1
    lsr
    rol menu_pad
    dey
    bne @button
    inx
    stx CONTROLLER_1
    lda menu_pad
    tay
    eor menu_pad_old
    and menu_pad
    sta menu_press
    sty menu_pad_old
    inc menu_count
    lda menu_pending
    beq @link
    jsr menu_exchange

@link:
    jsr menu_link
    jsr menu_draw
    jsr menu_handle
    lda #$00
    sta menu_busy
    rts

; The mode's handler, which ends the frame.
menu_handle:
    lda menu_mode
    asl
    tax
    lda menu_handlers+1,x
    pha
    lda menu_handlers,x
    pha
    rts

menu_handlers:
    .word menu_mode_main-1, menu_mode_hosting-1, menu_mode_edit-1, menu_mode_joining-1

; The picture on, at the top left of the first nametable, with no sprites.
menu_picture:
    lda PPUSTATUS
    lda #$00
    sta PPUSCROLL
    sta PPUSCROLL
    lda PPUCTRL_SETTINGS
    and #$fc
    sta PPUCTRL
    lda #$0a
    sta PPUMASK
    rts

; The first NMI of the menu.
menu_enter:
    lda #$00
    sta APU_STATUS              ; the title's tune stops here
    ldx #MENU_VARS+16-1

@clear:
    sta menu_line,x
    dex
    bpl @clear
    lda #STATE_NONE             ; and no hello yet: whatever the nesp32
    sta menu_state              ; was doing ends with that
    lda #NET_DELAY
    sta menu_delay
    lda #$02
    sta net_menu
    inc menu_busy
    jsr menu_screen_off
    ldx #$00
    jsr menu_marks
    jsr menu_show_main
    lda #$00
    sta menu_busy
    rts

; The menu's two marks into their tiles (X = 00), or the tiles blank again
; (X = 20). With the picture off.
menu_marks:
    lda PPUSTATUS
    lda #>MARKS
    sta PPUADDR
    lda #<MARKS
    sta PPUADDR
    ldy #$20

@byte:
    lda menu_mark_tiles,x
    sta PPUDATA
    inx
    dey
    bne @byte
    rts

; Each is the tile's two planes, of which the letters use the first.
menu_mark_tiles:
    .byte $00,$00,$00,$00,$00,$00,$7e,$00, $00,$00,$00,$00,$00,$00,$00,$00   ; a dash, low
    .byte $60,$70,$78,$7c,$78,$70,$60,$00, $00,$00,$00,$00,$00,$00,$00,$00   ; the cursor
    .res 32, $00

; --- the first screen ------------------------------------------------------------

menu_mode_main:
    lda menu_press
    and #BTN_UP
    beq @down
    lda menu_cursor
    beq @down
    dec menu_cursor
    jsr menu_cursor_moved

@down:
    lda menu_press
    and #BTN_DOWN
    beq @pick
    lda menu_cursor
    cmp #$02
    beq @pick
    inc menu_cursor
    jsr menu_cursor_moved

@pick:
    lda menu_press
    and #BTN_A | BTN_START
    beq @exit
    lda menu_cursor
    cmp #$02
    beq menu_leave_local
    ; The other two need a nesp32 that is on a network.
    ldx menu_state
    beq @exit                   ; NESP_LOBBY_NO_WIFI
    cpx #STATE_OLD
    bcs @exit                   ; or STATE_NONE
    cmp #$00
    bne menu_join
    jmp menu_host

@exit:
    rts

; Wait for player 2, the way chosen.
menu_host:
    lda #NESP_PEER_HOST
    ldx menu_way
    bne @host
    lda #NESP_PEER_HOST_ROOM

@host:
    jsr menu_command
    jmp menu_show_hosting

; The join screen, the way chosen. A code starts as the last one entered;
; an address as the last joined, from the nesp32.
menu_join:
    lda menu_way
    beq @edit
    lda menu_filled
    bne @edit
    lda #NESP_PEER_LAST
    jsr menu_command

@edit:
    jmp menu_show_join

; Select: the other way, on the screen it was pressed on.
menu_other_way:
    lda menu_way
    eor #$01
    sta menu_way
    lda #$00                    ; a code has fewer places than an address
    sta menu_pos
    rts

.assert NESP_LOBBY_NO_WIFI = 0, error

menu_cursor_moved:
    lda menu_dirty
    ora #DIRTY_CURSOR
    sta menu_dirty
    rts

; Back to the game, with no session: its Start goes on as it would have.
menu_leave_local:
    jsr menu_leave
    lda #$0f
    sta APU_STATUS
    jmp net_menu_local

; The picture off, and the menu's marks out of the pattern table.
menu_leave:
    jsr menu_screen_off
    ldx #$20
    jsr menu_marks
    lda PPUSTATUS
    lda PPUCTRL_SETTINGS
    sta PPUCTRL
    rts

; --- waiting for player 2 ----------------------------------------------------------

menu_mode_hosting:
    lda menu_press
    and #BTN_SELECT
    beq @back
    jsr menu_other_way
    jmp menu_host               ; which hangs up whatever there was

@back:
    lda menu_press
    and #BTN_B
    beq @state
    lda #NESP_PEER_LEAVE
    jsr menu_command
    jmp menu_show_main

@state:
    lda menu_done
    beq menu_exit
    lda menu_state
    cmp #NESP_LOBBY_HOST
    beq @session
    ldx menu_way
    bne menu_exit
    jmp menu_room_status

@session:
    lda #$00

; Into a session, as player A + 1.
menu_leave_session:
    sta menu_role
    jsr menu_leave
    lda menu_role
    ldx menu_delay
    jmp net_start_session

menu_exit:
    rts

; In a room, what the screen says of it (state in A): opening it, nothing
; while it waits (its code says enough), or why it could not be met in.
menu_room_status:
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
    bne @exit
    ldx menu_why
    cpx #WHY_TEXTS
    bcc @why
    ldx #$00

@why:
    lda menu_why_status,x
    tax

@show:
    txa
    cmp menu_status
    beq @exit
    jmp menu_set_status

@exit:
    rts

menu_why_status:
    .byte STATUS_FAILED, STATUS_NO_SERVER, STATUS_NO_ROOM, STATUS_MISMATCH
    .byte STATUS_FULL, STATUS_UNREACHABLE, STATUS_GONE
WHY_TEXTS = * - menu_why_status
.assert WHY_TEXTS = NESP_MEET_GONE + 1, error, "a status for each NESP_MEET_*"

; --- the code to join ------------------------------------------------------------------

menu_mode_code:
    lda menu_press
    and #BTN_LEFT
    beq @right
    lda menu_pos
    beq @right
    dec menu_pos
    jsr menu_mark_moved

@right:
    lda menu_press
    and #BTN_RIGHT
    beq @up
    lda menu_pos
    cmp #CODE_TILES-1
    beq @up
    inc menu_pos
    jsr menu_mark_moved

@up:
    ldx menu_pos
    lda menu_press
    and #BTN_UP
    beq @down
    inc menu_code,x
    bne @changed

@down:
    lda menu_press
    and #BTN_DOWN
    beq @back
    dec menu_code,x

@changed:
    lda menu_code,x
    and #LETTERS-1
    sta menu_code,x
    lda menu_dirty
    ora #DIRTY_DIGITS
    sta menu_dirty

@back:
    lda menu_press
    and #BTN_B
    beq @go
    jmp menu_show_main

@go:
    lda menu_press
    and #BTN_A | BTN_START
    beq @exit
    lda #NESP_PEER_JOIN_ROOM
    jsr menu_command
    lda #MODE_JOINING
    sta menu_mode
    lda #STATUS_CONNECTING
    jmp menu_set_status

@exit:
    rts

.assert LETTERS = 32, error, "a letter's number is kept to its five bits"

; A code's letters, by number: the title's tiles for them are ASCII, as
; the code is when it crosses the link.
menu_letters:
    .byte "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
.assert * - menu_letters = LETTERS, error

; --- the address to join -------------------------------------------------------------

menu_mode_edit:
    lda menu_press
    and #BTN_SELECT
    beq @way
    jsr menu_other_way
    jmp menu_join

@way:
    lda menu_way
    bne @address
    jmp menu_mode_code

@address:
    lda menu_press
    and #BTN_LEFT
    beq @right
    lda menu_pos
    beq @right
    dec menu_pos
    jsr menu_mark_moved

@right:
    lda menu_press
    and #BTN_RIGHT
    beq @up
    lda menu_pos
    cmp #11
    beq @up
    inc menu_pos
    jsr menu_mark_moved

@up:
    ldx menu_pos
    lda menu_press
    and #BTN_UP
    beq @down
    inc menu_digits,x
    lda menu_digits,x
    cmp #10
    bcc @changed
    lda #$00
    sta menu_digits,x
    beq @changed

@down:
    lda menu_press
    and #BTN_DOWN
    beq @back
    dec menu_digits,x
    bpl @changed
    lda #$09
    sta menu_digits,x

@changed:
    lda #$01
    sta menu_filled
    lda menu_dirty
    ora #DIRTY_DIGITS
    sta menu_dirty

@back:
    lda menu_press
    and #BTN_B
    beq @go
    jmp menu_show_main

@go:
    lda menu_press
    and #BTN_A | BTN_START
    beq @exit
    lda #NESP_PEER_JOIN
    jsr menu_command
    lda #MODE_JOINING
    sta menu_mode
    lda #STATUS_CONNECTING
    jmp menu_set_status

@exit:
    rts

menu_mark_moved:
    lda menu_dirty
    ora #DIRTY_MARK
    sta menu_dirty
    rts

menu_mode_joining:
    lda menu_press
    and #BTN_B
    beq @state
    lda #NESP_PEER_LEAVE
    jsr menu_command
    lda #STATUS_NONE
    beq @edit

@state:
    lda menu_done
    beq @exit
    lda menu_state
    cmp #NESP_LOBBY_CONNECTING
    beq @exit
    cmp #NESP_LOBBY_MEETING
    beq @exit
    cmp #NESP_LOBBY_GUEST
    bne @failed
    lda #$01
    jmp menu_leave_session

@failed:
    ldx menu_way
    bne @address
    jsr menu_room_status        ; why the room could not be met in
    jmp @back

@address:
    lda #STATUS_FAILED

@edit:
    jsr menu_set_status

@back:
    lda #MODE_EDIT
    sta menu_mode

@exit:
    rts

menu_set_status:
    sta menu_status
    lda menu_dirty
    ora #DIRTY_STATUS
    sta menu_dirty
    rts

; --- the nesp32 ------------------------------------------------------------------------

; Send op A of PEER's, in place of the next question about the nesp32's
; state, and again until it is answered.
menu_command:
    sta menu_want
    lda #$00
    sta menu_done
    rts

; Take the reply to the last request, if it has come or been given up, and
; make the next request when it is time.
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
    jsr menu_hello_answered
    jmp @clear

@reply:
    lda nesp_status
    beq @good
    cmp #NESP_ST_NO_OP
    bne @unlinked
    ; A firmware from before rooms: by address only, which the screen says,
    ; and Select is the way to.
    lda #$00
    sta menu_want
    lda #$01
    sta menu_done
    lda menu_mode
    cmp #MODE_JOINING
    bne @old
    lda #MODE_EDIT
    sta menu_mode

@old:
    lda #STATUS_OLD
    jsr menu_set_status
    jmp @clear

@unlinked:
    ; Not in use: the nesp32 was switched off and on, and knows of no hello.
    lda #$00
    sta menu_linked
    jmp @missed

@good:
    lda #$00
    sta menu_misses
    ldx #$03

@address:
    lda nesp_reply+1,x
    sta menu_octets,x
    dex
    bpl @address
    lda menu_sent
    cmp #NESP_PEER_LAST
    bne @state
    ; The address last joined, to start the edit from. With none, this
    ; nesp32's own: the other is most likely on the same network.
    lda menu_octets
    ora menu_octets+1
    ora menu_octets+2
    ora menu_octets+3
    beq @own
    ldx #$00
    jsr menu_octets_to_digits
    jmp @filled

@own:
    ldx #11

@copy:
    lda menu_own,x
    sta menu_digits,x
    dex
    bpl @copy

@filled:
    lda #$01
    sta menu_filled
    lda menu_dirty
    ora #DIRTY_DIGITS
    sta menu_dirty
    bne @answered

@state:
    lda nesp_reply
    sta menu_state
    ; The delay to begin a session with, if the nesp32 gives one.
    lda nesp_reply+5
    beq :+
    cmp #NET_DELAY_MAX+1
    bcs :+
    sta menu_delay
:
    ldx #12
    jsr menu_octets_to_digits
    lda menu_dirty
    ora #DIRTY_OWN
    sta menu_dirty
    ; A room's op: its code, and why a meeting failed.
    lda menu_sent
    cmp #NESP_PEER_HOST_ROOM
    bcc @answered
    ldx #CODE_TILES

@code:
    lda nesp_reply+5,x
    sta menu_room-1,x
    dex
    bne @code
    lda nesp_reply+6+CODE_TILES
    sta menu_why
    lda menu_dirty
    ora #DIRTY_CODE
    sta menu_dirty

@answered:
    ; Is that the answer to the op the screen is waiting on?
    lda menu_sent
    beq @clear
    lda menu_want
    bne @clear
    lda #$01
    sta menu_done
    bne @clear

@missed:
    lda menu_sent               ; an op is sent again; a hello is anyway,
    beq @count                  ; and a question is asked again in its time
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
    lda #$00                    ; whatever answers next is asked who it is
    sta menu_linked
    lda #STATE_NONE
    jsr menu_set_state

@clear:
    lda #$00
    sta menu_result

@send:
    lda menu_pending
    bne @exit
    ; A request every fourth frame at most: with no nesp32 each one is a
    ; quarter of a frame spent waiting, and an op is sent until answered.
    lda menu_count
    and #$03
    bne @exit
    lda menu_linked
    bne @linked
    lda #HELLO
    sta menu_sent
    bne @go

@linked:
    lda menu_want
    bne @request
    lda menu_count
    and #$0f
    bne @exit
    ; How the nesp32 stands: in a room, with the room's code.
    lda #NESP_PEER_STATUS
    ldx menu_way
    bne @request
    ldx menu_mode
    beq @request                ; MODE_MAIN
    lda #NESP_PEER_ROOM

@request:
    sta menu_sent
    ldy #$00
    cmp #NESP_PEER_JOIN_ROOM
    beq @to_join
    cmp #NESP_PEER_JOIN
    bne @length
    jsr menu_digits_to_octets
    ldx #$03

@payload:
    lda menu_octets,x
    sta nesp_request,x
    dex
    bpl @payload
    ldy #$04
    bne @length

@to_join:
    ldx #CODE_TILES-1

@letter:
    ldy menu_code,x
    lda menu_letters,y
    sta nesp_request,x
    dex
    bpl @letter
    ldy #CODE_TILES

@length:
    sty menu_len
    lda #$00
    sta menu_want

@go:
    lda #$01
    sta menu_pending

@exit:
    rts

.assert NESP_PEER_STATUS = 0, error, "menu_link takes NESP_PEER_STATUS for no op"
.assert NESP_PEER_JOIN_ROOM > NESP_PEER_HOST_ROOM && NESP_PEER_ROOM > NESP_PEER_HOST_ROOM, error
.assert NESP_PEER_LAST < NESP_PEER_HOST_ROOM && NESP_PEER_JOIN < NESP_PEER_HOST_ROOM, error
.assert NESP_PEER_JOIN_ROOM - NESP_PEER_JOIN = NESP_PEER_HOST_ROOM - NESP_PEER_HOST, error

; The hello has been answered. With any status but OK the firmware has no
; PEER, or speaks another protocol.
menu_hello_answered:
    lda nesp_status
    beq @linked
    lda #STATE_OLD
    bne menu_set_state

@linked:
    lda #$01
    sta menu_linked
    lda #$00
    sta menu_misses
    lda #$0f                    ; the first question follows at once
    sta menu_count
    ; A nesp32 that was switched off and on has forgotten what it was told.
    lda menu_want
    bne @exit
    lda menu_mode
    cmp #MODE_HOSTING
    bne @joining
    lda #NESP_PEER_HOST
    bne @again

@joining:
    cmp #MODE_JOINING
    bne @exit
    lda #NESP_PEER_JOIN

@again:
    ; In a room, the room's op: the same but for its number.
    ldx menu_way
    bne @command
    clc
    adc #NESP_PEER_HOST_ROOM - NESP_PEER_HOST

@command:
    jmp menu_command

@exit:
    rts

; The nesp32's state is A, if that is news.
menu_set_state:
    cmp menu_state
    beq @exit
    sta menu_state
    lda menu_dirty
    ora #DIRTY_OWN
    sta menu_dirty

@exit:
    rts

; The request menu_link made, and its reply.
menu_exchange:
    ldx menu_sent
    cpx #HELLO
    bne @op
    lda #NESP_SVC_PEER
    sta nesp_request+3+NESP_APP_ID
    ldy #$01
    jsr net_far_hello
    jmp @result

@op:
    ldy menu_len
    jsr net_far_call

@result:
    lda #$00
    sta menu_pending
    lda #$01
    bcc @store
    lda #$ff

@store:
    sta menu_result
    rts

; --- addresses -----------------------------------------------------------------------

; menu_octets as 12 digits at menu_digits + X (X = 12: menu_own).
menu_octets_to_digits:
    ldy #$00

@octet:
    sty menu_tmp
    lda menu_octets,y
    ldy #$00

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
    ldy #$00

@ten:
    cmp #10
    bcc @ones
    sbc #10
    iny
    bne @ten

@ones:
    sta menu_digits+2,x
    tya
    sta menu_digits+1,x
    inx
    inx
    inx
    ldy menu_tmp
    iny
    cpy #$04
    bne @octet
    rts

; menu_digits as menu_octets. Three digits past 255 are 255.
menu_digits_to_octets:
    ldx #$00
    ldy #$00

@octet:
    lda menu_digits,x           ; hundreds and tens: 0-99
    asl
    sta menu_tmp
    asl
    asl
    clc
    adc menu_tmp
    adc menu_digits+1,x
    cmp #26
    bcs @most
    asl                         ; and ten times that: 0-250
    sta menu_tmp
    asl
    asl
    adc menu_tmp
    adc menu_digits+2,x
    bcc @store

@most:
    lda #255

@store:
    sta menu_octets,y
    inx
    inx
    inx
    iny
    cpy #$04
    bne @octet
    rts

; --- drawing -------------------------------------------------------------------------

; Stage one of the things that have changed, for the next NMI to draw.
menu_draw:
    lda menu_draw_len
    bne menu_draw_exit
    lda menu_dirty
    ldx #$00

@find:
    lsr
    bcs @draw
    inx
    cpx #DRAWERS
    bne @find
    rts

@draw:
    txa
    asl
    tax
    lda menu_drawers+1,x
    pha
    lda menu_drawers,x
    pha
    rts

; By the bits of menu_dirty, from the lowest.
menu_drawers:
    .word menu_draw_own-1, menu_draw_digits-1, menu_draw_mark-1, menu_draw_status-1
    .word menu_draw_cursor-1, menu_draw_code-1
DRAWERS = (* - menu_drawers) / 2
.assert DIRTY_CODE = 1 << (DRAWERS - 1), error, "a drawer for each of menu_dirty's bits"

menu_draw_exit:
    rts

menu_draw_own:
    lda #DIRTY_OWN
    jsr menu_drawn
    lda menu_mode
    cmp #MODE_HOSTING
    bne @main
    lda menu_way                ; a room's host has its code to show instead
    bne @row
    rts

@main:
    cmp #MODE_MAIN
    bne menu_draw_exit

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
    ldx #12
    jsr menu_digits_to_line
    jmp @at

@why:
    jsr menu_text_to_line

@at:
    lda menu_mode
    cmp #MODE_HOSTING
    beq @host
    ldx #<($2000 + 20 * 32 + 8)
    ldy #>($2000 + 20 * 32 + 8)
    bne menu_stage_line

@host:
    ldx #<($2000 + 14 * 32 + 8)
    ldy #>($2000 + 14 * 32 + 8)

menu_stage_line:
    lda #IP_TILES

menu_stage:
    stx menu_draw_lo
    sty menu_draw_hi
    sta menu_draw_len
    rts

menu_draw_digits:
    lda #DIRTY_DIGITS
    jsr menu_drawn
    jsr menu_joining
    bcc menu_draw_exit
    lda menu_way
    bne @address
    ; The code's letters.
    ldx #CODE_TILES-1

@letter:
    ldy menu_code,x
    lda menu_letters,y
    sta menu_line,x
    dex
    bpl @letter
    ldx #<($2000 + 12 * 32 + 14)
    ldy #>($2000 + 12 * 32 + 14)
    lda #CODE_TILES
    jmp menu_stage

@address:
    ldx #$00
    jsr menu_digits_to_line
    ldx #<($2000 + 12 * 32 + 8)
    ldy #>($2000 + 12 * 32 + 8)
    bne menu_stage_line

menu_draw_mark:
    lda #DIRTY_MARK
    jsr menu_drawn
    jsr menu_joining
    bcs @here
    rts

@here:
    ; A dash under the digit: its place in the line is its number and one
    ; more for each dot before it.
    ldx #IP_TILES-1
    lda #TILE_BLANK

@blank:
    sta menu_line,x
    dex
    bpl @blank
    lda menu_way
    bne @address
    ; Under a code's letter, which has no dots before it.
    ldx menu_pos
    lda #TILE_DASH
    sta menu_line,x
    ldx #<($2000 + 13 * 32 + 14)
    ldy #>($2000 + 13 * 32 + 14)
    lda #CODE_TILES
    jmp menu_stage

@address:
    lda menu_pos
    ldx #$00
    cmp #$03
    bcc @place
    inx
    cmp #$06
    bcc @place
    inx
    cmp #$09
    bcc @place
    inx

@place:
    stx menu_tmp
    clc
    adc menu_tmp
    tax
    lda #TILE_DASH
    sta menu_line,x
    ldx #<($2000 + 13 * 32 + 8)
    ldy #>($2000 + 13 * 32 + 8)
    jmp menu_stage_line

menu_draw_status:
    lda #DIRTY_STATUS
    jsr menu_drawn
    jsr menu_joining
    bcs @at
    lda menu_mode               ; and a room's host says how its room stands
    cmp #MODE_HOSTING
    bne menu_draw_done
    lda menu_way
    bne menu_draw_done

@at:
    ldx menu_status
    jsr menu_text_to_line
    ldx #<($2000 + 16 * 32 + 8)
    ldy #>($2000 + 16 * 32 + 8)
    jmp menu_stage_line

menu_draw_cursor:
    ; The mark goes from its old place, then comes at its new one.
    lda menu_mode
    bne @done
    lda #TILE_BLANK
    ldx menu_shown
    bpl @one
    lda #TILE_CURSOR
    ldx menu_cursor

@one:
    sta menu_line
    cpx menu_shown
    bne @came
    lda #$ff
    sta menu_shown
    bne @where

@came:
    stx menu_shown
    lda #DIRTY_CURSOR
    jsr menu_drawn

@where:
    ldy menu_cursor_hi,x
    lda menu_cursor_lo,x
    tax
    lda #$01
    jmp menu_stage

@done:
    lda #DIRTY_CURSOR
    jsr menu_drawn

menu_draw_done:
    rts

; The room's code, on its host's screen: ASCII, as the nesp32 gave it,
; and as the title's tiles are, but for the space.
menu_draw_code:
    lda #DIRTY_CODE
    jsr menu_drawn
    lda menu_mode
    cmp #MODE_HOSTING
    bne @exit
    lda menu_way
    bne @exit
    ldx #CODE_TILES-1

@letter:
    lda menu_room,x
    cmp #$20                    ; ASCII's space
    bne @tile
    lda #TILE_BLANK

@tile:
    sta menu_line,x
    dex
    bpl @letter
    ldx #<($2000 + 14 * 32 + 14)
    ldy #>($2000 + 14 * 32 + 14)
    lda #CODE_TILES
    jmp menu_stage

@exit:
    rts

menu_cursor_lo:
    .byte <($2000 + 9 * 32 + 9), <($2000 + 11 * 32 + 9), <($2000 + 13 * 32 + 9)

menu_cursor_hi:
    .byte >($2000 + 9 * 32 + 9), >($2000 + 11 * 32 + 9), >($2000 + 13 * 32 + 9)

; Take A out of what is to be drawn.
menu_drawn:
    eor #$ff
    and menu_dirty
    sta menu_dirty
    rts

; Carry set on the join screen.
menu_joining:
    lda menu_mode
    cmp #MODE_EDIT
    rts

.assert MODE_JOINING > MODE_EDIT && MODE_HOSTING < MODE_EDIT && MODE_MAIN < MODE_EDIT, error

; 12 digits at menu_digits + X into menu_line, with their dots.
menu_digits_to_line:
    ldy #$00

@digit:
    lda menu_digits,x
    ora #$30
    sta menu_line,y
    inx
    iny
    tya
    and #$03
    cmp #$03
    bne @next
    lda #TILE_DOT
    sta menu_line,y
    iny

@next:
    cpy #IP_TILES+1
    bcc @digit
    rts

; One of menu_status_texts into menu_line.
menu_text_to_line:
    ldy #$00

@tile:
    lda menu_status_texts,x
    sta menu_line,y
    inx
    iny
    cpy #IP_TILES
    bne @tile
    rts

; Each is a line, and named by where it begins.
STATUS_NONE        = 0 * IP_TILES
STATUS_CONNECTING  = 1 * IP_TILES
STATUS_FAILED      = 2 * IP_TILES
STATUS_NO_NESP32   = 3 * IP_TILES
STATUS_OLD         = 4 * IP_TILES
STATUS_NO_WIFI     = 5 * IP_TILES
STATUS_OPENING     = 6 * IP_TILES
STATUS_NO_SERVER   = 7 * IP_TILES
STATUS_NO_ROOM     = 8 * IP_TILES
STATUS_MISMATCH    = 9 * IP_TILES
STATUS_FULL        = 10 * IP_TILES
STATUS_UNREACHABLE = 11 * IP_TILES
STATUS_GONE        = 12 * IP_TILES

menu_status_texts:
.assert * - menu_status_texts = STATUS_NONE, error
    .byte "               "
.assert * - menu_status_texts = STATUS_CONNECTING, error
    .byte "CONNECTING     "
.assert * - menu_status_texts = STATUS_FAILED, error
    .byte "COULD NOT JOIN "
.assert * - menu_status_texts = STATUS_NO_NESP32, error
    .byte "NO NESP32      "
.assert * - menu_status_texts = STATUS_OLD, error
    .byte "UPDATE NESP32  "
.assert * - menu_status_texts = STATUS_NO_WIFI, error
    .byte "NO WIFI        "
.assert * - menu_status_texts = STATUS_OPENING, error
    .byte "OPENING A ROOM "
.assert * - menu_status_texts = STATUS_NO_SERVER, error
    .byte "NO RENDEZVOUS  "
.assert * - menu_status_texts = STATUS_NO_ROOM, error
    .byte "NO SUCH ROOM   "
.assert * - menu_status_texts = STATUS_MISMATCH, error
    .byte "NOT THIS GAME  "
.assert * - menu_status_texts = STATUS_FULL, error
    .byte "ROOM IS FULL   "
.assert * - menu_status_texts = STATUS_UNREACHABLE, error
    .byte "CANNOT REACH IT"
.assert * - menu_status_texts = STATUS_GONE, error
    .byte "ROOM CLOSED    "
.assert * - menu_status_texts <= 256, error, "a line is named by X"

; The screens. Each is drawn whole, with the picture off.
menu_show_main:
    lda #MODE_MAIN
    ldx #SCREEN_MAIN
    jsr menu_show
    lda #$ff
    sta menu_shown
    lda #DIRTY_OWN | DIRTY_CURSOR
    sta menu_dirty
    rts

menu_show_hosting:
    lda menu_way
    beq @room
    lda #MODE_HOSTING
    ldx #SCREEN_HOSTING
    jsr menu_show
    lda #DIRTY_OWN
    sta menu_dirty
    rts

@room:
    lda #$20                    ; no code until the room is open: ASCII's spaces
    ldx #CODE_TILES-1

@blank:
    sta menu_room,x
    dex
    bpl @blank
    lda #STATUS_OPENING
    sta menu_status
    lda #MODE_HOSTING
    ldx #SCREEN_ROOM
    jsr menu_show
    lda #DIRTY_CODE | DIRTY_STATUS
    sta menu_dirty
    rts

menu_show_join:
    lda #STATUS_NONE
    sta menu_status
    ldx #SCREEN_JOIN
    lda menu_way
    bne @show
    ldx #SCREEN_JOIN_ROOM

@show:
    lda #MODE_EDIT
    jsr menu_show
    lda #DIRTY_DIGITS | DIRTY_MARK | DIRTY_STATUS
    sta menu_dirty
    rts

; Mode A, and screen X (menu_far.inc).
menu_show:
    sta menu_mode
    jsr menu_screen_off
    jmp net_far_draw

; The picture and the NMI off, and nothing left for the NMI to draw.
menu_screen_off:
    lda #$00
    sta PPUCTRL
    sta PPUMASK
    sta menu_draw_len
    lda PPUSTATUS
    rts

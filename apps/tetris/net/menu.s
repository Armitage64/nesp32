; Netplay: the menu, in a bank of its own (the game's is full).
;
; Select on the title comes here (net_menu, net.inc) with the NMI off. This bank has its own NMI handler and draws its own screens:
;
;   HOST GAME     the nesp32 waits for the other to call. The screen shows
;                 the address player 2 has to enter.
;   JOIN GAME     an address to edit, and the nesp32 calls it
;   LOCAL GAME    back to the game, for two players on this console
;
; When the nesp32s are connected it starts a session in the game's bank
; (net_go, with the role in Y and the delay to begin with in X), and does
; not come back. That delay is the nesp32's advice, from how long the
; network took while the two connected.
;
; A session's frames are made from this bank too (net/session.inc): the
; game's NMI comes in at SESSION_ENTRY for each.
;
; The nesp32 is spoken to through nesp32's library for the console, of
; which this bank has its own copy: a hello as TTRS that asks for the PEER
; service, and then that service's lobby (nesp32's docs/PROTOCOL.md), one
; exchange an NMI at most, as a session's are. The hello is said again to a
; nesp32 that was switched off and on.
;
; Nothing here may change the game's memory: LOCAL GAME goes on with it.
; The menu keeps its own in addresses the game leaves free.

.include "net/common.inc"
.include "net/ram.inc"

; The link's library, before the font below is in force: its hello carries
; the name as it is written here.
.define NESP_APP "TTRS"
NESP_APP_VERSION = 1
.include "nesp.inc"

; The font, in the CHR page the game's title and menus use. By number: a
; character constant is itself put through the map made so far.
.repeat 10, i
    .charmap $30 + i, i         ; 0-9
.endrepeat
.repeat 26, i
    .charmap $41 + i, $0A + i   ; A-Z
.endrepeat
.charmap $2D, $24               ; -
.charmap $3E, $27               ; >
.charmap $2E, $6F               ; .
.charmap $20, $F3               ; space
TILE_DASH   = $24
TILE_CURSOR = $27
TILE_DOT    = $6F
TILE_BLANK  = $F3
FONT_PAGE   = $00

BTN_RIGHT = $01
BTN_LEFT  = $02
BTN_DOWN  = $04
BTN_UP    = $08
BTN_START = $10
BTN_B     = $40
BTN_A     = $80

IP_TILES    = 15                ; 192.168.001.023
; What the nesp32 says of itself is one of NESP_LOBBY_*. The menu's own:
STATE_NONE  = $FF               ; no nesp32 answers
STATE_OLD   = $FE               ; one answers, and its firmware has no PEER
MISSES      = 8                 ; requests in a row unanswered before STATE_NONE
HELLO       = $FF               ; in menu_sent: the last request was the hello

; The menu's memory.
menu_ptr        = nesp_ptr      ; 2 bytes of zero page, while the NMI is off
menu_tmp        = net_temp      ; the NMI leaves this one alone
menu_line       = $0380         ; 16: tiles for the NMI to draw
menu_vars       = $0390
menu_draw_len   = menu_vars + 0 ; how many of menu_line, 00 none
menu_draw_hi    = menu_vars + 1
menu_draw_lo    = menu_vars + 2
menu_frame      = menu_vars + 3 ; 01 after an NMI
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
menu_delay      = menu_vars + 50    ; the delay the session is to begin with
MENU_VARS       = 51

.assert IP_TILES + 1 <= menu_vars - menu_line, error
.assert menu_vars + MENU_VARS <= $03F0, error   ; the game's statsByType

MODE_MAIN    = 0
MODE_HOSTING = 1
MODE_EDIT    = 2
MODE_JOINING = 3

DIRTY_OWN    = $01              ; this nesp32's address, or why there is none
DIRTY_DIGITS = $02
DIRTY_MARK   = $04
DIRTY_STATUS = $08
DIRTY_CURSOR = $10

.macro text row, column, string
    .byte >($2000 + row * 32 + column), <($2000 + row * 32 + column)
    .byte .strlen(string), string
.endmacro



.segment "MENU"

    .assert * = MENU_ENTRY, error, "the game comes in at MENU_ENTRY"
    JMP menu_entry
    .assert * = SESSION_ENTRY, error, "and at SESSION_ENTRY, from its NMI in a session"
    JMP session_frame

.include "net/session.inc"



menu_entry:
    LDA #$00
    STA $2001
    STA $4015                   ; the title's tune stops here
    LDA #FONT_PAGE              ; the background's tiles
    LDX #$04
@bank:
    STA $DFFF
    LSR
    DEX
    BPL @bank
    LDA #$00
    LDX #MENU_VARS - 1
@clear:
    STA menu_vars,X
    DEX
    BPL @clear
    STA net_pending
    STA net_result
    LDA #NET_DELAY              ; until the nesp32 advises one
    STA menu_delay
    LDA #STATE_NONE             ; and no hello yet: whatever the nesp32
    STA menu_state              ; was doing ends with that
    LDA #$3F
    STA $2006
    LDA #$00
    STA $2006
    LDX #$00
@palette:
    LDA palette,X
    STA $2007
    INX
    CPX #$04
    BNE @palette
    JSR show_main

menu_loop:
    JSR menu_wait
    JSR menu_link
    JSR menu_draw
    LDA menu_mode
    ASL
    TAX
    LDA handlers + 1,X
    PHA
    LDA handlers,X
    PHA
    RTS

handlers:
    .word mode_main - 1, mode_hosting - 1, mode_edit - 1, mode_joining - 1

palette:
    .byte $0F, $30, $16, $00



; --- the first screen ------------------------------------------------------------

mode_main:
    LDA menu_press
    AND #BTN_UP
    BEQ @down
    LDA menu_cursor
    BEQ @down
    DEC menu_cursor
    JSR cursor_moved
@down:
    LDA menu_press
    AND #BTN_DOWN
    BEQ @pick
    LDA menu_cursor
    CMP #$02
    BEQ @pick
    INC menu_cursor
    JSR cursor_moved
@pick:
    LDA menu_press
    AND #BTN_A | BTN_START
    BEQ @loop
    LDA menu_cursor
    CMP #$02
    BEQ leave_local
    ; The other two need a nesp32 that is on a network.
    LDX menu_state
    BEQ @loop                   ; NESP_LOBBY_NO_WIFI
    CPX #STATE_OLD
    BCS @loop                   ; or STATE_NONE
    CMP #$00
    BNE @join
    LDA #NESP_PEER_HOST
    JSR command
    JSR show_hosting
    JMP menu_loop
@join:
    LDA menu_filled
    BNE @edit
    LDA #NESP_PEER_LAST
    JSR command
@edit:
    JSR show_join
@loop:
    JMP menu_loop

cursor_moved:
    LDA menu_dirty
    ORA #DIRTY_CURSOR
    STA menu_dirty
    RTS



; Back to the game, with no session.
leave_local:
    JSR screen_off
    LDA #$0F
    STA $4015
    LDA net_back
    STA net_vector
    LDA net_back + 1
    STA net_vector + 1
    LDA #$00
    JMP net_far

; Into a session, as player Y + 1.
leave_session:
    JSR screen_off
    LDX menu_delay
    LDA net_go
    STA net_vector
    LDA net_go + 1
    STA net_vector + 1
    LDA #$00
    JMP net_far



; --- waiting for player 2 ----------------------------------------------------------

mode_hosting:
    LDA menu_press
    AND #BTN_B
    BEQ @state
    LDA #NESP_PEER_LEAVE
    JSR command
    JSR show_main
    JMP menu_loop
@state:
    LDA menu_done
    BEQ @loop
    LDA menu_state
    CMP #NESP_LOBBY_HOST
    BNE @loop
    LDY #$00
    JMP leave_session
@loop:
    JMP menu_loop



; --- the address to join -------------------------------------------------------------

mode_edit:
    LDA menu_press
    AND #BTN_LEFT
    BEQ @right
    LDA menu_pos
    BEQ @right
    DEC menu_pos
    JSR mark_moved
@right:
    LDA menu_press
    AND #BTN_RIGHT
    BEQ @up
    LDA menu_pos
    CMP #11
    BEQ @up
    INC menu_pos
    JSR mark_moved
@up:
    LDX menu_pos
    LDA menu_press
    AND #BTN_UP
    BEQ @down
    INC menu_digits,X
    LDA menu_digits,X
    CMP #10
    BCC @changed
    LDA #$00
    STA menu_digits,X
    BEQ @changed
@down:
    LDA menu_press
    AND #BTN_DOWN
    BEQ @back
    DEC menu_digits,X
    BPL @changed
    LDA #$09
    STA menu_digits,X
@changed:
    LDA #$01
    STA menu_filled
    LDA menu_dirty
    ORA #DIRTY_DIGITS
    STA menu_dirty
@back:
    LDA menu_press
    AND #BTN_B
    BEQ @go
    JSR show_main
    JMP menu_loop
@go:
    LDA menu_press
    AND #BTN_A | BTN_START
    BEQ @loop
    LDA #NESP_PEER_JOIN
    JSR command
    LDA #MODE_JOINING
    STA menu_mode
    LDA #STATUS_CONNECTING
    JSR set_status
@loop:
    JMP menu_loop

mark_moved:
    LDA menu_dirty
    ORA #DIRTY_MARK
    STA menu_dirty
    RTS



mode_joining:
    LDA menu_press
    AND #BTN_B
    BEQ @state
    LDA #NESP_PEER_LEAVE
    JSR command
    LDA #STATUS_NONE
    BEQ @edit
@state:
    LDA menu_done
    BEQ @loop
    LDA menu_state
    CMP #NESP_LOBBY_CONNECTING
    BEQ @loop
    CMP #NESP_LOBBY_GUEST
    BNE @failed
    LDY #$01
    JMP leave_session
@failed:
    LDA #STATUS_FAILED
@edit:
    JSR set_status
    LDA #MODE_EDIT
    STA menu_mode
@loop:
    JMP menu_loop

set_status:
    STA menu_status
    LDA menu_dirty
    ORA #DIRTY_STATUS
    STA menu_dirty
    RTS



; --- the nesp32 ------------------------------------------------------------------------

; Send op A of PEER's, in place of the next question about the nesp32's
; state, and again until it is answered.
command:
    STA menu_want
    LDA #$00
    STA menu_done
    RTS

; Take the reply to the last request, if it has come or been given up, and
; make the next request when it is time.
menu_link:
    LDA net_result
    BNE @result
    JMP @send
@result:
    BPL @came
    JMP @missed
@came:
    LDA menu_sent
    CMP #HELLO
    BNE @reply
    JSR hello_answered
    JMP @clear
@reply:
    LDA nesp_status
    BEQ @good
    ; Not in use: the nesp32 was switched off and on, and knows of no hello.
    LDA #$00
    STA menu_linked
    BEQ @missed
@good:
    LDA #$00
    STA menu_misses
    LDX #$03
@address:
    LDA nesp_reply + 1,X
    STA menu_octets,X
    DEX
    BPL @address
    LDA menu_sent
    CMP #NESP_PEER_LAST
    BNE @state
    ; The address last joined, to start the edit from. With none, this
    ; nesp32's own: the other is most likely on the same network.
    LDA menu_octets
    ORA menu_octets + 1
    ORA menu_octets + 2
    ORA menu_octets + 3
    BEQ @own
    LDX #$00
    JSR octets_to_digits
    JMP @filled
@own:
    LDX #11
@copy:
    LDA menu_own,X
    STA menu_digits,X
    DEX
    BPL @copy
@filled:
    LDA #$01
    STA menu_filled
    LDA menu_dirty
    ORA #DIRTY_DIGITS
    STA menu_dirty
    BNE @answered
@state:
    LDA nesp_reply
    STA menu_state
    ; The delay to begin a session with, if the nesp32 gives one.
    LDA nesp_reply + 5
    BEQ @digits
    CMP #NET_DELAY_MAX + 1
    BCS @digits
    STA menu_delay
@digits:
    LDX #12
    JSR octets_to_digits
    LDA menu_dirty
    ORA #DIRTY_OWN
    STA menu_dirty
@answered:
    ; Is that the answer to the op the screen is waiting on?
    LDA menu_sent
    BEQ @clear
    LDA menu_want
    BNE @clear
    LDA #$01
    STA menu_done
    BNE @clear
@missed:
    LDA menu_sent               ; an op is sent again; a hello is anyway
    BEQ @count
    CMP #HELLO
    BEQ @count
    LDA menu_want
    BNE @count
    LDA menu_sent
    STA menu_want
@count:
    INC menu_misses
    LDA menu_misses
    CMP #MISSES
    BCC @clear
    DEC menu_misses
    LDA #$00                    ; whatever answers next is asked who it is
    STA menu_linked
    LDA #STATE_NONE
    JSR set_state
@clear:
    LDA #$00
    STA net_result
@send:
    LDA net_pending
    BNE @RTS
    ; A request every fourth frame at most: with no nesp32 each one is a
    ; third of a frame spent waiting, and an op is sent until answered.
    LDA menu_count
    AND #$03
    BNE @RTS
    LDA menu_linked
    BNE @linked
    LDA #HELLO
    STA menu_sent
    BNE @go
@linked:
    LDA menu_want
    BNE @request
    LDA menu_count
    AND #$0F
    BNE @RTS
    ; A = 00, NESP_PEER_STATUS
@request:
    STA menu_sent
    LDY #$00
    CMP #NESP_PEER_JOIN
    BNE @length
    JSR digits_to_octets
    LDX #$03
@payload:
    LDA menu_octets,X
    STA nesp_request,X
    DEX
    BPL @payload
    LDY #$04
@length:
    STY menu_len
    LDA #$00
    STA menu_want
@go:
    LDA #$01
    STA net_pending
@RTS:
    RTS

.assert NESP_PEER_STATUS = 0, error, "menu_link takes NESP_PEER_STATUS for no op"

; The hello has been answered. With any status but OK the firmware has no
; PEER, or speaks another protocol.
hello_answered:
    LDA nesp_status
    BEQ @linked
    LDA #STATE_OLD
    BNE set_state
@linked:
    LDA #$01
    STA menu_linked
    LDA #$00
    STA menu_misses
    LDA #$0F                    ; the first question follows at once
    STA menu_count
    ; A nesp32 that was switched off and on has forgotten what it was told.
    LDA menu_want
    BNE @RTS
    LDA menu_mode
    CMP #MODE_HOSTING
    BNE @joining
    LDA #NESP_PEER_HOST
    BNE @again
@joining:
    CMP #MODE_JOINING
    BNE @RTS
    LDA #NESP_PEER_JOIN
@again:
    JMP command
@RTS:
    RTS

; The nesp32's state is A, if that is news.
set_state:
    CMP menu_state
    BEQ @RTS
    STA menu_state
    LDA menu_dirty
    ORA #DIRTY_OWN
    STA menu_dirty
@RTS:
    RTS

; The request menu_link made, and its reply: from the NMI, as every
; exchange is.
menu_exchange:
    LDX menu_sent
    CPX #HELLO
    BNE @op
    LDA #NESP_SVC_PEER
    STA nesp_request + NESP_HELLO_FIXED
    LDY #$01
    JSR nesp_hello
    JMP @result
@op:
    LDY menu_len
    LDA #NESP_SVC_PEER
    JSR nesp_call
@result:
    LDA #$00
    STA net_pending
    LDA #$01
    BCC @store
    LDA #$FF
@store:
    STA net_result
    RTS



; --- addresses -----------------------------------------------------------------------

; menu_octets as 12 digits at menu_digits + X (X = 12: menu_own).
octets_to_digits:
    LDY #$00
@octet:
    STY menu_tmp
    LDA menu_octets,Y
    LDY #$00
@hundreds:
    CMP #100
    BCC @tens
    SBC #100
    INY
    BNE @hundreds
@tens:
    PHA
    TYA
    STA menu_digits,X
    PLA
    LDY #$00
@ten:
    CMP #10
    BCC @ones
    SBC #10
    INY
    BNE @ten
@ones:
    STA menu_digits + 2,X
    TYA
    STA menu_digits + 1,X
    INX
    INX
    INX
    LDY menu_tmp
    INY
    CPY #$04
    BNE @octet
    RTS

; menu_digits as menu_octets. Three digits past 255 are 255.
digits_to_octets:
    LDX #$00
    LDY #$00
@octet:
    LDA menu_digits,X           ; hundreds and tens: 0-99
    ASL
    STA menu_tmp
    ASL
    ASL
    CLC
    ADC menu_tmp
    ADC menu_digits + 1,X
    CMP #26
    BCS @most
    ASL                         ; and ten times that: 0-250
    STA menu_tmp
    ASL
    ASL
    ADC menu_tmp
    ADC menu_digits + 2,X
    BCC @store
@most:
    LDA #255
@store:
    STA menu_octets,Y
    INX
    INX
    INX
    INY
    CPY #$04
    BNE @octet
    RTS



; --- drawing -------------------------------------------------------------------------

; Draw one of the things that have changed, if the NMI has drawn the last.
menu_draw:
    LDA menu_draw_len
    BNE draw_RTS
    LDA menu_dirty
    LSR
    BCS draw_own
    LSR
    BCS draw_digits
    LSR
    BCS draw_mark
    LSR
    BCS draw_to_status
    LSR
    BCC draw_RTS
    JMP draw_cursor
draw_to_status:
    JMP draw_status
draw_RTS:
    RTS

draw_own:
    LDA #DIRTY_OWN
    JSR drawn
    LDA menu_mode
    CMP #MODE_HOSTING
    BEQ draw_own_row
    CMP #MODE_MAIN
    BNE draw_RTS
draw_own_row:
    LDA menu_state
    LDX #STATUS_NO_WIFI
    CMP #NESP_LOBBY_NO_WIFI
    BEQ draw_why
    LDX #STATUS_NO_NESP32
    CMP #STATE_NONE
    BEQ draw_why
    LDX #STATUS_OLD
    CMP #STATE_OLD
    BEQ draw_why
    LDX #12
    JSR digits_to_line
    JMP draw_own_at
draw_why:
    JSR text_to_line
draw_own_at:
    LDA menu_mode
    CMP #MODE_HOSTING
    BEQ draw_host_row
    LDX #<($2000 + 20 * 32 + 8)
    LDY #>($2000 + 20 * 32 + 8)
    BNE draw_stage
draw_host_row:
    LDX #<($2000 + 14 * 32 + 8)
    LDY #>($2000 + 14 * 32 + 8)
draw_stage:
    LDA #IP_TILES
stage:
    STX menu_draw_lo
    STY menu_draw_hi
    STA menu_draw_len
    RTS

draw_digits:
    LDA #DIRTY_DIGITS
    JSR drawn
    JSR joining
    BCC draw_RTS
    LDX #$00
    JSR digits_to_line
    LDX #<($2000 + 12 * 32 + 8)
    LDY #>($2000 + 12 * 32 + 8)
    BNE draw_stage

draw_mark:
    LDA #DIRTY_MARK
    JSR drawn
    JSR joining
    BCC draw_RTS
    ; A dash under the digit: its place in the line is its number and one
    ; more for each dot before it.
    LDX #IP_TILES - 1
    LDA #TILE_BLANK
draw_blank:
    STA menu_line,X
    DEX
    BPL draw_blank
    LDA menu_pos
    LDX #$00
    CMP #$03
    BCC draw_place
    INX
    CMP #$06
    BCC draw_place
    INX
    CMP #$09
    BCC draw_place
    INX
draw_place:
    STX menu_tmp
    CLC
    ADC menu_tmp
    TAX
    LDA #TILE_DASH
    STA menu_line,X
    LDX #<($2000 + 13 * 32 + 8)
    LDY #>($2000 + 13 * 32 + 8)
    JMP draw_stage

draw_status:
    LDA #DIRTY_STATUS
    JSR drawn
    JSR joining
    BCC draw_done
    LDX menu_status
    JSR text_to_line
    LDX #<($2000 + 16 * 32 + 8)
    LDY #>($2000 + 16 * 32 + 8)
    JMP draw_stage

draw_cursor:
    ; The mark goes from its old place, then comes at its new one.
    LDA menu_mode
    BNE draw_cursor_done
    LDA #TILE_BLANK
    LDX menu_shown
    BPL draw_one
    LDA #TILE_CURSOR
    LDX menu_cursor
draw_one:
    STA menu_line
    CPX menu_shown
    BNE draw_came
    LDA #$FF
    STA menu_shown
    BNE draw_where
draw_came:
    STX menu_shown
    LDA #DIRTY_CURSOR
    JSR drawn
draw_where:
    LDY cursor_hi,X
    LDA cursor_lo,X
    TAX
    LDA #$01
    JMP stage
draw_cursor_done:
    LDA #DIRTY_CURSOR
    JSR drawn
draw_done:
    RTS

cursor_lo:
    .byte <($2000 + 9 * 32 + 9), <($2000 + 11 * 32 + 9), <($2000 + 13 * 32 + 9)
cursor_hi:
    .byte >($2000 + 9 * 32 + 9), >($2000 + 11 * 32 + 9), >($2000 + 13 * 32 + 9)

; Take A out of what is to be drawn.
drawn:
    EOR #$FF
    AND menu_dirty
    STA menu_dirty
    RTS

; Carry set on the join screen.
joining:
    LDA menu_mode
    CMP #MODE_EDIT
    RTS

.assert MODE_JOINING > MODE_EDIT && MODE_HOSTING < MODE_EDIT && MODE_MAIN < MODE_EDIT, error

; 12 digits at menu_digits + X into menu_line, with their dots.
digits_to_line:
    LDY #$00
@digit:
    LDA menu_digits,X
    STA menu_line,Y
    INX
    INY
    TYA
    AND #$03
    CMP #$03
    BNE @next
    LDA #TILE_DOT
    STA menu_line,Y
    INY
@next:
    CPY #IP_TILES + 1
    BCC @digit
    RTS

; One of status_texts into menu_line.
text_to_line:
    LDY #$00
@tile:
    LDA status_texts,X
    STA menu_line,Y
    INX
    INY
    CPY #IP_TILES
    BNE @tile
    RTS

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



; The three screens. Each is drawn whole, with the picture off.
show_main:
    LDA #MODE_MAIN
    LDX #<screen_main
    LDY #>screen_main
    JSR show
    LDA #$FF
    STA menu_shown
    LDA #DIRTY_OWN | DIRTY_CURSOR
    STA menu_dirty
    RTS

show_hosting:
    LDA #MODE_HOSTING
    LDX #<screen_hosting
    LDY #>screen_hosting
    JSR show
    LDA #DIRTY_OWN
    STA menu_dirty
    RTS

show_join:
    LDA #STATUS_NONE
    STA menu_status
    LDA #MODE_EDIT
    LDX #<screen_join
    LDY #>screen_join
    JSR show
    LDA #DIRTY_DIGITS | DIRTY_MARK
    STA menu_dirty
    RTS

; Mode A, and its screen at Y:X.
show:
    STA menu_mode
    JSR screen_off              ; the NMI's exchange uses menu_ptr's bytes
    STX menu_ptr
    STY menu_ptr + 1
    LDA #$20
    STA $2006
    LDA #$00
    STA $2006
    ; 960 blank tiles, and 64 attributes: the one palette.
    LDA #TILE_BLANK
    LDY #$04
    LDX #$C0
@tiles:
    STA $2007
    DEX
    BNE @tiles
    DEY
    BNE @tiles
    LDA #$00
    LDX #$40
@attributes:
    STA $2007
    DEX
    BNE @attributes
    LDY #$00
@string:
    LDA (menu_ptr),Y
    BEQ @shown
    STA $2006
    INY
    LDA (menu_ptr),Y
    STA $2006
    INY
    LDA (menu_ptr),Y
    TAX
    INY
@tile:
    LDA (menu_ptr),Y
    STA $2007
    INY
    DEX
    BNE @tile
    BEQ @string
@shown:
    LDA #$90                    ; the NMI on: it turns the picture on
    STA $2000
    RTS

; The picture and the NMI off, and nothing left for the NMI to draw.
screen_off:
    LDA #$00
    STA $2000
    STA $2001
    STA menu_draw_len
    RTS

screen_main:
    text 4, 10, "NETWORK GAME"
    text 9, 11, "HOST GAME"
    text 11, 11, "JOIN GAME"
    text 13, 11, "LOCAL GAME"
    text 18, 7, "THIS NESP32 IS AT"
    .byte 0

screen_hosting:
    text 4, 10, "NETWORK GAME"
    text 9, 6, "WAITING FOR PLAYER 2"
    text 12, 7, "PLAYER 2 JOINS AT"
    text 24, 12, "B - BACK"
    .byte 0

screen_join:
    text 4, 10, "NETWORK GAME"
    text 9, 8, "JOIN THE GAME AT"
    text 22, 8, "START - CONNECT"
    text 24, 12, "B - BACK"
    .byte 0



; --- frames --------------------------------------------------------------------------

; Wait for the NMI, and work out which buttons went down.
menu_wait:
    LDA #$00
    STA menu_frame
@wait:
    LDA menu_frame
    BEQ @wait
    LDA menu_pad
    TAY
    EOR menu_pad_old
    AND menu_pad
    STA menu_press
    STY menu_pad_old
    INC menu_count
    RTS

menu_nmi:
    PHA
    TXA
    PHA
    TYA
    PHA
    LDA menu_draw_len
    BEQ @picture
    LDA $2002
    LDA menu_draw_hi
    STA $2006
    LDA menu_draw_lo
    STA $2006
    LDX #$00
@tile:
    LDA menu_line,X
    STA $2007
    INX
    CPX menu_draw_len
    BNE @tile
    LDA #$00
    STA menu_draw_len
@picture:
    LDA #$90
    STA $2000
    LDA #$00
    STA $2005
    STA $2005
    LDA #$0A                    ; the background, and no sprites
    STA $2001
    ; The controller. OUT0 rests at mark, as in the game.
    LDX #$00
    STX $4016
    LDX #$08
@button:
    LDA $4016
    LSR
    ROL menu_pad
    DEX
    BNE @button
    INX
    STX $4016
    LDA net_pending
    BEQ @done
    JSR menu_exchange
@done:
    LDA #$01
    STA menu_frame
    PLA
    TAY
    PLA
    TAX
    PLA
menu_irq:
    RTI



.segment "COMMON"
net_boot = $FF00                ; never reached from here: see net_common
menu_reset:
    net_common

.segment "VECTORS"
    .word menu_nmi, menu_reset, menu_irq

; Serial link: a nesp32 on controller port 2 holds the music. The link ROM's
; host, in place of fake_link.inc.
;
; Provides link_init, link_service, link_button and the link_nmi_hook macro.
;
; The link itself is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md):
; one firmware on the nesp32 serves every ROM, and this one asks it for the
; JUKE service, and for RAW, which carries sampled sound. Every use of the
; link is one exchange: a request goes out, and one reply comes back or does
; not. The NMI is the timeout: an exchange that has not ended by the next
; vblank is dropped there and reported as failed.
;
; Right after an NMI, link_service makes the frame's one exchange. Most
; frames that is JUKE STREAM: "this is where I have got to in the stream,
; and I have room for this much more", answered with the bytes from there,
; which go into the ring. Nothing needs asking twice in any special way: a
; reply that was lost is the same question again a frame later, with the
; same position, and the same bytes come.
;
; The reply says which epoch its bytes belong to. An epoch is a stretch of
; the stream with no jump in it; a reply from another one than the ring's
; (another track, stop, the music after a sound) means that what the ring
; holds is not wanted, and it is dropped before the reply's bytes go in.
;
; A press on the controller (ui.inc) goes out as JUKE BUTTON, in place of
; one frame's stream request, and is sent again until it is answered. The
; nesp32 does it once however often it hears it, and what comes of it is
; the stream it then sends, usually in a new epoch.
;
; While the music is stopped the screen is a menu of the tracks, a row
; each where the bars go, with the cursor's game and name over it where a
; track's are. Up and Down move the cursor, Left and Right a page; A or
; Start plays its track (JUKE CHOOSE), and Select is the cartridge's menu again.
; The nesp32 says how many tracks there are and their names, a track at a
; time (JUKE LIST), in place of a frame's stream request: a row is drawn
; when its names come. With the music playing, A or Start plays and
; pauses, Left and Right are the track before and after, and B stops it,
; which is the menu again. The foot says what A and B do: B is read only
; with the NMI on, so not while sampled sound plays.
;
; Sampled sound (docs/PROTOCOL.md, part 4) takes the line over. When the
; NMI plays a sound record, link_service asks for the sound (JUKE SOUND) in
; place of the stream. If the answer is GO, the console does nothing but
; receive from there: the NMI is off, the screen stands still, and one of
; the routines in pcm_rates.inc writes each byte to $4011 as it arrives, at
; a rate several times the link's own, until a byte marked as the last.
; Then the NMI goes back on and the link carries on where it was.
;
; Button A is all of the controller that is looked at during a sound, and
; it pauses: the console leaves the sound, tells the nesp32 so, and is back
; with the NMI on and the whole controller read. The sound is still wanted,
; and the nesp32 says the music is paused, so the stream is asked for until
; it says otherwise; then the sound is, and goes on from where it was left.
;
; The nesp32 knows this ROM by its hello, which goes out before anything
; else and again whenever the nesp32 says it has no such service in use: it
; was switched off and on, and has forgotten the hello.

OUT0_MARK = $01

NESP_RX_MASK = $3F              ; replies of up to 63 bytes
NESP_TX_MAX  = 10               ; the hello, with its three services
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a reply is checked and in the
                                ; ring well inside the frame it arrived in
.define NESP_APP "JUKE"
NESP_APP_VERSION = 2

NESP_KEY_PAD = 1                ; the Bluetooth keyboard's keys as the controller's buttons
.include "nesp.inc"
.include "pcm_rates.inc"

.assert NESP_TX_MAX = NESP_HELLO_FIXED + 3, error, "the hello names three services"

; JUKE STREAM's reply (nesp32's docs/PROTOCOL.md): the state of the music,
; the epoch its bytes belong to, and the bytes.
STREAM_STATE = nesp_reply
STREAM_EPOCH = nesp_reply + 1
STREAM_BYTES = nesp_reply + 2
STREAM_HEAD  = 2
; JUKE SOUND's: the state, and whether the sound is coming.
SOUND_ANSWER = nesp_reply + 1

; The most a reply brings: a frame of 65 bytes is 15015 cycles on the line,
; and with the request before it and the NMI before that it leaves the nesp32
; some 4 ms to answer in (docs/PROTOCOL.md, "Timing").
CREDIT_MAX = 56
.assert CREDIT_MAX + STREAM_HEAD <= NESP_RX_MASK, error, "a reply must fit its buffer"

BUTTON_TRIES = 30               ; frames a press is sent for before it is given up
MISSED_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is not there

; wait_unit is 2306 cycles. A run of RAW's is listened for from
; NESP_RAW_SETTLE_MS after the reply that agreed to it, while the nesp32
; makes sure and changes its rate, and NESP_RAW_REST_MS pass after its last
; byte, while it changes back.
UNIT_CYCLES = 2306
SOUND_SETTLE = NESP_RAW_SETTLE_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
SOUND_REST = NESP_RAW_REST_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
.assert SOUND_SETTLE > 0 && SOUND_SETTLE < 256 && SOUND_REST > 0, error, "waits are counted in X"

.segment "ZEROPAGE"
credit:      .res 1             ; bytes of room this frame's request says there are
rx_count:    .res 1             ; bytes of the stream in the reply
sound_vector: .res 2            ; the routine for the rate

.segment "BSS"
greeted:     .res 1             ; the nesp32 has answered this ROM's hello
link_epoch:  .res 1             ; the epoch of what the ring holds
link_pos:    .res 1             ; how many of its bytes have been taken, less a multiple of 256
link_fresh:  .res 1             ; a hello has been said since the last reply's bytes
button_pending: .res 1          ; EVENT_* bits not yet sent
choose_pending: .res 1          ; a track of the menu's to play, plus one; 0 for none
button_sending: .res 1          ; a press is out and unanswered: the frames it has left
link_missed: .res 1             ; exchanges in a row with no reply, up to MISSED_MAX
link_failed: .res 2             ; every exchange with none, for a debugger's watch list
view:        .res 1             ; VIEW_*, or $FF before the first
menu_new:    .res 1             ; the menu has come: how many tracks, and which, to ask
menu_count:  .res 1             ; tracks in it
menu_cursor: .res 1             ; the one A plays
menu_top:    .res 1             ; the one on its first row
paint_rows:  .res 1             ; a bit for each of its rows still to draw, first row lowest
list_asked:  .res 1             ; the track a LIST asked about
presses:     .res 1             ; the main loop's copy of pad_new
list_left:   .res 1             ; ask_list's and show_name's: characters still to copy,
list_line:   .res 1             ; the line they go on,
list_from:   .res 1             ; and where they come from in the reply
on_cart:     .res 1             ; this is on nesp32's cartridge, which has a menu
keys_ok:     .res 1             ; the hello had KBD: what is typed is asked for
key_at:      .res 1             ; ask_keys's: the next key of its reply
KEYS_EVERY = $07                ; every eighth frame, in place of the stream,
KEYS_ROOM = 2 * CREDIT_MAX      ; while the ring has less room than this

VIEW_MENU   = 0
VIEW_PLAYER = 1

; The cartridge's reset stub (nesp32's nes/cart/gen_cart.py) is at the same
; place in every program's bank: an `inc` of itself, which resets the
; mapper and puts the menu's bank at $C000, and a jump to the menu. Built by
; itself, this ROM has padding there. As Bluesky's Select does.
CART_STUB = $FFDA
CART_STUB_FIRST = $EE           ; inc absolute

; JUKE LIST's reply: the state, how many tracks, the one play would start,
; and with names, the track's number, its game's name's length, the game's
; name and the track's.
LIST_COUNT   = nesp_reply + 1
LIST_CURRENT = nesp_reply + 2
LIST_INDEX   = nesp_reply + 3
LIST_GAME    = nesp_reply + 4
LIST_HEAD    = 5

.segment "RODATA"
row_bit: .byte $01, $02, $04, $08, $10, $20, $40, $80
.assert LIST_ROWS = 8, error, "paint_rows has a bit for each row"

.segment "CODE"

.macro link_nmi_hook
    nesp_nmi_hook
.endmacro

; OUT0 rests at mark, which is also what keeps the controller loading its
; buttons (ui.inc). The hello waits for link_service.
.proc link_init
    lda #OUT0_MARK
    sta JOY1
    lda #$FF                    ; no view yet: the first is the menu
    sta view
    lda CART_STUB
    cmp #CART_STUB_FIRST
    bne @alone
    inc on_cart
@alone:
    rts
.endproc

; The controller asked for something (EVENT_* bits in A). Called from the
; NMI; the main loop sends it with its next exchange.
.proc link_button
    ora button_pending
    sta button_pending
    rts
.endproc
.assert EVENT_NEXT = NESP_PRESS_NEXT, error, "the controller's bits are JUKE's"
.assert EVENT_PREV = NESP_PRESS_PREVIOUS, error, "the controller's bits are JUKE's"
.assert EVENT_PLAY = NESP_PRESS_PLAY, error, "the controller's bits are JUKE's"
.assert EVENT_STOP = NESP_PRESS_STOP, error, "the controller's bits are JUKE's"

; The frame's exchange. An exchange that the next NMI cut off comes back
; here with carry set and frame_count moved on, so the main loop serves the
; new frame at once; one that ended inside its frame, good or not, leaves
; the next for the next NMI.
.proc link_service
    jsr menu_frame
    lda greeted
    bne @greeted
    jmp say_hello
@greeted:
    lda button_sending
    beq @no_resend
    jsr nesp_again              ; the same request, byte for byte: done once
    jmp button_answer           ; however often it is heard
@no_resend:
    lda choose_pending
    beq @no_choice
    sec
    sbc #1
    sta nesp_request
    lda #0
    sta choose_pending
    lda #BUTTON_TRIES
    sta button_sending
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_CHOOSE
    ldy #1
    jsr nesp_call
    jmp button_answer
@no_choice:
    lda button_pending
    beq @no_button
    sta nesp_request
    lda #0
    sta button_pending
    lda #BUTTON_TRIES
    sta button_sending
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_BUTTON
    ldy #1
    jsr nesp_call
    jmp button_answer
@no_button:
    jsr keys_due
    bcc @sound
    jmp ask_keys
@sound:
    lda sound_wanted
    beq @music
    lda paused                  ; held: the stream's reply says when it is not
    bne @music
    lda pad                     ; A still down would end the sound as it began
    and #PAD_A
    bne @music
    jmp ask_sound
@music:
    lda view
    bne @stream
    lda menu_new                ; the menu: how many tracks, and which
    beq @rows
    lda #0
    jmp ask_list
@rows:
    jsr row_track               ; or the names of a row's track
    bcs @stream
    jmp ask_list
@stream:
    jmp ask_stream
.endproc

; Hello: this is the jukebox, and it needs JUKE and RAW. A nesp32 that
; lacks either, or speaks another protocol, has older firmware than this
; ROM, and the screen says so. It asks for KBD too, though it takes no
; keys, so that the keyboard stays connected from one program on the
; cartridge to the next; a nesp32 without KBD is one to use.
.proc say_hello
    lda #NESP_SVC_JUKE
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_RAW
    sta nesp_request + NESP_HELLO_FIXED + 1
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED + 2
    ldy #3
    jsr nesp_hello
    bcc @came
    jmp link_silent
@came:
    ldx #1
    cmp #NESP_ST_OK
    beq @greeted
    cmp #NESP_ST_NO_SERVICE     ; only KBD missing is a nesp32 to use
    bne @old
    lda nesp_reply + 6
    cmp #1
    bne @old
    lda nesp_reply + 7
    cmp #NESP_SVC_KBD
    bne @old
    dex
@greeted:
    stx keys_ok
    lda #1
    sta greeted
    sta link_fresh              ; whatever the ring holds, the nesp32 knows nothing of it
    lda view
    bne @playing
    jsr menu_again              ; and its tracks may be others
@playing:
    lda #0
    sta link_pos
    sta button_sending
    jmp link_heard
@old:
    lda #LINK_OLD
    sta link_state
    jmp link_heard
.endproc

; --- the menu ------------------------------------------------------------------

; Every frame, before its exchange: the view follows the music, the buttons
; are taken, the foot says what they do, and a row that needs no names is
; drawn.
.proc menu_frame
    jsr follow_view
    jsr take_buttons
    jsr pick_foot
    jmp paint_step
.endproc

; The menu while the music is stopped, or there is none, or no nesp32; the
; player while it plays or is paused. Either way every row of the menu is
; drawn again, as the menu or as blanks over it, and the bars wait for
; that.
.proc follow_view
    ldx #VIEW_MENU
    lda link_state
    cmp #LINK_STREAMING
    bne @want
    ldx #VIEW_PLAYER
@want:
    cpx view
    beq @done
    stx view
    lda #1
    sta bars_off
    lda #$FF
    sta paint_rows
    ldx #BAR_COUNT - 1          ; the rows go over the bars, which are down after
    lda #0
@bar:
    sta ui_level,x
    sta ui_drawn,x
    dex
    bpl @bar
    lda view
    bne @done
    jsr menu_again
    ldx #TITLE_MAX - 1          ; the cursor's game and name go where a track's do;
    lda #' '                    ; the clock's line is blank, and does not flash
@line:
    sta game_buf,x
    sta title_buf,x
    dex
    bpl @line
    ldx #TIME_WIDTH - 1
    lda #0
@time:
    sta time_buf,x
    dex
    bpl @time
    lda #PENDING_GAME | PENDING_TITLE | PENDING_TIME
    ora text_pending
    sta text_pending
@done:
    rts
.endproc

; The menu is to be had from the nesp32 again: how many tracks, and which
; play would start, and then every row.
.proc menu_again
    lda #1
    sta menu_new
    lda #$FF
    sta paint_rows
    rts
.endproc

; What the buttons that went down since the last frame ask for.
.proc take_buttons
    jsr nesp_key_next           ; and a key typed that stands for buttons
    ldx #0
    ora pad_new
    stx pad_new
    bne @some
@done:
    rts
@some:
    sta presses
    and #PAD_SELECT             ; Select: back to the cartridge's menu, from
    beq @no_quit                ; either view, with a nesp32 or none
    lda on_cart
    beq @no_quit
    jmp quit
@no_quit:
    lda view
    beq @menu
    bmi @done                   ; no view yet
    lda presses                 ; the player: JUKE BUTTON's bits
    and #PAD_RIGHT | PAD_LEFT   ; these are EVENT_NEXT and EVENT_PREV
    tay
    lda presses
    and #PAD_A | PAD_START
    beq @no_play
    tya
    ora #EVENT_PLAY
    tay
@no_play:
    lda presses
    and #PAD_B
    beq @send
    ldy #EVENT_STOP             ; B: back to the menu, and nothing else
@send:
    tya
    beq @done
    jmp link_button
@menu:
    lda menu_new                ; B: nothing to go back to
    bne @done
    lda menu_count
    beq @done                   ; nothing to choose
    lda presses
    and #PAD_A | PAD_START
    beq @move
    ldx menu_cursor
    inx
    stx choose_pending
    rts
@move:
    ldy menu_cursor             ; Y: where it was
    ldx menu_cursor
    lda presses
    and #PAD_UP
    beq @down
    dex
    cpx #$FF
    bne @moved
    ldx menu_count              ; from the first round to the last
    dex
    jmp @moved
@down:
    lda presses
    and #PAD_DOWN
    beq @page_up
    inx
    cpx menu_count
    bcc @moved
    ldx #0                      ; and from the last to the first
    beq @moved
@page_up:
    lda presses
    and #PAD_LEFT
    beq @page_down
    txa
    sec
    sbc #LIST_ROWS
    bcs @to
    lda #0
    beq @to
@page_down:
    lda presses
    and #PAD_RIGHT
    beq @still
    txa
    clc
    adc #LIST_ROWS
    bcs @last
    cmp menu_count
    bcc @to
@last:
    lda menu_count
    sec
    sbc #1
@to:
    tax
@moved:
    stx menu_cursor
    cpy menu_cursor
    bne @changed
@still:
    rts
@changed:
    tya                         ; the row it left is drawn again,
    sec
    sbc menu_top
    tax
    lda row_bit,x
    ora paint_rows
    sta paint_rows
    lda menu_cursor             ; and the one it came to, if it is on the page
    sec
    sbc menu_top
    cmp #LIST_ROWS
    bcs @place
    tax
    lda row_bit,x
    ora paint_rows
    sta paint_rows
@place:
    jmp place_top
.endproc

; The page has the cursor on it: if it is above the first row, it is the
; first row; if it is below the last, the last. A page that moves is all
; drawn again.
.proc place_top
    lda menu_cursor
    cmp menu_top
    bcc @set
    sec
    sbc menu_top
    cmp #LIST_ROWS
    bcc @done
    lda menu_cursor
    sbc #LIST_ROWS - 1          ; carry is set
@set:
    sta menu_top
    lda #$FF
    sta paint_rows
@done:
    rts
.endproc

; The foot: on the menu, A chooses, and on the cartridge Select is its
; menu; in the player, A plays and pauses, and B is the menu again but
; while sampled sound plays, when it cannot be read. B never leaves the
; program, so that B pressed again and again cannot.
.proc pick_foot
    lda view
    bne @player
    lda #FOOT_CART
    ldx on_cart
    bne @set
    lda #FOOT_ALONE
    jmp @set
@player:
    lda #FOOT_BACK
    ldx sound_wanted
    beq @set
    ldx paused
    bne @set
    lda #FOOT_PLAIN
@set:
    sta foot
    rts
.endproc

; A row of the menu to draw, if the last one has been drawn: blank in the
; player, and on the menu past its last track. The bars come back once the
; player's rows are all blank. A row with a track on it waits for its names
; (row_track, and ask_list).
.proc paint_step
    lda row_dirty
    bne @done
    lda paint_rows
    bne @some
    lda view
    beq @done
    lda #0                      ; the player's rows are blank: the bars
    sta bars_off
@done:
    rts
@some:
    jsr lowest_row
    lda view
    beq @menu
@blank:
    jsr row_place
    lda #0
    ldy #LIST_WIDTH - 1
@clear:
    sta row_buf,y
    dey
    bpl @clear
    inc row_dirty
    rts
@menu:
    lda menu_new
    bne @done
    txa
    clc
    adc menu_top
    cmp menu_count
    bcs @blank
    rts
.endproc

; X = the first row still to draw.
.proc lowest_row
    ldx #0
    lda paint_rows
@bit:
    lsr a
    bcs @found
    inx
    bne @bit
@found:
    rts
.endproc

; Row X is the one being drawn: where it goes, and that it is not to be
; drawn again. Preserves X.
.proc row_place
    lda list_addr_hi,x
    sta row_addr
    lda list_addr_lo,x
    sta row_addr + 1
    lda row_bit,x
    eor #$FF
    and paint_rows
    sta paint_rows
    rts
.endproc

; The track whose names the menu wants next, in A, with carry clear; carry
; set if it wants none.
.proc row_track
    lda row_dirty
    bne @none
    lda paint_rows
    beq @none
    jsr lowest_row
    txa
    clc
    adc menu_top
    cmp menu_count
    bcs @none
    clc
    rts
@none:
    sec
    rts
.endproc

; JUKE LIST: how many tracks there are, and the names of track A. The
; first after the menu has come puts the cursor on the track play would
; start; after that, a row is drawn when its track's names come, and the
; cursor's are where a track's game and name go.
.proc ask_list
    sta list_asked
    sta nesp_request
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_LIST
    ldy #1
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
    jsr take_state
    lda menu_new
    beq @known
    lda LIST_COUNT              ; the menu has come
    sta menu_count
    lda LIST_CURRENT
    cmp menu_count
    bcc @current
    lda #0
@current:
    sta menu_cursor
    lda #0
    sta menu_new
    sta menu_top
    jsr place_top
    lda #$FF
    sta paint_rows
@heard:
    jmp link_heard
@known:
    lda LIST_COUNT
    cmp menu_count
    beq @same
    jsr menu_again              ; the nesp32 has other tracks now
    jmp link_heard
@same:
    lda nesp_reply_len
    cmp #LIST_HEAD
    bcc @heard                  ; no names yet: asked again next frame
    lda LIST_INDEX
    cmp list_asked
    bne @heard
    jsr row_track               ; and the row still wants them
    bcs @heard
    cmp list_asked
    bne @heard
    jsr row_place
    ldy #LIST_WIDTH - 1         ; the track's name after the cursor, or a blank
    lda #' '
@clear:
    sta row_buf,y
    dey
    bpl @clear
    lda list_asked
    cmp menu_cursor
    bne @name
    ldy #LIST_NAME - 1
@cursor:
    lda list_cursor,y
    sta row_buf,y
    dey
    bpl @cursor
@name:
    lda LIST_GAME               ; where the track's name is, and how long
    clc
    adc #LIST_HEAD
    tax
    lda nesp_reply_len
    sec
    sbc LIST_GAME
    sbc #LIST_HEAD              ; carry is set
    bcc @drawn
    beq @drawn
    tay
    cpy #LIST_WIDTH - LIST_NAME
    bcc @fits
    ldy #LIST_WIDTH - LIST_NAME
@fits:
    sty list_left
    ldy #LIST_NAME
@char:
    lda nesp_reply,x
    sta row_buf,y
    inx
    iny
    dec list_left
    bne @char
@drawn:
    inc row_dirty
    lda list_asked
    cmp menu_cursor
    beq @cursor_names
    jmp link_heard
@cursor_names:
    ; The cursor's: its game and name where a track's go.
    ldx #LINE_GAME
    ldy #LIST_HEAD
    lda LIST_GAME
    jsr show_name
    ldx #LINE_TITLE
    lda LIST_GAME
    clc
    adc #LIST_HEAD
    tay
    lda nesp_reply_len
    sec
    sbc LIST_GAME
    sbc #LIST_HEAD              ; carry is set
    jsr show_name
    jmp link_heard
.endproc

; A name from the reply, from nesp_reply + Y and A long, centered on the
; line at X (LINE_GAME or LINE_TITLE), which a coming vblank draws.
.proc show_name
    cmp #TITLE_MAX + 1
    bcc @fits
    lda #TITLE_MAX
@fits:
    sta list_left
    stx list_line
    sty list_from
    ldy #TITLE_MAX
    lda #' '
@clear:
    sta text_lines,x
    inx
    dey
    bne @clear
    lda #TITLE_MAX
    sec
    sbc list_left
    lsr a
    clc
    adc list_line
    tax                         ; where it begins
    ldy list_from
    lda list_left
    beq @drawn
@char:
    lda nesp_reply,y
    sta text_lines,x
    inx
    iny
    dec list_left
    bne @char
@drawn:
    lda #PENDING_GAME
    ldx list_line
    beq @pending
    lda #PENDING_TITLE
@pending:
    ora text_pending
    sta text_pending
    rts
.endproc
.assert LINE_GAME = 0, error, "show_name tells the lines apart by zero"

; Back to the cartridge's menu, as reset would go: through its stub, with
; the NMI off first, since the stub's `inc` puts the menu's bank, and its
; NMI, under this. The menu says hello to the nesp32 (KBD alone), and the
; next program's hello is what tells it which one runs.
.proc quit
    lda #0
    sta PPUCTRL
    sta PPUMASK
    sta APU_STATUS
    jmp CART_STUB
.endproc

; Carry set if this frame's exchange is to ask what has been typed: every
; eighth frame, with a nesp32 that has KBD, and only where the stream can
; spare it, on the menu or with the ring nearly full. The ring's room is
; asked first, as the stream's request asks it.
.proc keys_due
    lda keys_ok
    beq @no
    lda frame_count
    and #KEYS_EVERY
    bne @no
    lda view
    beq @yes
    jsr ring_free
    lda free + 1
    bne @no
    lda free
    cmp #KEYS_ROOM
    bcs @no
@yes:
    sec
    rts
@no:
    clc
    rts
.endproc

; What has been typed on the Bluetooth keyboard: the keys that stand for
; the controller's buttons, kept for take_buttons (nesp_key_queue).
.proc ask_keys
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
    lda #0
    sta key_at
@key:
    ldx key_at
    cpx nesp_reply
    bcs @heard
    lda nesp_reply + 1,x
    jsr nesp_key_queue
    inc key_at
    bne @key
@heard:
    jmp link_heard
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
    lda #LINK_WAITING
    sta link_state
    rts
.endproc

; The nesp32 answered, and not with OK: it no longer has the service in
; use. Say hello again.
.proc link_refused
    lda #0
    sta greeted
    sta button_sending
    jmp link_heard
.endproc

.proc button_answer
    bcs @silent
    cmp #NESP_ST_OK
    bne @refused
    lda #0
    sta button_sending          ; the stream will say what came of it
    jmp link_heard
@refused:
    jmp link_refused
@silent:
    dec button_sending
    jmp link_silent
.endproc

; Ask for more of the stream, sized to the room in the ring, and take what
; comes. It is asked every frame, room or no room: the reply is also how
; the console hears that the music was stopped, paused or changed.
.proc ask_stream
    jsr ring_free
    bne @use_max
    lda free
    cmp #CREDIT_MAX
    bcc @have_credit
@use_max:
    lda #CREDIT_MAX
@have_credit:
    sta credit
    sta nesp_request + 2
    lda link_epoch
    sta nesp_request
    lda link_pos
    sta nesp_request + 1
    lda underruns               ; the nesp32 keeps the total, for its own screen
    sta nesp_request + 3
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_STREAM
    ldy #4
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    sec
    sbc #STREAM_HEAD
    bcc @bad                    ; not a reply to this at all
    sta rx_count
    lda credit                  ; more than was asked for would run past the
    cmp rx_count                ; free space, into music that has not played
    bcs @fits
@bad:
    jmp link_heard
@fits:
    lda STREAM_EPOCH
    cmp link_epoch
    bne @flush
    lda link_fresh
    beq @same
@flush:
    ; Another epoch: the NMI moves head to here, where this reply's bytes
    ; begin, and stops playback until the ring has refilled. flush_head is
    ; whole before the flag is set.
    lda STREAM_EPOCH
    sta link_epoch
    lda #0
    sta link_pos
    sta link_fresh
    sta link_done
    sta sound_wanted            ; a sound that was due went with the rest
    lda tail
    sta flush_head
    lda tail + 1
    sta flush_head + 1
    lda #1
    sta flush_pending
@same:
    jsr take_state
    ldx rx_count
    beq @copied
    jsr begin_write
    ldx #0
@byte:
    lda STREAM_BYTES,x
    ldy #0
    sta (wptr),y
    advance_wptr                ; preserves A, X and Y
    inx
    cpx rx_count
    bne @byte
    jsr commit_tail
    clc
    lda link_pos
    adc rx_count
    sta link_pos
@copied:
    lda STREAM_STATE
    and #NESP_PLAYER_DRAIN
    beq @more
    lda #1                      ; no more is coming for now, so play what there
    sta link_done               ; is, however little
@more:
    jmp link_heard
.endproc

; What the nesp32 says of the music, from any of JUKE's replies: for the
; screen's status line, and paused or not. Paused, the NMI stops decoding
; and the APU is silenced, with everything buffered kept; when it goes on,
; the channel enables are put back from the screen's copy.
.proc take_state
    lda nesp_reply
    and #NESP_PLAYER_STATE
    ldx #LINK_STOPPED
    cmp #NESP_PLAYER_STOPPED
    beq @state
    ldx #LINK_EMPTY
    cmp #NESP_PLAYER_NO_TRACKS
    beq @state
    ldx #LINK_STREAMING
@state:
    stx link_state
    cmp #NESP_PLAYER_PAUSED
    bne @running
    lda paused
    bne @done
    lda #1
    sta paused
    lda #0
    sta APU_STATUS
    rts
@running:
    lda paused
    beq @done
    lda apu_shadow + $15
    sta APU_STATUS
    lda #0
    sta paused
@done:
    rts
.endproc

; A sound record has played. Ask for the sound, once every line the
; record's frame changed is on the screen, with the foot, and the bars are
; off it: it will not be drawn again until the sound is over.
.proc ask_sound
    lda text_pending
    ora row_dirty
    ora paint_rows
    bne @idle
    lda ui_status
    cmp status_drawn
    bne @idle
    lda foot
    cmp foot_drawn
    bne @idle
    ldx #BAR_COUNT - 1          ; and every bar is down, on the screen too
@bar:
    lda ui_drawn,x
    ora ui_level,x
    bne @idle
    dex
    bpl @bar
    lda link_epoch
    sta nesp_request
    jsr sound_rate
    sta nesp_request + 1
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_SOUND
    ldy #2
    jsr nesp_call
    bcc @came
    jmp link_silent
@idle:
    rts
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    jsr take_state
    lda SOUND_ANSWER
    cmp #NESP_SOUND_GO
    bne @not_go
    jsr sound_go
    jmp link_heard
@not_go:
    cmp #NESP_SOUND_WAIT        ; paused: ask again
    beq @heard
    lda #0                      ; gone: the stream has what comes next, in an
    sta sound_wanted            ; epoch that is not this one
@heard:
    jmp link_heard
.endproc

; A = the rate to ask for sound at: the one its record named, or
; NESP_JUKE_SOUND_REFUSED if this console cannot play it. That is a rate it
; has no routine for, or a port that does not read as the routines count on
; (the line is at rest here: the nesp32 only sends when asked).
.proc sound_rate
    ldx sound_wanted
    dex
    cpx #PCM_COUNT
    bcs @refuse
    lda JOY2
    cmp #PORT_IDLE
    bne @refuse
    txa
    rts
@refuse:
    lda #NESP_JUKE_SOUND_REFUSED
    rts
.endproc
.assert PCM_COUNT = NESP_JUKE_SOUND_RATES, error, "a routine for every rate the nesp32 may send at"

; The nesp32 has agreed to send the sound. It listens for a moment in case
; this console did not hear and asks again, then changes its UART's rate
; and sends the samples; the wait before listening for them covers both. An
; NMI would take cycles from the receiver, so it is off until the sound is
; over, and with it the controller's read: the line is silent, which is how
; the nesp32 knows that the console heard.
;
; A routine that comes back with carry set was left because button A is
; down. The nesp32 is told (pcm_hush), and pauses; the sound is still
; wanted, for when it is played again. The press was this, and is not to
; be taken for another by the NMI's next read.
.proc sound_go
    ldx sound_wanted
    dex
    cpx #PCM_COUNT
    bcs @out                    ; none was asked for
    lda #0
    sta PPUCTRL
    sta APU_STATUS
    lda pcm_stream_lo,x
    sta sound_vector
    lda pcm_stream_hi,x
    sta sound_vector + 1
    ldx #SOUND_SETTLE
    jsr wait_units
    jsr @play
    bcc @ended
    jsr pcm_hush
    lda pad_prev
    ora #PAD_A
    sta pad_prev
    bne @back
@ended:
    lda #0
    sta sound_wanted
    ldx #SOUND_REST
    jsr wait_units
@back:
    bit PPUSTATUS               ; a vblank that came and went is not an NMI now
    lda #PPUCTRL_NMI
    sta PPUCTRL
@out:
    rts
@play:
    jmp (sound_vector)
.endproc

; X units of about 1.3 ms.
.proc wait_units
@unit:
    jsr wait_unit
    dex
    bne @unit
    rts
.endproc

; About 1.3 ms (2306 cycles). Preserves X.
.proc wait_unit
    ldy #0
@loop:
    nop
    nop
    dey
    bne @loop
    rts
.endproc

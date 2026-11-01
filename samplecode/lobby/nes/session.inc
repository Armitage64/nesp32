; The session: two consoles running one game in lockstep (nesp32's
; docs/MULTIPLAYER.md, "The idea").
;
; Both consoles run the whole game, and only buttons cross the link: one
; byte for each *tick* each way, a tick being one step of the game (here,
; one frame of it). A console takes a tick only when it holds both
; players' buttons for it, so both games see the same buttons at the same
; tick and stay the same game, with nothing else sent.
;
; A console's own buttons are used net_delay ticks after the frame they
; were read in: that is the time they have to reach the other console. The
; buttons wait in a ring each way, net_local and net_remote, indexed by
; the tick's low bits.
;
; Every NMI of a session is one of three things:
;
;   a tick    the main loop was waiting, and both players' buttons for the
;             tick are here: the game gets them (game_buttons), and the
;             main loop runs its tick (game_tick, nes/pads.inc)
;   a stall   the main loop was waiting, but the other console's buttons
;             are not here yet. The exchange is made, and the picture
;             stands; a later NMI takes the tick
;   a lag     the main loop was still at work on the last tick. Nothing
;             of the game is done (this sample's main loop never lags)
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when frames fell, nor on how long the nesp32 or the
; network took.
;
; The exchange is PEER's TICKS as a short frame (nesp32's
; docs/PROTOCOL.md, "Short frames" and "A session"), made in every NMI
; that is not a lag, as soon as the controller has been read:
;
;   request   count, first tick and tick wanted, buttons (and buttons)
;   reply     count, buttons
;
; The request carries this console's buttons from the first tick the
; nesp32 has not said it holds, two at most, and names the tick of the
; other console's that is wanted next. The reply carries one tick of the
; other's, if the nesp32 has it. That a reply comes at all says the nesp32
; holds what it was sent. A reply that is not heard costs nothing: the
; next frame's exchange asks again.
;
; Two parts are optional, marked OPTIONAL below. A game can leave both
; out and still be a game in lockstep:
;
; - The delay report. One exchange in 128 carries this console's report
;   (its delay, how often it waited for the other's buttons, and how
;   close it came to waiting), and the reply has the delay the nesp32
;   advises, from how long the network has been taking. Without it a
;   console keeps the delay it began with: too short on a slow network
;   (it stalls often) or too long on a fast one (presses feel late).
; - The digest. One tick in 256 carries, in place of buttons, a digest of
;   the game as it stood a few ticks before; a console whose digest
;   differs from the other's ends the session. Without it two games that
;   came apart (a bug that reads something not the same on both, such as
;   uninitialized memory or the frame count) go on apart, unseen. This
;   sample's game cannot come apart, so here it never fires: point it at
;   your own game's state.
;
; The session ends, and the lobby says why, when the nesp32 says the
; other console is gone (or that there is no session: it was switched off
; and on), when SILENT_FRAMES NMIs in a row have not been ticks, or when
; the digests differ.

NET_DELAY       = NESP_PEER_DELAY_UNKNOWN   ; the delay with no advice yet
NET_DELAY_MAX   = NESP_PEER_DELAY_MAX       ; the most the rings have room for
PER_FRAME       = NESP_PEER_PER_FRAME       ; ticks of buttons an exchange can carry
RING            = 8                         ; ticks of buttons kept, each way
SILENT_FRAMES   = 240                       ; NMIs with no tick before giving up: 4 s
; OPTIONAL, the delay report: it goes with the exchange for one tick in 128,
; the one after this place in this console's buttons.
TUNE_AT         = $40
; OPTIONAL, the digest: one tick in 256 carries it in place of buttons. It
; is of the game at the start of CHECK_AT, on both consoles alike, and is
; kept until each console comes to send it, a few ticks later by its delay.
CHECK_TICK      = $FF
CHECK_AT        = CHECK_TICK - 8
.assert NET_DELAY_MAX < CHECK_TICK - CHECK_AT, error
.assert NET_DELAY_MAX + PER_FRAME < RING, error
.assert RING & (RING - 1) = 0, error, "RING must be a power of two"
.assert RING <= 16, error, "a short frame names ticks by their low four bits"

.segment "BSS"
net_vars:
net_local:      .res RING       ; this console's buttons, by tick
net_remote:     .res RING       ; the other's
net_role:       .res 1          ; 0 this console is player 1, 1 player 2
net_tick:       .res 1          ; the tick the next NMI may take
net_read:       .res 1          ; the first tick this console has no buttons for
net_acked:      .res 1          ; the first of this console's ticks the nesp32 lacks
net_have:       .res 1          ; the first of the other's ticks not here yet
net_delay:      .res 1          ; ticks from a press being read to its use
net_silent:     .res 1          ; NMIs in a row that were not ticks
net_over:       .res 1          ; not 0: the session is over, and why (status_texts)
net_count:      .res 1          ; ticks of buttons this NMI's exchange carries
net_want:       .res 1          ; OPTIONAL: the delay the nesp32 advises
net_late:       .res 1          ; OPTIONAL: NMIs that waited for the other's buttons, since the last report
net_margin:     .res 1          ; OPTIONAL: the fewest ticks of them held at a tick, since then
net_tune:       .res 1          ; OPTIONAL: not 0, this NMI's exchange carries the report
net_check:      .res 1          ; OPTIONAL: the digest, from when it was taken to when it is sent
game_waiting:   .res 1          ; 1: the main loop has run the last tick, and waits for the next
NET_VARS = * - net_vars

; The game's state, which the digest is of. Yours goes here, or the digest
; is pointed at it.
game_state:
game_buttons:   .res 2          ; player 1's, then player 2's, for this tick
game_ticks:     .res 2          ; ticks run
GAME_STATE = * - game_state

.segment "CODE"



; From the lobby, when the two nesp32s are joined: a session, as player
; Y + 1, beginning with the delay the nesp32 advised. Both consoles begin
; it from the same state, and need not begin at the same moment: neither
; takes a tick without the other's buttons for it.
start_session:
    lda #0
    ldx #NET_VARS - 1
@clear:
    sta net_vars,x
    dex
    bpl @clear
    ldx #GAME_STATE - 1
@game:
    sta game_state,x
    dex
    bpl @game
    sty net_role
    lda menu_delay
    sta net_delay
    sta net_want
    ; PEER counts each console's stream of buttons from 0. Both consoles
    ; count their ticks from -NET_DELAY_MAX, whatever their delays, and
    ; the ticks before 0 have no buttons: a console starts reading its
    ; controller at the tick that is its delay before 0.
    lda #<-NET_DELAY_MAX
    sta net_tick
    lda #$FF
    sta net_margin
    lda #1
    sta game_waiting
    jsr show_session
    lda #MODE_SESSION
    sta mode
    rts

; The session's screen: the two controllers, and which of them is this
; console's.
show_session:
    jsr screen_off
    lda #<session_screen
    sta ptr
    lda #>session_screen
    sta ptr + 1
    jsr draw_nametable
    lda #<you_1
    ldx #>you_1
    ldy net_role
    beq @you
    lda #<you_2
    ldx #>you_2
@you:
    sta ptr
    stx ptr + 1
    jsr draw_texts              ; no sprites yet: the lobby left none
    jmp screen_on

.segment "RODATA"
you_1:
    .byte >YOU_1, <YOU_1, 3, "YOU", 0
you_2:
    .byte >YOU_2, <YOU_2, 3, "YOU", 0
.segment "CODE"



; The session's frame, from the main loop: back to the lobby if the
; session is over, or the next tick if the NMI has given it one.
session_main:
    lda net_over
    beq @tick
    jsr hide_sprites
    lda net_over
    jmp lobby_start             ; which says hello again: that ends a session on the nesp32
@tick:
    lda game_waiting
    bne @rts                    ; a stall: no tick this frame
    jsr game_tick
    lda #1
    sta game_waiting
@rts:
    rts

; The session's part of the NMI. A lag does nothing; a session that is over
; waits for the main loop to leave it.
session_nmi:
    lda net_over
    bne @rts
    lda game_waiting
    bne session_frame
@rts:
    rts



; Read this console's controller for the tick net_delay from now, make the
; exchange, and give the game both players' buttons for this tick if they
; are here.
session_frame:
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    bne @exchange               ; read already: in an NMI that stalled
    sec
    sbc net_acked
    cmp #RING - 1
    bcs @exchange               ; no room until the nesp32 has taken some
    ; OPTIONAL, the delay report: the delay changes as the nesp32 advises,
    ; a tick at a time. Nothing has to be agreed for it: the other console
    ; only ever takes the buttons it is given for each tick.
    lda net_want
    cmp net_delay
    beq @read
    bcs @longer
    dec net_delay               ; a tick shorter: this read goes by, as this
    bne @exchange               ; tick's buttons were read a tick ago
@longer:
    inc net_delay               ; a tick longer: the tick between has the
    lda pad                     ; buttons as they were last read
    jsr session_store
@read:
    jsr read_pad
    lda pad
    jsr session_store
@exchange:
    jsr session_exchange
    lda net_over
    bne @rts
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    beq @stall                  ; this console's buttons are still to read: no room
    lda net_have
    cmp net_tick
    beq @late                   ; the other's are not here
    ; OPTIONAL, the delay report: the fewest ticks of the other's held.
    sec
    sbc net_tick
    cmp net_margin
    bcs @digest
    sta net_margin
@digest:
    ; OPTIONAL, the digest: taken at the start of CHECK_AT, before the
    ; tick's buttons are given to the game.
    lda net_tick
    cmp #CHECK_AT
    bne @take
    jsr session_digest
    sta net_check
@take:
    lda net_tick
    and #RING - 1
    tax
    lda net_tick
    cmp #CHECK_TICK
    bne @buttons
    ; OPTIONAL, the digest: the tick that carried the digests. If they are
    ; alike the game goes on with the buttons of the tick before, for both
    ; players.
    lda net_local,x
    cmp net_remote,x
    bne @differ
    dex
    txa
    and #RING - 1
    tax
@buttons:
    ; The tick: this console's buttons are its player's, the other's the
    ; other player's.
    ldy net_role
    lda net_local,x
    sta game_buttons,y
    tya
    eor #1
    tay
    lda net_remote,x
    sta game_buttons,y
    inc net_tick
    lda #0
    sta net_silent
    sta game_waiting            ; the main loop runs the tick
@rts:
    rts
@late:
    inc net_late
@stall:
    inc net_silent
    lda net_silent
    cmp #SILENT_FRAMES
    bcc @rts
    lda #STATUS_QUIET
    sta net_over
    rts
@differ:
    lda #STATUS_DIFFER
    sta net_over
    rts



; A into this console's buttons, for the next tick that has none: or, if
; that is the tick that carries the digest, the digest.
session_store:
    ldx net_read
    cpx #CHECK_TICK
    bne @buttons
    lda net_check               ; OPTIONAL, the digest
@buttons:
    pha
    txa
    and #RING - 1
    tax
    pla
    sta net_local,x
    inc net_read
    ; OPTIONAL, the delay report: one tick in 128 has it go with its
    ; buttons.
    lda net_read
    and #$7F
    cmp #TUNE_AT + 1
    bne @rts
    sta net_tune
@rts:
    rts



; OPTIONAL, the digest: of the game's state, into A. Any sum that a
; difference anywhere in it is likely to change will do.
session_digest:
    lda #0
    clc
    ldx #0
@byte:
    rol a
    adc game_state,x
    inx
    cpx #GAME_STATE
    bne @byte
    rts



; The exchange: PEER's TICKS as a short frame. nesp_short sends the request
; whose count is in A and data at nesp_tx + 1, and waits for a reply of Y
; bytes of data, which comes back at nesp_rx + 3. Carry set: no reply.
session_exchange:
    ; Two ticks of this console's buttons from the first the nesp32 lacks
    ; (the second may not be read yet: the count says how many go).
    lda net_acked
    and #RING - 1
    tax
    lda net_local,x
    sta nesp_tx + 2
    inx
    txa
    and #RING - 1
    tax
    lda net_local,x
    sta nesp_tx + 3
    ; The first tick sent, and the tick of the other's wanted, by their
    ; low four bits in one byte.
    lda net_acked
    asl a
    asl a
    asl a
    asl a
    sta temp
    lda net_have
    and #$0F
    ora temp
    sta nesp_tx + 1
    lda net_tune
    bne @tune
    lda net_read                ; how many ticks the nesp32 does not hold,
    sec                         ; two at the most
    sbc net_acked
    cmp #PER_FRAME + 1
    bcc @count
    lda #PER_FRAME
@count:
    sta net_count
    ldy #1                      ; the reply: one tick of the other's, or none
    jsr nesp_short
    bcs @rts
    cmp #NESP_SHORT_NONE
    beq @gone                   ; the other console is gone, or the nesp32 was switched off and on
    pha                         ; whether one of the other's buttons came
@held:
    lda net_acked               ; the nesp32 holds what it was sent
    clc
    adc net_count
    sta net_acked
    pla
    beq @rts
    lda net_have
    sec
    sbc net_tick
    cmp #RING
    bcs @rts                    ; no room for it: it is asked for again
    lda net_have
    and #RING - 1
    tax
    lda nesp_rx + 3
    sta net_remote,x
    inc net_have
@rts:
    rts
@gone:
    lda #STATUS_LEFT
    sta net_over
    rts
@tune:
    ; OPTIONAL, the delay report, in place of a second tick of buttons: the
    ; delay, the NMIs that waited (7 at the most) and the fewest ticks held
    ; (3), as delay << 5 | late << 2 | margin. It goes with the buttons
    ; just read, in this NMI or not at all. The reply has the delay advised
    ; after the other's buttons.
    lda #0
    sta net_tune
    lda net_late
    cmp #8
    bcc @late
    lda #7
@late:
    asl a
    asl a
    sta temp
    lda net_margin
    cmp #4
    bcc @margin
    lda #3
@margin:
    ora temp
    sta temp
    lda net_delay
    asl a
    asl a
    asl a
    asl a
    asl a
    ora temp
    sta nesp_tx + 3
    lda #1                      ; one tick of buttons goes with it
    sta net_count
    lda #NESP_PEER_TUNE
    ldy #2
    jsr nesp_short
    bcs @rts
    cmp #NESP_SHORT_NONE
    beq @gone
    pha
    lda #0                      ; a new report begins
    sta net_late
    lda #$FF
    sta net_margin
    lda nesp_rx + 4             ; the advice: 1 to NET_DELAY_MAX, or none
    beq @advised
    cmp #NET_DELAY_MAX + 1
    bcs @advised
    sta net_want
@advised:
    jmp @held

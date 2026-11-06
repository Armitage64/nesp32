; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network.
; net/jackal_net.inc includes it, after net/ram.inc. It runs from the PRG RAM, where the
; reset copies it (net/cart.inc). It is Contra's (apps/contra/net/net.inc),
; with Jackal's NMI, controllers and title.
;
; Both consoles run the whole game. What crosses the link is the buttons:
; one byte for each tick, where a tick is one frame of the game. A console
; takes a tick only when it holds both players' buttons for it, so the two
; games see the same buttons at the same tick and stay the same. Its own
; buttons are used net_delay ticks after they were read, which is the time
; they have to reach the other console.
;
; That delay is each console's own, and changes as the game goes. Nothing
; has to be agreed for it: the other console only ever takes the buttons
; it is given for each tick. Made a tick longer, this console sends the
; buttons it last read once more, for the tick between; made a tick
; shorter, it lets one read go by. Its nesp32 says when, from what the
; other console reports of how this one's buttons have been arriving
; (nesp32's peer.c); and this console reports the same of the other's, in
; one exchange in 128: how many NMIs waited for them, and the fewest ticks
; of them it ever held when it took one.
;
; All of the game runs in its NMI handler, and so does this. An NMI in a
; session is one of three things:
;
;   a tick    the buttons are here. The handler does all its work.
;   a stall   the other console's buttons for this tick are not here.
;             The handler has done its writes to the PPU and now stops
;             short of the game (net_read_input). The NMIs that follow
;             (net_nmi_stalled) write nothing to the PPU but the scroll,
;             and the picture stands; the sound goes on, and the buttons
;             are tried for again. The one that has them runs the game.
;   a lag     the last NMI's work was not finished. The game's own answer
;             to that is left as it is: the scroll and the sound, and
;             nothing else.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The music is the exception: the sound engine runs in every NMI,
; and keeps the frames' time. The game's random number counts the ticks
; (subProcessGameControl), and nothing of the game reads the sound
; engine's memory.
;
; The exchange is made where the game reads its controllers, after the
; NMI's writes to the PPU and its scroll (the split for the last boss's
; tank, a wait that counts cycles from the NMI, comes before it) and before
; the game's work: the buttons go out at once, and the other console's are
; asked for at the last moment they can be used. It is the PEER service's
; TICKS as a short frame (nesp32's docs/PROTOCOL.md). Nothing interrupts
; the library's cycle-timed serial routines but a sample's fetches, which
; net_ask allows for.
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.pushseg
.segment "NETCODE"

.define NESP_APP "JACK"
NESP_APP_VERSION = 1

.pushseg
.include "nesp.inc"
.popseg

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

; From the reset (net_cart_reset), once it has cleared the memory and
; before the NMI is on: OUT0 to mark, and into a session if
; net_start_session asked for one.
net_reset:
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_mode
    sta net_stalled
    sta net_menu
    sta nesp_fast               ; the link's rate, until a session asks for its own
    sta net_rate_ask
    sta net_rate_tries
    sta net_rate_misses
    lda net_boot
    cmp #NET_BOOT_MARK
    bne @exit
    lda net_boot+1
    eor net_boot+2
    eor #NET_BOOT_CHECK
    cmp net_boot+3
    bne @exit
    lda #$00
    sta net_boot
    ; Straight into a game for two, with no title first: the players have
    ; said what they want, in the menu. The title is come back to when the
    ; game ends, still in the session, and player 1's Start begins another
    ; from there.
    lda #$01
    sta Player2Active
    jsr net_two_players
    ; The picture on, as the title's set-up leaves it for the game
    ; (subTitleScreenInitialization): the game turns it on in each NMI from
    ; this copy, which nothing else writes, and the reset cleared it.
    lda #NormalPPUMaskValue
    sta NormalPPUMASK
    ; The memory past what the reset clears, the same on both consoles
    ; whatever each did before: the scores, and the top score's 5000 as a
    ; console switched on has it. (The mark of an earlier power-on above
    ; them is the same on any console past its first reset.)
    ldx #$1F
    lda #$00
:
    sta $07D0,x
    dex
    bpl :-
    lda #$50
    sta HighScore_xx99xx
    lda net_boot+1
    sta net_role
    lda net_boot+2
    sta net_delay
    sta net_want
    ; The ticks before 0 have no buttons, and are as many on both consoles
    ; whatever the delay of each: a console begins to read when it comes
    ; to the tick that is its delay before 0.
    lda #<-NET_DELAY_MAX
    sta net_tick
    lda #$00                    ; and both streams of buttons begin at tick 0
    sta net_read
    sta net_acked
    sta net_have
    lda #$ff
    sta net_margin
    lda #$00
    ldx #RING * 2 - 1
:
    sta net_local,x
    dex
    bpl :-
    sta net_late
    sta net_tune
    sta net_silent
    sta net_pad
    lda #$01
    sta net_rate_ask            ; the session's own rate, asked for in its first NMI
    sta net_mode                ; last, when the rest is in place

@exit:
    rts

; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks. Both consoles begin from the state of one switched on for the
; first time, at the first tick. Does not return: the game starts again
; from its reset.
net_start_session:
    sei
    sta net_boot+1
    stx net_boot+2
    eor net_boot+2
    eor #NET_BOOT_CHECK
    sta net_boot+3
    lda #NET_BOOT_MARK
    sta net_boot

; The session is over: the other console is gone, or the games differ.
; Start again as a console that was reset.
net_drop:
    sei
    lda #$00
    sta PPUCTRL
    sta PPUMASK
    sta net_mode
    sta net_menu
    sta net_stalled
    jmp RESET_VECTOR

; --- the title -----------------------------------------------------------------

; The title's Start or Select, in A, while it waits for one (Label774,
; GameControlState 1). Select changes the choice of one player or two, but
; not in a session, which is for two. Start with 2 PLAYERS chosen and no
; session is the menu's, from the next NMI on, with the game for two set up
; to begin when the menu gives the NMI back (LOCAL GAME); otherwise it
; begins the game, as the title's Start does.
net_title_button:
    and #SelectButton
    beq @start
    lda net_mode
    bne @exit
    jmp net_title_toggle        ; the game's own

@start:
    lda net_mode
    beq @local
    lda #$01
    sta Player2Active
    bne @game

@local:
    lda Player2Active
    beq @game
    jsr net_two_players
    lda #NET_MENU_FIRST
    sta net_menu

@exit:
    rts

@game:
    lda #$03
    jmp subWrite_A_ToGameControlState_SetScreenTimer_ClearTitleScreenState

; The game for two, as the title's Start with 2 PLAYERS begins it, but past
; the choice's flashing, which would be drawn on whatever screen is up (the
; menu's, or none): the game's set-up of the players (GameControlState 3,
; its third step), in the next tick.
net_two_players:
    lda #$03
    sta GameControlState
    lda #$02
    sta ControlSubState
    rts

; From the menu: LOCAL GAME. The game for two that the title's Start set up
; begins at the next NMI, which is the game's.
net_menu_local:
    lda #$00
    sta net_menu
    rts

; --- the NMI ---------------------------------------------------------------------

; An NMI after one that stalled (net_nmi, net/cart.inc), with the
; registers on the stack. The PPU has had the last tick's writes and the
; picture stands, so only the scroll and the sound are done before the
; buttons are tried for again, as in a lag frame; with them, the game goes
; on from where its NMI reads the controllers.
net_nmi_stalled:
    lda PPUSTATUS
    jsr subProcessScreenScrolling
    inc GameFrameLogicInProgress
    jsr subProcessSound_Music
    jsr net_read_input          ; and with no buttons it ends the NMI
    jmp net_nmi_resume

; The controllers, in place of the NMI's call of subProcessControllerInputs.
;
; With no session it is the game's own read, and OUT0 back to mark after
; it: the game leaves it low, which the nesp32 would take for the start of
; a byte.
;
; In a session it reads this console's controller for the tick net_delay
; from now, makes the exchange, and gives the game both players' buttons
; for this tick if they are here, as the game's read gives them. If they
; are not, it ends the NMI there: the game is not run.
net_read_input:
    lda net_mode
    bne @session
    jsr subProcessControllerInputs
    lda #OUT0_MARK
    sta JOY1
    rts

@session:
    lda net_rate_ask
    beq @ticks
    dec net_rate_ask
    bne @ticks
    jsr net_rate                ; in place of this NMI's exchange: a stall
    jmp net_stall

@ticks:
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    bne @exchange               ; read already: in an NMI that stalled, or a tick ago
    sec
    sbc net_acked
    cmp #RING-1
    bcs @exchange               ; no room until the nesp32 has taken some
    lda net_want
    cmp net_delay
    beq @read
    bcs @longer
    dec net_delay               ; a tick shorter: this tick's buttons went a tick ago,
    bne @exchange               ; and this read goes by

@longer:
    inc net_delay               ; a tick longer: the tick between has the buttons
    lda net_pad                 ; as they were last read
    jsr net_store

@read:
    jsr net_read_pad
    jsr net_store

@exchange:
    jsr net_exchange
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    beq net_stall               ; this console's own buttons are still to read: no room
    lda net_have
    cmp net_tick
    beq net_late_stall          ; the other's are not here
    sec
    sbc net_tick                ; how many ticks of them are
    cmp net_margin
    bcs :+
    sta net_margin
:
    lda net_tick
    cmp #CHECK_AT
    bne :+
    jsr net_digest              ; for both consoles to send when they come to CHECK_TICK
    sta net_check
:
    lda net_tick
    and #RING-1
    tax
    lda net_tick
    cmp #CHECK_TICK
    bne @buttons
    ; A tick that carried the digests. If they are alike the game goes on
    ; with the buttons of the tick before, for both players.
    lda net_local,x
    cmp net_remote,x
    beq :+
    jmp net_drop
:
    dex
    txa
    and #RING-1
    tax

@buttons:
    ldy net_role
    lda net_local,x
    sta $0004,y                 ; $04 player 1 and $05 player 2, as the game's read has them
    tya
    eor #$01
    tay
    lda net_remote,x
    sta $0004,y
    inc net_tick
    lda #$00
    sta net_silent
    sta net_stalled
    ; What the game's read leaves behind it, the same on both consoles: its
    ; first read of each, and the last of port 2 (which here is the line).
    lda $04
    sta $08
    lda $05
    sta $09
    lda #$00
    sta $07
    ldx #$00
    jmp ControllerReadOK        ; the rest of the game's read: a press is the frame it went down

net_late_stall:
    inc net_late

; No buttons for this tick: the NMI ends here, with the game not run, and
; the next is the stall's (net_nmi_stalled).
net_stall:
    lda #NET_STALL
    sta net_stalled
    inc net_silent
    lda net_silent
    cmp #SILENT_FRAMES
    bcc :+
    jmp net_drop
:
    pla                         ; net_read_input's return
    pla
    lda #$00
    sta GameFrameLogicInProgress
    jmp END_NMI

; A into this console's buttons, for the next tick that has none: or, if
; that is the tick that carries the digest, the digest. One tick in 128 is
; the one whose exchange carries the report.
net_store:
    ldx net_read
    cpx #CHECK_TICK
    bne :+
    lda net_check
:
    pha
    txa
    and #RING-1
    tax
    pla
    sta net_local,x
    inc net_read
    lda net_read
    and #$7f
    cmp #TUNE_AT+1
    bne :+
    sta net_tune
:
    rts

; A digest of the game into A: the zero page the game keeps, less its
; scratch ($00-$0F), the sound engine's ($E0-$F0) and the link's own bytes;
; the game's bytes in page 1 ($0110-$011F); and every object's kind and
; place on the screen ($0500-$057F). Both consoles work it out at the start
; of the same tick, CHECK_AT.
net_digest:
    lda #$00
    clc
    ldx #$10
@low:
    rol a
    adc $00,x
    inx
    cpx #$E0
    bne @low
    ldx #$F1
@high:
    rol a
    adc $00,x
    inx
    cpx #nesp_rx_data
    bne @high
    ldx #$FC
@top:
    rol a
    adc $00,x
    inx
    bne @top
    ldx #$0F
@page1:
    rol a
    adc $0110,x
    dex
    bpl @page1
    ldx #$7F
@objects:
    rol a
    adc $0500,x
    dex
    bpl @objects
    rts
.assert nesp_rx_data = $F7 && nesp_tries = $EB && nesp_tx_data > $F7 && nesp_rx_end < $FC, error, "the digest's ranges"

; This console's controller into A. While a sample plays it is read twice,
; and if a fetch spoiled one of the reads, it is as it was the last time
; both were alike. With none playing nothing spoils a read, and one does.
; The sample channel is asked before the first read: the fetch that spoils
; a read may be the sample's last (nesp32's docs/PHANTOM-RIGHT.md).
net_read_pad:
    lda APU_STATUS
    and #$10                    ; a sample has bytes still to fetch
    beq @once
    jsr net_read_port
    sta net_temp
    jsr net_read_port
    cmp net_temp
    beq @good
    lda net_pad
    rts

@once:
    jsr net_read_port

@good:
    sta net_pad
    rts

; Controller 1 into A, as the game's read reads it: D0, or D1 for a Famicom's
; expansion port. OUT0 is low for the reads and no longer: the nesp32 takes
; it for a byte of noise. Port 2 is the line to the nesp32, and is not read.
net_read_port:
    ldx #$00
    stx JOY1
    ldy #$08

@bit:
    lda JOY1
    sta net_temp+1
    lsr
    ora net_temp+1
    lsr
    rol net_temp+2
    dey
    bne @bit
    ldx #OUT0_MARK
    stx JOY1
    lda net_temp+2
    rts

; A session's exchange: PEER's TICKS, as a short frame (nesp32's
; docs/PROTOCOL.md). Out: up to PER_FRAME ticks of this console's buttons,
; from the first the nesp32 has not said it holds, and the tick of the
; other console's that is wanted next, the two named by their low four
; bits in one byte. In: one tick of the other's, if it is there.
;
;   request   count, first tick and tick wanted, buttons (and buttons)
;   reply     count, buttons
;
; A reply names no ticks. That one comes says the nesp32 holds the buttons
; it was sent, and its CRC says which request it answers.
;
; With net_tune set the request's count is NESP_PEER_TUNE: one tick of
; buttons and then this console's report, and the reply has the delay
; advised after its buttons.
net_exchange:
    lda net_acked
    and #RING-1
    tax
    lda net_local,x
    sta nesp_tx+2
    inx
    txa
    and #RING-1
    tax
    lda net_local,x
    sta nesp_tx+3
    lda net_acked
    asl
    asl
    asl
    asl
    sta net_temp
    lda net_have
    and #$0f
    ora net_temp
    sta nesp_tx+1
    lda net_tune
    beq @plain
    ; The report, in place of a second tick of buttons: the delay, the
    ; NMIs that waited (7 at the most) and the fewest ticks held (3). It
    ; goes with the buttons just read, in this NMI or not at all: in a
    ; later one there might be none to send.
    lda #$00
    sta net_tune
    lda net_late
    cmp #$08
    bcc :+
    lda #$07
:
    asl
    asl
    sta net_temp
    lda net_margin
    cmp #$04
    bcc :+
    lda #$03
:
    ora net_temp
    sta net_temp
    lda net_delay
    asl
    asl
    asl
    asl
    asl
    ora net_temp
    sta nesp_tx+3
    ldx #$01                    ; one tick of buttons goes with it
    stx net_temp
    lda #NESP_PEER_TUNE
    ldy #$02
    jsr net_ask
    bcs @missed
    cmp #NESP_SHORT_NONE
    beq @drop
    pha
    lda #$00                    ; a new report begins
    sta net_late
    lda #$ff
    sta net_margin
    lda nesp_rx+4               ; the advice
    beq @acks
    cmp #NET_DELAY_MAX+1
    bcs @acks
    sta net_want
    bcc @acks

@plain:
    jsr net_unsent
    cmp #PER_FRAME+1
    bcc :+
    lda #PER_FRAME
:
    sta net_temp                ; how many ticks of buttons go
    ldy #$01
    jsr net_ask
    bcs @missed
    cmp #NESP_SHORT_NONE
    beq @drop                   ; the other console is gone, or the nesp32 was switched off and on
    pha                         ; whether one of the other's buttons came

@acks:
    lda #$00
    sta net_rate_misses
    lda net_acked               ; the nesp32 holds what it was sent
    clc
    adc net_temp
    sta net_acked
    pla
    beq @exit
    lda net_have
    sec
    sbc net_tick
    cmp #RING
    bcs @exit                   ; no room: it is asked for again
    lda net_have
    and #RING-1
    tax
    lda nesp_rx+3
    sta net_remote,x
    inc net_have

@exit:
    rts

@missed:
    jmp net_rate_missed

@drop:
    jmp net_drop

; A short request of count A, whose reply is to have Y bytes of data, and
; the same once more if no reply to it is heard. On a console a sample's
; fetch takes cycles from the serial routines now and again, and a reply
; is misheard; the nesp32 has taken the buttons all the same, and passes
; them over when they come twice. Asked again in the same NMI, the game
; does not have to stand still a frame for it. Jackal's music plays
; samples all the time. Carry and A as nesp_short leaves them.
net_ask:
    pha
    jsr nesp_short
    bcc @heard
    pla
    ldy nesp_count              ; as it was asked
    jmp nesp_short

@heard:
    tax
    pla
    txa
    clc
    rts

; Ask the nesp32 for the session's line at its own rate, NESP_SHORT_PERIOD
; cycles a bit (PEER's RATE), at the link's rate. With its answer that it
; is at that rate, from its next request on, this console's exchanges are
; at it too (nesp32's nesp.inc, nesp_fast). With any other answer, or none,
; or from a nesp32 whose firmware has no RATE (NO_OP), the line stays the
; link's.
net_rate:
    lda #$00
    sta net_rate_ask
    sta net_rate_misses
    inc net_rate_tries
    lda #NESP_SHORT_PERIOD
    sta nesp_request
    lda #NESP_SVC_PEER
    ldx #NESP_PEER_RATE
    ldy #$01
    jsr nesp_call
    bcs @exit
    cmp #NESP_ST_OK
    bne @exit
    lda nesp_reply_len
    cmp #$01
    bne @exit
    lda nesp_reply
    cmp #NESP_SHORT_PERIOD
    bne @exit
    lda #$80
    sta nesp_fast

@exit:
    rts

; An exchange at the session's own rate had no reply. Many in a row, and
; the line may not be good enough at it, or the nesp32 has gone back to
; the link's (it does when it hears nothing at it for a while): this
; console goes back to the link's rate too, and asks again once the nesp32
; will have, a few times a session at the most.
net_rate_missed:
    bit nesp_fast
    bpl @exit
    inc net_rate_misses
    lda net_rate_misses
    cmp #NET_RATE_MISSES
    bcc @exit
    lda #$00
    sta nesp_fast
    lda net_rate_tries
    cmp #NET_RATE_TRIES
    bcs @exit
    lda #NET_RATE_WAIT          ; once the nesp32 has gone back to the link's too
    sta net_rate_ask

@exit:
    rts

; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    lda net_read
    sec
    sbc net_acked
    rts

.ifdef NET_FAST
.include "fast.inc"
.endif

; The end of what net_cart_reset copies into the PRG RAM: the library's
; code is the last of it (net/jackal_net.cfg).
.pushseg
.segment "CODE"
net_image_end:
.popseg
.assert net_image_end <= NET_IMAGE_END, error, "net_cart_reset copies too little"

.popseg

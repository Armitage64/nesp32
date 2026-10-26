; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. All of bank 1,
; which the game leaves empty; net/glue.inc has what has to be in the fixed
; bank. It is TMNT II's (apps/tmnt2/net/net.asm), which is Contra's.
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
;   a stall   the other console's buttons for this tick are not here. The
;             handler has sent the sprites and its buffer of writes to the
;             PPU, and now stops short of the sound and the game
;             (net_nmi_pads). The NMIs that follow send the same sprites
;             and draw nothing (net_nmi_draw), so the picture stands, and
;             try again; the one that has the buttons runs the game.
;   a lag     the last NMI's work was not finished. The game's own answer
;             to that is left as it is: the scroll is set, and nothing
;             else is done.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The sound engine too runs once a tick, and not in a stall, though
; that holds the music back a frame in each: the game reads back whether
; a level's closing music has ended, and waits for it (README.md, "The
; sound").
;
; The exchange is made where the NMI would have read the controllers, with
; the IRQs held off: the split under the status bar is some 5900 cycles
; after the NMI begins, and the exchange is over by some 4700 at the latest
; (README.md), so nothing interrupts the library's cycle-timed serial
; routines and the split does not come late. It is the PEER service's TICKS
; as a short frame (nesp32's docs/PROTOCOL.md).
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.segment "CODE"

; What the fixed bank calls, by number in X (net_call, net/glue.inc), first
; in the bank.
net_entry:
    lda net_entries_hi,x
    pha
    lda net_entries_lo,x
    pha
    rts
.assert net_entry = $8000, error, "net_call calls $8000"

net_entries_lo:
    .byte <(net_frame - 1), <(net_reset - 1), <(menu_frame - 1)
net_entries_hi:
    .byte >(net_frame - 1), >(net_reset - 1), >(menu_frame - 1)
.assert NET_FRAME = 0 && NET_RESET = 1 && NET_MENU = 2, error, "net_entries' order"

.define NESP_APP "SMBX"
NESP_APP_VERSION = 1

.include "nesp.inc"

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

.segment "CODE"

; From the end of the reset: OUT0 to mark, and into a session if
; net_start_session asked for one.
net_reset:
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_mode
    sta net_stalled
    sta net_menu
    sta net_go
    sta net_local_go
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
    ; Straight into a game for two, past the title: the players have said
    ; what they want, in the menu (net_title_pad).
    lda #$01
    sta net_go
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
    lda #$01
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
    sta PPU_CTRL
    sta PPU_MASK
    sta net_mode
    jmp GAME_RESET

; Each NMI of a session (net_nmi_pads, net/glue.inc).
;
; It reads this console's controller for the tick net_delay from now,
; makes the exchange, and leaves both players' buttons for this tick in
; net_pads if they are here, or net_stalled set if not.
net_frame:
    php
    sei
    jsr net_session
    plp
    rts

net_session:
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
    jsr net_digest_irqs         ; for both consoles to send when they come to CHECK_TICK
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
    sta net_pads,y
    tya
    eor #$01
    tay
    lda net_remote,x
    sta net_pads,y
    inc net_tick
    lda #$00
    sta net_silent
    sta net_stalled
    ; The title's Start, which the session's first title takes as pressed,
    ; until the game has begun.
    lda OPER_MODE
    beq :+
    lda #$00
    sta net_go
:
    rts

net_late_stall:
    inc net_late

net_stall:
    lda #$01
    sta net_stalled
    inc net_silent
    lda net_silent
    cmp #SILENT_FRAMES
    bcc :+
    jmp net_drop
:
    rts

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

; The digest, with the IRQs let in: it is not timed, and the split comes
; when it should. The IRQ's handler sets the scroll and nothing the digest
; reads. They are held off again for the way back.
net_digest_irqs:
    cli
    jsr net_digest
    sei
    rts

; A digest of the game into A: of the zero page, and of the sprites. Left
; out of the zero page are the game's scratch ($00-$07) and the six bytes
; the link has lent to it, which are the link's now (net/glue.inc). Both
; consoles work it out at the start of the same tick, CHECK_AT.
net_digest:
    lda #$00
    clc
    ldx #$08
@zero:
    rol a
    adc $00,x
    inx
    cpx #LENT
    bne :+
    ldx #LENT + LENT_ZP
:
    cpx #$00
    bne @zero
    ldx #$00
@sprites:
    rol a
    adc SPRITE_PAGE,x
    inx
    bne @sprites
    rts

; This console's controller into A. While a sample plays it is read twice,
; and if a fetch spoiled one of the reads, it is as it was the last time
; both were alike. With none playing nothing spoils a read, and one does.
net_read_pad:
    jsr net_read_port
    lda APU_STATUS
    and #APU_STATUS_DMC
    beq @once
    lda net_temp
    pha
    jsr net_read_port
    pla
    cmp net_temp
    beq @once
    lda net_pad
    rts

@once:
    lda net_temp
    sta net_pad
    rts

; Controller 1 into net_temp, A first, as the game's own read has it.
; OUT0 is low for the reads and no longer: the nesp32 takes it for a byte
; of noise.
net_read_port:
    ldx #$00
    stx JOY1
    ldy #$08

@bit:
    lda JOY1
    lsr
    rol net_temp
    dey
    bne @bit
    ldx #OUT0_MARK
    stx JOY1
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
    bcs @exit
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
    bcs @exit
    cmp #NESP_SHORT_NONE
    beq @drop                   ; the other console is gone, or the nesp32 was switched off and on
    pha                         ; whether one of the other's buttons came

@acks:
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

@drop:
    jmp net_drop

; A short request of count A, whose reply is to have Y bytes of data, and
; the same once more if no reply to it is heard. A sample's fetch takes
; cycles from the serial routines now and again, and a reply is misheard;
; the nesp32 has taken the buttons all the same, and passes them over when
; they come twice. Asked again in the same NMI, the game does not have to
; stand still a frame for it. Carry and A as nesp_short leaves them.
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

; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    lda net_read
    sec
    sbc net_acked
    rts

.include "menu.inc"

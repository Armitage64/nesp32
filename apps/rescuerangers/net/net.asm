; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. In bank 8 of
; the netplay ROM, which the game never has in (net/rescuerangers_net.cfg);
; rescuerangers.asm includes this at its end when NETPLAY is defined, and
; net/cart.inc has what runs from the PRG RAM, net_call among it. It is
; Bubble Bobble's (apps/bubblebobble/net/net.asm), with Rescue Rangers'
; ticks.
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
; The game runs in tasks, coroutines on stacks of their own that sleep a
; number of frames, which the NMI counts down; SCHEDULE runs the ones that
; are ready, one after another, and waits when none is. So an NMI in a
; session is one of three things (net_nmi, net_nmi_tick, net/cart.inc):
;
;   a lag     a task is still at work, or ready. The NMI does nothing of
;             the game: no writes to the PPU, no count of the frame, no
;             sleeps counted down.
;   a stall   the game is waiting, but the other console's buttons for this
;             tick are not here. The NMI has made its writes to the PPU, and
;             stops short of waking the tasks; the PPU's lists are empty
;             by then, so the NMIs that follow write nothing and the
;             picture stands.
;   a tick    the game is waiting and the buttons are here. The NMI counts
;             the frame and wakes the tasks, which take the tick's buttons
;             as they read the controllers (net_ctrl_read).
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The music is the exception: the sound engine runs in every NMI,
; and keeps the frames' time.
;
; The exchange is made after the NMI's writes to the PPU and before the
; tasks are woken: the buttons go out at once, and the other console's are
; asked for at the last moment they can be used. Rescue Rangers has no
; splits of the screen, and no IRQs, so nothing can interrupt the library's
; cycle-timed serial routines. It is the PEER service's TICKS as a short
; frame (nesp32's docs/PROTOCOL.md).
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.segment "CODE"

; What the PRG RAM calls, by number in X (net_call, net/cart.inc), first
; in the bank.
net_entry:
    lda net_entries_hi,x
    pha
    lda net_entries_lo,x
    pha
    rts
.assert net_entry = NET_ENTRY, error, "net_call calls NET_ENTRY"

net_entries_lo:
    .byte <(net_frame - 1), <(net_reset - 1), <(menu_frame - 1)
net_entries_hi:
    .byte >(net_frame - 1), >(net_reset - 1), >(menu_frame - 1)
.assert NET_FRAME = 0 && NET_RESET = 1 && NET_MENU = 2, error, "net_entries' order"

.define NESP_APP "RESC"
NESP_APP_VERSION = 2              ; 2: the reset a frame longer (net/fast.inc), so FRAME_COUNT is not 1's

.include "nesp.inc"

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error
.assert NESP_PEER_DUMP_BYTES = $800 && DUMP_PIECE = $40, error, "net_differ's pieces"

.segment "CODE"

; From the reset, once the game has cleared its RAM, with the NMI off: OUT0
; to mark, and into a session if net_start_session asked for one. The
; game's own reset in a session, which it makes after its ending, goes on
; with the session: both consoles come to it at the same tick.
net_reset:
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_stalled
    sta net_menu
    sta net_autostart
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
    sta net_mode
    ; Straight into a game for two, past the title (net_title_frame): the
    ; players have said what they want, in the menu.
    lda #$01
    sta net_autostart
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
    sta net_pads
    sta net_pads+1
    sta net_pad
    sta net_lags
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
    sta net_rate_ask            ; the session's own rate, asked for in its first NMI
    sta net_mode                ; last, when the rest is in place

@exit:
    rts

; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks. Both consoles begin from the state of one switched on for the
; first time, at the first tick. Does not return: the game starts again
; from its reset.
; The reset clears the game's RAM, but the stack's page only in part, and
; what each console left in the rest, from its last game or its power-on,
; would be in the session too: so all 2 KB are cleared first, with the NMI
; off.
net_start_session:
    sei
    ldy #$00
    sty PPUCTRL
    sta net_boot+1
    stx net_boot+2
    eor net_boot+2
    eor #NET_BOOT_CHECK
    sta net_boot+3
    lda #NET_BOOT_MARK
    sta net_boot
    tya
:
    sta $0000,y
    sta $0100,y
    sta $0200,y
    sta $0300,y
    sta $0400,y
    sta $0500,y
    sta $0600,y
    sta $0700,y
    iny
    bne :-

; The session is over: the other console is gone, or the games differ.
; Start again as a console that was reset.
net_drop:
    sei
    cld
    lda #$00
    sta PPUCTRL
    sta PPUMASK
    sta net_mode
    sta net_menu
    jmp RESET_MAIN

; The games differ. Before the session is given up, this console's RAM
; goes to its nesp32 (PEER's DUMP), as it stands at the start of the tick
; whose digests differed, where the other console stops too. The nesp32
; writes it to its log, and the two logs say which bytes differ. The link's
; own bytes ($AA-$AF) and the stack below this are the dump's doing. A
; nesp32 that does not answer, or has no DUMP, is given no more.
net_differ:
    sei
    lda #$00
    sta PPUCTRL
    sta PPUMASK
    sta net_dumped
    sta nesp_fast               ; the link's rate, which nesp_call's are at
@piece:
    lda net_dumped              ; where the piece begins: 64 bytes a piece
    lsr a
    lsr a
    sta nesp_ptr+1
    sta nesp_request+1
    lda net_dumped
    and #$03
    lsr a
    ror a
    ror a
    sta nesp_ptr
    sta nesp_request
    ldy #DUMP_PIECE-1
@copy:
    lda (nesp_ptr),y
    sta nesp_request+2,y
    dey
    bpl @copy
    lda #DUMP_TRIES
    ldx net_dumped
    bne :+
    lda #DUMP_FIRST_TRIES
:
    sta net_temp
    lda #NESP_SVC_PEER
    ldx #NESP_PEER_DUMP
    ldy #DUMP_PIECE+2
    jsr nesp_call
@heard:
    bcc @answered
    dec net_temp
    beq net_drop
    jsr nesp_again
    jmp @heard

@answered:
    cmp #NESP_ST_OK
    bne net_drop
    inc net_dumped
    lda net_dumped
    cmp #NESP_PEER_DUMP_BYTES / DUMP_PIECE
    bne @piece
    jmp net_drop

; --- a frame -------------------------------------------------------------------

; In a session, each NMI that finds the game waiting (net_nmi_tick): it
; reads this console's controller for the tick net_delay from now and
; makes the exchange. With both players' buttons for this tick here, they
; go to net_pads, for the game's read (net_ctrl_read); with them not here,
; net_stalled is set, and the NMI goes on with the music alone.
net_frame:
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
    jmp net_differ
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
    rts

net_late_stall:
    inc net_late

net_stall:
    lda #NET_STALL
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

; A digest of the game into A: of the zero page the game keeps, and of the
; objects' page. Left out of the zero page are NMI_SEEN ($90), which says
; only where an NMI landed; the sound engine's ($C0-$D8) and its queue
; ($DB-$E3), which run in every NMI, a stall's too; and the link's own
; bytes ($AA-$AF). Both consoles work it out at the start of the same
; tick, CHECK_AT.
; Each byte goes in with A rotated, its bits round and not through the
; carry, and EORed: a step that loses nothing, so that one byte that
; differs always makes the digest differ. (A rotate through the carry and
; an ADC lost what came early.)
net_digest:
    lda #$00
    clc
    ldy #$00
@range:
    ldx net_digest_ranges+1,y
    stx net_temp                ; where it ends
    ldx net_digest_ranges,y
@zero:
    cmp #$80                    ; bit 7 into carry: a rotate of A alone
    rol a
    eor $00,x
    inx
    cpx net_temp
    bne @zero
    iny
    iny
    cpy #net_digest_ranges_end - net_digest_ranges
    bne @range
    ldx #$00
@objects:
    cmp #$80
    rol a
    eor OBJECTS,x
    inx
    bne @objects
    rts

OBJECTS         = $0400         ; the page the players and the rest are in

; The zero page in the digest: from each first byte to before each second.
net_digest_ranges:
    .byte $00, $90, $91, nesp_rx_data, nesp_ptr + 2, $C0, $D9, $DB, $E4, $00
net_digest_ranges_end:
.assert nesp_rx_data = $AA && nesp_ptr = $AE, error, "the digest's ranges"

; This console's controller into A. While a sample plays it is read twice,
; and if a fetch spoiled one of the reads, it is as it was the last time
; both were alike. With none playing nothing spoils a read, and one does.
; The game plays none, but the check costs little.
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

; Controller 1 into net_temp, as the game's CTRL_READ reads it, with the
; Famicom's expansion pad's buttons too. OUT0 is low for the reads and no
; longer: the nesp32 takes it for a byte of noise.
net_read_port:
    ldx #$00
    stx JOY1
    ldy #$08

@bit:
    lda JOY1
    sta nesp_tries              ; free until the exchange
    lsr
    ora nesp_tries
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
; the same once more if no reply to it is heard. Asked again in the same
; NMI, the game does not have to stand still a frame for it. Carry and A
; as nesp_short leaves them.
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
; link's. Made where the exchange would be: it takes less time than the
; exchange it stands in for.
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

; From the menu: LOCAL GAME. A game for two on this console, as the title's
; Start would have begun it: the title, asleep since (net_title_start),
; goes on at the next NMI, which is the game's.
net_menu_local:
    lda #$00
    sta net_menu
    rts

.include "menu.inc"

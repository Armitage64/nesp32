; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. At the end of
; bank 6, where the game leaves 6.7 KB empty; bubblebobble.asm includes
; this at its end when NETPLAY is defined, and net/fill.inc has what has to
; be in the fixed bank. It is TMNT II's (apps/tmnt2/net/net.asm), with
; Bubble Bobble's NMI and title.
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
; All of the game runs in its NMI handler, and so does this. The handler
; turns the NMI off as it begins and on again as it ends, so a frame whose
; work runs long has no NMI at its next vblank: no NMI ever finds the
; last one's work unfinished. An NMI in a session is one of two things:
;
;   a tick    the buttons are here. The handler does all its work.
;   a stall   the other console's buttons for this tick are not here. The
;             handler has made its writes to the PPU, and stops short of
;             the game (net_ctrl_hook). The PPU's list of writes is left
;             empty, so the NMIs that follow write nothing to it and the
;             picture stands; the one that has the buttons runs the game.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The music is the exception: the sound engine runs in every NMI,
; and keeps the frames' time (net_sound).
;
; The exchange is made where the game reads its controllers, after the
; NMI's writes to the PPU and before the game's work: the buttons go out
; at once, and the other console's are asked for at the last moment they
; can be used. Bubble Bobble has no splits of the screen, and no IRQs, so
; nothing can interrupt the library's cycle-timed serial routines. It is
; the PEER service's TICKS as a short frame (nesp32's docs/PROTOCOL.md).
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.
;
; The game's main loop counts IDLE_COUNT up to $FF from the reset, which
; the game reads as it plays; how far it had got at the first NMI was a
; matter of cycles. The netplay ROM has it $FF from the reset (net_reset).

.include "net_ram.inc"

.segment "CODE"

; What the fixed bank calls, by number in X (net_call, net/fill.inc),
; first in the bank's part.
net_entry:
    lda net_entries_hi,x
    pha
    lda net_entries_lo,x
    pha
    rts
.assert net_entry = NET_ENTRY, error, "net_call calls NET_ENTRY"

net_entries_lo:
    .byte <(net_frame - 1), <(net_reset - 1), <(menu_frame - 1), <(net_title_start_at - 1)
    .byte <(net_title_cursor_at - 1), <(net_title_select_at - 1)
net_entries_hi:
    .byte >(net_frame - 1), >(net_reset - 1), >(menu_frame - 1), >(net_title_start_at - 1)
    .byte >(net_title_cursor_at - 1), >(net_title_select_at - 1)
.assert NET_FRAME = 0 && NET_RESET = 1 && NET_MENU = 2 && NET_TITLE = 3, error, "net_entries' order"
.assert NET_CURSOR = 4 && NET_SELECT = 5, error, "net_entries' order"

.define NESP_APP "BUBL"
NESP_APP_VERSION = 2

.include "nesp.inc"

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

.segment "CODE"

; From the reset, once the game has set itself up: the faster ways into
; the PRG RAM, OUT0 to mark, IDLE_COUNT up, and into a session if
; net_start_session asked for one.
net_reset:
.ifdef NET_FAST
    jsr net_fast_copy
.endif
    lda #OUT0_MARK
    sta JOY1
    lda #$FF
    sta IDLE_COUNT
    lda #$00
    sta net_mode
    sta net_stalled
    sta net_menu
    sta net_autostart
    sta net_in_nmi
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
    ; Straight into a game for two, past the logo and the title: the
    ; players have said what they want, in the menu (net_logo,
    ; net_title_cursor). The scroll as the logo would have left it.
    lda #$10
    sta net_autostart
    lda #$00
    sta SCROLL_Y
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
    sta PPUCTRL
    sta PPUMASK
    sta net_mode
    sta net_menu
    jmp RESET

; --- the title -----------------------------------------------------------------

; Start at the title's choices (net_title_start): with 2P START and no
; session, the menu has the NMIs from the next on. A session that has
; just begun is on its way into its game for two.
net_title_start_at:
    lda #$00
    sta net_autostart
    lda net_mode
    bne @exit
    lda TITLE_CURSOR
    cmp #TITLE_2P_START
    bne @exit
    lda #NET_MENU_FIRST
    sta net_menu

@exit:
    rts

; The title's choices begin with the cursor on 1P START; in a session, on
; 2P START, a line further down (net_title_cursor). The game has put its
; marker beside the first line.
net_title_cursor_at:
    lda #$00
    sta TITLE_CURSOR
    lda net_mode
    beq @exit
    inc TITLE_CURSOR
    lda SPRITES
    clc
    adc #TITLE_LINE
    sta SPRITES
    sta SPRITES+4

@exit:
    rts

; Select at the title's choices: the cursor a line down, as the game's
; own code then has it (net_title_select). In a session it passes over the
; choices for one: 1P CONTINUE to 2P CONTINUE, its marker a line further,
; and from PASSWORD round to 2P START, its marker put a line above it for
; the game to move down. With no session it passes over 2P CONTINUE, which
; goes on with a session's game: 1P CONTINUE to PASSWORD.
net_title_select_at:
    inc TITLE_CURSOR
    lda TITLE_CURSOR
    ldx net_mode
    beq @alone
    cmp #TITLE_LINES
    bne @session
    lda #TITLE_2P_START
    sta TITLE_CURSOR
    lda TITLE_MARKER            ; the marker's place beside 1P START
    sta SPRITES
    sta SPRITES+4
    rts

@session:
    cmp #TITLE_1P_CONTINUE
    beq @pass
    rts

@alone:
    cmp #TITLE_2P_CONTINUE
    bne @exit

@pass:
    inc TITLE_CURSOR
    lda SPRITES
    clc
    adc #TITLE_LINE
    sta SPRITES
    sta SPRITES+4

@exit:
    rts

TITLE_2P_START  = 1
TITLE_1P_CONTINUE = 2
TITLE_2P_CONTINUE = 3
TITLE_LINES     = 5             ; the last, PASSWORD, is 4
TITLE_LINE      = $18           ; the marker's move from one choice to the next
SPRITES         = $0200         ; the marker is the first two
TITLE_MARKER    = L7_C976       ; the title's sprites, the marker beside 1P START first

; --- a frame -------------------------------------------------------------------

; Each NMI, in place of the game's read of the controllers
; (net_ctrl_hook).
;
; With no session it is the game's read, with OUT0 put back to mark after
; it.
;
; In a session it reads this console's controller for the tick net_delay
; from now and makes the exchange. With both players' buttons for this tick
; here, they go where the game's read would have put them; with them not
; here, net_stalled is set, and the NMI ends.
net_frame:
    lda net_mode
    bne @session
    jsr CTRL_READ
    lda #OUT0_MARK
    sta JOY1
    rts

@session:
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
    ; As the game's read leaves them: the buttons in PAD_PRESSED, and from
    ; them what is newly pressed and what is held.
    lda net_pads
    sta PAD_PRESSED
    lda net_pads+1
    sta PAD_PRESSED+1
    jmp CTRL_EDGES

net_late_stall:
    inc net_late

net_stall:
    lda #NET_STALL
    sta net_stalled
    lda #$00                    ; the NMI ends here (net_ctrl_hook), and is off till then
    sta net_in_nmi
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
; sprites. Left out of the zero page are its scratch ($00-$0F), the NMI's
; stack pointer as the tasks saw it ($1D), the PPU's status as the NMI read
; it ($20, for the sprites' flicker), the link's own bytes, and the sound
; engine's ($CA-$F0), which runs in every NMI, a stall's too. Both
; consoles work it out at the start of the same tick, CHECK_AT.
; Each byte goes in with A rotated, its bits round and not through the
; carry, and EORed: a step that loses nothing, so that one byte that
; differs always makes the digest differ. (A rotate through the carry and
; an ADC, as it was, lost what came early: a byte of the zero page that
; differed went unseen some 255 times in 256.)
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
@sprites:
    cmp #$80                    ; bit 7 into carry: a rotate of A alone
    rol a
    eor SPRITES,x
    inx
    bne @sprites
    rts

; The zero page in the digest: from each first byte to before each second.
net_digest_ranges:
    .byte $10, $1D, $1E, $20, $21, nesp_ptr, nesp_ptr + 2, $CA, $F5, $FC
net_digest_ranges_end:
.assert nesp_ptr = $64 && nesp_rx_data = $F1 && nesp_tries = $F4, error, "the digest's ranges"

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

; Controller 1 into net_temp, as the game's CTRL_READ_ONCE reads it, with
; the Famicom's expansion pad's buttons too. OUT0 is low for the reads and
; no longer: the nesp32 takes it for a byte of noise.
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

; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    lda net_read
    sec
    sbc net_acked
    rts

; From the menu: LOCAL GAME. A game for two on this console, as the title's
; 2P START would have begun it: the title, asleep since (net_title_start),
; goes on at the next NMI, which is the game's.
net_menu_local:
    lda #$00
    sta net_menu
    rts

.include "menu.inc"
.ifdef NET_FAST
.include "fast.inc"
.else
.segment "FAST"                 ; none: the game keeps its own
.endif

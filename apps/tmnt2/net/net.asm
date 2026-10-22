; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. All of bank 29,
; which the game leaves empty; tmnt2.asm includes this at its end when
; NETPLAY is defined, and net/fill.inc has what has to be in the fixed
; bank.
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
;             handler has done its writes to the PPU and set up the IRQs,
;             and now stops short of the game (net_ctrl). The NMIs that
;             follow (net_nmi_stalled) write nothing to the PPU, whose
;             picture stands, and try again; the one that has the buttons
;             runs the game.
;   a lag     the last NMI's work was not finished. The game's own answer
;             to that is left as it is: the sound goes on and nothing else
;             is done.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The music is the exception: the sound engine runs in every NMI,
; and keeps the frames' time.
;
; The exchange is made where the NMI has set up the scanline counter for
; the frame's IRQs, and before it lets them in: the first IRQ is never
; sooner than 5794 cycles after (README.md), and the exchange takes some
; 3100, so nothing interrupts the library's cycle-timed serial routines
; and no split of the screen comes late. The controller is read there too,
; so that the buttons go out at once and the other console's are asked for
; at the last moment they can be used. It is the PEER service's TICKS as a
; short frame (nesp32's docs/PROTOCOL.md).
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.
;
; The game's own idle loop stirred INF_LOOP_COUNTER, its random number, for
; as long as the CPU had nothing else to do, so its value hung on how many
; cycles each frame took. Two consoles given the same buttons would not
; play the same game. The netplay ROM's idle loop does nothing, and the
; number is stirred once a tick instead (net_stir), in a game for one or two
; on one console too.

.include "net_ram.inc"

.segment "CODE"

; What the fixed bank calls, by number in X (net_call29, net/fill.inc),
; first in the bank.
net_entry:
    lda net_entries_hi,x
    pha
    lda net_entries_lo,x
    pha
    rts
.assert net_entry = $A000, error, "net_call29 calls $A000"

net_entries_lo:
    .byte <(net_frame - 1), <(net_reset - 1), <(menu_frame - 1)
net_entries_hi:
    .byte >(net_frame - 1), >(net_reset - 1), >(menu_frame - 1)
.assert NET_FRAME = 0 && NET_RESET = 1 && NET_MENU = 2, error, "net_entries' order"

.define NESP_APP "TMN2"
NESP_APP_VERSION = 1

.include "nesp.inc"

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

.segment "CODE"

; From the reset, once it has cleared the memory: the PRG RAM on, OUT0 to
; mark, and into a session if net_start_session asked for one.
net_reset:
    lda #MMC3_RAM_ON
    sta MMC3_PRG_RAM
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_mode
    sta net_stalled
    sta net_menu
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
    ; Straight into a game for two, past the story and the title: the
    ; players have said what they want, in the menu. The title's 2 TURTLES
    ; is taken as chosen, and the game goes on to the turtle select.
    lda #$01
    sta TITLE_PLAYERS_COUNT_CURSOR_0_1
    lda #$03
    sta STATE_SWITCH_INITIAL_MENUS
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
    jmp RESET_HANDLER


; From the menu: LOCAL GAME. A game for two on this console, as the title's
; Start would have begun it, past the flashing of 2 TURTLES (the menu has
; the screen): on to the title's next state, with the picture off for a
; few frames while it draws its own.
net_menu_local:
    lda #$00
    sta net_menu
    lda #$03
    sta DISABLE_RENDERING_X_FRAMES
    jmp SWITCH_MENU_STATE_TO_A  ; state 3, the game's data for two

; Each NMI, after the counter's setup and before the IRQs are let in.
;
; With no session it stirs the random number, and the game's own read of
; the controllers follows (net_ctrl).
;
; In a session it reads this console's controller for the tick net_delay
; from now, makes the exchange, and leaves both players' buttons for this
; tick in net_pads if they are here, or net_stalled set if not.
net_frame:
    lda net_mode
    bne @session
    jmp net_stir

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
    ; The countdown the NMI keeps before it lets the picture on, which the
    ; game reads too, goes by ticks: one less than when this NMI began, as
    ; the NMI's own code makes it, whichever way the NMI came here; and
    ; so before the digest is taken.
    lda net_dis
    beq :+
    sec
    sbc #$01
:
    sta DISABLE_RENDERING_X_FRAMES
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
    ; fall through

; INF_LOOP_COUNTER, stirred once a tick from what both consoles have alike:
; the number itself, the script's count of frames and the buttons the
; players held at the last tick.
net_stir:
    lda INF_LOOP_COUNTER
    asl
    asl
    clc
    adc INF_LOOP_COUNTER        ; 5 times the number
    sec
    adc IRQ_SCRIPT_RUN_COUNT
    eor CTRL_PREV_A
    clc
    adc CTRL_PREV_A+1
    sta INF_LOOP_COUNTER
    rts

net_late_stall:
    inc net_late

net_stall:
    lda #$01
    sta net_stalled
    ; The countdown goes by ticks: as it was when this NMI began.
    lda net_dis
    sta DISABLE_RENDERING_X_FRAMES
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
; sprites. Left out of the zero page are its scratch ($00-$0F), the flag
; of a frame under way (set before this in a tick's NMI, and after it in a
; stalled one's), the link's own bytes, the sound engine's, and what the
; IRQs keep: the frame's chain
; of handlers and the background's animation, which step with the picture
; in every frame, a stall's too (README.md). Both consoles work it out at
; the start of the same tick, CHECK_AT.
net_digest:
    lda #$00
    clc
    ldy #$00
@range:
    ldx net_digest_ranges+1,y
    stx net_temp                ; where it ends
    ldx net_digest_ranges,y
@zero:
    rol a
    adc $00,x
    inx
    cpx net_temp
    bne @zero
    iny
    iny
    cpy #net_digest_ranges_end - net_digest_ranges
    bne @range
    ldx #$00
@sprites:
    rol a
    adc SPRITE_PAGE,x
    inx
    bne @sprites
    rts

; The zero page in the digest: from each first byte to before each second.
net_digest_ranges:
    .byte $10, nesp_rx_data, nesp_rx_data + 1, FLAG_FRAME_UNFINISHED
    .byte FLAG_FRAME_UNFINISHED + 1, nesp_tx_data
    .byte nesp_tx_data + 1, nesp_rx_end, $2F, nesp_ptr
    .byte nesp_tries + 1, $50, $53, $56, $58, $5A, $5B, $5C, $5E, $A6, $A7, $E0
net_digest_ranges_end:
.assert nesp_rx_data = $1A && nesp_tx_data = $26 && nesp_rx_end = $2C, error, "the digest's ranges"
.assert FLAG_FRAME_UNFINISHED = $1C, error, "the digest's ranges"
.assert nesp_ptr = $35 && nesp_tries = $37, error, "the digest's ranges"

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

; Controller 1 into net_temp, as the game's LATCH_READ_CTRL reads it.
; OUT0 is low for the reads and no longer: the nesp32 takes it for a byte
; of noise.
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

; The last byte of bank 29 is the ROM's.
.segment "NET29_END"
    .byte $3D

; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. net/net.asm
; includes it, after net/net_ram.inc. It runs from the PRG RAM, where the
; reset copies it (net/cart.inc). It is Jackal's (apps/jackal/net/net.inc),
; with River City Ransom's tick.
;
; Both consoles run the whole game. What crosses the link is the buttons:
; one byte for each tick. A console takes a tick only when it holds both
; players' buttons for it, so the two games see the same buttons at the
; same tick and stay the same. Its own buttons are used net_delay ticks
; after they were read, which is the time they have to reach the other
; console. That delay is each console's own, and changes as the game goes,
; as its nesp32 advises (nesp32's peer.c), from what the other console
; reports of how this one's buttons have been arriving; this console
; reports the same of the other's, in one exchange in 128.
;
; A tick is a read of the controllers by the game: every read goes through
; READ_PADS ($FD1D), which comes here (net_read_pads). In play that is once
; a pass of the main loop, which takes two frames, or three when its work
; runs long; on the pause's screens, the choices before the game and
; Slick's letter, once a frame. The game's state depends on the buttons it
; reads and on nothing else: not on how many frames a pass took, nor on
; where in the pass an NMI or an IRQ came (tests/test_lockstep.py). So a
; read that has no buttons for its tick yet waits for them, and the game
; with it, and nothing else need be done to keep the two alike.
;
; Where the exchange is made:
;
;   in play       the main loop reads at the top of each pass, with the NMI
;                 on. The game's NMI (NMI_C0), once it has written to the
;                 PPU and set up the IRQ that splits off the HUD, makes the
;                 exchange for the next tick (net_nmi_count). This
;                 console's controller for it is read there too, in the NMI
;                 net_lead frames before the pass is to end (net_read_late),
;                 not at the read: a press need not wait out the pass. A
;                 read that finds no buttons waits for an NMI that brings
;                 them; the picture stands, and the music goes on (the
;                 sound engine runs in the IRQ).
;   the screens   those read with the NMI off, after the frame's writes to
;                 the PPU. The read makes the exchange itself, with the IRQ
;                 held off, and with no buttons waits for the next vblank
;                 and makes it again.
;
; Nothing breaks into an exchange: in an NMI the IRQ waits, and in the main
; thread the NMI is off and the IRQ held off. So the library's counting
; receiver serves both.
;
; The title's first screen reads the controllers in its NMI (NMI_80_READ).
; In a session that read has no buttons: the screen is passed with 2P PLAY
; chosen (net_select_wait).
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.pushseg
.segment "NETCODE"

.define NESP_APP "RIVR"
NESP_APP_VERSION = 1

.pushseg
.include "nesp.inc"
.popseg

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

; From the reset (net_cart_start), with the RAM cleared and before the
; game's own reset: OUT0 to mark, and into a session if net_start_session
; asked for one.
net_reset:
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_mode
    sta net_ready
    sta net_menu
    sta net_drawing
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
    lda net_boot+1
    sta net_role
    lda net_boot+2
    jsr net_advise
    sta net_delay
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
    sta net_waiting
    sta net_defer
    sta net_done
    sta net_work
    lda #$02
    sta net_rate_ask            ; the session's own rate, asked for at its second try:
    lda #$01                    ; the first, the reset's, is followed by the logo
    sta net_mode                ; last, when the rest is in place

@exit:
    rts

; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks. Both consoles begin from the state of one switched on, at the
; first tick. Does not return: the game starts again from its reset.
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
    jmp net_cart_start

; --- the first screen ------------------------------------------------------------

; Each frame of the first screen, in place of its wait for the NMI
; (SELECT_WAIT). In a session it is passed at once, with 2P PLAY chosen and
; the boys' sides as the screen begins them: Start, as its NMI's read
; would have it.
net_select_wait:
    jsr WAIT_NMI_COUNT
    lda net_mode
    beq @exit
    lda #$01
    sta MODE_LINE
    lda #$02
    sta PLAYERS
    lda #BUTTON_START
    sta PAD_PRESSED

@exit:
    rts

; Start at the first screen (SELECT_DONE), in place of its call of
; NMI_OFF. With 2P PLAY chosen and no session, the menu has the NMI until
; LOCAL GAME, and the main thread waits here; then the game goes on as the
; screen's Start would have. A session that is begun from the menu starts
; again from the reset, and does not come back.
net_select_start:
    lda net_mode
    bne @game
    lda MODE_LINE
    beq @game
    lda #NET_MENU_FIRST
    sta net_menu
:
    lda net_menu
    bne :-
    jsr SET_SPRITE_CHR          ; the menu's cursor had a bank of its own

@game:
    jmp NMI_OFF

; From the menu: LOCAL GAME. The main thread goes on from net_select_start.
net_menu_local:
    lda #$00
    sta net_menu
    rts

BUTTON_START    = $10

; --- the NMI ---------------------------------------------------------------------

; The NMI vector. The menu's while the menu is up: bank 9 in for it, and
; the game's banks put back after, as the game's NMI puts them back
; (BANKS_BACK). Otherwise the game's. Each counts toward net_quiet.
net_nmi:
    inc net_quiet
    bne :+
    dec net_quiet
:
    bit net_menu
    bmi @menu
    jmp NMI

@menu:
    pha
    txa
    pha
    tya
    pha
    lda #$06
    sta MMC3_SELECT
    lda #NET_MENU_R6
    sta MMC3_DATA
    lda #$07
    sta MMC3_SELECT
    lda #NET_MENU_R6 + 1
    sta MMC3_DATA
    jsr menu_frame
    jsr BANKS_BACK
    pla
    tay
    pla
    tax
    pla
    rti

; In the game's NMI (NMI_C0), in place of its count of NMI_COUNT, once it
; has written to the PPU and set up the IRQ: the count, and in a session
; with no buttons yet for the next read, an exchange for them. The first
; NMI of a pass sends the buttons its read took, a frame or two before the
; other console's next read needs them.
net_nmi_count:
    inc NMI_COUNT
    lda net_mode
    beq @exit
    lda net_done
    cmp #$01
    bne @ready
    inc net_done                ; the first NMI since the work's end: how long it took
    lda NMI_COUNT
    sec
    sbc net_took
    sta net_work

@ready:
    lda net_ready
    bne @exit
    lda net_defer
    beq @try
    ; The read for the next tick is put off: until the NMI it is due in, or
    ; the work is done (the pass may end at the next NMI), or the game's read
    ; waits. Until then no exchange: there is nothing new to send.
    lda net_waiting
    ora net_done
    bne @due
    lda NMI_COUNT
    cmp net_due
    bcc @exit

@due:
    lda #$00
    sta net_defer

@try:
    jmp net_try

@exit:
    rts

; A pass's work is done, in place of its last call (L7_FAB8, the sound
; engine's orders), just before MAIN_WAIT.
net_pass_done:
    jsr L7_FAB8
    lda #$01
    sta net_done
    rts

; --- the sprites ------------------------------------------------------------------

; The game's pass fills the sprites' page ($0200) in DRAW_OBJECTS and hides
; the slots it did not fill (L7_DFE2), and its NMI sends the page to the
; PPU (SPRITE_DMA). DRAW_OBJECTS began with a wait until no IRQ had come
; since the NMI (IRQ_SPLIT clear), so that the page was filled before the
; next NMI sent it: a pass that came to it after the HUD's IRQ, on line 29,
; waited for the next frame, half a frame a pass on the whole. In the
; netplay ROM it does not wait. An NMI that comes while the page is being
; filled does not send it, and the sprites of the frame before stand for a
; frame, as they do in a frame the game runs late. This is the time of the
; frames only: nothing of the game depends on it. With and without a
; session alike.

; At DRAW_OBJECTS, in place of its wait.
net_draw_begin:
    lda #$80
    sta net_drawing
    lda $BFFF                   ; each bank's last byte is its pair's number
    sta net_draw_bank
    rts

; In place of the pass's call of L7_DFE2, which ends the page. The banks
; the pass had at DRAW_OBJECTS put back, if the objects' drawing left
; bank 3's pair in.
net_draw_end:
    jsr L7_DFE2
    lda #$00
    sta net_drawing
    lda net_draw_bank
    asl a
    cmp BANK_R6
    beq :+
    lda net_draw_bank
    jmp BANK_PAIR
:
    rts

; Each object's drawing (L7_ED0E) puts in the pair of bank 3, its sprites'
; tables, and puts back the pair it found when it is done: two switches an
; object, some 80 cycles each. In the pass's drawing the pair is put in for
; the first object and left in until net_draw_end. Called from elsewhere,
; by banks 1 and 2, the drawing switches as the game's does. X kept.
net_object_bank:
    bit net_drawing
    bpl :+
    lda BANK_R6
    cmp #$03 * 2
    beq @in
:
    lda #$03
    jmp BANK_PAIR

@in:
    rts

; At the drawing's end, with A the pair it found.
net_object_back:
    bit net_drawing
    bmi :+
    jmp BANK_PAIR
:
    rts

; In the game's NMI, in place of SPRITE_DMA.
net_sprite_dma:
    bit net_drawing
    bmi :+
    jmp SPRITE_DMA
:
    rts

; --- a read ----------------------------------------------------------------------

; Each read of the controllers, in place of READ_PADS's first call of
; READ_JOYS (so at $FD1D, which jumps here).
;
; With no session it is the game's read, with OUT0 back to mark after it:
; the game leaves it low, which the nesp32 would take for the start of a
; byte.
;
; In a session it is a tick: both players' buttons for it, as the game's
; read would have them, once they are here.
net_read_pads:
    lda net_mode
    bne @session
    jsr READ_JOYS
    jsr READ_FAMICOM
    lda #OUT0_MARK
    sta JOY1
    jmp READ_EDGES

@session:
    ; OUT0 to mark: the game's reset left it low, and the nesp32 has to
    ; see it at rest before a request.
    lda #OUT0_MARK
    sta JOY1
    ; The first screen's read in its NMI: no buttons.
    tsx
    lda $0101,x
    cmp #<(NMI_80_READ + 2)
    bne @wait
    lda $0102,x
    cmp #>(NMI_80_READ + 2)
    bne @wait
    ; It is in the NMI, after the NMI's writes to the PPU: a try for the
    ; next tick, or with one here, an exchange all the same. The screens
    ; that have this NMI (the first, the title) read nothing for seconds,
    ; and a session's line falls back to the link's rate with no frames on
    ; it for half a second (PEER_RATE_QUIET_MS).
    lda net_ready
    bne :+
    jsr net_try
    jmp @none
:
    jsr net_exchange

@none:
    lda #$00
    sta PAD_PRESSED
    sta PAD_PRESSED+1
    jmp READ_EDGES

@wait:
    lda net_ready
    bne @take
    lda #$01
    sta net_waiting
    lda PPUCTRL_SHADOW
    bmi @wait                   ; the NMI is on: its exchanges bring them
    php
    sei
    jsr net_try
    plp
    lda net_ready
    bne @take
:
    bit PPUSTATUS               ; a frame, and try again
    bpl :-
    jmp @wait

@take:
net_take:                       ; (a name for the tests: a tick taken)
    ; The game as it is at the start of this tick, the same on both consoles,
    ; for both to send when they come to CHECK_TICK.
    lda net_tick
    cmp #CHECK_AT
    bne :+
    jsr net_digest
    sta net_check
:
    lda net_pads
    sta PAD_PRESSED
    lda net_pads+1
    sta PAD_PRESSED+1
    inc net_tick
    ; This console's controller for the tick net_delay on: a press is used
    ; net_delay ticks after the game would have used it alone. No NMI
    ; tries while net_ready is set, and none makes an exchange, with OUT0
    ; low, in the middle of this read.
    jsr net_read_late
    bcc :+
    jsr net_read_local
:
    lda #$00                    ; last: an NMI may now try for the next
    sta net_waiting
    sta net_ready
    ; With the NMI off, a screen's read: its exchange for the next tick now,
    ; which sends the buttons just read, a frame before the other console's
    ; next read wants them.
    lda PPUCTRL_SHADOW
    bmi :+
    php
    sei
    jsr net_try
    plp
:
    jmp READ_EDGES

; --- a try for a tick's buttons ----------------------------------------------------

; Read this console's controller for the tick net_delay from net_tick, make
; the exchange, and if both players' buttons for net_tick are here, put
; them in net_pads and set net_ready. In an NMI, or in the main thread with
; the NMI off and the IRQ held off.
net_try:
    bit nesp_fast
    bpl @asked
    lda net_quiet
    cmp #NET_QUIET_FRAMES
    bcc @asked
    ; The nesp32 has gone back to the link's rate: so does this console, and
    ; asks again, which is no try that failed.
    lda #$00
    sta nesp_fast
    dec net_rate_tries
    jmp net_rate

@asked:
    lda net_rate_ask
    beq @ticks
    dec net_rate_ask
    bne @ticks
    jmp net_rate                ; in place of this try's exchange

@ticks:
    jsr net_read_local          ; one the read had no room for
    jsr net_exchange
    lda net_read
    sec
    sbc net_tick
    beq net_none                ; this console's own buttons are still to read: no room
    bmi net_none
    lda net_have
    cmp net_tick
    beq net_late_none           ; the other's are not here
    sec
    sbc net_tick                ; how many ticks of them are
    cmp net_margin
    bcs :+
    sta net_margin
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
    lda #$00
    sta net_silent
    lda #$01
    sta net_ready
    rts

net_late_none:
    lda net_waiting             ; a tick the game waited for
    beq net_none
    inc net_late

; No buttons for this tick yet.
net_none:
    inc net_silent
    lda net_silent
    cmp #SILENT_FRAMES
    bcc :+
    jmp net_drop
:
    rts

; This console's controller for the tick net_delay after net_tick's last,
; net_tick + net_delay - 1, unless it is in already. The delay is changed
; here, as the nesp32 advises: made a tick longer, the tick between has the
; buttons as they were last read; made a tick shorter, this read goes by.
net_read_local:
    lda net_defer
    bne @exit                   ; put off (net_read_late)
    lda net_read
    clc
    adc #$01
    sec
    sbc net_delay
    cmp net_tick
    bne @exit                   ; read already
    lda net_read
    sec
    sbc net_acked
    cmp #RING-1
    bcs @exit                   ; no room until the nesp32 has taken some
    lda net_want
    cmp net_delay
    beq @read
    bcs @longer
    dec net_delay               ; a tick shorter: this read goes by
    rts

@longer:
    inc net_delay               ; a tick longer: the tick between
    lda net_pad
    jsr net_store

@read:
    jsr net_read_port
    sta net_pad
    jmp net_store

@exit:
    rts

; At a read that takes a tick, in play: whether this console's controller
; for the next tick is to be read now (carry set) or put off to an NMI
; (net_nmi_count). Read at the top of the pass, a press waits the whole
; pass, two frames or three, before the other console can be sent it; but
; it only has to reach the other console by the end of the pass, net_lead
; frames after it is sent. So the read is put off to the NMI that is
; net_lead before the pass is to end: the pass ends at the NMI of the
; second count of NMI_COUNT, or at the first after the work is done if
; later, which the last pass's work foretells (net_work). A pass whose
; work ends sooner than foretold has the read in the NMI after it.
; Only with a delay of one tick, and with the NMI on.
net_read_late:
    lda #$00
    sta net_done
    lda PPUCTRL_SHADOW
    bpl @now                    ; a screen's read: its exchange follows at once
    lda net_delay
    cmp #$02
    bcs @now
    cmp net_want
    bne @now                    ; the delay changes at this read
    lda NMI_COUNT
    sta net_took
    clc
    adc net_work                ; the NMI the work will end by
    cmp #$02
    bcs :+
    lda #$02                    ; and the pass's end
:
    sec
    sbc net_lead
    bcc @now
    beq @now
    cmp NMI_COUNT
    bcc @now
    beq @now
    sta net_due
    lda #$01
    sta net_defer
    clc
    rts

@now:
    sec
    rts

; The nesp32's advice, A: the frames a press needs to cross (the network's
; time one way, and a margin), for it counts a tick as a frame. They are
; the late read's lead (net_lead). The delay in this game's ticks, of two
; frames or three, is half of them, rounded up, into net_want and A: a read
; at the top of a pass is sent a frame later, at the pass's first NMI, so
; one tick covers no more than 2 frames.
net_advise:
    sta net_lead
    clc
    adc #$01
    lsr a
    sta net_want
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

; A digest of the game into A: the zero page the game keeps, less its
; scratch and the HUD's split ($00-$14), the scratch of its drawing of the
; background's columns, which it does only while the queue of writes to the
; PPU has room ($1A-$1C, $24-$26, $2A-$2B), the link's own bytes and the
; PPU's and the banks' shadows ($F7-$FF), and $3E's bit 3 (a new palette
; for the NMI to upload, which the main thread sets and the NMI clears);
; and the objects' pages ($0300-$04FF).
; The sound engine's ($0700 on) is not in it, nor the NMI's queue of writes
; to the PPU, which keep the frames' time. Both consoles work it out at the
; start of the same tick, CHECK_AT.
; Each byte goes in with A rotated, its bits round and not through the
; carry, and EORed: a step that loses nothing, so that one byte that
; differs always makes the digest differ.
net_digest:
    lda #$00
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
    sta net_temp
    lda $3E
    and #<~$08
    eor net_temp
    ldx #$00
@objects:
    cmp #$80
    rol a
    eor $0300,x
    cmp #$80
    rol a
    eor $0400,x
    inx
    bne @objects
    rts

; The zero page in the digest: from each first byte to before each second.
net_digest_ranges:
    .byte $18, $1A, $1D, $24, $27, $2A, $2C, $3E, $3F, nesp_tries, nesp_tries + 1, PPUMASK_SHADOW
net_digest_ranges_end:
.assert nesp_rx_data = $15 && nesp_ptr = $16 && nesp_tries = $F3 && PPUMASK_SHADOW = $F7, error, "the digest's ranges"

; Controller 1 into A, as the game's read reads it: D0, or D1 for a
; Famicom's expansion port. OUT0 is low for the reads and no longer: the
; nesp32 takes it for a byte of noise. Port 2 is the line to the nesp32,
; and is not read. The game plays no samples, so nothing spoils a read
; (nesp32's docs/PHANTOM-RIGHT.md), and one does.
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
    ; tries that waited (7 at the most) and the fewest ticks held (3). It
    ; goes with the buttons just read, in this try or not at all: in a
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
    jsr net_advise
    jmp @acks

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
    sta net_quiet
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
; the same once more if no reply to it is heard: the nesp32 has taken the
; buttons all the same, and passes them over when they come twice. Asked
; again in the same try, the game does not have to wait a frame for it.
; Carry and A as nesp_short leaves them.
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
; link's. The try has no buttons.
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
    bcs @unheard
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
    lda #$00
    sta net_quiet

@exit:
    jmp net_none

@unheard:
    lda net_rate_tries          ; asked again at the next try, a few times
    cmp #NET_RATE_TRIES
    bcs @exit
    lda #$01
    sta net_rate_ask
    bne @exit

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

; The end of what net_cart_start copies into the PRG RAM: the library's
; code is the last of it (net/rcr_net.cfg).
.pushseg
.segment "CODE"
net_image_end:
.popseg
.assert net_image_end <= NET_IMAGE_END, error, "net_cart_start copies too little"

.popseg

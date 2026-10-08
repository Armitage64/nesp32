; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. In the space
; the game leaves at the end of its fixed bank; bank7.asm includes it when
; NETPLAY is defined.
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
;             short of the game. The NMIs that follow (net_nmi_stalled)
;             write nothing to the PPU, whose picture stands, and try
;             again; the one that has the buttons runs the game.
;   a lag     the last NMI's work was not finished. The game's own
;             answer to that is left as it is: the sound goes on and
;             nothing else is done.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. The music is the exception: the sound engine runs in every NMI,
; and keeps the frames' time.
;
; The exchange with the nesp32 is made before the game's work, as soon as
; the controller has been read, so that the buttons go out at once and the
; other console's are asked for at the last moment they can be used. It is
; the PEER service's TICKS as a short frame (nesp32's docs/PROTOCOL.md):
; every cycle of it is one the game's frame has to spare. The link is
; nesp32's library, whose cycle-timed serial routines nothing interrupts
; here but a sample: see the tests.
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.include "ram.inc"

; The menu is in bank 5 (net/menu.inc).
.import menu_frame
.export net_far_call, net_far_hello, net_start_session, net_menu_local

.define NESP_APP "CNTR"
NESP_APP_VERSION = 1

.pushseg
.include "nesp.inc"
.popseg

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

; From the reset code, once it has cleared the memory: OUT0 to mark, and
; into a session if net_start_session asked for one.
net_reset:
    lda #OUT0_MARK
    sta JOY1
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
    sta CPU_GRAPHICS_BUFFER+$f0 ; no mark of an earlier game: the top score is the first one
    ; Straight into a two-player game, with no title first: the players
    ; have said what they want, in the menu. (The title is come back to
    ; when the game ends, still in the session, and player 1's Start
    ; begins another from there.)
    lda #$01
    sta PLAYER_MODE
    lda #$04
    sta GAME_ROUTINE_INDEX      ; game_routine_04: a new game's scores and lives
    lda #$1e
    sta PPUMASK_SETTINGS        ; the picture on, which the title's graphics would have set
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
    lda #$ff
    sta net_margin
    lda #$01
    sta net_mode                ; last, when the rest is in place

@exit:
    rts

; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks. Both consoles begin from the state of one switched on for the
; first time, at the first tick. Does not return: the game starts again
; from its title.
net_start_session:
    sei
    sta net_boot+1
    stx net_boot+2
    eor net_boot+2
    eor #NET_BOOT_CHECK
    sta net_boot+3
    lda #NET_BOOT_MARK
    sta net_boot

; The session is over: the other console is gone. Start again as a
; console that was reset.
net_drop:
    lda #$00
    sta PPUCTRL
    sta PPUMASK
    jmp reset_vector

; Start at the title. Carry set if it is not to start a game: 2 PLAYERS
; with no session is the menu's (net/menu.inc), from the next NMI on.
net_title_start:
    lda PLAYER_MODE
    beq @game
    lda net_mode
    bne @game
    lda #$01
    sta net_menu
    sec
    rts

@game:
    clc
    rts

; An NMI while the menu has the console.
net_menu_nmi:
    ldy #$05
    jsr set_rom_bank_to_y
    jsr menu_frame
    jmp remove_registers_from_stack_and_rti

; From the menu: LOCAL GAME. The title's Start goes on as it would have.
net_menu_local:
    lda #$00
    sta net_menu
    sta CPU_GRAPHICS_BUFFER
    sta GRAPHICS_BUFFER_OFFSET
    lda #$03
    jmp set_game_routine_index_to_a

; From the menu, in bank 5: an exchange. The library's CRC table is in
; bank 1. net_far_hello is nesp_hello; net_far_call is nesp_call for op X
; of PEER's, with Y bytes of payload. Carry set if no reply came.
net_far_hello:
    sty net_temp
    ldy #$01
    jsr set_rom_bank_to_y
    ldy net_temp
    jsr nesp_hello
    jmp net_far_back

net_far_call:
    sty net_temp
    ldy #$01
    jsr set_rom_bank_to_y
    ldy net_temp
    lda #NESP_SVC_PEER
    jsr nesp_call

net_far_back:
    php
    ldy #$05
    jsr set_rom_bank_to_y
    plp
    rts

; An NMI after one that stalled. The PPU has had the last tick's writes
; and the picture stands, so only the sound engine runs before the buttons
; are tried for again.
net_nmi_stalled:
    inc NMI_CHECK
    ldy #$01
    jsr load_bank_number
    jsr handle_sound_slots
    jmp net_nmi_tick

; The controllers. Carry set if there is to be no tick in this NMI.
;
; With no session it is the game's own read, and after it the stir of the
; random number that the idle loop used to do: see net_stir.
;
; In a session it reads this console's controller for the tick net_delay
; from now, makes the exchange, and gives the game both players' buttons
; for this tick if they are here.
net_read_input:
    lda net_mode
    bne @session
    jsr load_controller_state
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
    ; What the game's read leaves behind it, the same on both consoles.
    lda $04
    sta $00
    lda $05
    sta $01
    lda #$00
    sta $07
    sta net_silent
    sta net_stalled
    jsr write_input
    ; fall through

; The original adds the frame counter to RANDOM_NUM for as long as the CPU
; has nothing else to do, so its value hangs on how many cycles each frame
; took: on what the sample channel stole, on where the picture's clock was
; when the console was switched on. Two consoles given the same buttons
; would not play the same game. Here it is stirred once for each frame of
; the game, from what both consoles have alike: the number itself, the
; frame counter and the buttons.
net_stir:
    lda RANDOM_NUM
    asl
    asl
    clc
    adc RANDOM_NUM              ; 5 times the number
    sec
    adc FRAME_COUNTER
    eor CONTROLLER_STATE
    clc
    adc CONTROLLER_STATE+1
    sta RANDOM_NUM
    clc
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
    sec
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

; A digest of the game into A: of the zero page the game keeps, less the
; link's own bytes in it and the sound engine's, and of the sprites. Both
; consoles work it out at the start of the same tick, CHECK_AT.
net_digest:
    lda #$00
    clc
    ldx #$18

@low:
    rol a
    adc $00,x
    inx
    cpx #nesp_rx_data
    bne @low
    ldx #nesp_tx_data+1

@high:
    rol a
    adc $00,x
    inx
    cpx #nesp_ptr
    bne @high
    ldx #$67

@sprites:
    rol a
    adc CPU_SPRITE_BUFFER,x
    dex
    bpl @sprites
    rts

; This console's controller into A. While a sample plays it is read twice,
; and if a fetch spoiled one of the reads, it is as it was the last time
; both were alike. With none playing nothing spoils a read, and one does.
net_read_pad:
    jsr net_read_port
    lda APU_STATUS
    and #$10                    ; a sample has bytes still to fetch
    beq @once
    lda $04
    sta $00
    jsr net_read_port
    lda $04
    cmp $00
    beq @good
    lda net_pad

@good:
    sta net_pad
    rts

@once:
    lda $04
    sta net_pad
    rts

; Controller 1 into $04, as read_controller_state reads it. OUT0 is low
; for the reads and no longer: the nesp32 takes it for a byte of noise.
net_read_port:
    ldx #$00
    stx JOY1
    ldy #$08

@bit:
    lda JOY1
    sta $07
    lsr
    ora $07
    lsr
    rol $04
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
; the same once more if no reply to it is heard. On a console a sample's fetch takes cycles from the serial routines
; now and again, and a reply is misheard; the nesp32 has taken the buttons
; all the same, and passes them over when they come twice. Asked again in
; the same NMI, the game does not have to stand still a frame for it.
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

; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    lda net_read
    sec
    sbc net_acked
    rts

; Netplay: a session's frame. In the menu's bank, where there is room for
; it and for the link's library with its table: the game's bank is full.
; The game's NMI comes here once in every frame of a session that is not a
; lag (net_read_input, net/net.inc), and this goes back by net_back.
;
; A console's own buttons are used net_delay ticks after they were read.
; That delay is each console's own, and changes as the game goes. Nothing
; has to be agreed for it: the other console only ever takes the buttons
; it is given for each tick. Made a tick longer, this console sends the
; buttons it last read once more, for the tick between; made a tick
; shorter, it lets one read go by. Its nesp32 says when, from how long the
; network has been taking (nesp32's docs/PROTOCOL.md, "The delay"), in the
; reply to one exchange in 128. That exchange carries this console's
; report: its delay, how many NMIs waited for the other's buttons, and the
; fewest ticks of them it ever held when it took one.
;
; The exchange with the nesp32 is made before the buttons are given to the
; game, as soon as the controller has been read, so that this console's go
; out at once and the other's are asked for at the last moment they can be
; used. It is the PEER service's TICKS as a short frame: every cycle of it
; is one the game's frame has to spare.
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error



; Reads this console's controller for the tick net_delay from now, makes
; the exchange, and gives the game both players' buttons for this tick if
; they are here. If they are not, net_stalled says so, and the game's NMI
; comes here again in the next frame.
session_frame:
    LDA net_tick
    CLC
    ADC net_delay
    CMP net_read
    BNE @exchange               ; read already: in an NMI that stalled, or a tick ago
    SEC
    SBC net_acked
    CMP #RING - 1
    BCS @exchange               ; no room until the nesp32 has taken some
    LDA net_want
    CMP net_delay
    BEQ @read
    BCS @longer
    DEC net_delay               ; a tick shorter: this tick's buttons went a tick ago,
    BNE @exchange               ; and this read goes by
@longer:
    INC net_delay               ; a tick longer: the tick between has the buttons
    LDA net_pad                 ; as they were last read
    JSR session_store
@read:
    JSR session_read_pad
    JSR session_store
@exchange:
    JSR session_exchange
    LDA net_tick
    CLC
    ADC net_delay
    CMP net_read
    BEQ @stall                  ; this console's own buttons are still to read: no room
    LDA net_have
    CMP net_tick
    BEQ @late                   ; the other's are not here
    SEC
    SBC net_tick                ; how many ticks of them are
    CMP net_margin
    BCS @margin
    STA net_margin
@margin:
    LDA net_tick
    CMP #CHECK_AT
    BNE @take
    JSR session_digest          ; for both consoles to send when they come to CHECK_TICK
    STA net_check
@take:
    LDA net_tick
    AND #RING - 1
    TAX
    LDA net_tick
    CMP #CHECK_TICK
    BNE @buttons
    ; A tick that carried the digests. If they are alike the game goes on
    ; with the buttons of the tick before, for both players.
    LDA net_local,X
    CMP net_remote,X
    BNE session_drop
    DEX
    TXA
    AND #RING - 1
    TAX
@buttons:
    LDY net_role
    LDA net_local,X
    STA a:NET_GAME_BUTTONS,Y
    TYA
    EOR #$01
    TAY
    LDA net_remote,X
    STA a:NET_GAME_BUTTONS,Y
    INC net_tick
    LDA #$00
    STA net_silent
    STA net_stalled
    STA net_waiting
    LDA #$01
    STA NET_GAME_NMI_FLAG       ; the main loop goes on
    BNE session_back
@late:
    INC net_late
@stall:
    LDA #$00
    STA NET_GAME_NMI_FLAG       ; and the main loop waits
    LDA #$01
    STA net_stalled
    INC net_silent
    LDA net_silent
    CMP #SILENT_FRAMES
    BCS session_drop
session_back:
    LDA net_back
    STA net_vector
    LDA net_back + 1
    STA net_vector + 1
    LDA #$00
    JMP net_far



; The session is over: the other console is gone, or is no longer playing
; the same game. Start again as a console that was reset.
session_drop:
    JMP menu_reset



; A into this console's buttons, for the next tick that has none: or, if
; that is the tick that carries the digest, the digest. One tick in 128 is
; the one whose exchange carries the report.
session_store:
    LDX net_read
    CPX #CHECK_TICK
    BNE @buttons
    LDA net_check
@buttons:
    PHA
    TXA
    AND #RING - 1
    TAX
    PLA
    STA net_local,X
    INC net_read
    LDA net_read
    AND #$7F
    CMP #TUNE_AT + 1
    BNE @RTS
    STA net_tune
@RTS:
    RTS



; A digest of the game into A: of the zero page, less the link's own
; bytes in it, the sound engine's, and the flag the main loop waits on.
; Both consoles work it out at the start of the same tick, CHECK_AT.
.macro session_digest_run from, to
    .local @byte
    LDX #from
@byte:
    ROL
    ADC $00,X
    INX
    CPX #<(to)
    BNE @byte
.endmacro

session_digest:
    LDA #$00
    CLC
    session_digest_run $00, NET_GAME_NMI_FLAG
    session_digest_run NET_GAME_NMI_FLAG + 1, net_temp
    session_digest_run net_temp + 1, NET_LINK_ZP
    session_digest_run NET_LINK_ZP + NET_LINK_ZP_SIZE, NET_SOUND_ZP
    session_digest_run NET_SOUND_ZP + NET_SOUND_ZP_SIZE, $100
    RTS



; This console's controller into A and net_pad. The music's drums are
; samples, and on a console the fetch of a sample's byte that falls on a
; read of the controller reads it once more: a button is lost and the ones
; after it come a place early, with Right pressed behind them
; (nesp32's docs/PHANTOM-RIGHT.md). So while a sample has bytes to fetch
; the controller is read twice, as the game's own routine reads it, and if
; a fetch spoiled one of the reads the buttons are as they were the last
; time both were alike. The two reads are done in less time than there is
; between two fetches, so no more than one of them is spoiled. Whether a
; sample plays is asked before the first read and not after it: the fetch
; that spoils a read may be the sample's last.
session_read_pad:
    LDA $4015
    AND #$10                    ; a sample has bytes still to fetch
    PHA
    JSR session_read_port
    PLA
    BEQ @once
    LDA net_temp
    PHA
    JSR session_read_port
    PLA
    CMP net_temp
    BEQ @good
    LDA net_pad
@good:
    STA net_pad
    RTS
@once:
    LDA net_temp
    STA net_pad
    RTS



; The controller into net_temp. OUT0 is low for the reads and no longer:
; the nesp32 takes it for a byte of noise.
session_read_port:
    LDX #$00
    STX JOY1
    LDY #$08
@bit:
    LDA JOY1
    LSR
    ROL net_temp
    DEY
    BNE @bit
    LDX #OUT0_MARK
    STX JOY1
    RTS



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
; it was sent, and its CRC says which request it answers. A reply that is
; not heard is not asked for again in this frame: the game plays no
; samples, and its line is clean.
;
; With net_tune set the request's count is NESP_PEER_TUNE: one tick of
; buttons and then this console's report, and the reply has the delay
; advised after its buttons.
session_exchange:
    LDA net_acked
    AND #RING - 1
    TAX
    LDA net_local,X
    STA nesp_tx + 2
    INX
    TXA
    AND #RING - 1
    TAX
    LDA net_local,X
    STA nesp_tx + 3
    LDA net_acked
    ASL
    ASL
    ASL
    ASL
    STA net_temp
    LDA net_have
    AND #$0F
    ORA net_temp
    STA nesp_tx + 1
    LDA net_tune
    BEQ @plain
    ; The report, in place of a second tick of buttons: the delay, the
    ; NMIs that waited (7 at the most) and the fewest ticks held (3). It
    ; goes with the buttons just read, in this NMI or not at all: in a
    ; later one there might be none to send.
    LDA #$00
    STA net_tune
    LDA net_late
    CMP #$08
    BCC @late
    LDA #$07
@late:
    ASL
    ASL
    STA net_temp
    LDA net_margin
    CMP #$04
    BCC @margin
    LDA #$03
@margin:
    ORA net_temp
    STA net_temp
    LDA net_delay
    ASL
    ASL
    ASL
    ASL
    ASL
    ORA net_temp
    STA nesp_tx + 3
    LDX #$01                    ; one tick of buttons goes with it
    STX net_temp
    LDA #NESP_PEER_TUNE
    LDY #$02
    JSR nesp_short
    BCS @RTS
    CMP #NESP_SHORT_NONE
    BEQ @drop
    PHA
    LDA #$00                    ; a new report begins
    STA net_late
    LDA #$FF
    STA net_margin
    LDA nesp_rx + 4             ; the advice
    BEQ @acks
    CMP #NET_DELAY_MAX + 1
    BCS @acks
    STA net_want
    BCC @acks
@plain:
    LDA net_read                ; how many ticks the nesp32 does not hold
    SEC
    SBC net_acked
    CMP #PER_FRAME + 1
    BCC @count
    LDA #PER_FRAME
@count:
    STA net_temp                ; how many ticks of buttons go
    LDY #$01
    JSR nesp_short
    BCS @RTS
    CMP #NESP_SHORT_NONE
    BEQ @drop                   ; the other console is gone, or the nesp32 was switched off and on
    PHA                         ; whether one of the other's buttons came
@acks:
    LDA net_acked               ; the nesp32 holds what it was sent
    CLC
    ADC net_temp
    STA net_acked
    PLA
    BEQ @RTS
    LDA net_have
    SEC
    SBC net_tick
    CMP #RING
    BCS @RTS                    ; no room: it is asked for again
    LDA net_have
    AND #RING - 1
    TAX
    LDA nesp_rx + 3
    STA net_remote,X
    INC net_have
@RTS:
    RTS
@drop:
    JMP session_drop

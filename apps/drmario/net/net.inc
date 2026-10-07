; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network
; (docs/PROTOCOL.md). Only in the NETPLAY build.
;
; Both consoles run the whole game. What crosses the link is the buttons:
; one byte for each tick, where a tick is one NMI that the game takes. A
; console takes a tick only when it holds both players' buttons for it, so
; the two games see the same buttons at the same tick and stay the same.
; Its own buttons are used INPUT_DELAY ticks after they were read, which is
; the time they have to reach the other console.
;
; An NMI in a session is one of three things:
;
;   a tick    the main loop was waiting and the buttons are here. The
;             handler does all its work, and afterwards makes an exchange
;             with the nesp32: buttons out, the other console's in.
;   a stall   the main loop was waiting but the other console's buttons
;             are not here. Nothing of the game runs. The handler only
;             makes the exchange, and the picture stands still.
;   a lag     the main loop was still at work. Nothing of the game runs.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took.
;
; The music is the exception, and keeps the frames' time, not the ticks'.
; The game runs its sound engine from the main loop, once for each pass,
; which in a session is once a tick: every stall and every lag held the
; music back by a frame, and it was heard. So in a session the engine is
; run from the NMI instead, in every one of the three. It keeps its memory
; to itself (00E0-00EF and 067E-06FF) and the game only leaves it orders
; there, but for the beat it counts for the viruses that dance in the
; one-player game's magnifier, which no session shows.
;
; The link is nesp32's, and the exchange is its PEER service's TICKS
; (nesp32's docs/PROTOCOL.md). All of it is made in the NMI, where nothing
; can interrupt the library's cycle-timed serial routines; the menu, in the
; other bank, has said the hello. sub_B793_read_joy_regs reads the
; controller without leaving OUT0 low.
;
; Ticks are counted from -INPUT_DELAY, so that the buttons read in a
; session's first frame are those of tick 0: the first byte of the stream
; that the nesp32s pass on.

.include "net/ram.inc"

; The link's library. Its routines go behind the serial routines, in the
; page the samples had (net/game.cfg); this file's stay here. The library
; is assembled to be placed by the linker, and the game is not.
NESP_NO_HELLO = 1
net_library_from = *
.pushseg
.reloc
.include "nesp.inc"
.popseg
.org net_library_from




; Wait for the NMI. In place of the game's own two loops, so that the NMI
; can tell a main loop that waits from one still at work.
net_wait_nmi:
    LDA net_mode
    BNE @session
    JSR sub_FFD0                ; the sound engine, as the game's own loop did
@session:
    LDA #$00
    STA ram_nmi_flag
    LDA #$01
    STA net_waiting
@loop:
    LDA ram_nmi_flag
    BEQ @loop
    RTS



; First thing in the NMI. Carry set if the handler is to do nothing more.
net_nmi_head:
    LDA net_mode
    BEQ @run
    LDA net_waiting
    BEQ @lag
    ; No room to read buttons for another tick until the nesp32 has taken
    ; some of those held?
    LDA net_tick
    CLC
    ADC #INPUT_DELAY
    SEC
    SBC net_acked
    CMP #RING
    BCS @stall
    LDA net_have
    CMP net_tick
    BNE @run
@stall:
    INC net_silent
    LDA net_silent
    CMP #SILENT_FRAMES
    BCS net_drop
    JSR net_exchange_game
@skip:
    SEC
    RTS
@lag:
    JSR sub_FFD0                ; the music goes on
    SEC
    RTS
@run:
    CLC
    RTS



; The session is over: the other console is gone. Start again as a
; console that was reset.
net_drop:
    JMP vec_FF00_RESET



; Last thing in an NMI that was not skipped.
net_nmi_tail:
    LDA net_mode
    BEQ @RTS
    LDA #$00
    STA net_waiting
    STA net_silent
    JMP net_exchange_game
@RTS:
    RTS



; The controllers, in a session. Reads this console's controller for the
; tick INPUT_DELAY from now, and gives the game both players' buttons for
; this tick. Then as the game's own: ram_btn_press and ram_btn_hold.
net_read_input:
    JSR sub_B793_read_joy_regs
    LDA net_tick
    CLC
    ADC #INPUT_DELAY
    AND #RING - 1
    TAX
    LDA ram_btn_press
    STA net_local,X
    LDA net_tick
    AND #RING - 1
    TAX
    LDY net_role
    LDA net_local,X
    STA a:ram_btn_press,Y
    TYA
    EOR #$01
    TAY
    LDA net_remote,X
    STA a:ram_btn_press,Y
    INC net_tick
    JMP bra_B7E7



; A session's exchange: PEER's TICKS. Out: up to PER_FRAME ticks of this
; console's buttons, from the first the nesp32 has not said it holds, and
; the tick of the other console's that is wanted next. In: which of this
; console's the nesp32 now holds, and up to PER_FRAME ticks of the other's.
;
;   request   first tick, tick wanted, buttons, buttons
;   reply     next tick to send, first tick, lost, buttons, buttons
;
; Every NMI of a session that is not a lag comes through here once.
net_exchange_game:
    JSR sub_FFD0                ; the sound engine: once a frame, tick or not
    LDA net_acked
    STA nesp_request
    AND #RING - 1
    TAX
    LDA net_local,X
    STA nesp_request + 2
    INX
    TXA
    AND #RING - 1
    TAX
    LDA net_local,X
    STA nesp_request + 3
    LDA net_have
    STA nesp_request + 1
    JSR net_unsent
    CMP #PER_FRAME + 1
    BCC @count
    LDA #PER_FRAME
@count:
    CLC
    ADC #$02
    TAY
    LDA #NESP_SVC_PEER
    LDX #NESP_PEER_TICKS
    JSR nesp_call
    BCS net_RTS
    BNE @drop                   ; a nesp32 that was switched off and on
    ; The nesp32 cannot hold more ticks than were ever read.
    LDA nesp_reply
    SEC
    SBC net_acked
    STA net_temp
    JSR net_unsent
    CMP net_temp
    BCC @buttons
    LDA nesp_reply
    STA net_acked
@buttons:
    LDA nesp_reply + 1
    CMP net_have
    BNE @peer
    LDA nesp_reply_len
    SEC
    SBC #$03
    BEQ @peer
    CMP #PER_FRAME + 1
    BCS @peer
    STA net_temp
    LDY #$00
@take:
    LDA net_have
    SEC
    SBC net_tick
    CMP #RING
    BCS @peer                   ; no room: it is asked for again
    LDA net_have
    AND #RING - 1
    TAX
    LDA nesp_reply + 3,Y
    STA net_remote,X
    INC net_have
    INY
    CPY net_temp
    BNE @take
@peer:
    LDA nesp_reply + 2
    BEQ net_RTS
@drop:
    JMP net_drop
net_RTS:
    RTS



; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    LDA net_tick
    CLC
    ADC #INPUT_DELAY
    SEC
    SBC net_acked
    RTS



; To the menu, in its own bank. It comes back to net_menu_back, or starts a
; session and does not.
net_menu:
    LDA #$00
    STA $2000                   ; no NMI while the banks change
    LDA #<net_menu_back
    STA net_back
    LDA #>net_menu_back
    STA net_back + 1
    LDA #<net_start_session_y
    STA net_go
    LDA #>net_start_session_y
    STA net_go + 1
    LDA #<MENU_ENTRY
    STA net_vector
    LDA #>MENU_ENTRY
    STA net_vector + 1
    LDA #$02
    JMP net_far
net_menu_back:
    LDA ram_for_2000
    STA $2000
    RTS

.assert PER_FRAME = NESP_PEER_PER_FRAME, error

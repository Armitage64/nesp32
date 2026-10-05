; Netplay: a two-player game over two consoles, each with an M5Stack Stick
; on controller port 2 (docs/PROTOCOL.md). Only in the NETPLAY build.
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
;             handler does all its work, and afterwards exchanges a frame
;             with the Stick: buttons out, the other console's in.
;   a stall   the main loop was waiting but the other console's buttons
;             are not here. Nothing of the game runs. The handler only
;             makes the exchange, and the picture stands still.
;   a lag     the main loop was still at work. Nothing runs at all.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the Stick took.
;
; All of the link's traffic is in the NMI, where nothing can interrupt the
; cycle-timed serial routines (link.inc, generated). The Stick drives D0
; (bit 0 of $4017, inverted by the port's buffer) and reads OUT0 (bit 0 of
; $4016 writes), which rests at mark; sub_B793_read_joy_regs reads the
; controller without leaving it low.

.include "net/ram.inc"



; Wait for the NMI. In place of the game's own two loops, so that the NMI
; can tell a main loop that waits from one still at work.
net_wait_nmi:
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
    BEQ @skip                   ; a lag
    ; No room to read buttons for another tick until the Stick has taken
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
    BEQ @menu
    LDA #$00
    STA net_waiting
    STA net_silent
    JMP net_exchange_game
@menu:
    LDA net_pending
    BEQ @RTS
    JSR net_exchange
    LDA #$00
    STA net_pending
    LDA #$01
    BCC @result
    LDA #$FF
@result:
    STA net_result
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



; A session's exchange. Out: up to PER_FRAME ticks of this console's
; buttons, from the first the Stick has not said it holds, and the tick of
; the other console's that is wanted next. In: which of this console's the
; Stick now holds, and up to PER_FRAME ticks of the other's.
;
;   request   REQUEST_GAME, first tick, count, buttons, buttons, tick wanted
;   reply     REPLY_GAME, next tick to send, first tick, count | peer,
;             buttons, buttons
net_exchange_game:
    LDA #REQUEST_GAME
    STA net_request
    LDA net_acked
    STA net_request + 1
    AND #RING - 1
    TAX
    LDA net_local,X
    STA net_request + 3
    INX
    TXA
    AND #RING - 1
    TAX
    LDA net_local,X
    STA net_request + 4
    JSR net_unsent
    CMP #PER_FRAME + 1
    BCC @count
    LDA #PER_FRAME
@count:
    STA net_request + 2
    LDA net_have
    STA net_request + 5
    JSR net_exchange
    BCS @RTS
    LDA net_reply
    CMP #REPLY_GAME
    BNE @RTS
    ; The Stick cannot hold more ticks than were ever read.
    LDA net_reply + 1
    SEC
    SBC net_acked
    STA net_temp
    JSR net_unsent
    CMP net_temp
    BCC @buttons
    LDA net_reply + 1
    STA net_acked
@buttons:
    LDA net_reply + 2
    CMP net_have
    BNE @peer
    LDA net_reply + 3
    AND #$0F
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
    LDA net_reply + 4,Y
    STA net_remote,X
    INC net_have
    INY
    CPY net_temp
    BNE @take
@peer:
    LDA net_reply + 3
    AND #$F0
    CMP #PEER_LOST
    BNE @RTS
    JMP net_drop
@RTS:
    RTS



; A = how many ticks of this console's buttons the Stick does not hold.
net_unsent:
    LDA net_tick
    CLC
    ADC #INPUT_DELAY
    SEC
    SBC net_acked
    RTS

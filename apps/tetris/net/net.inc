; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network
; (docs/PROTOCOL.md). Only in the NETPLAY build.
;
; Both consoles run the whole game, the two-player one of
; net/twoplayer.inc with both playfields on each screen. What crosses the
; link is the buttons: one byte for each tick, where a tick is one NMI
; that the game takes. A console takes a tick only when it holds both
; players' buttons for it, so the two games see the same buttons at the
; same tick and stay the same. Its own buttons are used net_delay ticks
; after they were read, which is the time they have to reach the other
; console.
;
; An NMI in a session is one of three things:
;
;   a tick    the main loop was waiting and the buttons are here. The
;             handler does all its work.
;   a stall   the main loop was waiting but the other console's buttons
;             are not here. The handler has done its writes to the PPU,
;             and the rest of its work but the controllers, and stops where
;             the game reads them. The NMIs that follow write nothing to
;             the PPU, whose picture stands, and try again from there; the
;             one that has the buttons goes on.
;   a lag     the main loop was still at work. Nothing of the game runs.
;
; So the game's state depends on how many ticks there have been and on
; nothing else: not on when the frames fell, nor on how long the nesp32
; took. That matters more here than in most games: the NMI draws the
; playfields a few rows a frame, the line-clearing animation is stepped
; from it, and the pieces wait for the rows to be drawn.
;
; The music is the exception, and keeps the frames' time, not the ticks'.
; The game runs its sound engine from the main loop, once for each pass,
; which in a session is once a tick: every stall and every lag would hold
; the music back by a frame. So in a session the engine is run from the
; NMI instead, in every one of the three. It keeps its memory to itself
; (00E0-00EF and 0680-06FF), and the game only leaves it orders there.
;
; The game reads its controllers last in its NMI, after its writes to the
; PPU. That is where a session makes its exchange with the nesp32,
; buttons out and the other console's in, before the main loop's work, so
; that a press leaves as soon as it is read. The exchange and all that
; goes with it are in the menu's bank (net/session.inc), with the link's
; library; this bank has no room for them, and only the way there. The
; banks are changed only in an NMI that found the main loop waiting, so
; never in the middle of the game's own writes to the mapper.

.include "net/ram.inc"

.assert NET_GAME_BUTTONS = newlyPressedButtons_player1, error
.assert NET_GAME_BUTTONS + 1 = newlyPressedButtons_player2, error
.assert NET_GAME_NMI_FLAG = verticalBlankingInterval, error
.assert NET_PLAYFIELD_1 = playfield, error
.assert NET_PLAYFIELD_2 = playfieldForSecondPlayer, error



; From the reset code: no session, and OUT0 at mark.
net_reset:
    LDA #$00
    LDX #NET_VARS - 1
@loop:
    STA net_local,X
    DEX
    BPL @loop
    LDA #OUT0_MARK
    STA JOY1
    RTS



; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks; the menu comes in at net_start_session_y with the player in
; Y. Both consoles begin from the state of one just switched on, at the
; first tick. Does not return: the game starts again, at the menus of a
; two-player game.
net_start_session:
    TAY
net_start_session_y:
    SEI
    LDA #$00
    STA PPUCTRL
    STA PPUMASK
    STX net_temp
    LDX #$FF
    TXS
    JSR net_reset               ; nothing left of before: net_waiting least of all
    STY net_role
    LDA net_temp
    STA net_delay
    STA net_want
    ; The ticks before 0 have no buttons, and are as many on both consoles
    ; whatever the delay of each: a console begins to read when it comes
    ; to the tick that is its delay before 0.
    LDA #<-NET_DELAY_MAX
    STA net_tick
    LDA #$FF
    STA net_margin
    LDA #<net_input_back
    STA net_back
    LDA #>net_input_back
    STA net_back + 1
    LDA #$01
    STA net_mode
    ; Both consoles with the high scores of one never played: the level
    ; menu draws them, and leaves a digit of them in the zero page.
    LDA #$00
    STA initMagic
    JMP initRam



; Wait for the NMI. In place of the game's own two loops, so that the NMI
; can tell a main loop that waits from one still at work.
net_wait_nmi:
    LDA net_mode
    BNE @session
    JSR updateAudio_jmp         ; the sound engine, as the game's own loops did
@session:
    LDA #$00
    STA verticalBlankingInterval
    LDA #$01
    STA net_waiting
@loop:
    LDA verticalBlankingInterval
    BEQ @loop
    RTS



; First thing in the NMI. Carry set if the handler is to do nothing more.
; After an NMI that stalled it does not come back: the PPU has had this
; tick's writes, and the handler goes on from where it reads the
; controllers.
net_nmi_head:
    LDA net_mode
    BEQ @run
    LDA net_waiting
    BEQ @lag
    LDA net_stalled
    BEQ @run
    PLA
    PLA
    JMP net_nmi_input
@lag:
    JSR updateAudio_jmp         ; the music goes on
    SEC
    RTS
@run:
    CLC
    RTS



; The controllers, in a session: to the menu's bank for the frame's
; exchange (net/session.inc), which gives the game both players' buttons
; for this tick if they are here, where the game's own read leaves them.
; Then as the game's own: newly pressed and held.
;
; If they are not here the NMI ends now: the game's handler called this.
net_read_input:
    JSR updateAudio_jmp         ; the sound engine: once a frame, tick or not
    LDA #<SESSION_ENTRY
    STA net_vector
    LDA #>SESSION_ENTRY
    STA net_vector + 1
    LDA #$02
    JMP net_far
net_input_back:
    LDA net_stalled
    BNE net_stall
    JMP diffOldAndNewButtons
net_stall:
    PLA
    PLA
    JMP net_nmi_end



; To the menu, in its own bank. It comes back to net_menu_back, or starts a
; session and does not.
net_menu:
    LDA #$00
    STA PPUCTRL                 ; no NMI while the banks change
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
    LDA currentPpuCtrl          ; the NMI on again
    STA PPUCTRL
    RTS

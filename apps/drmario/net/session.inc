; Netplay: starting a session, and ending one. In the padding after the
; reset code (net.inc has the rest).



; From the reset vector: no session, and OUT0 at mark.
net_reset:
    LDA #$00
    LDX #NET_VARS - 1
@loop:
    STA net_local,X
    DEX
    BPL @loop
    LDA #$01
    STA $4016
    RTS



; Start a session, as player 1 (A = 00) or player 2 (A = 01); the menu
; comes in at net_start_session_y with that in Y. Both consoles begin from the state of one switched on for the first time, at
; the first tick. Does not return: the game starts again from its title.
net_start_session:
    TAY
net_start_session_y:
    SEI
    LDA #$00
    STA $2000
    STA $2001
    LDX #$FF
    TXS
    ; What the game's reset keeps: the top score, the options and the
    ; mark that it has run before.
    TAX
@loop:
    STA $0700,X
    INX
    BNE @loop
    STA ram_p1_virus_level
    STA ram_p2_virus_level
    STA ram_p1_speed
    STA ram_p2_speed
    STY net_role
    LDA #$01
    STA net_mode
    ; The first INPUT_DELAY ticks have no buttons, on both consoles: the
    ; buttons read in them are those of ticks 0 on.
    LDA #<-INPUT_DELAY
    STA net_tick
    JMP loc_8000_reset_init

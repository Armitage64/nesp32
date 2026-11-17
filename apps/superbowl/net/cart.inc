; Netplay: the cartridge, and what has to be in the fixed bank.
;
; The netplay ROM is the game's own board, an MMC3 with 8 KB of battery
; RAM, with twice the PRG ROM (net/superbowl_net.cfg). The game's 8 KB
; banks are where they were, and its fixed two are the MMC3's last two;
; the netplay's are between. The game picks its banks one 8 KB window at a
; time, and keeps what it last picked for each in SOFT_8000_BANK and
; SOFT_A000_BANK, from which the end of its NMI puts them back
; (RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS): so the NMI may put the
; netplay's bank in at $A000, as it puts the sound engine's in at $8000,
; and leave it there.
;
; The fixed bank keeps the hooks, in the bytes the game leaves empty at
; $FF80 (FREE_31_FF80) and in place of an unused routine at $D05F (L_D05F):
;
;   net_nmi_check   the NMI's first test: the menu's, a lag, a stall's
;                   NMI after the one that wrote to the PPU, or the game's
;   net_sound_hook  the NMI's call of the sound engine, with the read of the
;                   controllers before it (net_nmi_read)
;   net_read_hook   the NMI's read of the controllers: on into the tasks or not
;   net_title_pick  the title's test for Start or A, which takes NETWORK
;                   GAME to the menu (net/title.inc)
;   net_intro       the intro's first wait, which a reset of the netplay's
;                   own goes past (net_skip)
;
; and the reset's hook is a call in place of writes to PPUADDR, which
; net_reset makes itself.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_PRG_RAM    = $A001
MMC3_SRAM_WRITE = $80           ; on and writable
MMC3_SRAM_READ  = $C0           ; on, and not to be written: the game's rest
MMC3_SRAM_OFF   = $40
RESET_VECTOR    = $FFFC

; The netplay's 8 KB banks, by their place in the file.
NET_BANK        = 30            ; the session and the library, at $A000
MENU_BANK       = 31            ; the menu, at $8000 (net_menu_nmi)
SOUND_BANK      = $1B           ; the sound engine's, at $8000 in the NMI

; RETURN_FROM_NMI_TASK_BUSY's LDY NMI_Y, LDX NMI_X, LDA NMI_A and RTI, past
; its write of the bank select.
NMI_REGISTERS_BACK = 6

HAVE_FREE_31_FF80 = 1

.macro FILL_FREE_31_FF80
; In place of NMI_START's test of TASK_BUSY_FLAG. With no session, that
; test, and the game's NMI. An NMI that comes while a session's NMI is
; still at its own work, before the tasks (net_nmi_busy), the exchange
; having run long, gives the registers back and nothing else: the banks
; are that NMI's, which the game's shadows do not know, and putting them
; back from those, as a lag does, would run the netplay's code from
; another bank. That frame goes without its splits and its music.
net_nmi_check:
    bit net_nmi_busy
    bpl :+
    jmp RETURN_FROM_NMI_TASK_BUSY + NMI_REGISTERS_BACK
:
    bit net_menu
    bmi @netplay
    bit TASK_BUSY_FLAG
    bmi @busy
    bit net_mode
    bmi @netplay
@game:
    jmp NMI_TASK_NOT_BUSY
@busy:
    jmp NMI_TASK_BUSY
@netplay:
    jsr net_bank_in
    jmp net_nmi                 ; the menu's NMI, or a session's (net/net.inc)

; The netplay's bank at $A000.
net_bank_in:
    lda SOFT_MODE_8000
    ora #$07
    sta MMC3_SELECT
    lda #NET_BANK
    sta MMC3_DATA
    rts

; In place of the NMI's CLI and call of the sound engine: the read of the
; controllers first (net_nmi_read), and in a session its exchange, which
; holds the IRQ off, done before the screen's first split comes (some
; 5,000 cycles into the frame, in play); then the same. The netplay's bank
; stays at $A000, as the game's tasks find it after a tick's NMI.
net_sound_hook:
    jsr net_bank_in
    jsr net_nmi_read
    lda #$00
    rol a
    sta net_stall_now
    cli
    jmp SOUND_ENGINE_START

; A lag's music (net_nmi), with the sound engine's bank in at $8000: called
; from here, as the sound engine changes the bank at $A000, and then the
; end of the game's NMI.
net_lag_sound:
    cli
    jsr SOUND_ENGINE_START
    lda NMI_BANK_SELECT
    sta SOFT_BANK_SELECT
    jmp RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS

; In place of the NMI's read of the controllers (READ_JOYPAD_START), after
; the sound: a tick goes on into the game's tasks; a stall leaves the NMI.
net_read_hook:
    lsr net_nmi_busy            ; its own work done: the tasks, or the RTI
    lda net_stall_now
    bne @stall
    jmp NMI_UPDATE_RANDOM_NUMS
@stall:
    jmp RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS

; In place of the intro's first wait for a frame, in the main thread's task
; with the intro's bank at $8000: that wait, or, after a reset of the
; netplay's own (net_skip, net/net.inc), the title at once, as the intro's
; Start goes to it, or the main menu, as the title's Start goes to it but
; for the title's own picture and wait.
net_intro:
    ldx net_skip
    bne @skip
    lda #$01
    jmp DELAY_TASK
@skip:
    pla                         ; the call, which does not return
    pla
    dex
    beq @title
    .assert NET_SKIP_TITLE = 1 && NET_SKIP_MENU = 2, error
    jsr END_DRAW_FADE_OUT_STOP_SOUND_CLEAR_SCREEN
    jmp DRAW_MAIN_MENU_INIT
@title:
    jmp DRAW_START_SCREEN
.endmacro

; In place of L_D05F, which nothing calls: 34 bytes.
.macro NET_FILL_D05F
; In place of the title's test of the presses for Start or A, in its loop
; (DRAW_START_SCREEN): first the stars moved (net_title_move, net/title.inc),
; then the test, A and the flags as the game's leaves them, not 0 for the
; game. With NETWORK GAME chosen, 0, and the console goes to the menu: the
; title's loop waits on, as the menu has the console until it starts it
; again. In a session, the game.
net_title_pick:
    jsr net_title_move
    lda JOY_PRESS_BOTH
    and #(START_BUTTON + A_BUTTON)
    beq @exit
    bit net_mode
    bmi @exit                   ; in a session
    ldx net_title_choice
    beq @exit                   ; LOCAL GAME
    lda #NET_MENU_FIRST
    sta net_menu
    lda #$00
@exit:
    ora #$00                    ; the flags as A is
    rts
.endmacro

; Netplay: what has to be in the fixed bank, which the game fills but for
; 73 bytes at its end. The rest is where four routines of the Famicom Disk
; System's game are, which nothing calls: three reads of the controllers,
; and the sprites or the background turned on or off alone (patches/,
; where they are). bubblebobble.asm includes this at its top
; when NETPLAY is defined. Everything else of the netplay is in bank 6
; (net/net.asm), which the game keeps at $8000 for most of its time but
; not all, so each call to it goes through net_call.

.include "net_ram.inc"

; The end of the fixed bank, 73 bytes.
HAVE_FREE_7_3FA9 = 1
.macro FILL_FREE_7_3FA9

; Call routine X of the netplay's bank, with the bank in at $8000, and the
; game's own bank back after it. A, X and the flags are not kept.
net_call:
    txa
    pha
    lda #NET_BANK
    jsr BANK_SWITCH
    pla
    tax
    jsr NET_ENTRY
    jmp BANK_HOME

; The NMI. While the menu has the console it is the menu's, and nothing of
; the game's runs; else it is the game's, unless the game's is still under
; way (net_in_nmi), when it does nothing. The game turns the NMI off as its
; own begins and on as it ends, but now and then turns it on before its end:
; whether an NMI then comes before the end is a matter of cycles, which two
; consoles do not share.
net_nmi:
    bit net_menu
    bmi @menu
    bit net_in_nmi
    bmi @exit
    pha
    lda #$80
    sta net_in_nmi
    pla
    jmp NMI

@menu:
    pha
    txa
    pha
    tya
    pha
    ldx #NET_MENU
    jsr net_call
    pla
    tay
    pla
    tax
    pla
@exit:
    rti

; At the title's choices, in place of putting the cursor on 1P START. In a
; session it is on 2P START (net_title_cursor_at, net/net.asm); and a session
; that has just begun goes straight on as if Start had been pressed there.
net_title_cursor:
    ldx #NET_CURSOR
    jsr net_call
    lda net_autostart
    beq :+
    pla
    pla
    jmp TITLE_START
:
    rts

.endmacro

; Where the first unused routine was, 11 bytes.
.macro NET_AT_F821

; In the reset, once the game has set itself up: the netplay's reset.
net_reset_hook:
    jsr L7_C14E
    ldx #NET_RESET
    jmp net_call

.endmacro

; Where the second was, 22 bytes.
.macro NET_AT_F83D

; At the title, in place of reading the cursor for Start. With 2P START
; chosen and no session, the NMI is the menu's from the next on, and the
; title sleeps until the menu is left for LOCAL GAME; then it goes on as the
; game's 2P START. Anything else goes on as it was.
net_title_start:
    ldx #NET_TITLE
    jsr net_call
@wait:
    bit net_menu
    bpl @done
    lda #$01
    jsr TASK_SLEEP
    jmp @wait

@done:
    lda TITLE_CURSOR
    rts

.endmacro

; Where the third was, 28 bytes.
.macro NET_AT_F86F

; In the NMI, in place of its read of the controllers: the netplay's frame
; (the game's read, or in a session the exchange and both players' buttons
; for the tick), and the sound engine, in every NMI. In a session's NMI
; that has no buttons for its tick, the NMI ends there: the picture's
; writes have been made, and none of the game's work is done.
net_ctrl_hook:
    ldx #NET_FRAME
    jsr net_call
    jsr net_sound
    bit net_stalled
    bmi @stall
    rts

@stall:
    pla
    pla
    jmp NMI_END

; At the title, in place of the Select's moving the cursor down a line. In
; a session it passes over 1P START and 1P CONTINUE (net_title_select_at,
; net/net.asm).
net_title_select:
    ldx #NET_SELECT
    jmp net_call

.endmacro

; Where the fourth was, 26 bytes: the sprites or the background turned on
; or off alone.
.macro NET_AT_F89B

; The logo, from the main task: in a session that has just begun, its
; set-up after Start alone (the screens cleared, the CHR banks and the
; palette), and then straight to the title's choices, which go on as if
; Start had been pressed on 2P START (net_title_cursor). Neither the logo
; nor the choices are drawn. The logo leaves its scroll at 0, and so does
; net_reset.
net_logo:
    lda net_autostart
    beq @logo
    jsr LOGO_SET_UP
    pla
    pla
    jmp MAIN_CHOICES

@logo:
    jmp LOGO

; The end of the game's NMI, in place of its last call: the random number
; stepped, and the NMI no longer under way.
net_nmi_done:
    jsr RNG_STEP
    lda #$00
    sta net_in_nmi
    rts

.endmacro

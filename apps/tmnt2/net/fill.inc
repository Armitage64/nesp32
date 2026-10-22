; Netplay: what goes into the space the game leaves empty, by the names
; tools/convert.py gives it (FREE_bb_oooo, its bank and its offset). Each
; is a macro, FILL_ and the name, which the converted source expands in
; place of that many bytes of $FF where HAVE_ and the name is defined; one
; that does not fit does not assemble. tmnt2.asm includes this at its top
; when NETPLAY is defined. Bank 29 is all the netplay's, and
; net/tmnt2_net.cfg links net/net.asm there instead.

.include "net_ram.inc"

; The end of the fixed bank, 187 bytes: what the NMI and the reset call,
; which cannot be in bank 29, since the game switches the bank at $A000.
HAVE_FREE_1F_1F35 = 1
.macro FILL_FREE_1F_1F35

; The NMI. While the menu has the console it is the menu's. After one that
; stalled, the next is the netplay's own; any other is the game's. Either way the countdown the game keeps before it lets
; the picture on is noted as the NMI found it (net_frame).
net_nmi:
    pha
    lda net_menu
    beq :+
    jmp net_nmi_menu
:
    lda DISABLE_RENDERING_X_FRAMES
    sta net_dis
    lda net_stalled
    bne net_nmi_stalled
    pla
    jmp NMI_HANDLER

; An NMI after one that stalled for want of the other console's buttons.
; The PPU has had the last tick's writes and the picture stands, so it is
; the game's own NMI for a frame that overran (FRAME_OVERRUN_NMI), with the
; exchange made where the counter is set up. If the buttons came, it goes
; on into the game as the game's own NMI would.
net_nmi_stalled:
    txa
    pha
    tya
    pha
    lda PPU_STATUS
    jsr SET_PPU_ADDR_SCROLL_CTRL
    jsr net_nmi_irq
    jsr SCRIPT_GFX_R0_R1_TO_MAPPER
    jsr WRITE_R2_R5_FROM_RAM
    jsr SOUND_FORWARD
    lda net_stalled
    bne :+
    inc FLAG_FRAME_UNFINISHED
    jmp NET_NMI_GAME
:
    jmp NET_OVERRUN_END

; In the NMI, in place of its setup of the counter: the setup, whose CLI is
; taken out, then the netplay's frame (the controller, and in a session the
; exchange), and then the CLI the setup would have done.
net_nmi_irq:
    jsr IRQ_UPDATING_RTN
    ldx #NET_FRAME
    jsr net_call29

net_cli:
    lda FLAG_IRQ_ENABLE         ; as the setup decides it
    beq :+
    cli
:
    rts

; The same in the NMI for a frame that overran, which makes no exchange.
net_lag_irq:
    jsr IRQ_UPDATING_RTN
    jmp net_cli

; Call routine X of bank 29's, with bank 29 in at $A000. The game always
; has a pair of banks in, an even one and the one after it, and the even
; one begins with $20 and its number, so the pair is put back from that.
; And the bank select as the game last left it, as its own IRQs do.
net_call29:
    lda #$07
    sta MMC3_BANK_CFG
    lda #$20 | 29
    sta MMC3_BANK_DATA
    jsr $A000
    lda #$07
    sta MMC3_BANK_CFG
    lda $8000
    clc
    adc #$01
    sta MMC3_BANK_DATA
    ldx BANK_CFG_RESTORE_INDEX
    lda COPY_BANK_CFG_F5,x
    sta MMC3_BANK_CFG
    rts

; In the NMI, in place of its read of the controllers. With no session it
; is the game's read, with OUT0 put back to mark after it. In a session
; it is both players' buttons for this tick, as the game's read leaves
; them; or, in a stall, the end of the NMI with no game. The NMI has sent
; the buffer of writes for the PPU and emptied it: a stall leaves it so,
; with its end marked where the next tick's game will begin to fill it.
net_ctrl:
    lda net_mode
    beq @local
    lda net_stalled
    beq @tick
    pla
    pla
    ldx PPU_UPDATE_BUF_INDEX
    lda #$00
    sta PPU_UPDATE_BUFFER,x
    sta FLAG_FRAME_UNFINISHED
    jmp RTI_RESTORE_AXY

@tick:
    lda net_pads
    sta TMP_00
    lda net_pads+1
    sta TMP_01
    ldx #$00
    jsr CTRL_X_PROCESS
    inx
    jmp CTRL_X_PROCESS

@local:
    jsr CTRL_READ_SAFE
    lda #OUT0_MARK
    sta JOY1
    rts

; In the reset, once it has cleared the memory: bank 29's net_reset, then
; the sound's reset that was called here, which puts the banks in.
net_reset_hook:
    ldx #NET_RESET
    jsr net_call29
    jmp SOUND_RESET_INIT_RTN

.endmacro

; The start of bank 30, 64 bytes, which is fixed too: what the menu needs
; of the fixed bank.
HAVE_FREE_1E_0000 = 1
.macro FILL_FREE_1E_0000

; An NMI while the menu has the console (A is saved): the menu's frame,
; and nothing of the game's.
net_nmi_menu:
    txa
    pha
    tya
    pha
    ldx #NET_MENU
    jsr net_call29
    jmp RTI_RESTORE_AXY

; At the title, in place of the sound its Start makes (A has it). With 2
; TURTLES chosen and no session, the next NMI is the menu's, and the rest
; of the title's Start is not done; else the Start goes on as it was.
net_title_start:
    ldx TITLE_PLAYERS_COUNT_CURSOR_0_1
    beq @game
    ldx net_mode
    bne @game                   ; a session's game over, and the title again
    ldx #$01
    stx net_menu
    pla
    pla
    rts

@game:
    jmp SND_BANKED_DISPATCH

.endmacro

; Netplay: what has to be in the fixed bank, in the 2100 bytes of it the
; game leaves unused (FIXED_FREE). It is what the game's code calls in place
; of what net/rom.asm took out, and the way into bank 1, which the game
; never brings in: the game itself switches the bank at $8000.

; The NMI vector's. While the menu has the console the NMI is the menu's;
; any other is the game's.
net_nmi:
    pha
    lda net_menu
    bne @menu
.ifdef NET_HUD
    lda net_mode                ; every NMI of a session, lags too
    beq :+
    inc net_hud_nmis
    bne :+
    inc net_hud_nmis+1
:
.endif
    pla
    jmp GAME_NMI

@menu:
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
    rti

; Call routine X of bank 1's (net_entry, net/net.asm), with bank 1 in at
; $8000, and bank 2 in after it, as the game has it but in its NMI. The
; link's serial routines count cycles by six bytes of zero page, which are
; the game's: they are kept here while bank 1 has them, and put back.
net_call:
.repeat LENT_ZP, i
    lda LENT + i
    sta net_lent + i
.endrepeat
    lda #BANK_NET
    sta VRC6_PRG16
    jsr net_entry
    lda #BANK_GAME
    sta VRC6_PRG16
.repeat LENT_ZP, i
    lda net_lent + i
    sta LENT + i
.endrepeat
    rts

; In the NMI, in place of bank 0 brought in for the sound engine and the
; controllers' read (HOOK_NMI_PADS). The NMI has sent the sprites and the
; buffer of writes to the PPU, and the split's IRQ is set, some 5900 cycles
; after the NMI began.
;
; With no session it is the sound and the game's read, with OUT0 put back
; to mark after it.
;
; In a session, bank 1's net_frame makes the exchange first, with the
; IRQs held off: it is over by some 4700 cycles at the latest
; (README.md), before the split. Then in a tick the sound engine runs, and
; the game takes both players' buttons for the tick as if it had read
; them. In a stall the NMI ends here, with no sound and no game: the
; scroll as the game's NMI sets it for a frame with no split, and the
; game's own end of an NMI.
net_nmi_pads:
    lda net_mode
    beq net_nmi_alone
    ldx #NET_FRAME
    jsr net_call
    lda net_stalled
    bne net_nmi_stall
    lda #BANK_SOUND
    sta VRC6_PRG16
net_tick_sound:                 ; for the tests
    jsr GAME_SOUND
    lda net_pads
    sta PAD_RAW
    lda net_pads+1
    sta PAD_RAW+1
    jmp GAME_PADS_USE

net_nmi_alone:
    lda #BANK_SOUND
    sta VRC6_PRG16
    jsr GAME_SOUND
    jsr GAME_PADS
    lda #OUT0_MARK
    sta JOY1
    rts

net_nmi_stall:
    pla
    pla
    lda SPLIT_WANTED
    bne :+
    jsr GAME_SCROLL
:
    jmp GAME_NMI_END

; In the NMI, in place of its call to draw the buffer of writes the game
; picked (DRAW_NEXT), after which it empties it and picks the game's own
; for the next NMI. A tick's game can fill two: the one picked, and the
; game's own, which the NMI after draws. So an NMI after one that stalled
; does no drawing at all: the stall's NMI drew what the tick before had
; picked, and the game's own waits for the NMI after the next tick, as it
; would have with no stall between. Else a stall's NMIs would draw it a
; tick early, and empty it, and the next tick's game would add to it on
; one console and begin it again on the other.
;
; Skipped, the drawing leaves the PPU as the game's leaves it: its scroll
; and its address at 0, and its mask as the game keeps it; and the game's
; scratch as the last drawing left it, where it had come to in the
; buffer, which is what this one would have left on a console that did
; not stall. Then on to the sound and the controllers, with A = 0 as
; there.
net_nmi_draw:
    lda net_mode
    beq @draw
    lda net_stalled
    bne @skip

@draw:
    jsr GAME_DRAW
.repeat DRAW_SCRATCH, i
    lda i
    sta net_drawn + i
.endrepeat
    lda #$00
    rts

@skip:
    pla
    pla
    lda PPU_MASK_RAM_COPY
    sta PPU_MASK
    ldx #DRAW_SCRATCH - 1
:
    lda net_drawn,x
    sta $00,x
    dex
    bpl :-
    lda #$00
    sta PPU_SCROLL
    sta PPU_SCROLL
    sta PPU_ADDR
    sta PPU_ADDR
    jmp HOOK_NMI_DRAWN

; At the end of the reset, in place of its call to hide the sprites, which
; follows: bank 1's net_reset, which turns the link's line to mark and
; starts a session if one was asked for.
net_reset_hook:
    ldx #NET_RESET
    jsr net_call
    jmp HOOK_RESET_CALL

; At the title, in place of its look at what player 1 pressed (A, as the
; title would have it, and X and Y kept).
;
; In a session the title is for two, and the first time it is shown Start
; is taken as pressed, and goes on being until the game has begun: the
; players chose a game for two in the menu. A game over brings the title
; back, where player 1's Start begins a game again.
;
; With none, Start with 2 PLAYERS GAME chosen is the menu's, and the title
; goes on this frame as if nothing were pressed; the next NMI is the
; menu's. LOCAL GAME in the menu comes back here as a Start.
net_title_pad:
    lda net_mode
    beq @alone
    lda #$01
    sta TWO_PLAYERS
    lda net_go
    beq @pressed

@start:
    lda #BUTTON_START
    rts

@alone:
    lda net_local_go
    beq @menu
    lda #$00
    sta net_local_go
    beq @start

@menu:
    lda TWO_PLAYERS
    beq @pressed
    lda PAD_PRESSED
    and #<~BUTTON_A
    cmp #BUTTON_START
    bne @pressed
    lda #$01
    sta net_menu
    lda #$00
    rts

@pressed:
    lda PAD_PRESSED
    rts

; Netplay: the cartridge, and what has to be in the fixed bank. bank7.asm
; includes it when NETPLAY is defined, in the 552 bytes the game leaves
; empty at the end of its fixed bank ($FDD2).
;
; The netplay ROM is on an MMC3 with 8 KB of PRG RAM at $6000, where the
; game's own board, a UxROM, has none. The game's 16 KB banks are the
; MMC3's 8 KB banks two by two, R6 at $8000 and R7 at $A000, and its fixed
; bank is the MMC3's last two, at $C000 and $E000 (net/jackal_net.cfg).
; Every switch the game makes is one of two: subChangeBank's, with the
; bank in Y, and subLoadNewPatternTable's own, with it in X. Both come
; here. The 8 KB of CHR RAM are the game's as they were, the MMC3's CHR
; banks laid out in order over them. It is Contra's (apps/contra/net/cart.inc),
; which is on the same board.
;
; The netplay's code runs from the PRG RAM, copied there from bank 8 at
; the reset: the session, and nesp32's library with its serial routines and
; its CRC table. That reads the same whichever bank the game has in. The
; menu is in bank 9, and has the NMI to itself while it is up.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_MIRRORING  = $A000         ; 0 vertical
MMC3_PRG_RAM    = $A001         ; $80 on and writable
MMC3_IRQ_OFF    = $E000

NET_IMAGE_BANK  = 8             ; the netplay's code, as the PRG RAM has it
NET_MENU_BANK   = 9             ; the menu
NET_IMAGE_LOAD  = $8000         ; where the image is in its bank

.pushseg
.segment "CART"

; The game's bank Y in: R6 and R7, each a register picked by a write to
; $8000 and then its bank written to $8001. A is Y as the game's own
; switch leaves it, which reads the bank's number from its first bytes, and
; so are the flags. X is kept.
net_set_bank:
    lda #$06
    sta MMC3_SELECT
    lda net_bank_low,y
    sta MMC3_DATA
    lda #$07
    sta MMC3_SELECT
    lda net_bank_high,y
    sta MMC3_DATA
    tya
    rts
net_set_bank_end:

; The same with the bank in X, for subLoadNewPatternTable. Y is kept.
net_set_bank_x:
    lda #$06
    sta MMC3_SELECT
    lda net_bank_low,x
    sta MMC3_DATA
    lda #$07
    sta MMC3_SELECT
    lda net_bank_high,x
    sta MMC3_DATA
    txa
    rts
net_set_bank_x_end:
.assert net_set_bank_x_end - net_set_bank < $100, error, "net_lag_leave measures from net_set_bank in a byte"

; Every bank's 8 KB halves, by the game's number for it. Bank 7, the fixed
; one, is the last in the file, as the MMC3 has it, and banks 8 and 9 come
; before it, after bank 6 (net/jackal_net.cfg).
net_bank_low:
    .byte 0, 2, 4, 6, 8, 10, 12, 30, 14, 16
net_bank_high:
    .byte 1, 3, 5, 7, 9, 11, 13, 31, 15, 17

; A lag frame's NMI (subProcessMinimalLogicDuringLagFrame) runs the sound
; engine in bank 0 and puts the game's bank back. It may have broken into
; a switch, between a register picked and its bank written, and the switch
; would go on to write the rest to its own pick. So this looks at where the
; NMI is to return to, and if that is in a switch it returns to its start
; instead: the switch is made again from the first write, with the Y or X
; it had, which the NMI puts back. The stack holds the NMI's Y, X, A and
; flags (PUSHALL), then the CPU's flags and the address.
NET_LAG_RETURN  = $0106         ; past the stack pointer, the address's low byte

net_lag_leave:
    tsx
    lda NET_LAG_RETURN,x
    sec
    sbc #<net_set_bank
    tay                         ; how far past net_set_bank, if less than 256
    lda NET_LAG_RETURN+1,x
    sbc #>net_set_bank
    bne @done
    cpy #net_set_bank_end - net_set_bank
    bcs @x
    lda #<net_set_bank
    ldy #>net_set_bank
    bne @back

@x:
    cpy #net_set_bank_x - net_set_bank
    bcc @done
    cpy #net_set_bank_x_end - net_set_bank
    bcs @done
    lda #<net_set_bank_x
    ldy #>net_set_bank_x

@back:
    sta NET_LAG_RETURN,x
    tya
    sta NET_LAG_RETURN+1,x

@done:
    jmp END_NMI

; The NMI vector. While a frame of the game is under way the game's own
; handler has the NMI, as a lag frame. Otherwise it is the menu's while the
; menu is up, or the stall's while the last NMI had no buttons for its tick
; (net_nmi_stalled, net/net.inc); and the game's.
net_nmi:
    pha
    lda GameFrameLogicInProgress
    bne @game
    bit net_menu
    bmi @menu
    bit net_stalled
    bmi @stalled

@game:
    pla
    jmp NMI_VECTOR

@stalled:
    pla
    PUSHALL
    jmp net_nmi_stalled

@menu:
    pla
    PUSHALL
    ldy #NET_MENU_BANK
    jsr net_set_bank
    jsr menu_frame
    ldy CurrentBank
    jsr net_set_bank
    jmp END_NMI

; R0 to R5: the CHR RAM in order, two banks of 2 KB and four of 1 KB.
net_chr_banks:
    .byte 0, 2, 4, 5, 6, 7

; The reset vector. Until the first write to $8000 sets the MMC3's mode,
; $C000 may be any bank, and the game's reset is there: only $E000 on is
; known to be the last bank. The mirroring is vertical, as the game's
; board has it, the PRG RAM is on, the scanline counter's IRQ is off, and
; bank 0 is in, as the UxROM begins.
net_cart_start:
    sei
    cld
    ldx #$00
    stx PPUCTRL                 ; no NMI until the game's reset has set up
    stx MMC3_SELECT             ; PRG mode 0: the last two banks at $C000 and $E000
    stx MMC3_MIRRORING
    stx MMC3_IRQ_OFF
    lda #$80
    sta MMC3_PRG_RAM
    ldx #$05

@chr:
    stx MMC3_SELECT
    lda net_chr_banks,x
    sta MMC3_DATA
    dex
    bpl @chr
    ldy #$00
    jsr net_set_bank
    jmp RESET_VECTOR

; From the reset, once it has cleared the memory, in place of its call of
; subInitAPUAndPPU, which turns the NMI on: the netplay's code into the PRG
; RAM, then net_reset there, then that call. The copy takes a frame and a
; half, with the NMI off: as many pages whatever is in them, so that every
; build takes as long to boot, and the tests can hold one to another tick
; by tick from power-on. The bank the game has in is put back.
net_cart_reset:
    ldy #NET_IMAGE_BANK
    jsr net_set_bank
    ldx #$00

@copy:
.repeat NET_IMAGE_PAGES, page
    lda NET_IMAGE_LOAD + page * $100,x
    sta NET_IMAGE_RUN + page * $100,x
.endrep
    inx
    beq @copied
    jmp @copy

@copied:
    ldy CurrentBank
    jsr net_set_bank
    jsr net_reset
    jmp subInitAPUAndPPU
.popseg

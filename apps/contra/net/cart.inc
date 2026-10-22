; Netplay: the cartridge. bank7.asm includes it when NETPLAY is defined,
; in the space the game leaves at the end of its fixed bank.
;
; The netplay ROM is on an MMC3 with 8 KB of PRG RAM at $6000, where the
; game's own board, a UxROM, has none. The game's 16 KB banks are the
; MMC3's 8 KB banks two by two, R6 at $8000 and R7 at $A000, and its fixed
; bank is the MMC3's last two, at $C000 and $E000 (net/contra_net.cfg).
; Every switch the game makes is set_rom_bank_to_y's, which writes both.
; The 8 KB of CHR RAM are the game's as they were, the MMC3's CHR banks
; laid out in order over them.
;
; Netplay's code runs from the PRG RAM, copied there from bank 8 at the
; reset: the session, and nesp32's library with its serial routines and
; its CRC table. That is what makes room in the fixed bank, and it reads
; the same whichever bank the game has in.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_MIRRORING  = $A000         ; 0 vertical
MMC3_PRG_RAM    = $A001         ; $80 on and writable
MMC3_IRQ_OFF    = $E000

NET_IMAGE       = $8100         ; where it is in bank 8
NET_IMAGE_RUN   = $6000         ; and where it runs
; As many pages whatever is in them, so that every build takes as long to
; boot, and the tests can hold one to another tick by tick from power-on.
NET_IMAGE_PAGES = $18
.assert net_image_end <= NET_IMAGE_RUN + NET_IMAGE_PAGES * $100, error, "net_cart_reset copies too little"

.pushseg
.segment "BANK_8"
.byte $08 ; The PRG ROM bank number (8)

.segment "CART"

; Every bank's 8 KB halves, by the game's number for it. Bank 7, the fixed
; one, is the last in the file, as the MMC3 has it, and bank 8 has its
; place (net/contra_net.cfg).
net_bank_low:
    .byte 0, 2, 4, 6, 8, 10, 12, 30, 14
net_bank_high:
    .byte 1, 3, 5, 7, 9, 11, 13, 31, 15

; set_rom_bank_to_y jumps here. The game's bank Y is R6 and R7, each a
; register picked by a write to $8000 and then its bank written to $8001.
; A, the flags and X as the original leaves them.
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
.assert >net_set_bank = >(net_set_bank_end - 1), error, "net_lag_leave looks for it on one page"

; A lag frame's NMI (handle_sounds_set_ppu_scroll_rti) runs the sound
; engine in bank 1 and puts the bank back. It may have broken into a
; switch, between a register picked and its bank written, and the switch
; would go on to write the rest to its own pick. So once the bank is back
; this looks at where the NMI is to return to, and if that is in
; net_set_bank it returns to its start instead: the switch is made again
; from the first write, with the Y it had, which the NMI puts back. The
; stack holds this call's return, then the NMI's Y, X, A and flags
; (nmi_start), then the CPU's flags and the address.
NET_LAG_RETURN  = $0108         ; past the stack pointer, the address's low byte

net_lag_leave:
    jsr set_rom_bank_to_y
    tsx
    lda NET_LAG_RETURN+1,x
    cmp #>net_set_bank
    bne @done
    lda NET_LAG_RETURN,x
    cmp #<net_set_bank
    bcc @done
    cmp #<net_set_bank_end
    bcs @done
    lda #<net_set_bank
    sta NET_LAG_RETURN,x

@done:
    rts

; R0 to R5: the CHR RAM in order, two banks of 2 KB and four of 1 KB.
net_chr_banks:
    .byte 0, 2, 4, 5, 6, 7

; The reset vector. Until the first write to $8000 sets the MMC3's mode,
; $C000 may be any bank, and the game's reset is there: only $E000 on is
; known to be the last bank. The mirroring is vertical, as the game's
; board has it, the PRG RAM is on, the scanline counter's IRQ is off, and
; bank 0 is in, as the simulation's UxROM begins.
net_cart_start:
    sei
    cld
    ldx #$00
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
    jsr set_rom_bank_to_y
    jmp reset_vector

; From the reset code, once it has cleared the memory: netplay's code into
; the PRG RAM, and then net_reset there. It takes two frames. The
; bank in place is put back, and nothing of the game's memory is used: a
; vblank in the middle of it finds the memory as it would be without it.
net_cart_reset:
    lda BANK_NUMBER
    pha
    ldy #$08
    jsr set_rom_bank_to_y
    ldx #$00

@copy:
.repeat NET_IMAGE_PAGES, page
    lda NET_IMAGE + page * $100,x
    sta NET_IMAGE_RUN + page * $100,x
.endrep
    inx
    beq @copied
    jmp @copy

@copied:
    pla
    tay
    jsr set_rom_bank_to_y
    jmp net_reset
.popseg

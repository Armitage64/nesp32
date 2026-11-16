; Netplay: the cartridge, and what has to be in the fixed bank: the reset,
; in 141 bytes the game leaves empty at $F9B3 (FREE_7_39B3), which
; tools/convert.py has a place for this macro in.
;
; The netplay ROM is on the game's own board, an MMC3, with 8 KB of PRG RAM
; at $6000 and twice the PRG ROM (net/rcr_net.cfg). The game's 16 KB banks
; are the MMC3's 8 KB banks two by two, and its own switch ($FED1) picks
; them so: nothing of it changes. Its fixed bank is the MMC3's last two.
;
; The netplay's code runs from the PRG RAM, copied there from bank 8 at the
; reset: the session, and nesp32's library with its serial routines and
; its CRC table. That reads the same whichever bank the game has in, in the
; NMI and out of it. The menu is in bank 9, and has the NMI to itself while
; it is up (net_nmi).

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_MIRRORING  = $A000         ; 0 vertical
MMC3_PRG_RAM    = $A001         ; $80 on and writable
MMC3_IRQ_OFF    = $E000

; The MMC3's 8 KB banks of the netplay's own, by their place in the file
; (net/rcr_net.cfg): bank 8 is the file's eighth 16 KB, 8 KB banks 14 and
; 15, and bank 9 the ninth.
NET_IMAGE_R6    = 14
NET_MENU_R6     = 16
NET_IMAGE_LOAD  = $8000         ; where the image is in its bank

HAVE_FREE_7_39B3 = 1

; The reset vector, at $E000 on, which the MMC3 always has the last bank
; at. With the NMI and the picture off: the MMC3 in PRG mode 0 (the last two
; banks at $C000 and $E000), vertical mirroring as the game sets, its IRQ
; off and the PRG RAM on; the netplay's code into the PRG RAM, as many
; pages whatever is in them; all of the console's RAM cleared, which the
; game's reset does not do but for $0200-$07FF, and so is the same on two
; consoles that begin a session; then net_reset, and the game's reset.
.macro FILL_FREE_7_39B3
net_cart_start:
    sei
    cld
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx MMC3_SELECT
    stx MMC3_MIRRORING
    stx MMC3_IRQ_OFF
    lda #$80
    sta MMC3_PRG_RAM
    lda #$06
    sta MMC3_SELECT
    lda #NET_IMAGE_R6
    sta MMC3_DATA
    lda #$07
    sta MMC3_SELECT
    lda #NET_IMAGE_R6 + 1
    sta MMC3_DATA
    ; The image, a page at a time, through the first four bytes of zero
    ; page, which are cleared after.
    stx $00
    stx $02
    lda #>NET_IMAGE_LOAD
    sta $01
    lda #>NET_IMAGE_RUN
    sta $03
    ldy #$00
    ldx #NET_IMAGE_PAGES
@copy:
    lda ($00),y
    sta ($02),y
    iny
    bne @copy
    inc $01
    inc $03
    dex
    bne @copy
    txa
@clear:
    sta $0000,x
    sta $0100,x
    sta $0200,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @clear
    jsr net_reset
    jmp RESET
.endmacro

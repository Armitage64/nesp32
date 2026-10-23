; The faster ROM's own bank, and what its reset copies to the PRG RAM.
;
; The original is an MMC3 with 128 KB of PRG ROM and no PRG RAM. The
; faster ROM is the same with 256 KB (fast/fast.cfg) and 8 KB of PRG RAM
; at $6000, from which its passes run. Its reset vector is fast_reset, in
; the fixed bank, which puts this bank at $8000 and comes to fast_boot.

.include "copy_bank_ram.inc"
.include "copy_bank_val.inc"
.include "fast.inc"

.segment "HEADER"
; NES 2.0: mapper 4, 256 KB of PRG ROM, 128 KB of CHR ROM, 8 KB of PRG RAM
; (64 << 7) with no battery, NTSC.
    .byte "NES", $1A
    .byte 256 / 16, 128 / 8
    .byte $40, $08
    .byte $00, $00, $07, $00, $00, $00, $00, $00

.segment "BANK_0E"
; The reset, from fast_reset: the PRG RAM on, the image copied to it,
; and then the game's own reset. As many pages are copied whatever the
; image's length, so that the boot takes as long whichever passes are in.
.export fast_boot
fast_boot:
    sei
    cld
    lda #MMC3_PRG_RAM_ON
    sta MMC3_PRG_RAM
    lda #<__IMAGE_LOAD__
    sta $00
    lda #>__IMAGE_LOAD__
    sta $01
    lda #<__IMAGE_RUN__
    sta $02
    lda #>__IMAGE_RUN__
    sta $03
    ldx #IMAGE_PAGES
    ldy #0
@copy:
    lda ($00),y
    sta ($02),y
    iny
    bne @copy
    inc $01
    inc $03
    dex
    bne @copy
    jmp vec_FD2B_RESET

.segment "IMAGE"
image_start:
.export fast_bankswitch, fast_switch_pair
.include "bankswitch.inc"
.export fast_probe
.include "probe.inc"
.export fast_sprites
.include "sprites.inc"
image_end:
.assert image_end - image_start <= IMAGE_PAGES * $100, error, "fast_boot copies too little"

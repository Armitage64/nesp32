; Netplay: the cartridge. rescuerangers.asm includes it when NETPLAY is
; defined, in the fixed bank, where SET_PRG's MMC1 writes were.
;
; The netplay ROM is on an MMC3 with 256 KB of PRG ROM and 8 KB of PRG RAM
; at $6000, where the game's own board is an MMC1 with 128 KB and none
; (net/rescuerangers_net.cfg). The game's 16 KB banks are the MMC3's 8 KB
; banks two by two, R6 at $8000 and R7 at $A000, and its fixed bank is the
; MMC3's last two, at $C000 and $E000, which the MMC3 keeps there in PRG
; mode 0. Banks 8 to 15 are new, between them in the file. The game's 4 KB
; CHR banks are the MMC3's: CHR bank 0 ($0000) is R0 and R1, of 2 KB, and
; CHR bank 1 ($1000) is R2 to R5, of 1 KB.
;
; The fixed bank has next to no room, so what the MMC3 needs runs from the
; PRG RAM, which the reset copies from bank 8 before anything else
; (net_cart_start). SET_PRG, SET_CHR0, SET_CHR1 and the NMI's switches
; jump there.
;
; A write to an MMC3 register is two: $8000 picks the register, then $8001
; gives it its bank. An NMI between the two would leave the pick its own,
; and the rest of the switch would go to the NMI's register. So every
; pick is kept in net_select too, and the NMI keeps the one it found and
; puts it back, in net_select and in $8000, before it returns.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_MIRRORING  = $A000         ; 0 vertical
MMC3_PRG_RAM    = $A001         ; $80 on and writable
MMC3_IRQ_OFF    = $E000

NET_BANK        = 14            ; bank 8, the MMC3's 8 KB bank: where the image is
NET_IMAGE       = $8000         ; where it is in bank 8
NET_IMAGE_RUN   = $6000         ; and where it runs
.import __NETCODE_SIZE__
NET_IMAGE_PAGES = >(__NETCODE_SIZE__ + $FF)
.assert NET_IMAGE_RUN + __NETCODE_SIZE__ <= NET_RAM, lderror, "the image runs into net/net_ram.inc's memory"

; The reset vector, and the game's own reset (L7_FFE0) once it is past its
; first instruction. Until the first write to $8000 sets the MMC3's mode,
; $C000 may be any bank, but this is in the last 8 KB, which is always at
; $E000. The PRG RAM on, the mirroring vertical as the game's MMC1 has
; it, the scanline counter's IRQ off; then the image copied, from bank 8
; at $8000. The game's reset clears the console's RAM after, so its zero
; page is used for the copy.
net_cart_start:
    sei
    cld
    ldx #$00
    stx MMC3_SELECT             ; PRG mode 0: the last two banks at $C000 and $E000
    stx MMC3_MIRRORING
    stx MMC3_IRQ_OFF
    lda #$80
    sta MMC3_PRG_RAM
    lda #$06
    sta MMC3_SELECT
    lda #NET_BANK
    sta MMC3_DATA
    lda #<NET_IMAGE
    sta $00
    lda #>NET_IMAGE
    sta $01
    lda #<NET_IMAGE_RUN
    sta $02
    lda #>NET_IMAGE_RUN
    sta $03
    ldx #NET_IMAGE_PAGES
    ldy #$00

@copy:
    lda ($00),y
    sta ($02),y
    iny
    bne @copy
    inc $01
    inc $03
    dex
    bne @copy
    stx net_select              ; 0, as $8000 was given
    jmp RESET_MAIN
net_cart_end:

.pushseg
.segment "NETCODE"

; SET_PRG, once it has kept the bank: A, a bank of the game's from 0 to 6,
; at $8000. As the original, BANK_SWITCHING is set while the MMC3 is
; written, so that an NMI leaves the sound engine to this (SOUND_MISSED);
; then it runs it, with bank 3 in, and puts the bank wanted back. X and Y
; are kept, but for the sound engine's turn, as the original. A is 0.
net_set_prg:
    inc BANK_SWITCHING
    jsr net_prg
    lda #$00
    sta BANK_SWITCHING
    lda SOUND_MISSED
    bne @sound
    rts

@sound:
    lda #$03
    jsr net_prg

@queue:
    ldx SOUND_HEAD
    lda SOUND_QUEUE,x
    cmp #$88
    beq @run
    pha
    lda #$88
    sta SOUND_QUEUE,x
    inx
    txa
    and #$07
    sta SOUND_HEAD
    pla
    jsr SOUND_PLAY
    jmp @queue

@run:
    jsr SOUND_RUN
    lda #$00
    sta SOUND_MISSED
    lda PRG_BANK_WANTED
    jmp SET_PRG

; The game's bank A at $8000: R6 its first 8 KB, R7 its second. X and Y
; kept; A is the second's number.
net_prg:
    asl a
    pha
    lda #$06
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    ora #$01
    pha
    lda #$07
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    rts

; The game's 4 KB CHR bank A at $0000: R0 and R1, 2 KB each, numbered in
; 1 KB. X and Y kept.
net_chr0:
    asl a
    asl a
    pha
    lda #$00
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    ora #$02
    pha
    lda #$01
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    rts

; The game's 4 KB CHR bank A at $1000: R2 to R5, 1 KB each. X and Y kept.
net_chr1:
    asl a
    asl a
.repeat 4, register
    pha
    lda #2 + register
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
  .if register < 3
    clc
    adc #$01
  .endif
.endrep
    rts

; The NMI vector. The pick in $8000 that the NMI broke in on, kept for
; net_nmi_leave; then the game's NMI.
net_nmi:
    pha
    lda net_select
    sta net_select_nmi
    pla
    jmp NMI

; The end of the game's NMI jumps here: the pick put back, and the game's
; return.
net_nmi_leave:
    lda net_select_nmi
    sta net_select
    sta MMC3_SELECT
    pla
    tay
    pla
    tax
    pla
    plp
    rti
.popseg

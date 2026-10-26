; The netplay ROM: baserom.nes, the hack as its player has it, with the
; netplay put in. None of the game is here. Each bank of it is copied from
; baserom.nes by its place in the file (rom_upto), up to each of the few
; places the netplay changes, where an instruction of the netplay's is put
; in place of one of the game's of the same length (net/game.inc's HOOK_*).
; Bank 1, all $FF in the hack, is the netplay's (net/net.asm), and the fixed
; bank's unused 2100 bytes have what has to be there (net/glue.inc).
;
; The Makefile checks baserom.nes against its SHA-512 first: an offset here
; is good for that file and no other.

.include "net_ram.inc"
.include "game.inc"

INES_HEADER     = 16
BANK_SIZE       = $4000

; Copy baserom.nes from where this bank has come to, up to `addr`.
.macro rom_upto addr
    .assert * <= addr, error, "past the place to copy to"
    .incbin "baserom.nes", INES_HEADER + rom_bank * BANK_SIZE + (* - rom_org), addr - *
.endmacro

; The rest of the bank, and no longer at a place of its own.
.macro rom_end
    rom_upto rom_org + BANK_SIZE
    .reloc
.endmacro

; Each bank as the hack has it, but for its hooks.
.macro rom_bank_at number, org
    rom_bank .set number
    rom_org .set org
    .org org
.endmacro

; --- the header ----------------------------------------------------------------
; NES 2.0: the hack's cartridge, a VRC6 with 64 KB of PRG ROM and 8 KB of
; CHR ROM, with its 8 KB of PRG RAM said, which the hack's own header
; leaves to be guessed.
.segment "HEADER"
    .byte "NES", $1A
    .byte $04                   ; 4 x 16 KB of PRG ROM
    .byte $01                   ; 1 x 8 KB of CHR ROM
    .byte $80                   ; mapper 24's low nibble, the mirroring by the mapper
    .byte $18                   ; its high nibble, and NES 2.0
    .byte $00, $00              ; no submapper; the ROMs' sizes as above
    .byte $07                   ; PRG RAM: 64 << 7 bytes, not kept
    .byte $00                   ; no CHR RAM
    .byte $00                   ; NTSC
    .byte $00, $00, $00

; --- bank 0: the sound engine and the controllers, as they are ----------------------
.segment "BANK0"
    rom_bank_at 0, $8000
    rom_end

; --- bank 1: the netplay -------------------------------------------------------------
.segment "CODE"
.include "net.asm"

; --- bank 2: the game -------------------------------------------------------------------
.segment "BANK2"
    rom_bank_at 2, $8000
    rom_upto HOOK_TITLE_PAD
    jsr net_title_pad
    rom_end

; --- bank 3: $C000, which the game keeps in, and the fixed bank ----------------------
.segment "BANK3"
    rom_bank_at 3, $C000
    rom_upto FIXED_FREE
.include "glue.inc"
    rom_upto HOOK_NMI_DRAW
    jsr net_nmi_draw
    rom_upto HOOK_NMI_PADS
    jsr net_nmi_pads
    jmp HOOK_NMI_PADS_END
    rom_upto HOOK_RESET
    jsr net_reset_hook
    rom_upto NMI_VECTOR
    .word net_nmi
    rom_end

; --- the CHR ROM -------------------------------------------------------------------------
.segment "CHR"
    .incbin "baserom.nes", INES_HEADER + 4 * BANK_SIZE, $2000

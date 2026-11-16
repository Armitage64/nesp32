; Netplay: everything of it, from the end of bank 7 (patches/bank7.patch),
; where the game leaves its fixed bank empty from $FDD2: the cartridge and
; the NMI's way in, there (net/cart.inc); the session, which the reset
; copies into the PRG RAM (net/net.inc); the menu, in bank 9 (net/menu.inc);
; and the vectors, the NMI's and the reset's now the netplay's.

PPUCTRL_COPY = NormalPPUCTRL    ; what the menu turns the picture on with

; The game's banks are each placed where they are (.org, tools/convert.py);
; what follows is placed by the linker (net/jackal_net.cfg).
.reloc

.include "ram.inc"
.include "cart.inc"
.include "net.inc"

.pushseg
.segment "MENU"
.include "menu.inc"
.popseg

.segment "VECTORS"
    .word net_nmi
    .word net_cart_start
    .word IRQ_BRK_VECTOR

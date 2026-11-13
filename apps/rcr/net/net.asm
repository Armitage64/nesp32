; Netplay: everything of it. rcr.asm includes this at its top when NETPLAY
; is defined (patches/rcr.patch), before the game's banks: the reset's
; place in the fixed bank's empty bytes, as a macro the converted source
; fills them with (net/cart.inc); the session, which the reset copies into
; the PRG RAM (net/net.inc); the distances between objects, in bank 6's
; empty bytes (net/distances.inc); and the menu, in bank 9 (net/menu.inc). The
; patches put the calls in the game, and the vectors.

PPUCTRL_COPY = PPUCTRL_SHADOW   ; what the menu gives the NMI back with

.include "net_ram.inc"
.include "cart.inc"
.include "net.inc"
.include "distances.inc"

.pushseg
.segment "MENU"
.include "menu.inc"
.popseg

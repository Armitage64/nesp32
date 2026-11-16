; Netplay: everything of it. tsb.asm includes this at its top when NETPLAY
; is defined (patches/tsb.patch), after the game's names and before its
; banks: the hooks in the fixed bank, as macros the patches put in its
; empty and unused bytes (net/cart.inc); the sprites' flicker and the
; collision checks, quicker, each in a bank of its own and both in by bank
; 22's empty bytes (net/flicker.inc, net/coll.inc); the session and nesp32's library,
; in the netplay's bank (net/net.inc); and the menu, in its own
; (net/menu.inc).

.include "net_ram.inc"
.include "cart.inc"
.include "coll.inc"
.include "flicker.inc"

.pushseg
.include "net.inc"
.popseg

.pushseg
.segment "MENU"
.include "menu.inc"
.popseg

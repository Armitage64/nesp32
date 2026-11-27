; Netplay's memory, in the PRG RAM above the code the reset copies there
; (net/cart.inc). The console's own 2 KB are all the game's.

NET_RAM         = $7F00

net_select      = NET_RAM + $00 ; the MMC3 register last picked at $8000
net_select_nmi  = NET_RAM + $01 ; the one the NMI broke in on

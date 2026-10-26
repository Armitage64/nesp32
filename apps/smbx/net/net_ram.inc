; Netplay: the memory it uses, and the numbers it is made of. Included by
; net/rom.asm before anything else.

.ifndef NET_RAM_INC
NET_RAM_INC = 1
;
; The game uses all of its own 2 KB, and clears it at the reset. The
; netplay's memory is the cartridge's 8 KB of PRG RAM at $6000, which the
; game turns on at its reset and never uses; the netplay ROM's header asks
; for it. The reset does not clear it, which is what lets a session be asked
; for across one (net_boot).
;
; The link's serial routines count cycles by six bytes of zero page, and the
; game has none to spare. They are the game's own bytes, lent: the fixed
; bank's net_call keeps them while bank 1's code runs, and puts them back
; (net/glue.inc).

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
JOY1            = $4016
JOY2            = $4017
OUT0_MARK       = $01
APU_STATUS      = $4015
APU_STATUS_DMC  = $10           ; a sample has bytes still to fetch
PPU_CTRL        = $2000
PPU_MASK        = $2001
PPU_STATUS      = $2002
PPU_SCROLL      = $2005
PPU_ADDR        = $2006
PPU_DATA        = $2007

; A button press is used net_delay ticks after the frame it was read in.
; It is the time the press has to cross to the other console. Each console
; keeps its own, and changes it as its nesp32 advises (net/net.asm).
NET_DELAY       = 2             ; with no advice to begin with
NET_DELAY_MAX   = 5             ; the most the rings have room for
; A console's report to its nesp32, and the advice back, go with the
; exchange for one tick in 128: the one after this place in its buttons.
TUNE_AT         = $40
RING            = 8             ; ticks of buttons the console keeps, each way
PER_FRAME       = 2             ; ticks of buttons an exchange can carry
; NMIs in a row with no tick before the console gives the session up.
SILENT_FRAMES   = 240
; One tick in 256 carries no buttons. In their place each console sends a
; digest of its game, and a console whose own differs from the other's
; gives the session up: the two are no longer playing the same game.
CHECK_TICK      = $FF
; The digest is taken at the start of this tick, on both consoles alike,
; and kept until each comes to send it: a few ticks later, by its delay.
CHECK_AT        = CHECK_TICK - 8
.assert NET_DELAY_MAX < CHECK_TICK - CHECK_AT, error

.assert RING & (RING - 1) = 0, error, "RING must be a power of two"
.assert NET_DELAY_MAX + PER_FRAME < RING, error

; The link's library (nesp32's nes/lib/nesp.inc).
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = 8             ; the longest request: a hello for one service
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; The game's zero page that the link borrows, six bytes in a row from
; LENT: net_call keeps the game's values meanwhile, and puts them back.
LENT            = $50
LENT_ZP         = 6
nesp_rx_data    = LENT
nesp_tx_data    = LENT + 1
nesp_rx_end     = LENT + 2
nesp_ptr        = LENT + 3      ; and LENT + 4
nesp_tries      = LENT + 5

NET_RAM         = $6000
net_local       = NET_RAM       ; RING: this console's buttons, by tick
net_remote      = NET_RAM + 8   ; RING: the other's
net_mode        = NET_RAM + 16  ; 01 in a session
net_role        = NET_RAM + 17  ; 00 this console is player 1, 01 player 2
net_delay       = NET_RAM + 18  ; ticks from a press being read to its use
net_tick        = NET_RAM + 19  ; the tick the next NMI may take
net_read        = NET_RAM + 20  ; first tick this console has no buttons for
net_acked       = NET_RAM + 21  ; first of this console's ticks the nesp32 lacks
net_have        = NET_RAM + 22  ; first of the other's ticks not here yet
net_stalled     = NET_RAM + 23  ; 01: this NMI has no buttons for its tick
net_silent      = NET_RAM + 24  ; NMIs in a row that were not ticks
net_pad         = NET_RAM + 25  ; the controller as it was last read twice alike
net_menu        = NET_RAM + 26  ; not 00: the NMI is the menu's (01 its first)
net_want        = NET_RAM + 27  ; the delay the nesp32 advises
net_late        = NET_RAM + 28  ; NMIs that waited for the other's buttons, since the last report
net_margin      = NET_RAM + 29  ; the fewest ticks of them held at a tick, since then
net_tune        = NET_RAM + 30  ; not 00: this NMI's exchange carries the report
net_check       = NET_RAM + 31  ; the digest, from when it was taken to when it is sent
net_temp        = NET_RAM + 32
net_pads        = NET_RAM + 33  ; 2: player 1's and player 2's buttons for this tick
net_go          = NET_RAM + 35  ; 01: a session's first title, where Start is taken as pressed
net_local_go    = NET_RAM + 36  ; 01: LOCAL GAME, and the title's next look is a Start
net_lent        = NET_RAM + 37  ; LENT_ZP: the game's bytes of zero page that the link has
nesp_seq        = NET_RAM + 44
nesp_tx_len     = NET_RAM + 45
nesp_count      = NET_RAM + 46
nesp_index      = NET_RAM + 47
nesp_crc_hi     = NET_RAM + 48
nesp_crc_lo     = NET_RAM + 49
nesp_status     = NET_RAM + 50
nesp_attention  = NET_RAM + 51
nesp_rng        = NET_RAM + 52  ; 2
nesp_rx         = NET_RAM + 54
nesp_tx         = nesp_rx + NESP_RX_MASK + 1 + 7
NET_RAM_END     = nesp_tx + NESP_TX_MAX + 7
.assert net_lent + LENT_ZP <= nesp_seq, error
net_drawn       = NET_RAM + $F0 ; 3: the scratch the NMI's last drawing left (net_nmi_draw)
.assert NET_RAM_END <= net_drawn, error

; The menu's memory, from here on (net/menu.inc).
MENU_RAM        = NET_RAM + $100
.assert NET_RAM_END <= MENU_RAM, error

; The order to start a session, which is carried through the reset
; (net_start_session, net_reset): the mark, the role, the delay, a check.
net_boot        = NET_RAM + $1F00
NET_BOOT_MARK   = $4E
NET_BOOT_CHECK  = $B1

; What the fixed bank calls in bank 1, by number in X (net_call,
; net/glue.inc; net_entry, net/net.asm).
NET_FRAME       = 0
NET_RESET       = 1
NET_MENU        = 2

.endif

; Netplay: the memory it uses, and the numbers it is made of. Included by
; net/fill.inc and net/net.asm both.

.ifndef NET_RAM_INC
NET_RAM_INC = 1
;
; The game uses nearly all of its own 2 KB and clears it at the reset, so
; the netplay's memory is the 8 KB of PRG RAM at $6000 that an MMC1
; cartridge can have, and that the netplay ROM's header asks for. The game
; never touches $6000-$7FFF, and keeps the RAM on: bit 4 of the PRG bank it
; writes is always clear. The reset does not clear it, which is what lets a
; session be asked for across one (net_boot). Only what the link's serial
; routines count cycles by has to be zero page: six bytes the game never
; uses (README.md, "Free RAM").

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
OUT0_MARK       = $01
APU_STATUS_DMC  = $10           ; in $4015: a sample has bytes still to fetch

; The faster ways through the game's busiest routines (net/fast.inc), which
; run from the PRG RAM; with NET_SLOW defined the game keeps its own, for
; the tests to hold the two alike.
.ifndef NET_SLOW
NET_FAST = 1
.endif

; The bank the netplay is in, at the end of the game's own bank 6
; (net/bubblebobble_net.cfg), and where its routines are called from the
; fixed bank (net_call, net/fill.inc; net_entry, net/net.asm).
NET_BANK        = 6
NET_ENTRY       = $A5A8
; The game's sound engine, in bank 4.
SOUND_BANK      = 4

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
; When the two differ, this console's RAM goes to its nesp32 for its log
; first (net_differ), in pieces of this many bytes, each asked up to
; DUMP_TRIES times.
DUMP_PIECE      = 64
DUMP_TRIES      = 3

.assert RING & (RING - 1) = 0, error, "RING must be a power of two"
.assert NET_DELAY_MAX + PER_FRAME < RING, error

; The link's library (nesp32's nes/lib/nesp.inc).
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = DUMP_PIECE + 2    ; the longest request: a piece of the RAM (net_differ)
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page that the game never writes once it is past its reset (README.md,
; "Free RAM"): $F1-$F4 only an unused routine of the Famicom Disk System's
; game names, and $64-$65 nothing does.
nesp_rx_data    = $F1
nesp_tx_data    = $F2
nesp_rx_end     = $F3
nesp_tries      = $F4
nesp_ptr        = $64           ; and $65

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
net_stalled     = NET_RAM + 23  ; $80: this NMI has no buttons for its tick
net_silent      = NET_RAM + 24  ; NMIs in a row that were not ticks
net_pad         = NET_RAM + 25  ; the controller as it was last read twice alike
net_menu        = NET_RAM + 26  ; bit 7: the NMI is the menu's; bit 6 too: its first
net_want        = NET_RAM + 27  ; the delay the nesp32 advises
net_late        = NET_RAM + 28  ; NMIs that waited for the other's buttons, since the last report
net_margin      = NET_RAM + 29  ; the fewest ticks of them held at a tick, since then
net_tune        = NET_RAM + 30  ; not 00: this NMI's exchange carries the report
net_check       = NET_RAM + 31  ; the digest, from when it was taken to when it is sent
net_temp        = NET_RAM + 32
net_pads        = NET_RAM + 33  ; 2: player 1's and player 2's buttons for this tick
net_autostart   = NET_RAM + 35  ; $10 from a session's reset to its game for two
nesp_seq        = NET_RAM + 36
nesp_tx_len     = NET_RAM + 37
nesp_count      = NET_RAM + 38
nesp_index      = NET_RAM + 39
nesp_crc_hi     = NET_RAM + 40
nesp_crc_lo     = NET_RAM + 41
nesp_status     = NET_RAM + 42
nesp_attention  = NET_RAM + 43
nesp_rng        = NET_RAM + 44  ; 2
nesp_rx         = NET_RAM + 46
nesp_tx         = nesp_rx + NESP_RX_MASK + 1 + 7
NET_RAM_END     = nesp_tx + NESP_TX_MAX + 7
; $80 from the game's NMI's start to its end. The game turns the NMI on
; again before its end now and then (at the logo's Start), and an NMI that
; then comes before the end, which is a matter of cycles, does nothing
; (net_nmi).
net_in_nmi      = NET_RAM_END
net_dumped      = NET_RAM_END + 1   ; pieces of the RAM sent (net_differ)

.assert net_dumped < MENU_RAM, error
NET_MENU_ON     = $80           ; in net_menu
NET_MENU_FIRST  = $C0
NET_STALL       = $80           ; in net_stalled

; The menu's memory, from here on (net/menu.inc).
MENU_RAM        = NET_RAM + $100

; The order to start a session, which is carried through the reset
; (net_start_session, net_reset): the mark, the role, the delay, a check.
net_boot        = NET_RAM + $1F00
NET_BOOT_MARK   = $4E
NET_BOOT_CHECK  = $B1

; What the fixed bank calls in the netplay's bank, by number in X
; (net_call, net/fill.inc; net_entry, net/net.asm).
NET_FRAME       = 0
NET_RESET       = 1
NET_MENU        = 2
NET_TITLE       = 3
NET_CURSOR      = 4
NET_SELECT      = 5

.endif

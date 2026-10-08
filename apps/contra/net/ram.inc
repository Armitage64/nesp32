; Netplay: the memory it uses. All of it is free in the game.

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
JOY1            = $4016
JOY2            = $4017
OUT0_MARK       = $01

; A button press is used net_delay ticks after the frame it was read in.
; It is the time the press has to cross to the other console. Each console
; keeps its own, and changes it as its nesp32 advises (net/net.inc).
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
.assert RING = 8, error, "the session's rings are laid out for 8 ticks"
.assert NET_DELAY_MAX + PER_FRAME < RING, error

; The link's library (nesp32's nes/lib/nesp.inc). The game has no run of
; zero page to spare, so its memory is placed here, a byte at a time.
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = 8             ; the longest request: a hello for one service
NESP_TIMEOUT    = 2             ; passes of 1.86 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page the game never uses. All but $F4, $F8 and $FB is cleared when a
; game or a level starts, so nothing is kept there from one NMI to the next.
nesp_rx_data    = $7E
nesp_tx_data    = $8F
nesp_ptr        = $DC           ; and $DD
nesp_rx_end     = $F4
nesp_tries      = $F8
net_temp        = $FB

; Past the end of the game's buffer of writes to the PPU, which stops at
; $0750. The console's reset clears it and nothing else in the game does.
NET_RAM         = $0752
net_local       = NET_RAM       ; RING: this console's buttons, by tick
net_remote      = NET_RAM + 8   ; RING: the other's
net_mode        = NET_RAM + 16  ; 01 in a session
net_role        = NET_RAM + 17  ; 00 this console is player 1, 01 player 2
net_delay       = NET_RAM + 18  ; ticks from a press being read to its use
net_tick        = NET_RAM + 19  ; the tick the next NMI may take
net_read        = NET_RAM + 20  ; first tick this console has no buttons for
net_acked       = NET_RAM + 21  ; first of this console's ticks the nesp32 lacks
net_have        = NET_RAM + 22  ; first of the other's ticks not here yet
net_stalled     = NET_RAM + 23  ; 01: the last NMI had no buttons for its tick
net_silent      = NET_RAM + 24  ; NMIs in a row that were not ticks
net_pad         = NET_RAM + 25  ; the controller as it was last read twice alike
net_menu        = NET_RAM + 26  ; not 00: the NMI is the menu's (01 its first)
net_want        = NET_RAM + 27  ; the delay the nesp32 advises
net_late        = NET_RAM + 28  ; NMIs that waited for the other's buttons, since the last report
net_margin      = NET_RAM + 29  ; the fewest ticks of them held at a tick, since then
net_tune        = NET_RAM + 30  ; not 00: this NMI's exchange carries the report
net_check       = NET_RAM + 31  ; the digest, from when it was taken to when it is sent
nesp_seq        = NET_RAM + 32
nesp_tx_len     = NET_RAM + 33
nesp_count      = NET_RAM + 34
nesp_index      = NET_RAM + 35
nesp_crc_hi     = NET_RAM + 36
nesp_crc_lo     = NET_RAM + 37
nesp_status     = NET_RAM + 38
nesp_attention  = NET_RAM + 39
nesp_rng        = NET_RAM + 40  ; 2
nesp_rx         = NET_RAM + 42
nesp_tx         = nesp_rx + NESP_RX_MASK + 1 + 7
NET_RAM_END     = nesp_tx + NESP_TX_MAX + 7

.assert NET_RAM_END <= $07C0, error, "netplay's memory runs into the palettes"

; Outside what the reset clears: the order to start a session, which is
; carried through one (net_start_session, net_reset).
net_boot        = $07E6         ; the mark, the role, the delay, a check
NET_BOOT_MARK   = $4E
NET_BOOT_CHECK  = $B1

; Netplay: the memory it uses. The game clears all of its own 2 KB at the
; reset and uses nearly all of it, so the netplay keeps its memory in the
; MMC3's 8 KB of PRG RAM (net/cart.inc), but for six bytes of zero page.
;
;   $6000-$77FF   the netplay's code, which the reset copies there from
;                 bank 8 (net_cart_reset): the session and nesp32's library
;   $7800-$78FF   the session's memory
;   $7900-$79FF   the menu's
;   $7A00-$7AFF   the menu's sprites, a page for the OAM's DMA
;   $7F00-$7F03   the order to start a session, carried through the reset

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
JOY1            = $4016
JOY2            = $4017
OUT0_MARK       = $01
APU_STATUS      = $4015

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
; NMIs in a row with no tick before the console gives the session up. A
; tick of the game's that loads a scene takes a few frames by itself, with
; no exchange in them, and is not counted: only NMIs that tried and had no
; buttons are.
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

; The link's library (nesp32's nes/lib/nesp.inc).
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = 8             ; the longest request: a hello for one service
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page the game never uses: the disassembly's RAM map has them as
; NOT_USED, no instruction names them, and none is in a range the game
; indexes. Only the reset clears them. Nothing is kept in them from one NMI
; to the next: each is the library's, for one exchange.
nesp_rx_data    = $F7
nesp_ptr        = $F8           ; and $F9
nesp_tx_data    = $FA
nesp_rx_end     = $FB
nesp_tries      = $EB

NET_RAM         = $7800
net_local       = NET_RAM       ; RING: this console's buttons, by tick
net_remote      = NET_RAM + 8   ; RING: the other's
net_mode        = NET_RAM + 16  ; 01 in a session
net_role        = NET_RAM + 17  ; 00 this console is player 1, 01 player 2
net_delay       = NET_RAM + 18  ; ticks from a press being read to its use
net_tick        = NET_RAM + 19  ; the tick the next NMI may take
net_read        = NET_RAM + 20  ; first tick this console has no buttons for
net_acked       = NET_RAM + 21  ; first of this console's ticks the nesp32 lacks
net_have        = NET_RAM + 22  ; first of the other's ticks not here yet
net_stalled     = NET_RAM + 23  ; $80: the last NMI had no buttons for its tick
net_silent      = NET_RAM + 24  ; NMIs in a row that were not ticks
net_pad         = NET_RAM + 25  ; the controller as it was last read twice alike
net_menu        = NET_RAM + 26  ; bit 7: the NMI is the menu's; bit 6 too: its first
net_want        = NET_RAM + 27  ; the delay the nesp32 advises
net_late        = NET_RAM + 28  ; NMIs that waited for the other's buttons, since the last report
net_margin      = NET_RAM + 29  ; the fewest ticks of them held at a tick, since then
net_tune        = NET_RAM + 30  ; not 00: this NMI's exchange carries the report
net_check       = NET_RAM + 31  ; the digest, from when it was taken to when it is sent
net_temp        = NET_RAM + 32  ; 3
nesp_fast       = NET_RAM + 35  ; bit 7: a session's exchanges at its own rate (net_rate)
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

; A session's line at its own rate (net_rate, net/net.inc).
net_rate_ask    = NET_RAM + $74 ; not 00: ask for it this many NMIs of the session on, less one
net_rate_tries  = NET_RAM + $75 ; times it has been asked for in this session
net_rate_misses = NET_RAM + $76 ; exchanges in a row that had no reply, at it
NET_RATE_TRIES  = 3
NET_RATE_MISSES = 30            ; half a second: and the line is the link's again
NET_RATE_WAIT   = 46            ; and asked for again after 3/4 of a second, once the nesp32
                                ; has gone back to the link's (PEER_RATE_QUIET_MS)

; The faster ways' own (net/fast.inc), within one call.
net_fast_y      = NET_RAM + $70
net_fast_r      = NET_RAM + $71
net_fast_j      = NET_RAM + $72
net_fast_op     = NET_RAM + $73
.assert NET_RAM_END <= net_fast_y, error, "the faster ways' memory runs into the session's"

NET_MENU_ON     = $80           ; in net_menu
NET_MENU_FIRST  = $C0
NET_STALL       = $80           ; in net_stalled

; The menu's memory (net/menu.inc).
MENU_RAM        = NET_RAM + $100
.assert NET_RAM_END <= MENU_RAM, error, "the session's memory runs into the menu's"

; Where the netplay's code runs (net/jackal_net.cfg), and how much of it the
; reset copies there: its pages, whatever is in them.
NET_IMAGE_RUN   = $6000
NET_IMAGE_PAGES = $18
NET_IMAGE_END   = NET_IMAGE_RUN + NET_IMAGE_PAGES * $100
.assert NET_IMAGE_END <= NET_RAM, error, "the netplay's code runs into its memory"

; The order to start a session, which is carried through the reset
; (net_start_session, net_reset): the mark, the role, the delay, a check.
net_boot        = $7F00
NET_BOOT_MARK   = $4E
NET_BOOT_CHECK  = $B1

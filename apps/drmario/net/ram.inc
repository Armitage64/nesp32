; Netplay: the memory both banks use. All of it is free in the game.

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
JOY1            = $4016
JOY2            = $4017
OUT0_MARK       = $01

; The link's library (nesp32's nes/lib/nesp.inc), which the menu's bank
; has: every exchange is made from there. Its memory is 16 bytes of zero
; page from $00B0 and its two buffers from $0330, which menu.cfg says.
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = 8             ; the longest request: a hello for one service
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page, free in the game.
net_temp        = $006F

; The game's own memory that a session's frame, in the menu's bank, has to
; know of (net/net.inc checks them against the game's names): where the
; controllers' buttons go, the flag its main loop waits on, and the sound
; engine's zero page, which a session keeps out of its digest as it does
; the link's.
NET_GAME_BUTTONS    = $00F5     ; player 1's, then player 2's
NET_GAME_NMI_FLAG   = $0033
NET_SOUND_ZP        = $00E0
NET_SOUND_ZP_SIZE   = $10
NET_LINK_ZP         = $00B0
NET_LINK_ZP_SIZE    = $10

; The session: free in the game, and outside what its reset clears.
net_local       = $0742         ; RING: this console's buttons, by tick
net_remote      = $074A         ; RING: the other's
net_mode        = $0752         ; 01 in a session
net_role        = $0753         ; 00 this console is player 1, 01 player 2
net_tick        = $0754         ; the tick the next NMI may take
net_acked       = $0755         ; first of this console's ticks the nesp32 lacks
net_have        = $0756         ; first of the other's ticks not here yet
net_waiting     = $0757         ; 01 while the main loop waits for an NMI
net_silent      = $0758         ; NMIs in a row that were not ticks
net_pending     = $0759         ; 01: the menu's request is to go out
net_result      = $075A         ; 01 its reply has come, FF none did
net_delay       = $075B         ; ticks from a press being read to its use
net_read        = $075C         ; first tick this console has no buttons for
net_stalled     = $075D         ; 01: the last NMI had no buttons for its tick
net_pad         = $075E         ; the controller as it was last read
net_want        = $075F         ; the delay the nesp32 advises
net_late        = $0760         ; NMIs that waited for the other's buttons, since the last report
net_margin      = $0761         ; the fewest ticks of them held at a tick, since then
net_tune        = $0762         ; not 00: this NMI's exchange carries the report
net_check       = $0763         ; the digest, from when it was taken to when it is sent
NET_VARS        = net_check + 1 - net_local

; For the jump between the banks: where net_far goes, and what the game
; gives the menu to come back by.
net_vector      = $072F
net_back        = $0738         ; to the game: from the menu with no session, or from a session's frame
net_go          = $073A         ; to the game, into a session; Y is the role and X the delay
MENU_ENTRY      = $8000         ; the menu
SESSION_ENTRY   = $8003         ; a session's frame (net/session.inc)

.assert RING = 8, error, "the session's rings are laid out for 8 ticks"
.assert net_remote = net_local + RING, error
.assert net_mode = net_remote + RING, error

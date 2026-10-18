; Netplay: the memory both banks use. All of it is free in the game.

; Controller port 2 is the line to the nesp32 (nesp32's docs/PROTOCOL.md):
; it drives D0 and reads OUT0, which rests at mark.
.ifndef JOY1                    ; the game's constants.asm has it
JOY1            = $4016
.endif
JOY2            = $4017
OUT0_MARK       = $01

; The link's library (nesp32's nes/lib/nesp.inc), which the menu's bank
; has: every exchange is made from there. Its memory is 16 bytes of zero
; page from $0020 and its two buffers from $0330, which menu.cfg says.
NESP_RX_MASK    = $1F           ; the longest reply payload: 32 bytes
NESP_TX_MAX     = 8             ; the longest request: a hello for one service
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page, free in the game.
net_temp        = $0006

; The game's own memory that a session's frame, in the menu's bank, has to
; know of (net/net.inc checks them against the game's names): where the
; controllers' buttons go, the flag its main loop waits on, and the sound
; engine's zero page, which a session keeps out of its digest as it does
; the link's. The two playfields are in the digest as well as the zero
; page: they are most of a game of Tetris.
NET_GAME_BUTTONS    = $00F5     ; player 1's, then player 2's
NET_GAME_NMI_FLAG   = $0033
NET_SOUND_ZP        = $00E0
NET_SOUND_ZP_SIZE   = $10
NET_LINK_ZP         = $0020
NET_LINK_ZP_SIZE    = $10
NET_PLAYFIELD_1     = $0400
NET_PLAYFIELD_2     = $0500
NET_PLAYFIELD_SIZE  = $C8

; The session: free in the game, and outside what its reset clears
; ($0000-$06FF; the high scores are kept, up to $0754).
net_local       = $0760         ; RING: this console's buttons, by tick
net_remote      = $0768         ; RING: the other's
net_mode        = $0770         ; 01 in a session
net_role        = $0771         ; 00 this console is player 1, 01 player 2
net_tick        = $0772         ; the tick the next NMI may take
net_acked       = $0773         ; first of this console's ticks the nesp32 lacks
net_have        = $0774         ; first of the other's ticks not here yet
net_waiting     = $0775         ; 01 while the main loop waits for an NMI
net_silent      = $0776         ; NMIs in a row that were not ticks
net_pending     = $0777         ; 01: the menu's request is to go out
net_result      = $0778         ; 01 its reply has come, FF none did
net_delay       = $0779         ; ticks from a press being read to its use
net_read        = $077A         ; first tick this console has no buttons for
net_stalled     = $077B         ; 01: the last NMI had no buttons for its tick
net_pad         = $077C         ; the controller as it was last read
net_want        = $077D         ; the delay the nesp32 advises
net_late        = $077E         ; NMIs that waited for the other's buttons, since the last report
net_margin      = $077F         ; the fewest ticks of them held at a tick, since then
net_tune        = $0780         ; not 00: this NMI's exchange carries the report
net_check       = $0781         ; the digest, from when it was taken to when it is sent
NET_VARS        = net_check + 1 - net_local

; For the jump between the banks: where net_far goes, and what the game
; gives the menu to come back by.
net_vector      = $0790
net_back        = $0792         ; to the game: from the menu with no session, or from a session's frame
net_go          = $0794         ; to the game, into a session; Y is the role and X the delay
MENU_ENTRY      = $8000         ; the menu
SESSION_ENTRY   = $8003         ; a session's frame (net/session.inc)

.assert RING = 8, error, "the session's rings are laid out for 8 ticks"
.assert net_remote = net_local + RING, error
.assert net_mode = net_remote + RING, error

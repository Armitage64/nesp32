; Netplay: the memory both banks use. All of it is free in the game.

; Zero page, free in the game. The serial routines' timing counts on it.
net_rx_data     = $006A
net_tx_data     = $006B
net_check_lo    = $006C
net_check_hi    = $006D
net_tries       = $006E
net_temp        = $006F

; Scratch, free in the game, cleared with the rest when a session starts.
net_request     = $0330         ; FRAME_SIZE
net_reply       = $0338         ; FRAME_SIZE

; The session: free in the game, and outside what its reset clears.
net_local       = $0742         ; RING: this console's buttons, by tick
net_remote      = $074A         ; RING: the other's
net_mode        = $0752         ; 01 in a session
net_role        = $0753         ; 00 this console is player 1, 01 player 2
net_tick        = $0754         ; the tick the next NMI may take
net_acked       = $0755         ; first of this console's ticks the Stick lacks
net_have        = $0756         ; first of the other's ticks not here yet
net_waiting     = $0757         ; 01 while the main loop waits for an NMI
net_silent      = $0758         ; NMIs in a row that were not ticks
net_pending     = $0759         ; 01: the menu's request is to go out
net_result      = $075A         ; 01 its reply is in net_reply, FF none came
NET_VARS        = net_result + 1 - net_local

; For the jump between the banks: where net_far goes, and what the game
; gives the menu to come back by.
net_vector      = $072F
net_back        = $0738         ; to the game, with no session
net_go          = $073A         ; to the game, into a session; Y is the role
MENU_ENTRY      = $8000

.assert RING = 8, error, "the session's rings are laid out for 8 ticks"
.assert net_remote = net_local + RING, error
.assert net_mode = net_remote + RING, error

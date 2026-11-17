; Netplay: the memory it uses.
;
; The game leaves no run of the console's RAM alone: from the power on
; through its menus and a game for two, all that was never written was 32
; bytes at $0660 and some scraps of the stack and the sound engine's page.
; Its save RAM is full too, but for two stretches that its checksum leaves
; out and nothing writes: 260 bytes at $6EFE (EMPTY_SEASON_INFO) and the
; 142 at $7F72, past the season's data (SRAM_FREE_SPACE). The netplay
; keeps its memory in the second, and its zero page is the game's LOCAL_1
; to LOCAL_8 ($3E-$45), which it uses only while every task is asleep: a
; task keeps its own on its stack while it sleeps.
;
; The game turns its save RAM's writes on and off ($A001) as it goes, and
; the register cannot be read: so the netplay finds out which it is, by a
; byte of its own (net_probe), turns them on, and puts back what it found
; (net_sram_on and net_sram_back, net/net.inc).
;
;   $7F72-$7FD8   the session's memory and the library's
;
; and the bytes the fixed bank's hooks look at in every NMI are in
; the console's RAM, at the end of a run of 31 bytes past the players'
; ($0661-$067F) that the disassembly has no name for and the game was
; never seen to write, with one more for the intro (net_skip, $067C). The game's reset clears them, before net_reset
; sets them.
;   $7FF0-$7FF3   the order to start a session, carried through the reset
;   $7FF4-$7FF5   where the game goes after that reset (net_skip_mark)
;   $7FFF         net_probe
;   $6EFE-$6F1D   for the length of an NMI: the stack that its exchange goes
;                 over, and the zero page it works in (net_nmi_read)
;   $6F1E-$6FAB   the library's frames, a reply and a request
;
; The menu has the console only at the title and starts it again when it
; is done, by a session or not: so it keeps its own memory in the
; console's RAM ($0500-$05FF), and its sprites in the game's page ($0200).
; (Not $0300 on, where the game's NMI keeps the registers it saves.)

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
; NMIs in a row with no tick, a lag's not counted, before the console
; gives the session up.
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
NESP_RX_MASK    = $3F           ; the longest reply payload: 64 bytes, a piece of the save
NESP_TX_MAX     = 2 + SAVE_PIECE    ; the longest request: SAVE_PUT's
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1             ; every exchange is made in an NMI
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short one

; Zero page: the game's LOCAL_1 to LOCAL_8, while every task sleeps.
; Nothing is kept in them from one NMI to the next.
nesp_rx_data    = $3E
nesp_tx_data    = $3F
nesp_ptr        = $40           ; and $41
nesp_rx_end     = $42
nesp_tries      = $43
net_temp        = $44           ; and $45

NET_RAM         = $7F72
net_local       = NET_RAM       ; RING: this console's buttons, by tick
net_remote      = NET_RAM + 8   ; RING: the other's
net_unused_16   = NET_RAM + 16
net_role        = NET_RAM + 17  ; 00 this console is player 1, 01 player 2
net_delay       = NET_RAM + 18  ; ticks from a press being read to its use
net_tick        = NET_RAM + 19  ; the tick the next NMI may take
net_read        = NET_RAM + 20  ; first tick this console has no buttons for
net_acked       = NET_RAM + 21  ; first of this console's ticks the nesp32 lacks
net_have        = NET_RAM + 22  ; first of the other's ticks not here yet
net_unused_23   = NET_RAM + 23
net_silent      = NET_RAM + 24  ; NMIs in a row that were not ticks
net_pad         = NET_RAM + 25  ; the controller as it was last read alike
net_unused_26   = NET_RAM + 26
net_want        = NET_RAM + 27  ; the delay the nesp32 advises
net_late        = NET_RAM + 28  ; NMIs that waited for the other's buttons, since the last report
net_margin      = NET_RAM + 29  ; the fewest ticks of them held at a tick, since then
net_tune        = NET_RAM + 30  ; not 00: this NMI's exchange carries the report
net_check       = NET_RAM + 31  ; the digest, from when it was taken to when it is sent
net_a001        = NET_RAM + 32  ; what $A001 was found as, to put back
nesp_seq        = NET_RAM + 33
nesp_tx_len     = NET_RAM + 34
nesp_count      = NET_RAM + 35
nesp_index      = NET_RAM + 36
nesp_crc_hi     = NET_RAM + 37
nesp_crc_lo     = NET_RAM + 38
nesp_status     = NET_RAM + 39
nesp_attention  = NET_RAM + 40
nesp_rng        = NET_RAM + 41  ; 2
; A session's line at its own rate (net_rate, net/net.inc).
nesp_fast       = NET_RAM + 43  ; bit 7: a session's exchanges at its own rate
net_rate_ask    = nesp_fast + 1 ; not 00: ask for it this many NMIs of the session on, less one
net_rate_tries  = nesp_fast + 2 ; times it has been asked for in this session
net_rate_misses = nesp_fast + 3 ; exchanges in a row that had no reply, at it
net_carry       = nesp_fast + 4 ; the NMI's read: 01 a stall, 00 a tick
NET_RAM_END     = nesp_fast + 5
NET_RATE_TRIES  = 3
NET_RATE_MISSES = 30            ; half a second: and the line is the link's again
NET_RATE_WAIT   = 46            ; and asked for again after 3/4 of a second, once the nesp32
                                ; has gone back to the link's (PEER_RATE_QUIET_MS)

; The order to start a session, which is carried through the reset
; (net_start_session, net_reset): the mark, the role, the delay, a check.
net_mode        = $067D         ; $80 in a session
net_menu        = $067E         ; bit 7: the NMI is the menu's; bit 6 too: its first
net_owed        = $067F         ; not 00: the PPU has not had the last tick's writes
net_skip        = $067C         ; NET_SKIP_*: where the intro goes (net_intro, net/cart.inc)
net_stall_now   = $067B         ; this NMI's read: 01 a stall, 00 a tick (net_sound_hook)
net_title_choice = $067A        ; the title's: 0 LOCAL GAME, 1 NETWORK GAME (net/title.inc)
net_nmi_busy    = $0679         ; bit 7: a session's NMI is at its own work, before the tasks

; Where the game goes after a reset of the netplay's own, which sets
; net_skip_mark before it and net_reset takes it into net_skip: past the
; intro to the title (LOCAL GAME, B, a session lost), or to the main menu
; (a session's start). A reset of the console's, or a power-on, finds none,
; and the intro plays.
NET_SKIP_NONE   = 0
NET_SKIP_TITLE  = 1
NET_SKIP_MENU   = 2
NET_SKIP_CHECK  = $C3           ; net_skip_mark+1 is the mark EOR this

net_boot        = $7FF0
NET_BOOT_MARK   = $4E
NET_BOOT_CHECK  = $B1
net_skip_mark   = $7FF4         ; and $7FF5: NET_SKIP_*, and its check
net_probe       = $7FFF         ; flipped and read back: are the writes on?

; The stack the NMI's exchange runs on is the scheduler's idle loop's, 14
; bytes at $01F2-$01FF ($01F1 down is the first task's), which the game's
; own NMI fits in. The exchange goes deeper: so it keeps the bytes it is to
; go over, and puts them back (net_nmi_read). They are kept for no longer
; than the NMI, in the save RAM that its checksum leaves out at $6EFE,
; which the game does not read. Its deepest, a short request's first try
; (net_exchange to net_ask to nesp_short), writes 15 bytes below where
; net_nmi_read keeps them from; 24 leaves room, and the tests fail a write
; below them (tests/netplay.py, guard_stack).
STACK_KEEP      = 24
net_stack_copy  = $6EFE         ; STACK_KEEP, and the 8 of LOCAL_1 to LOCAL_8

; The save a session's two consoles must have alike (net/menu.inc): the
; save RAM from the game's random seed to the end of its season, but for
; the stretch the game leaves empty, which is the netplay's. Before it,
; the scratch of the game's scenes and sprites, which a session clears.
SAVE_SCRATCH    = $6000
SAVE_START      = $6403         ; SAVED_RANDOM_1
SAVE_GAP        = $6EFE         ; EMPTY_SEASON_INFO: 260 bytes
SAVE_GAP_END    = $7002
SAVE_END        = $7F72         ; SRAM_FREE_SPACE: the netplay's memory on
SAVE_LENGTH     = (SAVE_GAP - SAVE_START) + (SAVE_END - SAVE_GAP_END)
SAVE_PIECE      = 64            ; bytes of it a request or a reply carries

.assert NET_RAM_END <= net_boot, error, "the netplay's memory runs into net_boot"

; The library's frames, past the stack the NMI keeps (net_stack_copy), in
; the save RAM that the game's checksum leaves out and nothing writes.
nesp_rx         = net_stack_copy + STACK_KEEP + 8
nesp_tx         = nesp_rx + NESP_RX_MASK + 1 + 7
NESP_FRAMES_END = nesp_tx + NESP_TX_MAX + 7
.assert NESP_FRAMES_END <= SAVE_GAP_END, error, "the library's frames run out of the gap"

NET_MENU_ON     = $80           ; in net_menu
NET_MENU_FIRST  = $C0

; The menu's memory (net/menu.inc).
MENU_RAM        = $0500

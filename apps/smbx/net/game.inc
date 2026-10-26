; What the netplay knows of the game: the addresses of its memory and its
; routines, in the hack as baserom.nes has it (README.md). Names are the
; netplay's own: the hack comes with no source. None of the game's code is
; here, only where it is.

.ifndef GAME_INC
GAME_INC = 1

; --- the cartridge ---------------------------------------------------------------
; A VRC6: 16 KB at $8000 picked by $8000, 8 KB at $C000 picked by $C000, and
; the last 8 KB fixed at $E000. The game keeps bank 2 at $8000 but in its
; NMI, which brings in bank 0 for the sound and the controllers. Bank 1 is
; all $FF, and is the netplay's.
VRC6_PRG16      = $8000
VRC6_PPU        = $B003         ; bit 7: the PRG RAM on, as the reset sets it
VRC6_IRQ_CONTROL = $F001
BANK_SOUND      = 0             ; at $8000: the sound and the controllers
BANK_NET        = 1             ; at $8000: the netplay
BANK_GAME       = 2             ; at $8000: the rest of the game

; --- its routines ------------------------------------------------------------------
GAME_RESET      = $FF48
GAME_NMI        = $FE28         ; the NMI vector's
GAME_NMI_END    = $FF1D         ; the NMI's last lines: A off the stack, the frame done, RTI
GAME_SCROLL     = $FF35         ; the scroll and PPUCTRL from their copies
GAME_IDLE       = $FFEF         ; where the reset waits for the NMIs, for ever
GAME_SOUND      = $8000         ; bank 0: the sound engine, once a frame
GAME_PADS       = $8D23         ; bank 0: read both controllers, then GAME_PADS_USE
GAME_PADS_USE   = $8D3C         ; bank 0: from both read into PAD_RAW: held, pressed, pause
GAME_PADS_DONE  = $8D92         ; bank 0: an RTS

GAME_DRAW       = $8D09         ; bank 2: the buffer of writes picked to the PPU; A = 0 after
DRAW_SCRATCH    = 3             ; the zero page from $00 that it leaves where it came to

; The places the netplay ROM changes, each by an instruction of the same
; length (net/rom.asm).
HOOK_NMI_DRAW   = $FE65         ; 3 bytes: the NMI's call to GAME_DRAW
HOOK_NMI_DRAWN  = HOOK_NMI_PADS ; where the NMI is once it has drawn and emptied the buffer
HOOK_NMI_PADS   = $FE89         ; 9 bytes: bank 0 in, the sound, the controllers
HOOK_NMI_PADS_END = $FE92       ; and what follows them: bank 2 in again
HOOK_RESET      = $FFD8         ; 3 bytes: a call, at the end of the reset
HOOK_RESET_CALL = $8015         ; bank 2: what that call was (the sprites hidden)
HOOK_TITLE_PAD  = $8055         ; bank 2, 3 bytes: the title's look at what was pressed
NMI_VECTOR      = $FFFA

; The fixed bank's free space, 2100 bytes the game never reads.
FIXED_FREE      = $F5AB
FIXED_FREE_END  = $FDDF

; --- its memory ----------------------------------------------------------------------
; The buttons in a byte as the game reads them, A first and Right last.
BUTTON_A        = $80
BUTTON_START    = $10

PAD_RAW         = $00           ; 2: what the controllers were read as, player 1's and player 2's
PAD_HELD        = $E0           ; 2
PAD_PRESSED     = $06F6         ; 2: pressed since the frame before
OPER_MODE       = $E2           ; 0 the title, 1 a game, then 3 and 2 at its end; the task after
SPLIT_WANTED    = $0722         ; 0: the NMI sets the scroll itself, with no split
PPU_CTRL_RAM_COPY = $076D
PPU_MASK_RAM_COPY = $076E
DRAW_NEXT       = $0768         ; which buffer the NMI draws: 0 the game's $0301, which it empties
PAUSED          = $076B         ; bit 0: the game stands paused
TWO_PLAYERS     = $076F         ; the title's choice: 0 1 PLAYER GAME, 1 2 PLAYERS GAME
LIVES           = $075B         ; the players', shared: $FF is the game over
NMI_ENTRIES     = $074C         ; 1 between NMIs, 0 in one, negative in one that came during another
LAG_COUNT       = $03F0         ; stepped in an NMI that came during another (in the PPU's buffer)
SPRITE_PAGE     = $0200

; What the sound engine keeps, which the game leaves orders in ($FA-$FF)
; and reads one byte of back: whether the music of an event is still
; playing ($07B1), at the end of a level (README.md, "The sound").
SOUND_ZP        = $F0           ; to $FF
SOUND_RAM       = $07B0         ; to $07CA

.endif

; Lobby: nesp32's sample of a game for two consoles over the network.
;
; Two consoles, each with a nesp32 on controller port 2. The ROM boots to
; the lobby that nesp32's netplay games have (docs/MULTIPLAYER.md): one
; player chooses HOST GAME, the other JOIN GAME, and they meet by a room's
; code or, with Select, by an address. Then both consoles show both
; players' controllers, with every button that is down lit, the same on
; both screens at the same tick.
;
; That picture is the whole "game" (nes/pads.inc). Everything else is what
; a real game would keep as it is:
;
;   nes/lobby.s     this file: reset, the NMI, the main loop, the
;                   controller, and drawing a screen
;   nes/menu.inc    the lobby: the hello, and the PEER service's lobby ops
;   nes/session.inc the session: buttons out and the other console's in, a
;                   byte a tick each way, in lockstep
;   nes/pads.inc    the game: both players' buttons as sprites
;
; How it talks to the nesp32. Every use of the link is one exchange, a
; request and its reply (nesp32's docs/PROTOCOL.md), through nesp32's
; library for the console (nes/lib/nesp.inc). The serial routines count
; CPU cycles, so nothing may interrupt them; this ROM makes every exchange
; inside its NMI, after the NMI's writes to the PPU, at most one a frame.
; That is how the netplay games do it, and it is the one way a session's
; exchange can be timed to the frame. The receiver gives up on a reply by
; counting (NESP_TIMEOUT), since inside the NMI no other NMI can end the
; wait.
;
; What crosses the link, from power on:
;
;   SYS HELLO       "PADS", version 1, asking for PEER. The nesp32 stops
;                   whatever it was doing for the last ROM. Said again
;                   whenever the nesp32 says PEER is not in use: it was
;                   switched off and on
;   PEER STATUS     a few times a second in the lobby: is the nesp32 on a
;                   network, and at what address; ROOM in a room, which
;                   also says the room's code and why a meeting failed
;   PEER HOST_ROOM, JOIN_ROOM, HOST, JOIN, LAST, LEAVE
;                   what the player chose. Sent until answered
;   PEER TICKS      as a short frame, every frame of a session: this
;                   console's buttons out, the other console's back
;
; The nesp32 says which player this console is when the two are joined:
; the one that hosted is player 1. From then on the lobby is left, and
; every frame is the session's (nes/session.inc). When the session ends
; (the other console went, the link went quiet, or the two games differ)
; the ROM says why, and is back in the lobby with a new hello.
;
; The tests (tests/test_lobby.py) run two consoles on this ROM, each with
; a nesp32's own firmware built for the computer, on a simulated network.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
OAMADDR   = $2003
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
OAMDMA    = $4014
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80               ; and both tables of tiles at $0000
PPUMASK_ON = $1E                ; background and sprites, left column included
FRAME_IRQ_INHIBIT = $40
PALETTE   = $3F00
SPRITE_HIDDEN = $FF             ; an OAM y past the bottom of the picture

PAD_A      = $80
PAD_B      = $40
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04
PAD_LEFT   = $02
PAD_RIGHT  = $01

; Controller port 2 is the line to the nesp32. It reads OUT0, which is
; also controller 1's strobe, and rests at mark (high).
OUT0_MARK = $01

; The link's library: what it is built for. See the top of nesp.inc.
NESP_RX_MASK = $1F              ; replies of up to 32 bytes
NESP_TX_MAX  = 8                ; the longest request: the hello, naming PEER
NESP_TIMEOUT = 1                ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY = 1               ; every exchange is made inside the NMI
NESP_CRC_TABLE = 1              ; faster checks, which short frames need
NESP_SHORT_FRAMES = 1           ; a session's exchange is a short frame
; The hello's name and version. PEER joins two consoles only if both said
; the same: a game changes the version whenever what crosses changes.
.define NESP_APP "PADS"
NESP_APP_VERSION = 1

MODE_LOBBY   = 0
MODE_SESSION = 1

; One run for draw_texts, at a row and column of the screen.
.macro text row, column, string
    .byte >($2000 + (row) * 32 + (column)), <($2000 + (row) * 32 + (column))
    .byte .strlen(string), string
.endmacro

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM)
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1            ; the last of them the main loop has seen
ptr:          .res 2            ; the main loop's, for drawing a screen
pad:          .res 1            ; controller 1, as last read: A B Select Start Up Down Left Right
temp:         .res 1

.segment "OAM"
oam:          .res 256          ; the sprites, copied to the PPU every NMI

.segment "BSS"
mode:         .res 1            ; MODE_*
; One run of tiles for the NMI to draw, staged by the main loop. Anything
; that changes on a screen goes this way, a run a frame.
draw_len:     .res 1            ; how many of draw_line, 0 for none
draw_hi:      .res 1            ; where, in the nametable
draw_lo:      .res 1
draw_line:    .res 16

.include "nesp.inc"
.assert NESP_TX_MAX = NESP_HELLO_FIXED + 1, error, "the hello names one service"

.segment "RODATA"
.include "layout.inc"           ; tools/gen_chr.py: the sprites' places, the palettes
session_screen:
    .incbin "session.bin"

.segment "CHARS"
    .incbin "chr.bin"

.segment "CODE"
.include "menu.inc"
.include "session.inc"
.include "pads.inc"



reset:
    sei
    cld
    ldx #FRAME_IRQ_INHIBIT
    stx APU_FRAME
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx APU_DMC
    stx APU_STATUS
    bit PPUSTATUS
@vblank1:
    bit PPUSTATUS
    bpl @vblank1
    txa
@clear:
    sta $0000,x
    sta $0100,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @clear
    jsr hide_sprites
@vblank2:
    bit PPUSTATUS
    bpl @vblank2
    jsr load_palettes
    lda #OUT0_MARK              ; the line rests at mark
    sta JOY1
    lda #STATUS_NONE            ; no session has ended
    jsr lobby_start             ; the lobby's first screen, with the NMI on
    ; fall through

; Once a frame, after the NMI: the lobby's work, or the game's. The tests
; skip ahead to the next NMI whenever the CPU waits at main_wait with
; frame_count equal to served_frame, so it stays a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    lda mode
    bne @session
    jsr menu_frame
    jmp main_loop
@session:
    jsr session_main
    jmp main_loop



; Every frame: what the main loop staged goes to the PPU first, while
; there is time in the vblank for it, then the link's one exchange.
nmi:
    pha
    txa
    pha
    tya
    pha
    lda draw_len
    beq @sprites
    bit PPUSTATUS
    lda draw_hi
    sta PPUADDR
    lda draw_lo
    sta PPUADDR
    ldx #0
@tile:
    lda draw_line,x
    sta PPUDATA
    inx
    cpx draw_len
    bne @tile
    lda #0
    sta draw_len
@sprites:
    lda #0
    sta OAMADDR
    lda #>oam
    sta OAMDMA
    lda #PPUCTRL_NMI
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_ON
    sta PPUMASK
    lda mode
    bne @session
    jsr read_pad
    jsr menu_nmi
    jmp @done
@session:
    jsr session_nmi             ; which reads the controller when it is time
@done:
    inc frame_count
    pla
    tay
    pla
    tax
    pla
irq:
    rti



; Controller 1 into pad. OUT0 is controller 1's strobe and the line to the
; nesp32 at once: it goes low for the reads and no longer, and the nesp32
; passes over what that looks like to it.
;
; A game that plays DPCM samples must read twice and compare, as a real
; NES can spoil a read that a sample's fetch falls on: nesp32's
; docs/PHANTOM-RIGHT.md. This one plays none.
read_pad:
    lda #0
    sta JOY1
    ldx #8
@bit:
    lda JOY1
    lsr a
    rol pad
    dex
    bne @bit
    lda #OUT0_MARK
    sta JOY1
    rts



; --- the screen ------------------------------------------------------------------

load_palettes:
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldy #4                      ; the background's four, all alike
@background:
    ldx #0
@colour:
    lda background_palette,x
    sta PPUDATA
    inx
    cpx #4
    bne @colour
    dey
    bne @background
    ldy #4                      ; and the sprites'
@sprite:
    ldx #0
@sprite_colour:
    lda sprite_palette,x
    sta PPUDATA
    inx
    cpx #4
    bne @sprite_colour
    dey
    bne @sprite
    rts

hide_sprites:
    lda #SPRITE_HIDDEN
    ldx #0
@sprite:
    sta oam,x
    inx
    bne @sprite
    rts

; The picture and the NMI off, so that the main loop may write the PPU,
; and nothing left staged. No exchange can be under way: they are all
; made in the NMI.
screen_off:
    lda #0
    sta PPUCTRL
    sta PPUMASK
    sta draw_len
    rts

; The NMI on again: it turns the picture on.
screen_on:
    lda #PPUCTRL_NMI
    sta PPUCTRL
    rts

; Fill the nametable, with the picture off: 960 tiles and 64 attributes
; from ptr.
draw_nametable:
    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #4
    ldy #0
@byte:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @byte
    inc ptr + 1
    dex
    bne @byte
    rts

; Text on the screen, with the picture off: from ptr, runs of the address
; (high byte first), the length and the characters, until a 0. The font
; is ASCII.
draw_texts:
    ldy #0
@run:
    lda (ptr),y
    beq @done
    sta PPUADDR
    iny
    lda (ptr),y
    sta PPUADDR
    iny
    lda (ptr),y
    tax
    iny
@char:
    lda (ptr),y
    sta PPUDATA
    iny
    dex
    bne @char
    beq @run
@done:
    rts



.segment "VECTORS"
    .word nmi, reset, irq

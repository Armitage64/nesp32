; nesp32 cartridge: the menu.
;
; One cartridge has the eight programs that use a nesp32, and this, which is
; what comes up at power-on and at reset: their names, an arrow, and A or
; Start to run the one it is at. nes/cart/gen_cart.py has where each of
; them is on the cartridge, and what it does to make reset come here.
;
; The cartridge is an MMC1. This is its last 16 KB of PRG, which that
; mapper has at $C000 when the power comes on, and keeps there while this
; runs. A program is started from RAM, since the bank changes under
; anything in ROM: the mapper is set as the program wants it, an NROM,
; and the program is entered where its own reset vector pointed. (NES
; Radar, which has two pages of tiles, then asks the mapper for each itself.)
;
; The menu's own hello asks the nesp32 for KBD alone, the Bluetooth keyboard:
; its keys are the controller's buttons here as in every program on the
; cartridge (nesp_key_pad), and the badge at the top right says how it
; stands. Asking for KBD keeps a keyboard connected from a program, through
; the menu, to the next. Each program begins with its own hello, which is
; what tells the nesp32 what to run. The badge is nes/lib/badge.inc's, as
; the setup ROM's is.

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
APU_FRAME = $4017

FRAME_IRQ_INHIBIT = $40
PPUCTRL_ON = $80                ; NMI on, nametable 0
PPUMASK_ON = $1E                ; background and sprites, left column included
PALETTE   = $3F00
NAMETABLE = $2000
OUT0_MARK = $01

; The MMC1's registers, each written a bit at a time, five writes.
MMC1_CONTROL = $8000
MMC1_CHR0    = $A000
MMC1_PRG     = $E000
MENU_CONTROL = $0E              ; the last bank at $C000, 8 KB of CHR, vertical mirroring

PAD_A      = $80
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04
PAD_DIRECTIONS = PAD_UP | PAD_DOWN
REPEAT_DELAY = 20               ; frames a direction is held before it repeats
REPEAT_EVERY = 5                ; and frames between repeats

oam = $0200                     ; sprites, copied to the PPU every NMI
SPRITE_HIDDEN = $F0
BADGE_OAM = oam + 4             ; the badge's four, after the arrow

; The link (nesp32's nes/lib/nesp.inc).
NESP_RX_MASK = $1F              ; KBD STATE's reply is 27 bytes at the most
NESP_TX_MAX  = 8                ; the hello, with its one service
NESP_CRC_TABLE = 1
NESP_KEY_PAD = 1
JOY2 = $4017
.define NESP_APP "MENU"
NESP_APP_VERSION = 1
HELLO_EVERY = $07               ; frames between hellos until one is answered, less one
STATE_EVERY = $0F               ; and between asking how the keyboard stands
MISSES_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is gone

.include "menu.inc"

.segment "ZEROPAGE"
frame_count:  .res 1
served_frame: .res 1
pad:          .res 1            ; controller 1 as the NMI read it
pad_seen:     .res 1
pad_new:      .res 1            ; buttons that went down, and directions repeating
pad_hold:     .res 1
choice:       .res 1            ; the program the arrow is at
ptr:          .res 2
; What `launch` gives the mapper, and where it goes.
go_control:   .res 1
go_chr:       .res 1
go_prg:       .res 1
go_addr:      .res 2
greeted:      .res 1            ; the nesp32 has answered the hello (badge_ok: with KBD)
misses:       .res 1            ; exchanges in a row with no reply
key_at:       .res 1            ; the next key of a KEYS reply

; A register of the mapper = A, from this bank: for a write that leaves it
; at $C000.
.macro mapper_write register
.repeat 4
    sta register
    lsr a
.endrepeat
    sta register
.endmacro

.segment "RODATA"
screen_data:
    .incbin "screen.bin"

.segment "CODE"

.include "nesp.inc"
.include "badge.inc"

.proc reset
    sei
    cld
    ldx #FRAME_IRQ_INHIBIT
    stx APU_FRAME
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx APU_DMC                 ; DMC IRQ off
    stx APU_STATUS              ; and whatever a program was playing
    lda #OUT0_MARK              ; the line to the nesp32 rests at mark
    sta JOY1
    lda #MENU_CONTROL
    mapper_write MMC1_CONTROL
    lda #MENU_CHR
    mapper_write MMC1_CHR0
    bit PPUSTATUS
@vblank1:
    bit PPUSTATUS
    bpl @vblank1

    txa
@clear:
    sta $0000,x
    sta $0100,x
    sta $0200,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @clear
    dex                         ; a button held at reset is not a press
    stx pad_seen

@vblank2:
    bit PPUSTATUS
    bpl @vblank2

    jsr ppu_init
    jsr place_arrow
    jsr badge_init
    jsr show_badge
    lda #PPUCTRL_ON             ; the first NMI turns the picture on
    sta PPUCTRL
    ; fall through
.endproc

; Once a frame, starting right after the NMI. The tests skip the clock
; ahead to the next NMI whenever the CPU sits at main_wait with frame_count
; equal to served_frame, so it is a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr link_frame              ; first, right after the NMI
    jsr read_input
    jsr show_badge
    lda pad_new
    and #PAD_A | PAD_START
    bne launch
    lda pad_new
    and #PAD_DOWN
    beq @up
    ldx choice
    inx
    cpx #ENTRIES
    bcc @down
    ldx #0
@down:
    stx choice
@up:
    lda pad_new
    and #PAD_UP
    beq @show
    ldx choice
    bne @back
    ldx #ENTRIES
@back:
    dex
    stx choice
@show:
    jsr place_arrow
    jmp main_loop

; Run the program the arrow is at. It does not come back.
.proc launch
    lda #0
    sta PPUCTRL                 ; no NMI: this bank is about to go
    sta PPUMASK
    ldx choice
    lda entry_control,x
    sta go_control
    lda entry_chr,x
    sta go_chr
    lda entry_prg,x
    sta go_prg
    lda entry_lo,x
    sta go_addr
    lda entry_hi,x
    sta go_addr + 1
    ldx #LAUNCH_SIZE - 1
@copy:
    lda launch_code,x
    sta launch_ram,x
    dex
    bpl @copy
    jmp launch_ram
.endproc

; What `launch` runs in RAM, so nothing in it is an address of its own. The
; write that ends each five takes effect at once: after the first of them
; this bank is no longer at $C000.
launch_code:
    lda go_control
    ldx #5
:   sta MMC1_CONTROL
    lsr a
    dex
    bne :-
    lda go_chr
    ldx #5
:   sta MMC1_CHR0
    lsr a
    dex
    bne :-
    lda go_prg
    ldx #5
:   sta MMC1_PRG
    lsr a
    dex
    bne :-
    jmp (go_addr)
LAUNCH_SIZE = * - launch_code

.segment "BSS"
launch_ram:   .res LAUNCH_SIZE

.segment "CODE"

; pad_new = the buttons that went down since the last frame, Up or Down if
; it has been held long enough to repeat, and a key typed on the Bluetooth
; keyboard that stands for buttons (nesp_key_next).
.proc read_input
    jsr read_pad
    jsr nesp_key_next
    ora pad_new
    sta pad_new
    rts
.endproc

.proc read_pad
    lda pad
    tax
    eor pad_seen
    stx pad_seen
    and pad_seen
    sta pad_new
    txa
    and #PAD_DIRECTIONS
    beq @released
    bit pad_new                 ; a new press starts the count again
    bne @released
    inc pad_hold
    lda pad_hold
    cmp #REPEAT_DELAY
    bcc @done
    lda #REPEAT_DELAY - REPEAT_EVERY
    sta pad_hold
    txa
    and #PAD_DIRECTIONS
    ora pad_new
    sta pad_new
@done:
    rts
@released:
    lda #0
    sta pad_hold
    rts
.endproc

; The arrow, beside the name `choice` is.
.proc place_arrow
    .assert LIST_STEP = 2, error, "a name is 16 lines below the last"
    lda choice
    asl a
    asl a
    asl a
    asl a
    clc
    adc #ARROW_Y - 1            ; a sprite shows a line below its Y
    sta oam
    lda #TILE_ARROW
    sta oam + 1
    lda #0
    sta oam + 2
    lda #ARROW_X
    sta oam + 3
    rts
.endproc

; --- the link ---------------------------------------------------------------------

; The frame's exchange, if it has one: the hello until it is answered, every
; eighth frame; then, with KBD, how the keyboard stands every sixteenth and
; what is typed every other.
.proc link_frame
    lda greeted
    bne @greeted
    lda frame_count
    and #HELLO_EVERY
    bne @done
    jmp say_hello
@greeted:
    lda badge_ok
    beq @done
    lda frame_count
    and #STATE_EVERY
    beq ask_state
    lda frame_count
    lsr a
    bcs ask_keys
@done:
    rts
.endproc

; Hello: this is the menu, and it asks for KBD. A nesp32 without it, or
; that speaks another protocol, is greeted all the same: there is just no
; keyboard to ask about.
.proc say_hello
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs missed
    ldx #0
    stx misses
    cmp #NESP_ST_OK
    bne @without
    inx
@without:
    stx badge_ok
    lda #1
    sta greeted
    rts
.endproc

; No reply. After MISSES_MAX in a row the nesp32 is taken to be gone, and
; the hello is said again until it is back.
.proc missed
    lda misses
    cmp #MISSES_MAX
    bcs @gone
    inc misses
    rts
@gone:
    lda #0
    sta greeted
    rts
.endproc

; A reply came to an exchange after the hello: carry clear if it is OK.
; With any other status the nesp32 was switched off and on, or no longer has
; KBD in use, and the hello is said again.
.proc replied
    bcs @none
    ldx #0
    stx misses
    cmp #NESP_ST_OK
    bne @refused
    clc
    rts
@refused:
    stx greeted
@none:
    jsr missed
    sec
    rts
.endproc

.proc ask_state
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_STATE
    ldy #0
    jsr nesp_call
    jsr replied
    bcs @done
    lda nesp_reply
    sta badge_state
    lda nesp_reply + 2          ; the paired one's name: none, none paired
    sta badge_paired
@done:
    rts
.endproc

; What has been typed, kept as presses of the buttons (nesp_key_queue).
.proc ask_keys
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr nesp_call
    jsr replied
    bcs @done
    lda #0
    sta key_at
@key:
    ldx key_at
    cpx nesp_reply
    bcs @done
    lda nesp_reply + 1,x
    jsr nesp_key_queue
    inc key_at
    bne @key
@done:
    rts
.endproc

; --- the badge --------------------------------------------------------------------

; The badge as the keyboard stands, and whether the nesp32 still answers.
.proc show_badge
    ldx #0
    lda misses
    cmp #MISSES_MAX
    bcc @answering
    inx
@answering:
    txa
    jmp badge_show
.endproc

; Palettes, and the screen with its attributes. Rendering is off.
.proc ppu_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda palette_data,x
    sta PPUDATA
    inx
    cpx #32
    bne @palette

    lda #>NAMETABLE
    sta PPUADDR
    lda #<NAMETABLE
    sta PPUADDR
    lda #<screen_data
    sta ptr
    lda #>screen_data
    sta ptr + 1
    ldx #4                      ; pages: 960 tiles and 64 attributes
    ldy #0
@tile:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @tile
    inc ptr + 1
    dex
    bne @tile

    lda #SPRITE_HIDDEN
@hide:
    sta oam,x
    inx
    bne @hide
    rts
.endproc

.proc nmi
    pha
    txa
    pha
    tya
    pha
    lda #0
    sta OAMADDR
    lda #>oam
    sta OAMDMA
    badge_nmi
    bit PPUSTATUS
    lda #PPUCTRL_ON
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_ON
    sta PPUMASK

    ; Controller 1 shares its strobe with the line to the nesp32, which
    ; must rest at mark: the buttons are latched by dropping it, read, and
    ; it goes back up, as in the setup ROM.
    lda #0
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #OUT0_MARK
    sta JOY1

    inc frame_count
    nesp_nmi_hook               ; an exchange cut off here gives up
    pla
    tay
    pla
    tax
    pla
    rti
.endproc

.proc irq
    rti
.endproc

; Where reset comes, here and in every program's bank, which has these
; bytes at this address too. The write is to the mapper, and its top bit
; resets it: this bank is at $C000 from the next instruction on, whichever
; one the `inc` was in.
.segment "STUB"
reset_stub:
    .assert * = RESET_STUB, error, "the build puts the stub at RESET_STUB"
    inc reset_stub              ; EE, written back: the top bit is all that counts
    jmp reset

.segment "VECTORS"
    .addr nmi
    .addr reset_stub
    .addr irq

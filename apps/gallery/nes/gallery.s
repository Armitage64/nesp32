; Gallery: pictures from Wikimedia Commons on the NES.
;
; Words typed on the search screen (keyboard.inc, NESpedia's) go to a
; nesp32 on controller port 2, whose COMMONS service finds pictures for
; them on Wikimedia Commons, keeping to its Quality and Featured pictures
; and leaving out adult ones as best a filter of words can. Each picture
; has an info page first (viewer.inc): its name, by whom, its licence. The
; nesp32 fetches its thumbnail meanwhile and makes it into the NES's tiles
; and colours; then it comes over the link and is shown whole, the screen
; split between two pattern tables of tiles.
;
; The cartridge has 8 KB of CHR RAM, which a picture fills: the font is
; kept in PRG and copied back for the search and the info page.
;
; Nametable 1 holds the header and the search screen, nametable 0 the info
; page or the picture. A frame: the NMI writes to the PPU (unless `quiet`:
; the main loop has it, with the picture off) and reads the controller.
; The main loop then makes the picture's split if one is up, acts on the
; controller and makes at most one exchange with the nesp32.

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

FRAME_IRQ_INHIBIT = $40
PPUCTRL_HEADER = $81            ; NMI on, nametable 1: the search screen
PPUMASK_ON = $1E                ; background and sprites, left column included
PALETTE   = $3F00
OUT0_MARK = $01
FONT_SIZE = $1000               ; the font's tiles: the first pattern table
; The cartridge's reset stub (nesp32's nes/cart/gen_cart.py) is at the same
; place in every program's bank: an `inc` of itself, which resets the
; mapper and puts the menu's bank at $C000, and a jump to the menu. Built by
; itself, this ROM has padding there.
CART_STUB = $FFDA
CART_STUB_FIRST = $EE           ; inc absolute

PAD_A      = $80
PAD_B      = $40
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04
PAD_LEFT   = $02
PAD_RIGHT  = $01
PAD_DIRECTIONS = PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
REPEAT_DELAY = 20               ; frames a direction is held before it repeats
REPEAT_EVERY = 5                ; and frames between repeats

STATE_SEARCH    = 0             ; the keyboard
STATE_SEARCHING = 1             ; the keyboard's screen, waiting for the nesp32
STATE_INFO      = 2             ; a picture's info page, while the nesp32 makes it
STATE_LOADING   = 3             ; the picture coming in, the screen dark
STATE_VIEW      = 4             ; the picture

; How a search stands, as COMMONS says (serial_link.inc checks them).
HOST_IDLE      = 0
HOST_NO_WIFI   = 1
HOST_SEARCHING = 2
HOST_READY     = 3
HOST_NOT_FOUND = 4
HOST_FAILED    = 5

POLL_MASK   = $07               ; ask the nesp32 how it is going every 8 frames
SILENT_MAX  = 225               ; polls with no answer before giving up: 30 s

oam = $0200                     ; sprites, copied to the PPU every NMI
SPRITE_HIDDEN = $F0

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 0                     ; no CHR ROM: 8 KB of CHR RAM
    .byte $01, $00              ; mapper 0 (NROM), vertical mirroring
    .res 8, 0

.segment "RODATA"
.include "screen.inc"
screen_data:
    .incbin "screen.bin"
font_chr:
    .incbin "chr.bin"
.assert * - font_chr = FONT_SIZE, error, "the font is a pattern table"

.segment "ZEROPAGE"
frame_count:  .res 1
served_frame: .res 1
state:        .res 1
quiet:        .res 1            ; the NMI leaves the PPU alone: the main loop has it
ctrl:         .res 1            ; PPUCTRL, written every NMI
mask:         .res 1            ; PPUMASK, likewise
pad:          .res 1            ; controller 1 as the NMI read it
pad_seen:     .res 1
pad_new:      .res 1            ; buttons that went down, and directions repeating
pad_hold:     .res 1
draw_len:     .res 1            ; tiles staged in draw_buf; 0 for none
draw_addr:    .res 2
silent:       .res 1
stall:        .res 2
tmp:          .res 2
ptr:          .res 2
on_cart:      .res 1            ; this is on nesp32's cartridge, which has a menu
chr_is_font:  .res 1            ; the first pattern table has the font, not a picture

.segment "BSS"
draw_buf:     .res 32
query:        .res QUERY_MAX
query_len:    .res 1
status_buf:   .res COLUMNS      ; a message from the nesp32

; a >= b: carry set. a = b: zero set. Both 16 bits; destroys A.
.macro cmp16 first, second
    lda first + 1
    cmp second + 1
    bne :+
    lda first
    cmp second
:
.endmacro

.macro inc16 value
    inc value
    bne :+
    inc value + 1
:
.endmacro

.include "keyboard.inc"
.include "serial_link.inc"
.include "viewer.inc"

.segment "CODE"

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
    stx APU_STATUS
    lda #OUT0_MARK              ; the line to the nesp32 rests at mark
    sta JOY1
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

@vblank2:
    bit PPUSTATUS
    bpl @vblank2

    lda CART_STUB
    cmp #CART_STUB_FIRST
    bne @alone
    inc on_cart
@alone:
    lda #$FF                    ; every button begins down, so that one held from
    sta pad_seen                ; before, as the cartridge's menu's A or Start is,
                                ; counts only once it has been let go
    jsr ppu_init                ; rendering is off; the first NMI turns it on
    jsr hide_sprites
    jsr kb_init
    lda #PPUMASK_ON
    sta mask
    lda #PPUCTRL_HEADER
    sta ctrl
    sta PPUCTRL
    ; fall through
.endproc

; Once a frame, starting right after the NMI. The loop compares with the
; last frame it served rather than waiting for a change: an NMI that cuts
; off a receive has already counted the new frame, and that frame still
; needs its turn.
;
; The tests skip the clock ahead to the next NMI whenever the CPU sits at
; main_wait with frame_count equal to served_frame, so it is a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    lda state
    cmp #STATE_VIEW
    bne @input
    jsr split                   ; first: it is tied to the raster
@input:
    jsr read_input
    lda pad_new                 ; Select: back to the cartridge's menu, from
    and #PAD_SELECT             ; every screen; by itself, nothing
    beq @dispatch
    lda on_cart
    beq @dispatch
    jmp quit
@dispatch:
    lda state
    beq @search
    cmp #STATE_SEARCHING
    beq @searching
    cmp #STATE_INFO
    beq @info
    cmp #STATE_LOADING
    beq @loading
    jsr view_frame
    jmp main_loop
@search:
    jsr kb_frame
    jmp main_loop
@searching:
    jsr searching_frame
    jmp main_loop
@info:
    jsr info_frame
    jmp main_loop
@loading:
    jsr loading_frame
    jmp main_loop

; pad_new = the buttons that went down since the last frame, any direction
; that has been held long enough to repeat, and a key typed that stands for
; buttons (link_key_next).
.proc read_input
    jsr read_pad
    jsr link_key_next
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

; A search is with the nesp32. Ask how it is going every few frames, and
; show the first picture's info page when it has found some. B gives up.
.proc searching_frame
    jsr kb_draw
    lda pad_new
    and #PAD_B
    beq @poll
    lda #STATUS_NONE
    jmp back_to_search
@poll:
    lda frame_count
    and #POLL_MASK
    bne @done
    jsr link_status
    bcc @answered
    inc silent
    lda silent
    cmp #SILENT_MAX
    bcc @done
    lda #STATUS_NO_ANSWER
    jmp back_to_search
@answered:
    ldx #0
    stx silent
    cmp #HOST_SEARCHING
    beq @done
    cmp #HOST_READY
    bne @failed
    lda #0
    sta index
    jmp to_info
@failed:
    cmp #HOST_NOT_FOUND
    bne @no_wifi
    lda #STATUS_NOT_FOUND
    jmp back_to_search
@no_wifi:
    cmp #HOST_NO_WIFI
    bne @error
    lda #STATUS_NO_WIFI
    jmp back_to_search
@error:
    cmp #HOST_FAILED
    bne @lost
    ldx #COLUMNS - 1            ; the nesp32 says what went wrong
@copy:
    lda link_text,x
    sta status_buf,x
    dex
    bpl @copy
    lda #STATUS_HOST
    jmp back_to_search
@lost:                          ; idle: the nesp32 has forgotten the search
    lda #STATUS_FAILED
    jmp back_to_search
@done:
    rts
.endproc

; Show the keyboard with status A.
.proc back_to_search
    jsr set_status
    lda #1                      ; what was typed while it was not up is dropped
    sta typed_stale
    lda #STATE_SEARCH
    sta state
    rts
.endproc

; --- the PPU -------------------------------------------------------------------

; The font, the palettes, an empty nametable 0 and the search screen in
; nametable 1. Rendering is off.
.proc ppu_init
    jsr restore_font
    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    tax
    ldy #4                      ; 1 KB of tile 0, which is blank, and palette 0
@blank:
    sta PPUDATA
    inx
    bne @blank
    dey
    bne @blank

    lda #<screen_data           ; the address is now $2400
    sta ptr
    lda #>screen_data
    sta ptr + 1
    ldx #4
@page:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @page
    inc ptr + 1
    dex
    bne @page

    lda on_cart                 ; on the cartridge, the help says Select is its menu
    beq @done
    lda #>HELP_CART_ADDR
    sta PPUADDR
    lda #<HELP_CART_ADDR
    sta PPUADDR
@help:
    lda help_cart,y
    sta PPUDATA
    iny
    cpy #HELP_CART_LENGTH
    bne @help
@done:
    rts
.endproc

; Back to the cartridge's menu, as reset would go: through its stub, with
; the NMI off first, since the stub's `inc` puts the menu's bank, and its
; NMI, under this.
.proc quit
    lda #0
    sta PPUCTRL
    sta PPUMASK
    jmp CART_STUB
.endproc

.proc nmi
    pha
    txa
    pha
    tya
    pha
    lda quiet
    bne @pad
    lda #0
    sta OAMADDR
    lda #>oam
    sta OAMDMA
    lda draw_len
    beq @scroll
    bit PPUSTATUS               ; reset the PPU's address latch
    lda draw_addr + 1
    sta PPUADDR
    lda draw_addr
    sta PPUADDR
    ldx #0
@tile:
    lda draw_buf,x
    sta PPUDATA
    inx
    cpx draw_len
    bne @tile
    lda #0
    sta draw_len
@scroll:
    bit PPUSTATUS
    lda ctrl
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda mask
    sta PPUMASK

@pad:
    ; Controller 1 shares its strobe with the line to the nesp32: OUT0 must
    ; rest at mark, so the buttons are latched by dropping it, read, and it
    ; goes back up. The nesp32 sees one low pulse of 94 cycles a frame,
    ; which its UART takes for a byte and its decoder passes over.
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
    link_nmi_hook               ; from the link include
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

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

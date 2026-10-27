; NESpedia: a Wikipedia reader for the NES.
;
; Two screens. The search screen (keyboard.inc) takes a few words from the
; controller. The reader (reader.inc) shows the article they find, 28
; columns wide, scrolled by the pixel under the header.
;
; The article is not here. A host holds it as lines of 28 characters and
; this ROM asks for them by number, one at a time. Two builds differ only in
; the host:
;
;   nespedia.nes       fake_link.inc: an article built into the ROM
;   nespedia_link.nes  serial_link.inc: an M5Stack Stick on controller port
;                      2, which fetches articles from Wikipedia (-D LINK)
;
; Nametable 1 holds the header and the search screen. Nametable 0 holds the
; article, as a ring of 30 lines; the cartridge mirrors it vertically, so
; scrolling past its last row comes back to its first. The reader shows the
; top of nametable 1 down to the end of the header and nametable 0 below
; it, changing the scroll where sprite 0 is hit (split.inc).
;
; A frame: the NMI writes to the PPU and reads the controller. The main
; loop then makes the split if the reader is up, acts on the controller,
; and asks the host for at most one line. Everything the main loop wants
; on the screen goes through one staging buffer, draw_buf, which the next
; NMI writes: up to 32 tiles in a row.

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
PPUCTRL_HEADER = $81            ; NMI on, nametable 1 at the top of the frame
PPUMASK_ON = $1E                ; background and sprites, left column included
PALETTE   = $3F00
OUT0_MARK = $01
; The cartridge's reset stub (nesp32's nes/cart/gen_cart.py) is at the same
; place in every program's bank: an `inc` of itself, which resets the
; mapper and puts the menu's bank at $C000, and a jump to the menu. Built by
; itself, this ROM has padding there. As Weather's B does.
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

STATE_SEARCH  = 0               ; the keyboard
STATE_LOADING = 1               ; the keyboard's screen, waiting for the host
STATE_OPENING = 2               ; the same, filling the ring's first lines
STATE_READER  = 3

; What the host says of itself (docs/PROTOCOL.md).
HOST_IDLE      = 0
HOST_NO_WIFI   = 1
HOST_FETCHING  = 2
HOST_READY     = 3
HOST_NOT_FOUND = 4
HOST_ERROR     = 5
HOST_STATE     = $3F            ; the state's bits of a reply's state byte
HOST_MORE      = $40            ; with ready: the article is still arriving

POLL_MASK   = $07               ; ask the host how a search is going every 8 frames
SILENT_MAX  = 225               ; polls with no answer before giving up: 30 s
STALL_MAX   = 600               ; frames with no line while opening: 10 s

oam = $0200                     ; sprites, copied to the PPU every NMI
THUMB_OAM = oam + 4             ; sprite 1
SPRITE_HIDDEN = $F0

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $01, $00              ; mapper 0 (NROM), vertical mirroring
    .res 8, 0

.segment "RODATA"
.include "screen.inc"
screen_data:
    .incbin "screen.bin"

.segment "ZEROPAGE"
frame_count:  .res 1
served_frame: .res 1
state:        .res 1
mask:         .res 1            ; PPUMASK, written every NMI
pad:          .res 1            ; controller 1 as the NMI read it
pad_seen:     .res 1
pad_new:      .res 1            ; buttons that went down, and directions repeating
pad_hold:     .res 1
draw_len:     .res 1            ; tiles staged in draw_buf; 0 for none
draw_addr:    .res 2
host_state:   .res 1
more:         .res 1            ; the article is still arriving at the host
silent:       .res 1
stall:        .res 2
tmp:          .res 2
ptr:          .res 2
on_cart:      .res 1            ; this is on nesp32's cartridge, which has a menu

.segment "BSS"
draw_buf:     .res 32
query:        .res QUERY_MAX
query_len:    .res 1
status_buf:   .res COLUMNS      ; a message from the host

; a >= b: carry set. a = b: zero set. Both 16 bits; destroys A. These use
; unnamed labels, which do not end the scope of an @ label as a named one
; would.
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

.macro dec16 value
    lda value
    bne :+
    dec value + 1
:
    dec value
.endmacro

.include "split.inc"
.include "keyboard.inc"
.include "reader.inc"
.ifdef LINK
.include "serial_link.inc"
.else
.include "fake_link.inc"
.endif

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
    lda #OUT0_MARK              ; the line to the host leaves break
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
    jsr oam_init
    jsr kb_init
    jsr link_init
    lda #PPUMASK_ON
    sta mask
    lda #PPUCTRL_HEADER
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
    cmp #STATE_READER
    bne @input
    jsr split                   ; first: it is tied to the raster
@input:
    jsr read_input
    lda pad_new                 ; Select: back to the cartridge's menu, from
    and #PAD_SELECT             ; every screen but the reader, where it is
    beq @dispatch               ; back to the search (reader_frame)
    lda state
    cmp #STATE_READER
    beq @dispatch
    lda on_cart
    beq @dispatch
    jmp quit
@dispatch:
    lda state
    beq @search
    cmp #STATE_LOADING
    beq @loading
    cmp #STATE_OPENING
    beq @opening
    jsr reader_frame
    jmp main_loop
@search:
    jsr kb_frame
    jmp main_loop
@loading:
    jsr loading_frame
    jmp main_loop
@opening:
    jsr opening_frame
    jmp main_loop

; pad_new = the buttons that went down since the last frame, and any
; direction that has been held long enough to repeat.
.proc read_input
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

; A search is with the host. Ask how it is going every few frames, and
; open the article when it is ready. B gives up.
.proc loading_frame
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
    sta host_state
    ldx #0
    stx silent
    cmp #HOST_FETCHING
    beq @done
    cmp #HOST_READY
    bne @failed
    jmp reader_open
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
    cmp #HOST_ERROR
    bne @lost
    ldx #COLUMNS - 1            ; the host says what went wrong
@copy:
    lda link_text,x
    sta status_buf,x
    dex
    bpl @copy
    lda #STATUS_HOST
    jmp back_to_search
@lost:                          ; idle: the host has forgotten the search
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
    lda #SPRITE_HIDDEN
    sta THUMB_OAM
    rts
.endproc

; The article is ready and the ring is filling. The reader takes the screen
; once every line it will show is in.
.proc opening_frame
    jsr kb_draw
    lda draw_len                ; the keyboard staged something: it goes first
    bne @waiting
    jsr reader_fetch
    bcs @waiting
    lda host_state
    cmp #HOST_READY
    bne lost_article
    lda #0
    sta stall
    sta stall + 1
    lda hi + 1
    bne @open
    lda hi
    cmp #WINDOW_ROWS + 1
    bcc @done
@open:
    lda #STATE_READER
    sta state
@done:
    rts
@waiting:
    inc16 stall
    lda stall + 1
    cmp #>STALL_MAX
    bcc @done
    lda stall
    cmp #<STALL_MAX
    bcc @done
    lda #STATUS_NO_ANSWER
    jmp back_to_search
.endproc

; The host answers, but no longer holds the article: it was switched off
; and on, perhaps. There is nothing to read.
.proc lost_article
    lda #STATUS_LOST
    jmp back_to_search
.endproc

; --- the PPU -------------------------------------------------------------------

; Palettes, an empty nametable 0 and the search screen in nametable 1.
; Rendering is off.
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
; NMI, under this. The menu says nothing to the nesp32; the next program's
; hello is what tells it this one has gone.
.proc quit
    lda #0
    sta PPUCTRL
    sta PPUMASK
    jmp CART_STUB
.endproc

; Sprite 0 on its pixel of the name, and every other sprite below
; the screen.
.proc oam_init
    ldx #0
    lda #SPRITE_HIDDEN
@hide:
    sta oam,x
    inx
    bne @hide
    lda #SPRITE0_Y
    sta oam
    lda #TILE_SPRITE0
    sta oam + 1
    lda #0
    sta oam + 2
    lda #SPRITE0_X
    sta oam + 3
    lda #TILE_THUMB
    sta THUMB_OAM + 1
    lda #0
    sta THUMB_OAM + 2
    lda #THUMB_X
    sta THUMB_OAM + 3
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
    ; The frame starts at the top of nametable 1, the header. The reader's
    ; split moves to the article below it.
    bit PPUSTATUS
    lda #PPUCTRL_HEADER
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda mask
    sta PPUMASK

    ; Controller 1 shares its strobe with the line to the host: OUT0 must
    ; rest at mark, so the buttons are latched by dropping it, read, and it
    ; goes back up. The host sees one low pulse of 94 cycles a frame, which
    ; its UART takes for a byte and its decoder passes over.
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

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

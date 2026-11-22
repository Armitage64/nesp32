; The pictures: the info page before each, the picture coming in, and the
; picture shown.
;
; The info page is nametable 0, in the font: which picture this is, its
; words from the nesp32 (its name, by whom, its licence), how it is going,
; and the buttons. While it is up the nesp32 fetches the picture and makes
; it into tiles; then the screen goes dark and the picture comes in, all of
; it written to the PPU as it arrives: 8 KB of tiles, both pattern tables,
; its nametable in nametable 0, and its palette. That is 145 exchanges of
; 64 bytes, one a frame, with the picture off and the NMI on (nesp.inc's
; exchanges need the NMI for their timeout), the NMI touching nothing of
; the PPU's meanwhile (`quiet`).
;
; A picture has 511 tiles of its own: the top 15 rows of tiles are drawn
; from the first pattern table, and the bottom 15 from the second. The
; split (below) changes table between them, at sprite 0's hit. Sprite 0 is
; one pixel of the picture's, which the nesp32 put behind a pixel of the
; background on the top half's last line, in the backdrop's colour.
;
;   Left, Right   the picture before or after this one
;   B             back to the search
;   Select        on nesp32's cartridge, back to its menu (gallery.s)

PHOTO_IDLE     = 0              ; COMMONS OPEN's states (serial_link.inc checks them)
PHOTO_NO_WIFI  = 1
PHOTO_FETCHING = 2
PHOTO_READY    = 3
PHOTO_FAILED   = 4
PICTURE_SIZE   = NESP_COMMONS_SIZE
PICTURE_NAMES  = NESP_COMMONS_NAMES
PICTURE_PALETTE = NESP_COMMONS_PALETTE
.assert NESP_COMMONS_CHR = 0, error, "a picture's tiles are where the PPU has them"
.assert NESP_COMMONS_PALETTE = NESP_COMMONS_NAMES + $400, error, "the palette is after the nametable"
.assert NESP_COMMONS_SPRITE = NESP_COMMONS_PALETTE + 32, error, "sprite 0 is after the palette"
.assert NESP_COMMONS_DELAY = NESP_COMMONS_SPRITE + 4, error, "the delay is after sprite 0"
.assert NESP_COMMONS_PALETTE .mod NESP_COMMONS_CHUNK = 0, error, "the tail comes by itself"
.assert NESP_COMMONS_SIZE - NESP_COMMONS_PALETTE <= NESP_COMMONS_CHUNK, error, "the tail comes in one"
.assert NESP_COMMONS_SPLIT_ROW = 15, error, "the split is half way down"
PPUCTRL_PICTURE = $80           ; NMI on, nametable 0, both halves' sprites and the top's tiles from $0000
PPUCTRL_BOTTOM  = $90           ; and the bottom's from $1000
PPUMASK_PICTURE = $1E
SPLIT_TRIES = 6                 ; loops of 256 looks for the hit: past its line, then no split
LOAD_STALL_MAX = 300            ; frames with no bytes before the nesp32 is given up on: 5 s
INFO_FIRST_CAPTION = 0

.segment "ZEROPAGE"
index:        .res 1            ; the picture, of `count`
count:        .res 1
load_at:      .res 2            ; the next byte of the picture wanted
split_delay:  .res 1            ; the picture's: loops from the hit to the write
caption_next: .res 1            ; the info page's next line to ask for; CAPTION_LINES when all are in
info_done:    .res 1            ; the info page has said the picture failed: no more asking

.segment "CODE"

; Rendering off and the NMI hands off the PPU: from here the main loop may
; write to it whenever it likes. The NMI is kept on.
.proc go_dark
    lda #1
    sta quiet
    lda #0
    sta mask
    sta PPUMASK
    rts
.endproc

; The font back in the first pattern table and the palettes back, after a
; picture. Rendering is off.
.proc restore_font
    lda chr_is_font
    bne @palette
    bit PPUSTATUS
    lda #0
    sta PPUADDR
    sta PPUADDR
    lda #<font_chr
    sta ptr
    lda #>font_chr
    sta ptr + 1
    ldx #>FONT_SIZE
    ldy #0
@copy:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @copy
    inc ptr + 1
    dex
    bne @copy
    inc chr_is_font
@palette:
    bit PPUSTATUS
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@colour:
    lda palette_data,x
    sta PPUDATA
    inx
    cpx #32
    bne @colour
    rts
.endproc

; Leave the pictures for the search screen, with status A.
.proc to_search
    pha
    jsr go_dark
    jsr restore_font
    jsr hide_sprites
    lda #PPUCTRL_HEADER
    sta ctrl
    lda #PPUMASK_ON
    sta mask
    lda #0
    sta quiet
    pla
    jmp back_to_search
.endproc

; Show the info page for picture `index`, and start the nesp32 on it.
.proc to_info
    jsr go_dark
    jsr restore_font
    jsr hide_sprites
    ; Nametable 0 blank, palette 0.
    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
    ldy #4
@blank:
    sta PPUDATA
    inx
    bne @blank
    dey
    bne @blank
    ; Its words that do not change.
    lda #<info_texts
    ldx #>info_texts
    jsr put_texts
    lda #<info_help
    ldx #>info_help
    ldy on_cart
    beq @help
    lda #<info_help_cart
    ldx #>info_help_cart
@help:
    jsr put_texts
    ; Which picture, of how many: two digits each.
    bit PPUSTATUS
    lda #>(COUNT_ADDR + COUNT_INDEX)
    sta PPUADDR
    lda #<(COUNT_ADDR + COUNT_INDEX)
    sta PPUADDR
    ldx index
    inx
    txa
    jsr put_number
    bit PPUSTATUS
    lda #>(COUNT_ADDR + COUNT_TOTAL)
    sta PPUADDR
    lda #<(COUNT_ADDR + COUNT_TOTAL)
    sta PPUADDR
    lda count
    jsr put_number
    lda #STATUS_LOADING
    jsr put_status
    inc open_id                 ; a new showing: the nesp32 starts on it afresh
    lda #INFO_FIRST_CAPTION
    sta caption_next
    lda #0
    sta info_done
    sta silent
    sta draw_len
    lda #STATE_INFO
    sta state
    lda #PPUCTRL_PICTURE
    sta ctrl
    lda #PPUMASK_ON
    sta mask
    lda #0
    sta quiet
    rts
.endproc

; The texts at A (low) and X (high): an address, a length and the tiles,
; until an address of 0. Rendering is off.
.proc put_texts
    sta ptr
    stx ptr + 1
@text:
    ldy #1
    lda (ptr),y
    beq @done
    bit PPUSTATUS
    sta PPUADDR
    dey
    lda (ptr),y
    sta PPUADDR
    ldy #2
    lda (ptr),y
    clc
    adc #3
    sta tmp
    iny
@tile:
    lda (ptr),y
    sta PPUDATA
    iny
    cpy tmp
    bne @tile
    tya
    clc
    adc ptr
    sta ptr
    bcc @text
    inc ptr + 1
    bne @text
@done:
    rts
.endproc

; A, 0 to 99, as two digits at the PPU's address, in the second colour.
.proc put_number
    ldx #'0' | ALT
@tens:
    cmp #10
    bcc @units
    sbc #10
    inx
    bne @tens
@units:
    stx PPUDATA
    ora #'0' | ALT
    sta PPUDATA
    rts
.endproc

; Status A on the info page, now: rendering is off.
.proc put_status
    jsr status_line
    bit PPUSTATUS
    lda #>INFO_STATUS_ADDR
    sta PPUADDR
    lda #<INFO_STATUS_ADDR
    sta PPUADDR
    ldx #0
@tile:
    lda draw_buf,x
    sta PPUDATA
    inx
    cpx #COLUMNS
    bne @tile
    rts
.endproc

; Status A on the info page, staged for the next NMI.
.proc stage_status
    jsr status_line
    lda #<INFO_STATUS_ADDR
    sta draw_addr
    lda #>INFO_STATUS_ADDR
    sta draw_addr + 1
    lda #COLUMNS
    sta draw_len
    rts
.endproc

; Status A's text (keyboard.inc's, or status_buf's for STATUS_HOST) into
; draw_buf.
.proc status_line
    tay
    ldx #0
    cpy #STATUS_HOST
    beq @host
@fixed:
    lda status_texts,y
    sta draw_buf,x
    iny
    inx
    cpx #COLUMNS
    bne @fixed
    rts
@host:
    lda status_buf,x
    sta draw_buf,x
    inx
    cpx #COLUMNS
    bne @host
    rts
.endproc

.proc hide_sprites
    ldx #0
    lda #SPRITE_HIDDEN
@hide:
    sta oam,x
    inx
    bne @hide
    rts
.endproc

; The picture before or after this one, if there is one: carry set if
; Left or Right took us to it.
.proc browse
    lda pad_new
    and #PAD_LEFT
    beq @right
    lda index
    beq @none
    dec index
    jsr to_info
    sec
    rts
@right:
    lda pad_new
    and #PAD_RIGHT
    beq @none
    ldx index
    inx
    cpx count
    bcs @none
    stx index
    jsr to_info
    sec
    rts
@none:
    clc
    rts
.endproc

; What is typed on the Bluetooth keyboard while the pictures are up, as
; the buttons it stands for: the arrows, Escape for B and Ctrl and Escape
; for Select (nesp.inc's nesp_key_pad).
.proc keys_as_buttons
    jsr link_keys
    bcs @done
    sta typed_count
    ldx #0
@key:
    cpx typed_count
    bcs @done
    stx typed_at
    lda link_typed,x
    jsr link_key_queue
    ldx typed_at
    inx
    bne @key
@done:
    rts
.endproc

; A frame of the info page: B is the search, Left and Right another
; picture; otherwise the next line of words, and every few frames, once
; they are in, how the picture is going.
.proc info_frame
    lda pad_new
    and #PAD_B
    beq @browse
    lda #STATUS_NONE
    jmp to_search
@browse:
    jsr browse
    bcc @ask
    rts
@ask:
    lda draw_len                ; last frame's line not drawn yet
    bne @done
    ldy caption_next
    cpy #CAPTION_LINES
    bcs @open
    jsr link_caption
    bcs @done
    cmp #HOST_IDLE
    beq @lost
    inc caption_next
@done:
    rts
@open:
    lda info_done
    bne @keys
    lda frame_count
    and #POLL_MASK
    bne @keys
    jsr link_open
    bcc @answered
    inc silent
    lda silent
    cmp #SILENT_MAX
    bcc @done
    lda #STATUS_NO_ANSWER
    bne @give_up
@answered:
    ldx #0
    stx silent
    cmp #PHOTO_FETCHING
    beq @done
    cmp #PHOTO_READY
    bne @failed
    jmp to_loading
@failed:
    cmp #PHOTO_FAILED
    bne @no_wifi
    ldx #COLUMNS - 1            ; the nesp32 says what went wrong
@copy:
    lda link_text,x
    sta status_buf,x
    dex
    bpl @copy
    lda #STATUS_HOST
    bne @give_up
@no_wifi:
    cmp #PHOTO_NO_WIFI
    bne @lost
    lda #STATUS_NO_WIFI
    bne @give_up
@lost:                          ; the nesp32 no longer has the search
    lda #STATUS_LOST
@give_up:
    inc info_done
    jmp stage_status
@keys:
    jmp keys_as_buttons
.endproc

; The picture is ready: dark, and in it comes.
.proc to_loading
    jsr go_dark
    lda #0
    sta load_at
    sta load_at + 1
    sta stall
    sta stall + 1
    sta chr_is_font             ; from the first byte the font is gone
    lda #STATE_LOADING
    sta state
    rts
.endproc

; A frame of the picture coming in: one exchange, its bytes straight to
; the PPU. B gives up.
.proc loading_frame
    lda pad_new
    and #PAD_B
    beq @ask
    lda #STATUS_NONE
    jmp to_search
@ask:
    jsr link_data
    bcs @stalled
    tax
    bne @bytes
    lda #STATUS_LOST            ; it is no longer ready: it says why on its page
    jsr to_info_with
    rts
@stalled:
    inc16 stall
    lda stall + 1
    cmp #>LOAD_STALL_MAX
    bcc @done
    lda stall
    cmp #<LOAD_STALL_MAX
    bcc @done
    lda #STATUS_NO_ANSWER
    jmp to_info_with
@bytes:
    stx tmp                     ; how many
    lda #0
    sta stall
    sta stall + 1
    lda load_at + 1
    cmp #>PICTURE_PALETTE
    bcs @tail
    bit PPUSTATUS               ; tiles or names: where the PPU has them
    sta PPUADDR
    lda load_at
    sta PPUADDR
    ldx #0
@put:
    lda DATA_BYTES,x
    sta PPUDATA
    inx
    cpx tmp
    bne @put
    lda tmp
    clc
    adc load_at
    sta load_at
    bcc @done
    inc load_at + 1
@done:
    rts
@tail:                          ; the palette, sprite 0 and the delay: the last of it
    bit PPUSTATUS
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@colour:
    lda DATA_BYTES,x
    sta PPUDATA
    inx
    cpx #32
    bne @colour
    ldx #3
@sprite:
    lda DATA_BYTES + NESP_COMMONS_SPRITE - NESP_COMMONS_PALETTE,x
    sta oam,x
    dex
    bpl @sprite
    lda DATA_BYTES + NESP_COMMONS_DELAY - NESP_COMMONS_PALETTE
    sta split_delay
    ; Shown from the next NMI on.
    lda #PPUCTRL_PICTURE
    sta ctrl
    lda #PPUMASK_PICTURE
    sta mask
    lda #STATE_VIEW
    sta state
    lda #0
    sta quiet
    rts
.endproc

; Back to the info page, with status A on it in place of LOADING.
.proc to_info_with
    pha
    jsr to_info
    pla
    inc info_done               ; nothing more is asked for this showing
    jmp stage_status
.endproc

; A frame of the picture: Left and Right another, B the search.
.proc view_frame
    lda pad_new
    and #PAD_B
    beq @browse
    lda #STATUS_NONE
    jmp to_search
@browse:
    jsr browse
    bcs @done
    jmp keys_as_buttons
@done:
    rts
.endproc

.segment "RXTX"

; The split: the bottom half's tiles from the second pattern table. The
; NMI has left PPUCTRL with the first. Sprite 0's hit comes on the top
; half's last line, where the nesp32 put it: this waits for the last
; frame's hit to clear at the pre-render line, then for this frame's, then
; split_delay loops of 5 cycles, and writes PPUCTRL. From the look that
; sees the hit to the write is 15 cycles with no delay and 13 + 5 a loop
; with some, which the nesp32 chose to land the write in the hblank, after
; the line's last tile is fetched and before the next line's first
; (COMMONS's tests check it on both consoles). Both waits give up within a
; frame: with no hit the picture's bottom half is wrong for that frame.
.proc split
    ldy #SPLIT_TRIES
    ldx #0
@clear:
    bit PPUSTATUS
    bvc @wait
    dex
    bne @clear
    dey
    bne @clear
    rts
@wait:
    ldy #SPLIT_TRIES
@hit:
    bit PPUSTATUS               ; the look: 11 cycles to the next
    bvs @found
    dex
    bne @hit
    dey
    bne @hit
    rts
@found:
    ldx split_delay
    beq @write
@delay:
    dex
    bne @delay
@write:
    lda #PPUCTRL_BOTTOM
    sta PPUCTRL
    rts
.endproc
.assert >split = >(* - 1), error, "split crosses a page"

.segment "CODE"

; The search screen: a field of up to QUERY_MAX characters and a keyboard
; to fill it from, in nametable 1 under the header.
;
;   D-pad    move over the keys; held, it repeats
;   A        type the key
;   B        delete the last character
;   Select   small letters / capitals
;   Start    search
;
; The keys are KEY_ROWS rows of KEY_COLUMNS, and a space bar under them
; that takes the whole of the last row. They are drawn in the font's second
; colour, and the one the cursor is on pulses from white through the
; logo's blues: its square of the screen has a palette of its own, and one
; colour of that palette is changed every few frames.
;
; Nothing here writes to the PPU. kb_draw stages one thing a frame in
; draw_buf, in this order: the cursor's old key, its new key, the field, a
; row of keys whose case changed, the status line, the pulse's next colour.

DIRTY_FIELD  = $01
DIRTY_STATUS = $02
DIRTY_ROW    = $04              ; << row, for the rows of letters: 1 to 3
DIRTY_LETTERS = DIRTY_ROW << 1 | DIRTY_ROW << 2 | DIRTY_ROW << 3
ROW_TILES = KEY_STEP * (KEY_COLUMNS - 1) + 1
NO_KEY = $FF
PULSE_MASK = $07                ; frames between the pulse's colours, less one

.segment "ZEROPAGE"
cur_row:    .res 1              ; KEY_ROWS is the space bar
cur_col:    .res 1
shown_row:  .res 1              ; the key drawn in white; NO_KEY for none
shown_col:  .res 1
lower:      .res 1              ; $20 while the letters are small
kb_dirty:   .res 1
status_id:  .res 1
key_row:    .res 1              ; arguments of key_char and draw_key
key_col:    .res 1
key_alt:    .res 1
pulse:      .res 1              ; where the cursor's colour is in its round

.segment "RODATA"

; The status line's texts, COLUMNS wide, centered. A status is its offset
; into them.
.macro status_text text
    .res (COLUMNS - .strlen(text)) / 2, ' '
    .byte text
    .res COLUMNS - .strlen(text) - (COLUMNS - .strlen(text)) / 2, ' '
.endmacro

status_texts:
STATUS_NONE = * - status_texts
    .res COLUMNS, ' '
STATUS_SEARCHING = * - status_texts
    status_text "SEARCHING..."
STATUS_LOADING = * - status_texts
    status_text "LOADING..."
STATUS_NOT_FOUND = * - status_texts
    status_text "NO ARTICLE FOUND"
STATUS_NO_WIFI = * - status_texts
    status_text "THE NESP32 HAS NO WI-FI"
STATUS_NO_ANSWER = * - status_texts
    status_text "NO ANSWER FROM THE NESP32"
STATUS_FAILED = * - status_texts
    status_text "THE SEARCH FAILED"
STATUS_LOST = * - status_texts
    status_text "THE NESP32 LOST THE ARTICLE"
STATUS_HOST = $FF               ; the text is in status_buf
.assert * - status_texts < 256, error, "too many status texts"

row_first: .byte 0, KEY_COLUMNS, 2 * KEY_COLUMNS, 3 * KEY_COLUMNS

.segment "CODE"

; The screen in nametable 1 already shows the default search and capitals.
.proc kb_init
    ldx #DEFAULT_LENGTH - 1
@copy:
    lda default_query,x
    sta query,x
    dex
    bpl @copy
    lda #DEFAULT_LENGTH
    sta query_len
    lda #1                      ; on the Q
    sta cur_row
    lda #NO_KEY
    sta shown_row
    rts
.endproc

; Show status A on the status line.
.proc set_status
    sta status_id
    lda kb_dirty
    ora #DIRTY_STATUS
    sta kb_dirty
    rts
.endproc

.proc kb_frame
    lda pad_new
    and #PAD_UP
    beq @down
    lda cur_row
    beq @down
    dec cur_row
@down:
    lda pad_new
    and #PAD_DOWN
    beq @left
    lda cur_row
    cmp #KEY_ROWS
    bcs @left
    inc cur_row
@left:
    lda pad_new
    and #PAD_LEFT
    beq @right
    dec cur_col
    bpl @right
    lda #KEY_COLUMNS - 1
    sta cur_col
@right:
    lda pad_new
    and #PAD_RIGHT
    beq @type
    inc cur_col
    lda cur_col
    cmp #KEY_COLUMNS
    bcc @type
    lda #0
    sta cur_col
@type:
    lda pad_new
    and #PAD_A
    beq @delete
    jsr type_key
@delete:
    lda pad_new
    and #PAD_B
    beq @case
    lda query_len
    beq @case
    dec query_len
    lda kb_dirty
    ora #DIRTY_FIELD
    sta kb_dirty
@case:
    lda pad_new
    and #PAD_SELECT
    beq @search
    lda lower
    eor #$20
    sta lower
    lda kb_dirty
    ora #DIRTY_LETTERS
    sta kb_dirty
@search:
    lda pad_new
    and #PAD_START
    beq @draw
    lda query_len
    beq @draw
    jsr link_search
    lda #0
    sta silent
    lda #STATUS_SEARCHING
    jsr set_status
    lda #STATE_LOADING
    sta state
@draw:
    jmp kb_draw
.endproc

; Add the cursor's key to the search, if there is room. A search does not
; begin with a space.
.proc type_key
    ldx query_len
    cpx #QUERY_MAX
    bcs @done
    lda cur_row
    sta key_row
    lda cur_col
    sta key_col
    jsr key_char
    cmp #' '
    bne @store
    cpx #0
    beq @done
@store:
    sta query,x
    inc query_len
    lda kb_dirty
    ora #DIRTY_FIELD
    sta kb_dirty
@done:
    rts
.endproc

; A = the character of key (key_row, key_col), in the case now showing.
; Preserves X.
.proc key_char
    ldy key_row
    cpy #KEY_ROWS
    bcc @key
    lda #' '
    rts
@key:
    lda row_first,y
    clc
    adc key_col
    tay
    lda key_chars,y
    cmp #'A'
    bcc @done
    cmp #'Z' + 1
    bcs @done
    ora lower
@done:
    rts
.endproc

; Stage the one thing that most needs drawing, if anything does.
.proc kb_draw
    lda shown_row
    cmp #NO_KEY
    beq @cursor_off
    cmp cur_row
    bne @unlight
    lda shown_col
    cmp cur_col
    beq @field
@unlight:                       ; the key the cursor left
    lda shown_row
    sta key_row
    lda shown_col
    sta key_col
    lda #NO_KEY
    sta shown_row
    lda #ALT
    jmp draw_key
@cursor_off:                    ; the key it is on
    lda kb_dirty                ; but rows about to be drawn again go first
    and #DIRTY_LETTERS
    bne @field
    lda cur_row
    sta key_row
    sta shown_row
    lda cur_col
    sta key_col
    sta shown_col
    lda #0
    jmp draw_key

@field:
    lda kb_dirty
    and #DIRTY_FIELD
    beq @rows
    eor kb_dirty
    sta kb_dirty
    ldx #0
@text:
    cpx query_len
    beq @cursor
    lda query,x
    sta draw_buf,x
    inx
    bne @text
@cursor:
    lda #CURSOR_CHAR
@pad:
    cpx #QUERY_MAX
    beq @field_out
    sta draw_buf,x
    lda #' '
    inx
    bne @pad
@field_out:
    lda #<FIELD_ADDR
    sta draw_addr
    lda #>FIELD_ADDR
    sta draw_addr + 1
    stx draw_len
    rts

@rows:
    lda kb_dirty
    and #DIRTY_LETTERS
    beq @status
    ldy #1
    lda #DIRTY_ROW << 1
@find:
    bit kb_dirty
    bne @row
    asl a
    iny
    bne @find
@row:
    eor kb_dirty
    sta kb_dirty
    sty key_row
    cpy shown_row               ; the cursor's key, if it is in this row,
    bne @keys                   ; is drawn again after
    lda #NO_KEY
    sta shown_row
@keys:
    lda #0
    sta key_col
    tax
@key:
    jsr key_char
    ora #ALT
    sta draw_buf,x
    inx
    cpx #ROW_TILES
    beq @row_out
    lda #' '
    sta draw_buf,x
    inx
    inc key_col
    bne @key
@row_out:
    ldy key_row
    lda key_row_lo,y
    sta draw_addr
    lda key_row_hi,y
    sta draw_addr + 1
    stx draw_len
    rts

@status:
    lda kb_dirty
    and #DIRTY_STATUS
    beq @pulse
    eor kb_dirty
    sta kb_dirty
    ldx #0
    ldy status_id
    cpy #STATUS_HOST
    beq @host
@fixed:
    lda status_texts,y
    sta draw_buf,x
    iny
    inx
    cpx #COLUMNS
    bne @fixed
    beq @status_out
@host:
    lda status_buf,x
    sta draw_buf,x
    inx
    cpx #COLUMNS
    bne @host
@status_out:
    lda #<STATUS_ADDR
    sta draw_addr
    lda #>STATUS_ADDR
    sta draw_addr + 1
    stx draw_len
@done:
    rts

@pulse:                         ; nothing else to draw: the cursor's colour
    lda state                   ; but not while an article's lines want
    cmp #STATE_OPENING          ; the staging buffer
    bcs @done
    lda frame_count
    and #PULSE_MASK
    bne @done
    ldx pulse
    inx
    cpx #PULSE_STEPS
    bcc @color
    ldx #0
@color:
    stx pulse
    lda pulse_colors,x
    sta draw_buf
    lda #<PULSE_ADDR
    sta draw_addr
    lda #>PULSE_ADDR
    sta draw_addr + 1
    lda #1
    sta draw_len
    rts
.endproc

; Stage key (key_row, key_col) lit (A = 0) or unlit (A = ALT). A key is
; lit by its palette: the square of 2 x 2 tiles it sits in takes the
; cursor's palette, in which the keys' colour pulses. One attribute byte
; covers four squares, but only one key is ever lit, so the byte is that
; key's bits or nothing.
.proc draw_key
    sta key_alt
    lda #KEY_ATTR_HI
    sta draw_addr + 1
    ldy key_row
    cpy #KEY_ROWS
    bcs @space
    lda row_first,y
    clc
    adc key_col
    tay
    lda key_attr_lo,y
    sta draw_addr
    lda #0
    ldx key_alt
    bne @one
    lda key_attr_on,y
@one:
    sta draw_buf
    lda #1
    sta draw_len
    rts
@space:
    lda #<SPACE_ATTR
    sta draw_addr
    ldx #SPACE_ATTRS - 1
@square:
    lda #0
    ldy key_alt
    bne @put
    lda space_attr_on,x
@put:
    sta draw_buf,x
    dex
    bpl @square
    lda #SPACE_ATTRS
    sta draw_len
    rts
.endproc
.assert >SPACE_ATTR = KEY_ATTR_HI, error, "the space bar's attributes"

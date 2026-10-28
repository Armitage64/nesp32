; The search screen: a field of up to QUERY_MAX characters and a keyboard
; to fill it from, in nametable 1 under the header.
;
;   D-pad    move over the keys; held, it repeats
;   A        type the key; on the shift key, small letters / capitals
;   B        delete the last character
;   Start    search
;   Select   on nesp32's cartridge, back to its menu
;
; and on a Bluetooth keyboard paired with the nesp32, through the link
; (link_keys), typing as it would anywhere: a letter in the case it is
; typed in, Backspace, Enter to search, and Escape, on the cartridge, back
; to its menu. What this keyboard has no key for is not typed.
;
; The field begins empty. Once the link knows there is no keyboard to type
; with, it puts DEFAULT_QUERY in it (kb_default), for Start to search; with
; one paired it stays empty (kb_paired), so nothing is seen typed and taken
; back.
;
; The keys are KEY_ROWS rows of KEY_COLUMNS, and under them a last row of
; two: the shift key, under the first column, and the space bar. On that
; row the cursor keeps its column, and the first is the shift key; Left
; and Right go from the one to the other. They are drawn in the font's second
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
; The Bluetooth keyboard's keys that are not characters, as KBD sends them
; (serial_link.inc checks them against nesp32's numbers).
KEY_BACKSPACE = $08
KEY_ENTER     = $0A
KEY_UP        = $11
KEY_DOWN      = $12
KEY_LEFT      = $13
KEY_RIGHT     = $14
KEY_PAGE_UP   = $15
KEY_PAGE_DOWN = $16
KEY_START     = $17             ; Ctrl and Enter
KEY_SELECT    = $18             ; Ctrl and Escape
KEY_ESCAPE    = $1B
SHIFT_COL = 0
PULSE_MASK = $07                ; frames between the pulse's colours, less one

.segment "ZEROPAGE"
cur_row:    .res 1              ; KEY_ROWS is the shift key and the space bar
cur_col:    .res 1              ; on that row, SHIFT_COL is the shift key
shown_row:  .res 1              ; the key drawn in white; NO_KEY for none
shown_col:  .res 1
lower:      .res 1              ; $20 while the letters are small
kb_dirty:   .res 1
status_id:  .res 1
key_row:    .res 1              ; arguments of key_char and draw_key
key_col:    .res 1
key_alt:    .res 1
pulse:      .res 1              ; where the cursor's colour is in its round
typed_count: .res 1             ; kb_typed's
typed_at:   .res 1
typed_stale: .res 1             ; the next of what was typed is from before this screen
untouched:  .res 1              ; the field is still as it began, empty

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

; The screen in nametable 1 already shows the empty field and capitals.
.proc kb_init
    lda #0
    sta query_len
    lda #1
    sta untouched
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
    jsr kb_typed
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
    lda cur_row
    cmp #KEY_ROWS
    bcc @key_left
    lda pad_new                 ; the last row: Left or Right is the other key
    and #PAD_LEFT | PAD_RIGHT
    beq @type
    ldx #SHIFT_COL
    cpx cur_col
    bne @other
    inx
@other:
    stx cur_col
    jmp @type
@key_left:
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
    jsr delete_char
@case:                          ; Select, the cartridge's menu, is the main loop's
@search:
    lda pad_new
    and #PAD_START
    beq @draw
    jsr search
@draw:
    jmp kb_draw
.endproc

; Search for the field's words, if it has any.
.proc search
    lda #0
    sta untouched
    lda query_len
    beq @done
    jsr link_search
    lda #0
    sta silent
    lda #STATUS_SEARCHING
    jsr set_status
    lda #STATE_LOADING
    sta state
@done:
    rts
.endproc

; Take the field's last character back.
.proc delete_char
    lda #0
    sta untouched
    lda query_len
    beq @done
    dec query_len
    lda kb_dirty
    ora #DIRTY_FIELD
    sta kb_dirty
@done:
    rts
.endproc

; What was typed on the Bluetooth keyboard, a character at a time, until
; a search begins. What comes first after the screen is back from a search
; was typed while it was not up, and is dropped: an Enter in it would search
; at once.
.proc kb_typed
    jsr link_keys
    bcs @done
    ldx typed_stale
    beq @fresh
    ldx #0
    stx typed_stale
    rts
@fresh:
    sta typed_count
    ldx #0
@char:
    cpx typed_count
    bcs @done
    lda state
    cmp #STATE_SEARCH           ; Enter has begun a search: the rest is dropped
    bne @done
    lda link_typed,x
    stx typed_at
    jsr type_typed
    ldx typed_at
    inx
    bne @char
@done:
    rts
.endproc

; There is no keyboard to type with: the field is DEFAULT_QUERY, if
; nothing has been done to it yet.
.proc kb_default
    lda untouched
    beq @done
    lda state
    cmp #STATE_SEARCH
    bne @done
    ldx #DEFAULT_LENGTH - 1
@copy:
    lda default_query,x
    sta query,x
    dex
    bpl @copy
    lda #DEFAULT_LENGTH
    sta query_len
    lda #0
    sta untouched
    lda kb_dirty
    ora #DIRTY_FIELD
    sta kb_dirty
@done:
    rts
.endproc

; The nesp32 has a keyboard paired: the field stays empty, for it.
.proc kb_paired
    lda #0
    sta untouched
    rts
.endproc

; One character from the Bluetooth keyboard, A.
.proc type_typed
    cmp #KEY_BACKSPACE          ; Backspace, and Escape, which is B
    beq @delete
    cmp #KEY_ESCAPE
    bne @enter
@delete:
    jmp delete_char
@enter:
    cmp #KEY_ENTER              ; Enter searches, here, where A types, as
    beq @search                 ; Ctrl and Enter, which is Start, does
    cmp #KEY_START
    bne @control
@search:
    jmp search
@control:
    cmp #' '                    ; the arrows and Select: buttons, a frame on,
    bcs @letter                 ; which for them is no matter
    jmp link_key_queue
@letter:
    cmp #' '
    beq type_char
    tax
    and #<~$20                  ; a letter in either case
    cmp #'A'
    bcc @other
    cmp #'Z' + 1
    bcs @other
    txa
    jmp type_char
@other:                         ; a key of the keyboard on the screen, or none
    txa
    ldx #KEY_ROWS * KEY_COLUMNS - 1
@key:
    cmp key_chars,x
    beq type_char
    dex
    bpl @key
    rts
.endproc

; Add the cursor's key to the search (type_char). The shift key changes
; the letters' case.
.proc type_key
    lda cur_row
    cmp #KEY_ROWS
    bcc @key
    lda cur_col
    cmp #SHIFT_COL
    bne @key
    lda lower
    eor #$20
    sta lower
    lda kb_dirty
    ora #DIRTY_LETTERS
    sta kb_dirty
    rts
@key:
    lda cur_row
    sta key_row
    lda cur_col
    sta key_col
    jsr key_char
    ; fall through
.endproc

; Add character A to the search, if there is room. A search does not
; begin with a space.
.proc type_char
    ldx query_len
    cpx #QUERY_MAX
    bcs @done
    cmp #' '
    bne @store
    cpx #0
    beq @done
@store:
    sta query,x
    inc query_len
    ldx #0
    stx untouched
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

; Stage key (key_row, key_col) lit (A = 0) or unlit (A = ALT); on the last
; row, key_col SHIFT_COL is the shift key and any other the space bar. A key is
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
    lda key_col
    cmp #SHIFT_COL
    bne @bar
    lda #<SHIFT_ATTR
    sta draw_addr
    lda #0
    ldx key_alt
    bne @one
    lda #SHIFT_ATTR_ON
    bne @one
@bar:
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
.assert >SHIFT_ATTR = KEY_ATTR_HI, error, "the shift key's attribute"

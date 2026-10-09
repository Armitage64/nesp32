; The keyboard: a network's name or its password, typed on the controller.
;
;   D-pad    move over the keys; held, it repeats
;   A        type the key
;   B        delete the last character; with none left, go back
;   Select   the next of the three sets of keys: small letters, capitals,
;            and the signs that are on neither
;   Start    done
;
; It is nes-wiki's (nes/keyboard.inc), with every printable character, a
; field longer than the screen is wide, and a sprite under the cursor's key
; in place of a palette. A password may be 63 characters; the field shows
; the end of it. It is shown as typed: there is no other way to type one
; with a controller, and the Stick never gives it back.
;
; Nothing here writes to the PPU. keys_frame stages one thing a frame in
; draw_buf: the field, or a row of keys that changed with the set.

KEYS_NAME     = 0               ; what is being typed
KEYS_PASSWORD = 1

DIRTY_FIELD = $10
DIRTY_ROWS  = $0F               ; bit r: row r of the keys
ROW_TILES   = KEY_STEP * (KEY_COLUMNS - 1) + 1
LAYER_KEYS  = KEY_ROWS * KEY_COLUMNS

.segment "ZEROPAGE"
keys_mode:  .res 1
keys_ptr:   .res 2              ; the text being typed
keys_len:   .res 1
keys_max:   .res 1
keys_layer: .res 1              ; which set of keys is up, as an offset into key_chars
cur_row:    .res 1              ; KEY_ROWS is the space bar
cur_col:    .res 1
keys_dirty: .res 1

.segment "RODATA"
name_screen:
    text  HEADING_ROW, LEFT, "NAME OF THE NETWORK"
    label SPACE_ROW, SPACE_COLUMN, "SPACE"
    text  HELP_ROW, LEFT, "A:TYPE B:DELETE START:DONE"
    text  HELP_ROW + 1, LEFT, "SELECT:abc ABC #+="
    .byte 0

password_screen:
    text  HEADING_ROW, LEFT, "PASSWORD FOR"
    label SPACE_ROW, SPACE_COLUMN, "SPACE"
    text  HELP_ROW, LEFT, "A:TYPE B:DELETE START:JOIN"
    text  HELP_ROW + 1, LEFT, "SELECT:abc ABC #+="
    .byte 0

key_row_lo:
.repeat KEY_ROWS, row
    .byte <($2000 + 32 * (KEY_ROW + KEY_STEP * row) + KEY_COLUMN)
.endrepeat
key_row_hi:
.repeat KEY_ROWS, row
    .byte >($2000 + 32 * (KEY_ROW + KEY_STEP * row) + KEY_COLUMN)
.endrepeat
row_first:
.repeat KEY_ROWS, row
    .byte KEY_COLUMNS * row
.endrepeat

.segment "CODE"

; Type a name (A = KEYS_NAME) or a password (KEYS_PASSWORD). What is
; already in net_name or net_pass, to its length, is there to be edited.
.proc open_keys
    sta keys_mode
    cmp #KEYS_NAME
    bne @password
    lda #<name_screen
    ldx #>name_screen
    jsr show_screen
    lda #<net_name
    sta keys_ptr
    lda #>net_name
    sta keys_ptr + 1
    lda net_name_len
    sta keys_len
    lda #NESP_NAME_MAX
    sta keys_max
    bne @ready
@password:
    lda #<password_screen
    ldx #>password_screen
    jsr show_screen
    at BODY_ROW, LEFT           ; the network's name, under the heading
    point net_name
    ldx #0
    ldy net_name_len
    cpy #WIDTH + 1
    bcc @name
    ldy #WIDTH
@name:
    jsr put_bytes
    ldy #WIDTH
    jsr stage_pad
    lda #<net_pass
    sta keys_ptr
    lda #>net_pass
    sta keys_ptr + 1
    lda net_pass_len
    sta keys_len
    lda #NESP_PASSWORD_MAX
    sta keys_max
@ready:
    lda #0
    sta keys_layer
    sta cur_col
    lda #1                      ; on the q
    sta cur_row
    lda #DIRTY_FIELD | DIRTY_ROWS
    sta keys_dirty
    lda #STATE_KEYS
    sta state
    rts
.endproc

.proc keys_frame
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
    beq @set
    lda keys_len
    bne @shorter
    jmp keys_back               ; nothing to delete: leave
@shorter:
    dec keys_len
    lda keys_dirty
    ora #DIRTY_FIELD
    sta keys_dirty
@set:
    lda pad_new
    and #PAD_SELECT
    beq @start
    lda keys_layer
    clc
    adc #LAYER_KEYS
    cmp #KEY_LAYERS * LAYER_KEYS
    bcc @layer
    lda #0
@layer:
    sta keys_layer
    lda keys_dirty
    ora #DIRTY_ROWS
    sta keys_dirty
@start:
    lda pad_new
    and #PAD_START
    beq @draw
    jmp keys_done
@draw:
    jsr keys_draw
    ; The cursor: a bar under its key, or under the middle of the space bar.
    lda cur_row
    cmp #KEY_ROWS
    bcc @key
    ldx #SPACE_X
    ldy #8 * SPACE_ROW + 8
    bne @cursor
@key:
    asl a
    asl a
    asl a
    asl a
    clc
    adc #KEY_Y + 8
    tay
    lda cur_col
    asl a
    asl a
    asl a
    asl a
    clc
    adc #KEY_X
    tax
@cursor:
    lda #TILE_UNDER
    jmp cursor_at
.endproc
.assert KEY_STEP = 2, error, "the cursor counts on keys 16 pixels apart"

; Add the cursor's key to the text, if there is room. An empty key types
; nothing.
.proc type_key
    ldy keys_len
    cpy keys_max
    bcs @done
    lda #' '
    ldx cur_row
    cpx #KEY_ROWS
    bcs @store                  ; the space bar
    lda row_first,x
    clc
    adc cur_col
    adc keys_layer
    tax
    lda key_chars,x
    cmp #' '
    beq @done
@store:
    sta (keys_ptr),y
    inc keys_len
    lda keys_dirty
    ora #DIRTY_FIELD
    sta keys_dirty
@done:
    rts
.endproc

; Start: the text is done.
.proc keys_done
    lda keys_mode
    bne @password
    lda keys_len
    beq @done                   ; a network has a name
    sta net_name_len
    lda #0
    sta net_pass_len
    lda #KEYS_PASSWORD
    jmp open_keys
@password:
    lda keys_len
    sta net_pass_len
    jmp open_send
@done:
    rts
.endproc

; B with nothing typed: back to the list, as it was.
.proc keys_back
    lda keys_mode
    bne @list
    lda #0
    sta net_name_len
@list:
    lda #0
    sta net_pass_len
    jmp open_list
.endproc

; Stage the one thing that most needs drawing, if anything does.
.proc keys_draw
    lda draw_len
    bne @done
    lda keys_dirty
    and #DIRTY_FIELD
    bne @field
    lda keys_dirty
    and #DIRTY_ROWS
    bne @rows
@done:
    rts

; The field: the text, or the end of it if it is longer than the field,
; then the cursor if more can be typed.
@field:
    eor keys_dirty
    sta keys_dirty
    ldy #0
    lda keys_len
    cmp #FIELD_WIDTH
    bcc @from
    sbc #FIELD_WIDTH - 1        ; the last characters, and room for the cursor
    tay
@from:
    ldx #0
@text:
    cpy keys_len
    beq @cursor
    lda (keys_ptr),y
    sta draw_buf,x
    inx
    iny
    bne @text
@cursor:
    lda keys_len
    cmp keys_max
    bcs @field_out
    lda #CURSOR_CHAR
    sta draw_buf,x
    inx
@field_out:
    at FIELD_ROW, LEFT
    ldy #FIELD_WIDTH
    jmp stage_pad

; The lowest row of keys that changed with the set.
@rows:
    ldy #0
    lda #1
@find:
    bit keys_dirty
    bne @row
    asl a
    iny
    bne @find
@row:
    eor keys_dirty
    sta keys_dirty
    lda key_row_lo,y
    sta draw_addr
    lda key_row_hi,y
    sta draw_addr + 1
    lda row_first,y
    clc
    adc keys_layer
    tay
    ldx #0
@key:
    lda key_chars,y
    ora #ALT
    sta draw_buf,x
    inx
    cpx #ROW_TILES
    beq @row_out
    lda #' '
    sta draw_buf,x
    inx
    iny
    bne @key
@row_out:
    stx draw_len
    rts
.endproc

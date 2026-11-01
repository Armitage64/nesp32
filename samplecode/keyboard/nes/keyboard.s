; Keyboard: nesp32's sample of a ROM that takes text from a Bluetooth
; keyboard.
;
; The keyboard is paired with the nesp32, not the console: the nesp32 keeps
; it over power-off, connects to it, and works out what each key is. The
; ROM asks the KBD service (nesp32's docs/PROTOCOL.md, "KBD") how the
; keyboard stands and what has been typed, and hears characters:
;
;   PAIRED    whether a keyboard is paired with this nesp32
;   STATE     how it stands: CONNECTED, NOT CONNECTED (a key wakes it),
;             NOT PAIRED, ...
;   NAME      the keyboard's name, as it gave it when it was paired (as
;             much of it as fits)
;
; and under those a text field of 6 lines of 28, with a blinking cursor,
; that takes what is typed. Enter starts a new line, Backspace deletes (and
; at the start of a line goes back to the end of the one before), and
; Escape clears the field. A keyboard is paired in the setup ROM's
; KEYBOARD screen (apps/setup/nes/kbd.inc), with KBD's SCAN, FOUND and
; PAIR, which this sample leaves out.
;
; What crosses the link:
;
;   SYS HELLO   "KEYS", version 1, asking for KBD, which turns Bluetooth
;               on. Again whenever the nesp32 says KBD is not in use: it
;               was switched off and on
;   KBD STATE   twice a second: the state and the name
;   KBD KEYS    every other frame: what has been typed since the last
;               KEYS, up to 16 characters, oldest first
;
; KEYS takes the characters off the nesp32 as it hands them over. If its
; reply is lost on the way, the ROM sends the very same request again
; (nesp_again, the same sequence number) before it asks anything else, and
; the nesp32 answers it with the reply it held: nothing typed is lost, and
; nothing comes twice.
;
; Every exchange is made from the main loop, right after the NMI, one a
; frame, as nesp32's HTTPS sample does (samplecode/https). The NMI ends
; any exchange it falls in (nesp_nmi_hook), and the main loop sees it as a
; reply that did not come.
;
; The NMI draws a row of text when a status line changes, and the field's
; characters as they are typed, a few a frame (the tile queue).

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
SPRITE_HIDDEN = $FF

; Controller port 2 is the line to the nesp32. It reads OUT0, which is
; also controller 1's strobe, and rests at mark (high).
OUT0_MARK = $01

; The link's library: what it is built for. See the top of nesp.inc.
NESP_RX_MASK = $1F              ; replies of up to 31 bytes: STATE's, with a name
NESP_TX_MAX  = 8                ; the longest request: the hello, naming KBD
NESP_CRC_TABLE = 1
.define NESP_APP "KEYS"
NESP_APP_VERSION = 1

; The screen.
COLUMNS     = 28
LEFT        = 2
.define ROW_AT(row) ($2000 + (row) * 32 + LEFT)
PAIRED_ROW  = 4
STATE_ROW   = 5
NAME_ROW    = 6
VALUE       = 10                ; the column a status line's value starts at
FIELD_ROW   = 12
FIELD_ROWS  = 6
NAME_MAX    = NESP_KBD_NAME_MAX
BLINK       = $10               ; frames the cursor is on, then off

; The phases of the link.
PHASE_HELLO = 0                 ; saying hello until the nesp32 answers
PHASE_OLD   = 1                 ; it did, and has no KBD: nothing more is asked
PHASE_RUN   = 2                 ; STATE and KEYS
MISSES      = 8                 ; exchanges in a row with no reply: no nesp32

; The status lines, by their place in dirty.
LINE_PAIRED = 0
LINE_STATE  = 1
LINE_NAME   = 2
LINES       = 3

TILES_MAX   = 16                ; tile writes the NMI makes in a frame, at most

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM)
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1            ; the last of them the main loop has seen
pad:          .res 1            ; controller 1, which this ROM does not use
temp:         .res 1

.include "nesp.inc"
.assert NESP_TX_MAX = NESP_HELLO_FIXED + 1, error, "the hello names one service"
.assert 3 + NAME_MAX <= NESP_RX_MASK, error, "STATE's reply, with a whole name, fits"
.assert 1 + NESP_KBD_KEYS_MAX <= NESP_RX_MASK, error, "KEYS's reply fits"

.segment "OAM"
oam:          .res 256          ; the sprites, copied to the PPU every NMI

.segment "BSS"
; A row of text for the NMI to draw,
row_buf:      .res COLUMNS
row_hi:       .res 1
row_lo:       .res 1
row_ready:    .res 1            ; 1: staged, and not drawn yet
; and single tiles, as characters are typed.
tile_hi:      .res TILES_MAX
tile_lo:      .res TILES_MAX
tile_char:    .res TILES_MAX
tile_count:   .res 1
dirty:        .res LINES        ; not 0: the status line is to be drawn
; The link.
phase:        .res 1            ; PHASE_*
misses:       .res 1            ; exchanges in a row with no reply
again:        .res 1            ; 1: the last KEYS had no reply, and is sent again
keyboard:     .res 1            ; NESP_KEYBOARD_*, from the last STATE
name_len:     .res 1            ; and the name of the keyboard paired
name:         .res NAME_MAX
; What the last KEYS brought, and how much of it is typed into the field.
keys:         .res NESP_KBD_KEYS_MAX
key_count:    .res 1
key_at:       .res 1
; The field: the cursor, and how long each line is.
cursor_row:   .res 1
cursor_col:   .res 1
line_len:     .res FIELD_ROWS
clearing:     .res 1            ; rows of the field still to clear, for Escape


.segment "CHARS"
    .incbin "chr.bin"

.segment "CODE"



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
    lda #SPRITE_HIDDEN
    sta oam,x
    lda #0
    inx
    bne @clear
@vblank2:
    bit PPUSTATUS
    bpl @vblank2
    jsr draw_screen             ; the picture is off; the first NMI turns it on
    lda #OUT0_MARK              ; the line rests at mark
    sta JOY1
    lda #'_'                    ; the cursor: a sprite of the font's underscore,
    sta oam + 1
    lda #0                      ; in the first sprite palette, in front
    sta oam + 2
    lda #NESP_KEYBOARD_NONE     ; until the nesp32 says
    sta keyboard
    lda #1
    sta dirty + LINE_PAIRED
    sta dirty + LINE_STATE
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through

; Once a frame, right after the NMI: a row to draw, what was typed into the
; field, the cursor, and the link's one exchange. The tests skip ahead to
; the next NMI whenever the CPU waits at main_wait with frame_count equal
; to served_frame, so it stays a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr draw_line
    jsr type_keys
    jsr place_cursor
    jsr link
    jmp main_loop



nmi:
    pha
    txa
    pha
    tya
    pha
    lda row_ready
    beq @tiles
    bit PPUSTATUS
    lda row_hi
    sta PPUADDR
    lda row_lo
    sta PPUADDR
    ldx #0
@char:
    lda row_buf,x
    sta PPUDATA
    inx
    cpx #COLUMNS
    bne @char
    lda #0
    sta row_ready
@tiles:
    ldx #0                      ; in the order they were typed: a character
@tile:                          ; may go where a Backspace has just erased one
    cpx tile_count
    beq @drawn
    lda tile_hi,x
    sta PPUADDR
    lda tile_lo,x
    sta PPUADDR
    lda tile_char,x
    sta PPUDATA
    inx
    bne @tile
@drawn:
    lda #0
    sta tile_count
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
    inc frame_count
    nesp_nmi_hook               ; an exchange under way is ended, and fails
    pla
    tay
    pla
    tax
    pla
irq:
    rti

.assert TILES_MAX * 22 + COLUMNS * 9 + 513 < 2273, error, "the NMI's writes fit the vblank"



; --- the link ------------------------------------------------------------------

; One exchange: the hello until the nesp32 has answered it; then a lost
; KEYS again, before anything else; then STATE twice a second, and KEYS
; every other frame once what the last one brought is in the field.
link:
    lda phase
    beq say_hello               ; PHASE_HELLO
    cmp #PHASE_OLD
    beq @rts
    lda again
    beq @fresh
    jmp keys_again
@fresh:
    lda frame_count
    and #$1F
    bne @keys
    jmp ask_state
@keys:
    lsr a
    bcs @rts                    ; every other frame
    lda key_at
    cmp key_count
    bcc @rts                    ; what came last is still being typed in
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr nesp_call
    jmp took_keys
@rts:
    rts

say_hello:
    lda #NESP_SVC_KBD           ; the one service this ROM needs
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs missed
    jsr answered
    lda nesp_status
    bne @old                    ; NO_SERVICE: a firmware from before KBD
    lda #PHASE_RUN
    sta phase
    lda #0
    sta again
    lda #1                      ; every line, as it now stands
    ldx #LINES - 1
@dirty:
    sta dirty,x
    dex
    bpl @dirty
    rts
@old:
    lda #PHASE_OLD
    sta phase
    lda #1
    sta dirty + LINE_STATE
    rts

; No reply. After MISSES in a row the state line says there is no nesp32.
missed:
    lda misses
    cmp #MISSES
    bcs @rts
    inc misses
    lda misses
    cmp #MISSES
    bne @rts
    lda #1
    sta dirty + LINE_STATE
@rts:
    rts

; A reply came. One that says KBD is not in use is from a nesp32 that was
; switched off and on: it is told hello again. Carry set for that.
answered:
    lda misses
    cmp #MISSES
    bcc @counted
    lda #1
    sta dirty + LINE_STATE
@counted:
    lda #0
    sta misses
    lda nesp_status
    cmp #NESP_ST_INACTIVE
    bne @ok
    lda #PHASE_HELLO
    sta phase
    sec
    rts
@ok:
    clc
    rts

; The KEYS that had no reply, byte for byte: the nesp32 answers it with the
; reply it sent before, keys and all.
keys_again:
    jsr nesp_again
    ; fall through

; What KEYS brought: its characters, for type_keys to put in the field.
took_keys:
    bcc @came
    lda #1                      ; lost: the same request goes again
    sta again
    jmp missed
@came:
    lda #0
    sta again
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts
    lda nesp_reply              ; how many
    cmp #NESP_KBD_KEYS_MAX + 1
    bcs @rts
    sta key_count
    tax
    beq @none
@key:
    lda nesp_reply,x            ; the characters, from nesp_reply + 1
    sta keys - 1,x
    dex
    bne @key
@none:
    stx key_at
@rts:
    rts

; STATE: the keyboard's state, how many a scan found, and the name of the
; one paired. The lines whose part of it changed are drawn again.
ask_state:
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_STATE
    ldy #0
    jsr nesp_call
    bcc @came
    jmp missed
@came:
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts
    lda nesp_reply
    cmp keyboard
    beq @name
    sta keyboard
    lda #1
    sta dirty + LINE_STATE
    sta dirty + LINE_PAIRED
@name:
    lda nesp_reply + 2          ; the name's length
    cmp #NAME_MAX + 1
    bcc @length
    lda #NAME_MAX
@length:
    cmp name_len
    beq @compare
    sta name_len
    lda #1
    sta dirty + LINE_NAME
    sta dirty + LINE_PAIRED
@compare:
    ldx name_len
    beq @rts
@char:
    lda nesp_reply + 2,x        ; the name, from nesp_reply + 3
    cmp name - 1,x
    beq @next
    sta name - 1,x
    lda #1
    sta dirty + LINE_NAME
@next:
    dex
    bne @char
@rts:
    rts



; --- the field -----------------------------------------------------------------

; What the last KEYS brought, into the field, as far as the NMI's tile queue
; has room for this frame.
type_keys:
    lda clearing
    bne @rts                    ; the field is being cleared
    ldx key_at
    cpx key_count
    bcs @rts
    lda tile_count
    cmp #TILES_MAX
    bcs @rts
    lda keys,x
    inc key_at
    jsr type_key
    jmp type_keys
@rts:
    rts

; One character, A, into the field.
type_key:
    cmp #NESP_KEY_ENTER
    beq new_line
    cmp #NESP_KEY_BACKSPACE
    beq backspace
    cmp #NESP_KEY_ESCAPE
    beq clear
    cmp #NESP_KEY_TAB
    bne @char
    lda #' '
@char:
    cmp #' '
    bcc @rts                    ; the arrows and the rest: this field has no use for them
    cmp #$7F
    bcs @rts
    ldx cursor_row
    cpx #FIELD_ROWS
    bcs @rts                    ; the field is full
    jsr put_tile
    inc cursor_col
    lda cursor_col
    ldx cursor_row
    sta line_len,x
    cmp #COLUMNS
    bcs new_line                ; a full line goes on on the next
@rts:
    rts

; Enter: the cursor to the start of the next line, if there is one.
new_line:
    ldx cursor_row
    cpx #FIELD_ROWS
    bcs @rts
    inc cursor_row
    lda #0
    sta cursor_col
@rts:
    rts

; Backspace: the last character goes. At the start of a line, the cursor
; goes back to the end of the one before.
backspace:
    lda cursor_col
    bne @erase
    ldx cursor_row
    beq @rts                    ; nothing typed
    dex
    stx cursor_row
    lda line_len,x
    sta cursor_col
    cmp #COLUMNS
    bne @rts                    ; a line that was ended with Enter
@erase:
    dec cursor_col
    ldx cursor_row
    lda cursor_col
    sta line_len,x
    lda #' '
    jmp put_tile
@rts:
    rts

; Escape: the field empty, a row a frame (draw_line does it).
clear:
    lda #FIELD_ROWS
    sta clearing
    lda #0
    sta cursor_row
    sta cursor_col
    ldx #FIELD_ROWS - 1
@line:
    sta line_len,x
    dex
    bpl @line
    rts

; A at the cursor, through the NMI's tile queue, which has room. Keeps
; nothing. The entry is whole before tile_count says it is there; and the
; main loop does this right after an NMI, long before the next one.
put_tile:
    ldx tile_count
    sta tile_char,x
    ldy cursor_row
    lda field_lo,y
    clc
    adc cursor_col
    sta tile_lo,x
    lda field_hi,y
    adc #0
    sta tile_hi,x
    inc tile_count
    rts

field_lo:
    .repeat FIELD_ROWS, index
    .byte <ROW_AT(FIELD_ROW + index)
    .endrepeat
field_hi:
    .repeat FIELD_ROWS, index
    .byte >ROW_AT(FIELD_ROW + index)
    .endrepeat

; The cursor's sprite where the next character goes, on for BLINK frames
; and off for as many; off with the field full.
place_cursor:
    lda #SPRITE_HIDDEN
    ldx cursor_row
    cpx #FIELD_ROWS
    bcs @y
    lda frame_count
    and #BLINK
    bne @off
    txa
    asl a
    asl a
    asl a
    adc #8 * FIELD_ROW - 1      ; OAM's y is the line above the sprite's first
    sta oam
    lda cursor_col
    asl a
    asl a
    asl a
    adc #8 * LEFT
    sta oam + 3
    rts
@off:
    lda #SPRITE_HIDDEN
@y:
    sta oam
    rts



; --- the status lines ----------------------------------------------------------

; Stage a row for the NMI, if it has drawn the last: a row of the field
; being cleared, or a status line that has changed.
draw_line:
    lda row_ready
    bne @rts
    jsr blank_row
    lda clearing
    beq @status
    dec clearing
    ldx clearing
    lda field_lo,x
    sta row_lo
    lda field_hi,x
    sta row_hi
    jmp stage
@status:
    ldx #0
@find:
    lda dirty,x
    bne @line
    inx
    cpx #LINES
    bne @find
@rts:
    rts
@line:
    lda #0
    sta dirty,x
    lda lines_lo,x
    sta row_lo
    lda lines_hi,x
    sta row_hi
    txa
    asl a
    tax
    lda lines + 1,x
    pha
    lda lines,x
    pha
    rts                         ; to the line's own; its jmp to stage stages it

lines_lo:
    .byte <ROW_AT(PAIRED_ROW), <ROW_AT(STATE_ROW), <ROW_AT(NAME_ROW)
lines_hi:
    .byte >ROW_AT(PAIRED_ROW), >ROW_AT(STATE_ROW), >ROW_AT(NAME_ROW)
lines:
    .word line_paired - 1, line_state - 1, line_name - 1
.assert (* - lines) / 2 = LINES, error

; row_buf all spaces.
blank_row:
    lda #' '
    ldx #COLUMNS - 1
@space:
    sta row_buf,x
    dex
    bpl @space
    rts

; The row staged: the NMI draws it.
stage:
    lda #1
    sta row_ready
    rts

; Text from words, at X, into row_buf from Y, up to its 0.
put_word:
    lda words,x
    beq @rts
    sta row_buf,y
    inx
    iny
    bne put_word
@rts:
    rts

; PAIRED: YES if a keyboard is paired with the nesp32, which is so when it
; has a name for one.
line_paired:
    ldx #w_paired - words
    ldy #0
    jsr put_word
    lda phase
    cmp #PHASE_RUN
    bne @stage                  ; not known
    ldx #w_no - words
    lda name_len
    beq @word
    ldx #w_yes - words
@word:
    ldy #VALUE
    jsr put_word
@stage:
    jmp stage

line_state:
    ldx #w_state - words
    ldy #0
    jsr put_word
    ldx #w_no_nesp32 - words
    lda misses
    cmp #MISSES
    bcs @word
    ldx #w_old - words
    lda phase
    cmp #PHASE_OLD
    beq @word
    ldx #w_hello - words
    cmp #PHASE_HELLO
    beq @word
    ldx keyboard
    cpx #NESP_KEYBOARD_FAILED + 1
    bcs @stage                  ; a state this ROM does not know
    lda state_words,x
    tax
@word:
    ldy #VALUE
    jsr put_word
@stage:
    jmp stage

; NAME: the keyboard paired's, as much of it as fits after the label (18
; of its up to 24 characters).
line_name:
    ldx #w_name - words
    ldy #0
    jsr put_word
    ldx #0
    ldy #VALUE
@char:
    cpx name_len
    beq @stage
    cpy #COLUMNS
    beq @stage
    lda name,x
    cmp #' '
    bcc @not
    cmp #$7F
    bcc @put
@not:
    lda #'?'                    ; a character the font has not
@put:
    sta row_buf,y
    inx
    iny
    bne @char
@stage:
    jmp stage

; By NESP_KEYBOARD_*.
state_words:
    .byte w_none - words, w_off - words, w_unpaired - words, w_waiting - words
    .byte w_connected - words, w_scanning - words, w_scanned - words
    .byte w_pairing - words, w_failed - words
.assert NESP_KEYBOARD_NONE = 0 && NESP_KEYBOARD_OFF = 1 && NESP_KEYBOARD_UNPAIRED = 2, error
.assert NESP_KEYBOARD_WAITING = 3 && NESP_KEYBOARD_CONNECTED = 4, error
.assert NESP_KEYBOARD_SCANNING = 5 && NESP_KEYBOARD_SCANNED = 6, error
.assert NESP_KEYBOARD_PAIRING = 7 && NESP_KEYBOARD_FAILED = 8, error

words:
w_paired:    .byte "PAIRED", 0
w_state:     .byte "STATE", 0
w_name:      .byte "NAME", 0
w_yes:       .byte "YES", 0
w_no:        .byte "NO", 0
w_none:      .byte "NO BLUETOOTH", 0
w_off:       .byte "STARTING", 0
w_unpaired:  .byte "NOT PAIRED", 0
w_waiting:   .byte "NOT CONNECTED", 0
w_connected: .byte "CONNECTED", 0
w_scanning:  .byte "SCANNING", 0
w_scanned:   .byte "SCANNED", 0
w_pairing:   .byte "PAIRING", 0
w_failed:    .byte "PAIRING FAILED", 0
w_hello:     .byte "SAYING HELLO", 0
w_old:       .byte "UPDATE NESP32", 0
w_no_nesp32: .byte "NO NESP32", 0
.assert * - words < 256, error, "words is indexed by X"



; --- the screen as it starts ---------------------------------------------------

; With the picture off: the palettes, a blank nametable, and what never
; changes on it.
draw_screen:
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@colour:
    lda palette,x
    sta PPUDATA
    inx
    cpx #palette_end - palette
    bne @colour
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    tax                         ; 1024 zeros: blank tiles, and the one palette
    ldy #4
@byte:
    sta PPUDATA
    inx
    bne @byte
    dey
    bne @byte
    ldx #0
@run:
    lda texts,x
    beq @done
    sta PPUADDR
    inx
    lda texts,x
    sta PPUADDR
    inx
    ldy texts,x
    inx
@char:
    lda texts,x
    sta PPUDATA
    inx
    dey
    bne @char
    beq @run
@done:
    rts

.macro text row, column, string
    .byte >($2000 + (row) * 32 + (column)), <($2000 + (row) * 32 + (column))
    .byte .strlen(string), string
.endmacro

texts:
    text 1, 5, "NESP32 KEYBOARD SAMPLE"
    text FIELD_ROW - 2, LEFT, "TYPE ON THE KEYBOARD"
    text FIELD_ROW - 1, LEFT, "----------------------------"
    text FIELD_ROW + FIELD_ROWS, LEFT, "----------------------------"
    text 22, LEFT, "ENTER      : NEW LINE"
    text 23, LEFT, "BACKSPACE  : DELETE"
    text 24, LEFT, "ESCAPE     : CLEAR"
    .byte 0
.assert * - texts < 256, error, "texts is indexed by X"

; The background's text is white; the sprites' first palette's colour 3,
; the cursor's, is too.
palette:
    .byte $0F, $00, $10, $30
    .byte $0F, $00, $10, $30, $0F, $00, $10, $30, $0F, $00, $10, $30
    .byte $0F, $16, $27, $30
palette_end:



.segment "VECTORS"
    .word nmi, reset, irq

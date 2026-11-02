; HTTPS: nesp32's sample of a ROM that fetches an address from the Internet.
;
; A nesp32 on controller port 2 does the fetching: the TLS, the request,
; the reply. The ROM names an address and asks for it with the HTTP
; service (nesp32's docs/PROTOCOL.md, "HTTP"), then shows what came back,
; as it came:
;
;   GET   the address, on up to three lines
;   STATE how the fetch stands: ASKING, READING, DONE, FAILED
;   STATUS, LENGTH, HELD, TIME
;         the server's status (200, 404, ...), its Content-Length, how
;         much of the body the nesp32 holds (the first 2 KB at most), and
;         how long it all took
;   TYPE  its Content-Type, or WHY it failed
;
; and under those the start of the body, as text wrapped to the screen.
; Down shows the next screenful of it, Up the first again. A or Start
; fetches the address again, and Select changes it: there are two, this
; repository's README on GitHub (a 200, 10 KB of plain text) and a file
; that is not there (a 404).
;
; What crosses the link:
;
;   SYS HELLO     "HTTP", version 1, asking for the HTTP service. Again
;                 whenever the nesp32 says it is not in use: it was
;                 switched off and on
;   HTTP URL      the address, in pieces of up to 60 characters
;   HTTP GET      with an id, until it is answered: a new id is a new fetch
;   HTTP STATE    a few times a second until the fetch is over
;   HTTP READ     the body, 60 bytes at a time, as the screen needs it
;
; Every exchange is made from the main loop, right after the NMI, one a
; frame. This is the simpler way to use the link, and the common one: a
; reply of 60 bytes takes a third of a frame, which the main loop can
; spare. The NMI ends any exchange it falls in (nesp_nmi_hook), and the
; main loop asks again in the next frame. (nesp32's lobby sample, which
; has to make its exchanges in step with the frames, makes them in the NMI
; instead: samplecode/lobby.)
;
; The NMI draws one row of text a frame, staged by the main loop in
; row_buf: the status lines when they change, then the body's rows.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80
PPUMASK_ON = $0A                ; the background, left column included
FRAME_IRQ_INHIBIT = $40
PALETTE   = $3F00

PAD_A      = $80
PAD_B      = $40
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04

; Controller port 2 is the line to the nesp32. It reads OUT0, which is
; also controller 1's strobe, and rests at mark (high).
OUT0_MARK = $01

; The link's library: what it is built for. See the top of nesp.inc.
NESP_RX_MASK = $3F              ; replies of up to 63 bytes
URL_PIECE    = 60               ; characters of the address a URL request carries
NESP_TX_MAX  = 1 + URL_PIECE    ; the longest request: URL's
NESP_CRC_TABLE = 1
.define NESP_APP "HTTP"
NESP_APP_VERSION = 1

; The screen: text in 28 columns, from the third.
COLUMNS   = 28
LEFT      = 2
.define ROW_AT(row) ($2000 + (row) * 32 + LEFT)
URL_ROW   = 4                   ; and the two after it
URL_ROWS  = 3
INFO_ROW  = 8                   ; STATE, then STATUS, LENGTH, HELD, TIME, TYPE
BODY_ROW  = 15
BODY_ROWS = 12
LABEL     = 8                   ; columns of a status line's label

; The phases of the link, which take turns at the one exchange a frame.
PHASE_HELLO = 0                 ; saying hello until the nesp32 answers
PHASE_OLD   = 1                 ; it did, and has no HTTP: nothing more is asked
PHASE_URL   = 2                 ; sending the address, a piece at a time
PHASE_GET   = 3                 ; asking for it until the nesp32 says it is
PHASE_RUN   = 4                 ; STATE until it is over, and READ as the body is wanted
MISSES      = 8                 ; exchanges in a row with no reply: no nesp32

; How the body's screenful stands.
PAGE_NONE   = 0
PAGE_BLANK  = 1                 ; its rows being cleared, for a new fetch
PAGE_LAYOUT = 2                 ; being laid out, a row at a time, as bytes come
PAGE_FULL   = 3                 ; every row has text, and there may be more: Down
PAGE_ENDED  = 4                 ; the body ended on it

; The status lines, which are drawn when they change, by their place in
; dirty and info_rows.
INFO_URL    = 0                 ; and 1 and 2
INFO_STATE  = 3
INFO_STATUS = 4
INFO_LENGTH = 5
INFO_HELD   = 6
INFO_TIME   = 7
INFO_TYPE   = 8
INFO_LINES  = 9

; HTTP STATE's reply (and GET's), as info keeps it.
REPLY_STATE  = 0
REPLY_ID     = 1
REPLY_STATUS = 2                ; 2 bytes, low first
REPLY_LENGTH = 4                ; 4
REPLY_HELD   = 8                ; 2
REPLY_MS     = 10               ; 2
REPLY_TEXT   = 12
CHUNK        = NESP_RX_MASK - 3 ; bytes a READ asks for: its reply has 3 before them

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM)
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1            ; the last of them the main loop has seen
ptr:          .res 2
pad:          .res 1            ; controller 1: A B Select Start Up Down Left Right
pad_old:      .res 1
pressed:      .res 1            ; buttons that went down this frame
temp:         .res 1
num:          .res 4            ; print_decimal's number,
try:          .res 3            ; its subtraction,
digit:        .res 1            ; the digit it is counting,
printed:      .res 1            ; and whether one has been printed yet

.segment "BSS"
; One row of text for the NMI to draw.
row_buf:      .res COLUMNS
row_hi:       .res 1
row_lo:       .res 1
row_ready:    .res 1            ; 1: staged, and not drawn yet
dirty:        .res INFO_LINES   ; not 0: the status line is to be drawn
; The link.
phase:        .res 1            ; PHASE_*
misses:       .res 1            ; exchanges in a row with no reply
preset:       .res 1            ; which address: 0 or 1
url_at:       .res 1            ; how much of it the nesp32 has
get_id:       .res 1            ; the last GET's id
info:         .res REPLY_TEXT   ; the last STATE's reply, but its text,
info_text:    .res COLUMNS      ; which is here,
info_len:     .res 1            ; this long
; The body's screenful.
page:         .res 1            ; PAGE_*
page_at:      .res 2            ; the body's offset of its first byte
next_at:      .res 2            ; and of the next screenful's, once it is FULL
page_row:     .res 1            ; rows staged, or cleared
pos:          .res 2            ; the offset of the next byte to lay out: chunk's first
chunk:        .res CHUNK        ; bytes of the body, from the last READ,
chunk_len:    .res 1
chunk_pos:    .res 1            ; and how many of them are laid out
line:         .res COLUMNS      ; the row being laid out,
col:          .res 1            ; how far,
last_space:   .res 1            ; where its last space is, $FF none,
line_at:      .res 2            ; and the body's offset of its first character

.include "nesp.inc"
.assert NESP_HELLO_FIXED + 1 <= NESP_TX_MAX, error, "the hello names one service"
.assert REPLY_TEXT + NESP_HTTP_TEXT_MAX <= NESP_RX_MASK, error, "STATE's reply fits"
.assert COLUMNS = NESP_HTTP_TEXT_MAX, error, "info_text holds what STATE says"

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
    jsr draw_screen             ; the picture is off; the first NMI turns it on
    lda #OUT0_MARK              ; the line rests at mark
    sta JOY1
    lda #$FF                    ; a button held at reset counts once let go
    sta pad_old
    lda #NESP_HTTP_LENGTH_UNKNOWN & $FF
    ldx #3
@length:
    sta info + REPLY_LENGTH,x
    dex
    bpl @length
    jsr choose                  ; the first address
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through

; Once a frame, right after the NMI: the buttons, a row to draw, and the
; link's one exchange. The tests skip ahead to the next NMI whenever the
; CPU waits at main_wait with frame_count equal to served_frame, so it
; stays a plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr read_pad
    jsr buttons
    jsr draw_next
    jsr link
    jmp main_loop



nmi:
    pha
    txa
    pha
    tya
    pha
    lda row_ready
    beq @picture
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
@picture:
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



; Controller 1 into pad, and what went down into pressed. OUT0 is the
; controller's strobe and the line to the nesp32 at once: it goes low for
; the reads and no longer.
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
    lda pad
    tay
    eor pad_old
    and pad
    sta pressed
    sty pad_old
    rts

buttons:
    lda phase
    cmp #PHASE_RUN
    bcc @rts                    ; nothing to do until the nesp32 has the address
    lda pressed
    and #PAD_SELECT
    beq @again
    lda preset                  ; the other address
    eor #1
    sta preset
    jmp choose
@again:
    lda pressed
    and #PAD_A | PAD_START
    beq @down
    jmp new_get
@down:
    lda pressed
    and #PAD_DOWN
    beq @up
    lda page
    cmp #PAGE_FULL
    bne @rts
    lda next_at                 ; the next screenful, from where this one stopped
    sta page_at
    lda next_at + 1
    sta page_at + 1
    jmp start_page
@up:
    lda pressed
    and #PAD_UP
    beq @rts
    lda page
    cmp #PAGE_FULL
    bcc @rts                    ; FULL or ENDED: the first again
    lda #0
    sta page_at
    sta page_at + 1
    jmp start_page
@rts:
    rts



; --- the link ------------------------------------------------------------------

; The address of preset: to be sent to the nesp32, then fetched.
choose:
    lda #PHASE_URL
    sta phase
    lda #0
    sta url_at
    lda #1
    sta dirty + INFO_URL
    sta dirty + INFO_URL + 1
    sta dirty + INFO_URL + 2
    sta dirty + INFO_STATE
    rts

; A GET with a new id: the nesp32 fetches the address again. The body's
; rows are cleared for it, and every status line drawn again.
new_get:
    lda #1
    ldx #INFO_TYPE - INFO_STATE
@dirty:
    sta dirty + INFO_STATE,x
    dex
    bpl @dirty
    ; fall through

; The same, with the status lines left as they are until the reply changes
; them: for asking again, every second, while the nesp32 has no network.
retry_get:
    inc get_id
    lda #PHASE_GET
    sta phase
    lda #PAGE_BLANK
    sta page
    lda #0
    sta page_row
    sta page_at
    sta page_at + 1
    rts

; One exchange, the one the phase calls for.
link:
    lda phase
    asl a
    tax
    lda phases + 1,x
    pha
    lda phases,x
    pha
    rts

phases:
    .word say_hello - 1, link_rts - 1, send_url - 1, send_get - 1, run - 1

say_hello:
    lda #NESP_SVC_HTTP          ; the one service this ROM needs
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs missed
    jsr answered
    lda nesp_status
    bne @old                    ; NO_SERVICE: a firmware from before HTTP
    jmp choose                  ; the nesp32 has forgotten the address, if it had it
@old:
    lda #PHASE_OLD
    sta phase
    lda #1
    sta dirty + INFO_STATE
link_rts:
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
    sta dirty + INFO_STATE
@rts:
    rts

; A reply came. One that says HTTP is not in use is from a nesp32 that was
; switched off and on: it is told hello again. Carry set for that.
answered:
    lda misses
    cmp #MISSES
    bcc @counted
    lda #1
    sta dirty + INFO_STATE
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

; URL: AT, then the next piece of the address.
send_url:
    jsr url_of_preset           ; ptr, and the length in A
    sec
    sbc url_at
    cmp #URL_PIECE + 1
    bcc @piece
    lda #URL_PIECE
@piece:
    sta temp                    ; the piece's length
    lda url_at
    sta nesp_request
    clc
    adc ptr
    sta ptr
    bcc @copy
    inc ptr + 1
@copy:
    ldy #0
@char:
    cpy temp
    beq @send
    lda (ptr),y
    sta nesp_request + 1,y
    iny
    bne @char
@send:
    iny                         ; and AT
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_URL
    jsr nesp_call
    bcs missed
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts                    ; BAD_ARG: never, for these addresses
    lda url_at
    clc
    adc temp
    sta url_at
    jsr url_of_preset
    cmp url_at
    bne @rts
    jmp new_get                 ; all of it: fetch it
@rts:
    rts

; GET, with this fetch's id, until the nesp32 says it has it.
send_get:
    lda get_id
    sta nesp_request
    ldy #1
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_GET
    jsr nesp_call
    bcc @came
    jmp missed
@came:
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts
    lda nesp_reply + REPLY_ID
    cmp get_id
    bne @rts
    jsr take_state
    lda #PHASE_RUN
    sta phase
    lda #1
    sta dirty + INFO_STATE
@rts:
    rts

; The fetch under way: READ when the body's screenful wants bytes the
; nesp32 holds, and otherwise STATE, every fourth frame, until the fetch is
; over. A GET that found the nesp32 on no network is over too, and is made
; again every 64 frames, as the nesp32 may have joined one since: it joins
; on its own, seconds after it is switched on.
run:
    lda info + REPLY_STATE
    cmp #NESP_FETCH_NO_WIFI
    bne @fetch
    lda frame_count
    and #$3F
    bne @fetch
    jmp retry_get
@fetch:
    lda page
    cmp #PAGE_LAYOUT
    bne @state
    lda chunk_pos
    cmp chunk_len
    bcc @state                  ; it has bytes still
    lda pos + 1                 ; pos < held: there are more to READ
    cmp info + REPLY_HELD + 1
    bcc read_body
    bne @state
    lda pos
    cmp info + REPLY_HELD
    bcc read_body
@state:
    jsr fetch_over
    bne @rts
    lda frame_count
    and #$03
    bne @rts
    ldy #0
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_STATE
    jsr nesp_call
    bcs @missed
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts
    jmp take_state
@missed:
    jmp missed
@rts:
    rts

; READ: CHUNK bytes of the body from pos, into chunk.
read_body:
    lda pos
    sta nesp_request
    lda pos + 1
    sta nesp_request + 1
    lda #CHUNK
    sta nesp_request + 2
    ldy #3
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_READ
    jsr nesp_call
    bcs @missed
    jsr answered
    bcs @rts
    lda nesp_status
    bne @rts
    lda nesp_reply + 1          ; the reply to this READ: from pos
    cmp pos
    bne @rts
    lda nesp_reply + 2
    cmp pos + 1
    bne @rts
    lda nesp_reply_len
    sec
    sbc #3
    bcc @rts
    sta chunk_len
    tax
    beq @rts
@copy:
    lda nesp_reply + 2,x        ; the bytes from nesp_reply + 3
    sta chunk - 1,x
    dex
    bne @copy
    stx chunk_pos
@rts:
    rts
@missed:
    jmp missed

; Z clear if the fetch is over: NO_WIFI, DONE or FAILED.
fetch_over:
    lda info + REPLY_STATE
    cmp #NESP_FETCH_NO_WIFI
    beq @over
    cmp #NESP_FETCH_DONE
    bcs @over
    lda #0
    rts
@over:
    lda #1
    rts

; STATE's reply (or GET's) into info, and every status line whose part of it
; changed to be drawn again.
take_state:
    ldy #REPLY_TEXT - 1
@byte:
    lda nesp_reply,y
    cmp info,y
    beq @same
    sta info,y
    ldx line_of_byte,y
    lda #1
    sta dirty,x
    cpx #INFO_STATE             ; a new state may change TYPE to WHY
    bne @same
    sta dirty + INFO_TYPE
@same:
    dey
    bpl @byte
    ; The text: the Content-Type, or why it failed.
    lda nesp_reply_len
    sec
    sbc #REPLY_TEXT
    bcs @length
    lda #0
@length:
    cmp #COLUMNS + 1
    bcc @text
    lda #COLUMNS
@text:
    cmp info_len
    beq @compare
    sta info_len
    lda #1
    sta dirty + INFO_TYPE
@compare:
    ldy info_len
    beq @rts
@char:
    lda nesp_reply + REPLY_TEXT - 1,y
    cmp info_text - 1,y
    beq @next
    sta info_text - 1,y
    lda #1
    sta dirty + INFO_TYPE
@next:
    dey
    bne @char
@rts:
    rts

line_of_byte:
    .byte INFO_STATE, INFO_STATE, INFO_STATUS, INFO_STATUS
    .byte INFO_LENGTH, INFO_LENGTH, INFO_LENGTH, INFO_LENGTH
    .byte INFO_HELD, INFO_HELD, INFO_TIME, INFO_TIME
.assert * - line_of_byte = REPLY_TEXT, error

; The preset's address into ptr, and its length into A.
url_of_preset:
    ldx preset
    lda url_lo,x
    sta ptr
    lda url_hi,x
    sta ptr + 1
    lda url_len,x
    rts



; --- the screen ----------------------------------------------------------------

; Stage the next row for the NMI, if it has drawn the last: a status line
; that has changed, or else the body's next row.
draw_next:
    lda row_ready
    bne @rts
    ldx #0
@find:
    lda dirty,x
    bne @info
    inx
    cpx #INFO_LINES
    bne @find
    jmp page_step
@info:
    lda #0
    sta dirty,x
    lda info_hi,x
    sta row_hi
    lda info_lo,x
    sta row_lo
    jsr blank_row
    txa
    asl a
    tax
    lda info_lines + 1,x
    pha
    lda info_lines,x
    pha
@rts:
    rts                         ; to the line's own; its rts stages it

; Each status line: where it goes, and what writes it into row_buf.
info_lo:
    .repeat URL_ROWS, index
    .byte <ROW_AT(URL_ROW + index)
    .endrepeat
    .repeat 6, index
    .byte <ROW_AT(INFO_ROW + index)
    .endrepeat
info_hi:
    .repeat URL_ROWS, index
    .byte >ROW_AT(URL_ROW + index)
    .endrepeat
    .repeat 6, index
    .byte >ROW_AT(INFO_ROW + index)
    .endrepeat
info_lines:
    .word line_url - 1, line_url - 1, line_url - 1, line_state - 1, line_status - 1
    .word line_length - 1, line_held - 1, line_time - 1, line_type - 1
.assert (* - info_lines) / 2 = INFO_LINES, error

; row_buf all spaces. Keeps X.
blank_row:
    lda #' '
    ldy #COLUMNS - 1
@space:
    sta row_buf,y
    dey
    bpl @space
    rts

; The row staged: the NMI draws it.
stage:
    lda #1
    sta row_ready
    rts

; A status line's label at the start of row_buf. Y is left at the column
; after the label's room.
.macro label text
    .local @string, @char
    ldy #.strlen(text) - 1
@char:
    lda @string,y
    sta row_buf,y
    dey
    bpl @char
    ldy #LABEL
    jmp :+
@string:
    .byte text
:
.endmacro

; The address, 28 characters a line: which line is row_lo's.
line_url:
    jsr url_of_preset
    sta temp
    lda row_lo                  ; the line's number: 0, 1 or 2
    ldx #0
@which:
    cmp info_lo,x
    beq @found
    inx
    bne @which
@found:
    lda #0
@times:
    dex
    bmi @from
    clc
    adc #COLUMNS
    bne @times
@from:
    tax                         ; the address's first character on this line
    ldy #0
@char:
    cpx temp
    bcs @done
    stx num
    sty num + 1
    txa
    tay
    lda (ptr),y
    ldy num + 1
    sta row_buf,y
    ldx num
    inx
    iny
    cpy #COLUMNS
    bne @char
@done:
    jmp stage

line_state:
    label "STATE"
    ldx #STATE_NO_NESP32
    lda misses
    cmp #MISSES
    bcs @word
    ldx #STATE_OLD
    lda phase
    cmp #PHASE_OLD
    beq @word
    ldx #STATE_HELLO
    cmp #PHASE_HELLO
    beq @word
    ldx #STATE_SENDING
    cmp #PHASE_RUN
    bcc @word
    lda info + REPLY_STATE
    cmp #NESP_FETCH_FAILED + 1
    bcs @stage                  ; a state this ROM does not know
    tax
@word:
    lda state_words,x
    tax
@char:
    lda state_text,x
    beq @stage
    sta row_buf,y
    inx
    iny
    bne @char
@stage:
    jmp stage

; By NESP_FETCH_*, then the ROM's own.
STATE_HELLO     = NESP_FETCH_FAILED + 1
STATE_OLD       = STATE_HELLO + 1
STATE_NO_NESP32 = STATE_OLD + 1
STATE_SENDING   = STATE_NO_NESP32 + 1
state_words:
    .byte s_idle - state_text, s_no_wifi - state_text, s_asking - state_text
    .byte s_reading - state_text, s_done - state_text, s_failed - state_text
    .byte s_hello - state_text, s_old - state_text, s_none - state_text
    .byte s_starting - state_text
state_text:
s_idle:     .byte "IDLE", 0
s_no_wifi:  .byte "NO WIFI", 0
s_asking:   .byte "ASKING", 0
s_reading:  .byte "READING", 0
s_done:     .byte "DONE", 0
s_failed:   .byte "FAILED", 0
s_hello:    .byte "SAYING HELLO", 0
s_old:      .byte "UPDATE NESP32", 0
s_none:     .byte "NO NESP32", 0
s_starting: .byte "STARTING", 0
.assert * - state_text < 256, error, "state_text is indexed by X"
.assert NESP_FETCH_IDLE = 0 && NESP_FETCH_NO_WIFI = 1 && NESP_FETCH_ASKING = 2, error
.assert NESP_FETCH_READING = 3 && NESP_FETCH_DONE = 4 && NESP_FETCH_FAILED = 5, error

line_status:
    label "STATUS"
    lda info + REPLY_STATUS
    ora info + REPLY_STATUS + 1
    beq @stage                  ; no answer yet
    lda info + REPLY_STATUS
    ldx info + REPLY_STATUS + 1
    jsr print_word
@stage:
    jmp stage

line_length:
    label "LENGTH"
    lda info + REPLY_LENGTH
    and info + REPLY_LENGTH + 1
    and info + REPLY_LENGTH + 2
    and info + REPLY_LENGTH + 3
    cmp #$FF
    beq @unknown                ; NESP_HTTP_LENGTH_UNKNOWN: no Content-Length
    ldx #3
@copy:
    lda info + REPLY_LENGTH,x
    sta num,x
    dex
    bpl @copy
    jsr print_decimal
    jmp bytes
@unknown:
    lda info + REPLY_STATE
    cmp #NESP_FETCH_READING
    bcc @stage                  ; not answered yet
    ldx #0
@char:
    lda unknown,x
    beq @stage
    sta row_buf,y
    inx
    iny
    bne @char
@stage:
    jmp stage
unknown:
    .byte "NOT SAID", 0

line_held:
    label "HELD"
    lda info + REPLY_HELD
    ldx info + REPLY_HELD + 1
    jsr print_word
    ; fall through

; " BYTES" after the number.
bytes:
    ldx #0
@char:
    lda bytes_text,x
    beq @stage
    sta row_buf,y
    inx
    iny
    bne @char
@stage:
    jmp stage
bytes_text:
    .byte " BYTES", 0

line_time:
    label "TIME"
    lda info + REPLY_MS
    ldx info + REPLY_MS + 1
    jsr print_word
    lda #' '
    sta row_buf,y
    lda #'M'
    sta row_buf + 1,y
    lda #'S'
    sta row_buf + 2,y
    jmp stage

; The Content-Type, or with FAILED why, as much as fits.
line_type:
    lda info + REPLY_STATE
    cmp #NESP_FETCH_FAILED
    beq @why
    label "TYPE"
    jmp @text
@why:
    label "WHY"
@text:
    ldx #0
@char:
    cpx info_len
    beq @stage
    cpy #COLUMNS
    beq @stage
    lda info_text,x
    jsr printable
    sta row_buf,y
    inx
    iny
    bne @char
@stage:
    jmp stage

; A byte as a character of the font: one it has not is '?'. Keeps X and Y.
printable:
    cmp #' '
    bcc @not
    cmp #$7F
    bcc @rts
@not:
    lda #'?'
@rts:
    rts

; A and X, the low byte and the high, in decimal into row_buf from Y.
print_word:
    sta num
    stx num + 1
    lda #0
    sta num + 2
    sta num + 3
    ; fall through

; num, 32 bits, in decimal into row_buf from Y, with no zeros before it.
; Y is left after it. A power of ten at a time: how many times it can be
; taken away is the digit.
print_decimal:
    lda #0
    sta printed
    ldx #0
@power:
    lda #0
    sta digit
@subtract:
    lda num
    sec
    sbc powers,x
    sta try
    lda num + 1
    sbc powers + 1,x
    sta try + 1
    lda num + 2
    sbc powers + 2,x
    sta try + 2
    lda num + 3
    sbc powers + 3,x
    bcc @digit                  ; less than the power: the digit is done
    sta num + 3
    lda try + 2
    sta num + 2
    lda try + 1
    sta num + 1
    lda try
    sta num
    inc digit
    bne @subtract
@digit:
    lda digit
    ora printed
    bne @print
    cpx #4 * 9                  ; the last digit is printed, 0 or not
    bne @skip
@print:
    lda digit
    ora #'0'
    sta row_buf,y
    iny
    sta printed
@skip:
    inx
    inx
    inx
    inx
    cpx #4 * 10
    bne @power
    rts

powers:
    .dword 1000000000, 100000000, 10000000, 1000000, 100000
    .dword 10000, 1000, 100, 10, 1



; --- the body --------------------------------------------------------------------

; The body's screenful from page_at.
start_page:
    lda page_at
    sta pos
    sta line_at
    lda page_at + 1
    sta pos + 1
    sta line_at + 1
    lda #0
    sta chunk_len
    sta chunk_pos
    sta col
    sta page_row
    lda #$FF
    sta last_space
    lda #PAGE_LAYOUT
    sta page
    rts

; The body's part of draw_next: a row cleared, or the next row laid out, if
; the bytes for it are here.
page_step:
    lda page
    cmp #PAGE_BLANK
    beq @blank
    cmp #PAGE_LAYOUT
    beq layout
    rts
@blank:
    jsr blank_row
    jsr stage_page_row
    lda page_row
    cmp #BODY_ROWS
    bne @rts
    jmp start_page              ; all clear: page_at is 0
@rts:
    rts

; Lay bytes out until a row is staged, or there are no more for now. At
; the body's end what is laid out is staged, and then blank rows to the
; foot of the screen.
layout:
    lda chunk_pos
    cmp chunk_len
    bcc @byte
    ; No bytes. Are there to be any more?
    jsr fetch_over
    beq @rts                    ; still coming
    lda pos + 1
    cmp info + REPLY_HELD + 1
    bcc @rts                    ; held, and READ will bring them
    bne @end
    lda pos
    cmp info + REPLY_HELD
    bcc @rts
@end:
    jsr emit
    lda #0                      ; and blank rows after it
    sta col
    lda page_row
    cmp #BODY_ROWS
    bne @rts
    lda #PAGE_ENDED
    sta page
@rts:
    rts
@byte:
    ldx chunk_pos
    lda chunk,x
    inc chunk_pos
    jsr put_char                ; carry set: a row was staged
    inc pos
    bne @staged
    inc pos + 1
@staged:
    bcc layout
    lda page_row
    cmp #BODY_ROWS
    bne @rts
    lda line_at                 ; the next screenful starts with the line
    sta next_at                 ; that did not fit on this one
    lda line_at + 1
    sta next_at + 1
    lda #PAGE_FULL
    sta page
    rts

; A byte of the body, at pos, onto the line, wrapping at a space. Carry set
; if a row was staged.
put_char:
    cmp #$0D                    ; CR: nothing, before LF
    beq @nothing
    cmp #$0A                    ; LF: the line ends
    bne @tab
    jsr emit
    jmp next_line_after
@tab:
    cmp #$09
    bne @char
    lda #' '
@char:
    jsr printable
    ldx col
    cpx #COLUMNS
    beq @full
    sta line,x
    cmp #' '
    bne @placed
    stx last_space
@placed:
    inc col
@nothing:
    clc
    rts
@full:
    ; The line is full. A space ends it; a word goes onto the next line
    ; with what of it is already on this one.
    cmp #' '
    bne @word
    jsr emit
    jmp next_line_after
@word:
    sta temp                    ; the character
    ldx last_space
    bpl @carry
    jsr emit                    ; no space: the word is cut
    lda #0
    sta col
    jsr next_line_here
    jmp @place
@carry:
    ; What comes after the last space goes on: the line is staged up to it.
    stx col
    jsr emit
    ldy #0
    ldx last_space
@move:
    inx
    cpx #COLUMNS
    beq @moved
    lda line,x
    sta line,y
    iny
    bne @move
@moved:
    tya
    pha
    jsr next_line_here
    pla
    sta col
    lda line_at                 ; which began that many characters before this one
    sec
    sbc col
    sta line_at
    bcs @place
    dec line_at + 1
@place:
    lda #$FF
    sta last_space
    lda temp
    ldx col
    sta line,x
    inc col
    sec
    rts

; A new line begins after the byte at pos, or with it.
next_line_after:
    lda pos
    clc
    adc #1
    sta line_at
    lda pos + 1
    adc #0
    sta line_at + 1
    jmp next_line
next_line_here:
    lda pos
    sta line_at
    lda pos + 1
    sta line_at + 1
next_line:
    lda #0
    sta col
    lda #$FF
    sta last_space
    sec
    rts

; The line, up to col, staged as the body's next row. Keeps nothing.
emit:
    ldx #0
@char:
    lda #' '
    cpx col
    bcs @put
    lda line,x
@put:
    sta row_buf,x
    inx
    cpx #COLUMNS
    bne @char
    ; fall through

; row_buf to the body's next row.
stage_page_row:
    ldx page_row
    lda body_lo,x
    sta row_lo
    lda body_hi,x
    sta row_hi
    inc page_row
    jmp stage

body_lo:
    .repeat BODY_ROWS, index
    .byte <ROW_AT(BODY_ROW + index)
    .endrepeat
body_hi:
    .repeat BODY_ROWS, index
    .byte >ROW_AT(BODY_ROW + index)
    .endrepeat



; --- the screen as it starts ---------------------------------------------------

; With the picture off: the palette, a blank nametable, and what never
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
    cpx #4
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
    text 1, 6, "NESP32 HTTPS SAMPLE"
    text URL_ROW - 1, LEFT, "GET"
    text 28, 4, "A : RETRY   SELECT : URL"
    .byte 0
.assert * - texts < 256, error, "texts is indexed by X"

palette:
    .byte $0F, $00, $10, $30

; The two addresses.
url_readme:
    .byte "https://raw.githubusercontent.com/Armitage64/nesp32/main/README.md"
URL_README = * - url_readme
url_missing:
    .byte "https://raw.githubusercontent.com/Armitage64/nesp32/main/NO-SUCH-FILE"
URL_MISSING = * - url_missing
url_lo:
    .byte <url_readme, <url_missing
url_hi:
    .byte >url_readme, >url_missing
url_len:
    .byte URL_README, URL_MISSING
.assert URL_README <= COLUMNS * URL_ROWS && URL_MISSING <= COLUMNS * URL_ROWS, error
.assert URL_README <= NESP_HTTP_URL_MAX && URL_MISSING <= NESP_HTTP_URL_MAX, error



.segment "VECTORS"
    .word nmi, reset, irq

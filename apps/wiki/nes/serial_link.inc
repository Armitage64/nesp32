; Serial link: an M5Stack Stick on controller port 2 holds the article
; (docs/PROTOCOL.md). The link ROM's host, in place of fake_link.inc.
;
; Provides link_init, link_search, link_status, link_line, link_text and
; the link_nmi_hook macro.
;
; Every use of the link is one exchange: a request goes out, and a reply of
; REPLY_SIZE bytes comes back or does not. The serial routines count CPU
; cycles (link.inc, generated), so nothing may interrupt them, and the
; receiver waits for a start bit with no timeout of its own. The NMI is the
; timeout: while an exchange is under way (rx_active), the NMI handler does
; its work as always and then, instead of going back into the middle of a
; bit, returns to rx_abort, which drops the exchange and reports it failed.
; So an exchange that does not fit before the next vblank costs nothing but
; itself, and the caller asks again in a later frame.
;
; The Stick drives D0 (bit 0 of $4017, inverted by the port's buffer) and
; reads OUT0 (bit 0 of $4016 writes), which rests at mark.

REQUEST_MARKER = $57
REPLY_MARKER   = $A5
OP_SEARCH = $01
OP_LINE   = $02
NO_LINE   = $FF                 ; a reply's line, high byte, when it is not a line's
REQUEST_MAX = 3 + 1 + QUERY_MAX + 2     ; marker, op, length; an id and a query; the CRC

.segment "ZEROPAGE"
rx_data:    .res 1
tx_data:    .res 1
rx_active:  .res 1              ; an exchange is under way: the NMI ends it
saved_sp:   .res 1              ; the stack as exchange's caller left it
crc_hi:     .res 1
crc_lo:     .res 1
crc_count:  .res 1
request_len: .res 1
search_id:  .res 1              ; which search this is: a new one, a new id

; rx_block, tx_byte and the CRC's tables. After the zero page's names, so
; that the routines use them as zero page: their timing counts on it.
.include "link.inc"

; A reply: marker, state, line (2), total (2), text, CRC (2).
REPLY_STATE = 1
REPLY_LINE  = 2
REPLY_TOTAL = 4
REPLY_CRC   = REPLY_SIZE - 2

.segment "BSS"
rx_buf:      .res REPLY_SIZE
request_buf: .res REQUEST_MAX
link_text = rx_buf + REPLY_TEXT ; the last reply's text

.segment "CODE"

; Last thing in the NMI. The stack holds Y, X and A above the flags and the
; address the NMI interrupted, which is replaced.
.macro link_nmi_hook
    lda rx_active
    beq :+
    tsx
    lda #<rx_abort
    sta $0105,x
    lda #>rx_abort
    sta $0106,x
:
.endmacro

.proc link_init
    rts
.endproc

; Search for query (query_len characters). Nothing is sent here: the next
; link_status sends it, and goes on sending it until the answer is in.
.proc link_search
    inc search_id
    rts
.endproc

; How is the search going? Carry clear and A = HOST_*; when it is
; HOST_READY, `total` is the article's length. Carry set if the host did
; not answer.
;
; The question is the search itself, with its id. The Stick starts on a
; search it has not seen and reports on one it has, so asking again is
; harmless, and a lost request or reply needs no handling of its own.
.proc link_status
    lda #OP_SEARCH
    sta request_buf + 1
    ldx query_len
    inx
    stx request_buf + 2
    lda search_id
    sta request_buf + 3
    ldx #0
@query:
    cpx query_len
    beq @send
    lda query,x
    sta request_buf + 4,x
    inx
    bne @query
@send:
    jsr exchange
    bcs @silent
    lda rx_buf + REPLY_LINE + 1
    cmp #NO_LINE
    bne @silent
    lda rx_buf + REPLY_LINE     ; about this search, or an older one?
    cmp search_id
    bne @silent
    lda rx_buf + REPLY_STATE
    and #HOST_MORE
    sta more
    lda rx_buf + REPLY_STATE
    and #HOST_STATE
    cmp #HOST_READY
    bne @done
    lda rx_buf + REPLY_TOTAL
    sta total
    lda rx_buf + REPLY_TOTAL + 1
    sta total + 1
    lda #HOST_READY
@done:
    clc
    rts
@silent:
    sec
    rts
.endproc

; Line `want` of the article into draw_buf. Carry set if it did not come.
; Any good reply leaves what the Stick says of itself in host_state, and
; if it holds the article, the article's length, which grows while it is
; still arriving (`more`).
.proc link_line
    lda #OP_LINE
    sta request_buf + 1
    lda #2
    sta request_buf + 2
    lda want
    sta request_buf + 3
    lda want + 1
    sta request_buf + 4
    jsr exchange
    bcs @failed
    lda rx_buf + REPLY_STATE
    and #HOST_STATE
    sta host_state
    cmp #HOST_READY
    bne @failed
    lda rx_buf + REPLY_STATE
    and #HOST_MORE
    sta more
    ; An article that is still arriving has grown since the last reply.
    lda rx_buf + REPLY_TOTAL
    cmp total
    bne @grew
    lda rx_buf + REPLY_TOTAL + 1
    cmp total + 1
    beq @line
@grew:
    lda rx_buf + REPLY_TOTAL
    sta total
    lda rx_buf + REPLY_TOTAL + 1
    sta total + 1
    jsr reader_resize
@line:
    lda rx_buf + REPLY_STATE
    bmi @failed                 ; bit 7: it has no such line
    lda rx_buf + REPLY_LINE
    cmp want
    bne @failed
    lda rx_buf + REPLY_LINE + 1
    cmp want + 1
    bne @failed
    ldx #COLUMNS - 1
@copy:
    lda link_text,x
    sta draw_buf,x
    dex
    bpl @copy
    clc
    rts
@failed:
    sec
    rts
.endproc

; Send the request in request_buf (its op, length and payload are set) and
; receive the reply into rx_buf. Carry clear if a whole reply came with a
; good CRC, set if not, or if the NMI cut the exchange off.
.proc exchange
    lda #REQUEST_MARKER
    sta request_buf
    ldx request_buf + 2         ; the CRC covers op, length and payload
    inx
    inx
    stx crc_count
    jsr crc_start
    ldy #1
@sum:
    lda request_buf,y
    jsr crc_update              ; preserves Y
    iny
    dec crc_count
    bne @sum
    lda crc_hi
    sta request_buf,y
    iny
    lda crc_lo
    sta request_buf,y
    iny
    sty request_len

    tsx
    stx saved_sp
    lda #1
    sta rx_active               ; from here the NMI may end this
    ldx #0
@send:
    lda request_buf,x
    jsr tx_byte                 ; preserves X
    inx
    cpx request_len
    bne @send
    jsr rx_block
    lda #0
    sta rx_active

    lda rx_buf
    cmp #REPLY_MARKER
    bne @bad
    jsr crc_start
    ldy #1
@check:
    lda rx_buf,y
    jsr crc_update
    iny
    cpy #REPLY_CRC
    bne @check
    lda crc_hi
    cmp rx_buf + REPLY_CRC
    bne @bad
    lda crc_lo
    cmp rx_buf + REPLY_CRC + 1
    bne @bad
    clc
    rts
@bad:
    sec
    rts
.endproc

; Where the NMI returns to when it cuts an exchange off: back to
; exchange's caller, with carry set. OUT0 may have been left low in the
; middle of a byte.
.proc rx_abort
    ldx saved_sp
    txs
    lda #0
    sta rx_active
    lda #OUT0_MARK
    sta JOY1
    sec
    rts
.endproc

; CRC-16/CCITT-FALSE.
.proc crc_start
    lda #$FF
    sta crc_hi
    sta crc_lo
    rts
.endproc

; Preserves Y.
.proc crc_update
    eor crc_hi
    tax
    lda crc_lo
    eor crc_table_hi,x
    sta crc_hi
    lda crc_table_lo,x
    sta crc_lo
    rts
.endproc

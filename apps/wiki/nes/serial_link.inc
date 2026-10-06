; Serial link: an M5Stack Stick on controller port 2 holds the article. The
; link ROM's host, in place of fake_link.inc.
;
; Provides link_init, link_search, link_status, link_line, link_text and
; the link_nmi_hook macro.
;
; The link itself is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md):
; one firmware on the Stick serves every ROM, and this one asks it for the
; WIKI service. Every use of the link is one exchange: a request goes out,
; and one reply comes back or does not. The NMI is the timeout: an exchange
; that has not ended by the next vblank is dropped there and reported as
; failed, and the caller asks again in a later frame.
;
; The Stick knows this ROM by its hello, which goes out before the first
; search and again whenever the Stick says it has no such service in use:
; it was switched off and on, and has forgotten the hello with the article.

NESP_RX_MASK = $3F              ; replies of up to 63 bytes: a line's is 33
NESP_TX_MAX  = 1 + QUERY_MAX    ; a search: its id and its words
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a line's reply is checked
                                ; in the frame it arrives in, with room to spare
.define NESP_APP "WIKI"
NESP_APP_VERSION = 2

.include "nesp.inc"

; WIKI's replies (nesp32's docs/PROTOCOL.md). To a search: its state, the
; search's id, the article's length, and with an error, words for the
; screen. To a line: the state, the line's number, the length, the line.
SEARCH_STATE = nesp_reply
SEARCH_ID    = nesp_reply + 1
SEARCH_TOTAL = nesp_reply + 2
link_text    = nesp_reply + 4   ; a failed search's message
LINE_STATE   = nesp_reply
LINE_NUMBER  = nesp_reply + 1
LINE_TOTAL   = nesp_reply + 3
LINE_TEXT    = nesp_reply + 5

.assert HOST_READY = NESP_ARTICLE_READY, error, "the ROM's states are WIKI's"
.assert HOST_ERROR = NESP_ARTICLE_ERROR, error, "the ROM's states are WIKI's"
.assert HOST_MORE = NESP_ARTICLE_MORE, error, "the ROM's states are WIKI's"
.assert HOST_STATE = NESP_ARTICLE_STATE, error, "the ROM's states are WIKI's"
.assert COLUMNS = NESP_WIKI_COLUMNS, error, "a line is as wide as the Stick lays it out"
.assert QUERY_MAX = NESP_WIKI_QUERY_MAX, error, "a search is as long as the Stick takes"

.segment "ZEROPAGE"
search_id:  .res 1              ; which search this is: a new one, a new id
greeted:    .res 1              ; the Stick has answered this ROM's hello

.segment "RODATA"
old_stick_text:                 ; COLUMNS wide, as the Stick's own messages are
    .byte " THE STICK NEEDS AN UPDATE  "
.assert * - old_stick_text = COLUMNS, error, "a message is a line wide"

.segment "CODE"

.macro link_nmi_hook
    nesp_nmi_hook
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
    lda greeted
    bne @search
    ; Hello first. This poll is then over; the next one searches.
    lda #NESP_SVC_WIKI
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs @silent
    cmp #NESP_ST_OK
    bne @old
    inc greeted
@silent:
    sec
    rts
@old:                           ; a firmware with no WIKI, or another protocol
    ldx #COLUMNS - 1
@text:
    lda old_stick_text,x
    sta link_text,x
    dex
    bpl @text
    lda #HOST_ERROR
    clc
    rts

@search:
    lda search_id
    sta nesp_request
    ldx #0
@query:
    cpx query_len
    beq @send
    lda query,x
    sta nesp_request + 1,x
    inx
    bne @query
@send:
    inx
    txa
    tay
    lda #NESP_SVC_WIKI
    ldx #NESP_WIKI_SEARCH
    jsr nesp_call
    bcs @silent
    cmp #NESP_ST_OK
    bne @refused
    lda SEARCH_ID               ; about this search, or an older one?
    cmp search_id
    bne @silent
    lda SEARCH_STATE
    and #HOST_MORE
    sta more
    lda SEARCH_STATE
    and #HOST_STATE
    cmp #HOST_READY
    bne @done
    lda SEARCH_TOTAL
    sta total
    lda SEARCH_TOTAL + 1
    sta total + 1
    lda #HOST_READY
@done:
    clc
    rts
@refused:                       ; the Stick has forgotten the hello: say it again
    lda #0
    sta greeted
    sec
    rts
.endproc

; Line `want` of the article into draw_buf. Carry set if it did not come.
; Any good reply leaves what the Stick says of itself in host_state, and
; if it holds the article, the article's length, which grows while it is
; still arriving (`more`).
.proc link_line
    lda want
    sta nesp_request
    lda want + 1
    sta nesp_request + 1
    lda #NESP_SVC_WIKI
    ldx #NESP_WIKI_LINE
    ldy #2
    jsr nesp_call
    bcs @failed
    cmp #NESP_ST_OK
    beq @heard
    ; The Stick no longer has the service in use, and so not the article.
    lda #0
    sta greeted
    lda #HOST_IDLE
    sta host_state
@failed:
    sec
    rts
@heard:
    lda LINE_STATE
    and #HOST_STATE
    sta host_state
    cmp #HOST_READY
    bne @failed
    lda LINE_STATE
    and #HOST_MORE
    sta more
    ; An article that is still arriving has grown since the last reply.
    lda LINE_TOTAL
    cmp total
    bne @grew
    lda LINE_TOTAL + 1
    cmp total + 1
    beq @line
@grew:
    lda LINE_TOTAL
    sta total
    lda LINE_TOTAL + 1
    sta total + 1
    jsr reader_resize
@line:
    lda LINE_STATE
    bmi @failed                 ; bit 7: it has no such line
    lda LINE_NUMBER
    cmp want
    bne @failed
    lda LINE_NUMBER + 1
    cmp want + 1
    bne @failed
    ldx #COLUMNS - 1
@copy:
    lda LINE_TEXT,x
    sta draw_buf,x
    dex
    bpl @copy
    clc
    rts
.endproc
.assert NESP_ARTICLE_NO_LINE = $80, error, "link_line tests bit 7 for a line not held"

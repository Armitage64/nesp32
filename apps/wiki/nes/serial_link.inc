; Serial link: an M5Stack Stick on controller port 2 holds the article. The
; link ROM's host, in place of fake_link.inc.
;
; Provides link_init, link_search, link_status, link_line, link_keys,
; link_text and the link_nmi_hook macro.
;
; The link itself is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md):
; one firmware on the Stick serves every ROM, and this one asks it for the
; WIKI service. Every use of the link is one exchange: a request goes out,
; and one reply comes back or does not. The NMI is the timeout: an exchange
; that has not ended by the next vblank is dropped there and reported as
; failed, and the caller asks again in a later frame.
;
; The Stick knows this ROM by its hello, which goes out from the search
; screen, before the first search, and again whenever the Stick says it has
; no such service in use: it was switched off and on, and has forgotten the
; hello with the article. The hello asks for KBD besides WIKI, so that what
; is typed on a Bluetooth keyboard paired with the nesp32 comes to the
; search; a nesp32 without KBD is used all the same, with the keyboard on
; the screen alone.

NESP_RX_MASK = $3F              ; replies of up to 63 bytes: a line's is 33
NESP_TX_MAX  = 1 + QUERY_MAX    ; a search: its id and its words
HELLO_EVERY  = 15               ; link_keys says hello at once, then every 16th call until answered
HELLO_MISSES = 2                ; hellos unanswered before the search is DEFAULT_QUERY
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a line's reply is checked
                                ; in the frame it arrives in, with room to spare
.define NESP_APP "WIKI"
NESP_APP_VERSION = 2
NESP_KEY_PAD = 1                ; the keyboard's keys as the controller's buttons

.include "nesp.inc"

link_key_queue = nesp_key_queue
link_key_next = nesp_key_next

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
.assert KEY_BACKSPACE = NESP_KEY_BACKSPACE, error, "the keyboard's keys are KBD's"
.assert KEY_ENTER = NESP_KEY_ENTER, error, "the keyboard's keys are KBD's"
.assert KEY_ESCAPE = NESP_KEY_ESCAPE, error, "the keyboard's keys are KBD's"
.assert KEY_UP = NESP_KEY_UP && KEY_DOWN = NESP_KEY_DOWN, error, "the keyboard's keys are KBD's"
.assert KEY_LEFT = NESP_KEY_LEFT && KEY_RIGHT = NESP_KEY_RIGHT, error, "the keyboard's keys are KBD's"
.assert KEY_PAGE_UP = NESP_KEY_PAGE_UP, error, "the keyboard's keys are KBD's"
.assert KEY_PAGE_DOWN = NESP_KEY_PAGE_DOWN, error, "the keyboard's keys are KBD's"
.assert KEY_START = NESP_KEY_START && KEY_SELECT = NESP_KEY_SELECT, error, "the keyboard's keys are KBD's"
.assert COLUMNS = NESP_WIKI_COLUMNS, error, "a line is as wide as the Stick lays it out"
.assert QUERY_MAX = NESP_WIKI_QUERY_MAX, error, "a search is as long as the Stick takes"

.segment "ZEROPAGE"
search_id:  .res 1              ; which search this is: a new one, a new id
greeted:    .res 1              ; the Stick has answered this ROM's hello
typing:     .res 1              ; and has KBD: what is typed comes to the search
kbd_asked:  .res 1              ; and has said whether a keyboard is paired
hello_wait: .res 1              ; link_keys's calls until its next hello
hello_missed: .res 1            ; hellos in a row with no answer

.segment "RODATA"
old_stick_text:                 ; COLUMNS wide, as the Stick's own messages are
    .byte " THE NESP32 NEEDS AN UPDATE "
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
    jsr link_hello
    bcc @old
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

; Hello, with WIKI and KBD. Carry set, and greeted, if the Stick answered
; with both, or with WIKI alone, which leaves typing 0. Carry clear if the
; Stick is one this ROM cannot use; carry set and nothing changed if it
; said nothing. Whatever says there is no keyboard to type with, a Stick
; without KBD or none that answers, puts DEFAULT_QUERY in the search.
.proc link_hello
    lda #NESP_SVC_WIKI
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED + 1
    ldy #2
    jsr nesp_hello
    bcs @silent
    ldx #0
    stx hello_missed
    inx
    cmp #NESP_ST_OK
    beq @greeted
    cmp #NESP_ST_NO_SERVICE     ; only KBD missing is a Stick to use
    bne @old
    lda nesp_reply + 6
    cmp #1
    bne @old
    lda nesp_reply + 7
    cmp #NESP_SVC_KBD
    bne @old
    ldx #0
@greeted:
    stx typing
    lda #1
    sta greeted
    txa
    bne @done                   ; whether a keyboard is paired is asked next
    jsr kb_default
@done:
    sec
    rts
@silent:
    inc hello_missed
    lda hello_missed
    cmp #HELLO_MISSES
    bcc @done
    jsr kb_default
    sec
    rts
@old:
    jsr kb_default
    clc
    rts
.endproc

; What has been typed on the nesp32's Bluetooth keyboard: carry clear, and
; A characters of it at link_typed. Carry set if there is nothing to have:
; no reply, no hello yet (which this says, at once and then now and
; again), or no KBD. The first call after the hello asks instead whether a
; keyboard is paired: if one is, the search's field stays empty
; (kb_paired), and if none is, it is DEFAULT_QUERY (kb_default).
link_typed = nesp_reply + 1

.proc link_keys
    lda greeted
    bne @greeted
    lda hello_wait
    beq @hello
    dec hello_wait
@none:
    sec
    rts
@hello:
    lda #HELLO_EVERY
    sta hello_wait
    jsr link_hello              ; an old Stick is for link_status to find out
    sec
    rts
@greeted:
    lda typing
    beq @none
    lda kbd_asked               ; first, once: is a keyboard paired?
    bne @keys
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_STATE
    ldy #0
    jsr nesp_call
    bcs @none
    cmp #NESP_ST_OK
    bne @forgot
    inc kbd_asked
    lda nesp_reply + 2          ; the length of its name: 0 for none paired
    bne @paired
    jsr kb_default
    sec
    rts
@paired:
    jsr kb_paired
    sec
    rts
@keys:
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr nesp_call
    bcs @none
    cmp #NESP_ST_OK
    bne @forgot
    lda nesp_reply
    cmp #NESP_KBD_KEYS_MAX + 1
    bcs @none
    clc
    rts
@forgot:                        ; the Stick was switched off and on
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

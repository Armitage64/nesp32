; Fake link: an article built into PRG ROM, standing in for the Stick. Used
; by the standalone ROM, which needs nothing on the controller port, so it
; runs in an emulator and on a flash cart.
;
; Provides what serial_link.inc does: link_init, link_search, link_status,
; link_line, link_keys, link_key_queue, link_key_next, link_text and the
; link_nmi_hook macro.
;
; Whatever is searched for, the answer is the built-in article, after a
; moment of "searching".

.include "article.inc"          ; ARTICLE_LINES

FAKE_POLLS = 6                  ; status polls a search takes: under a second

.segment "ZEROPAGE"
fake_wait: .res 1

.segment "BSS"
link_text: .res COLUMNS         ; a host's error message; this one has none

.segment "ARTICLE"
article_data:
    .incbin "article.bin"

.segment "RODATA"
; Everything reads the article through this, so the tests can point it at
; another without building the ROM again.
article_desc:
    .addr article_data
    .word ARTICLE_LINES

.segment "CODE"

.macro link_nmi_hook
.endmacro

.proc link_init
    jmp kb_default              ; no nesp32, and no keyboard
.endproc

; Search for query (query_len characters).
.proc link_search
    lda #FAKE_POLLS
    sta fake_wait
    rts
.endproc

; How is the search going? Carry clear and A = HOST_*; when it is
; HOST_READY, `total` is the article's length. Carry set if the host did
; not answer, which this one always does.
.proc link_status
    lda fake_wait
    beq @ready
    dec fake_wait
    lda #HOST_FETCHING
    clc
    rts
@ready:
    lda article_desc + 2
    sta total
    lda article_desc + 3
    sta total + 1
    lda #HOST_READY
    clc
    rts
.endproc

; There is no Bluetooth keyboard: nothing is ever typed on it.
link_typed = link_text

.proc link_keys
    sec
    rts
.endproc

; Nor kept as the controller's buttons.
.proc link_key_queue
    rts
.endproc

.proc link_key_next
    lda #0
    rts
.endproc

; Line `want` of the article into draw_buf. Carry set if it did not come.
; The line is at COLUMNS * want = 32 * want - 4 * want.
.proc link_line
    lda want
    sta ptr
    lda want + 1
    sta ptr + 1
    asl ptr
    rol ptr + 1
    asl ptr
    rol ptr + 1                 ; 4 * want
    lda ptr
    sta tmp
    lda ptr + 1
    sta tmp + 1
    asl ptr
    rol ptr + 1
    asl ptr
    rol ptr + 1
    asl ptr
    rol ptr + 1                 ; 32 * want
    sec
    lda ptr
    sbc tmp
    sta ptr
    lda ptr + 1
    sbc tmp + 1
    sta ptr + 1
    clc
    lda ptr
    adc article_desc
    sta ptr
    lda ptr + 1
    adc article_desc + 1
    sta ptr + 1
    ldy #COLUMNS - 1
@copy:
    lda (ptr),y
    sta draw_buf,y
    dey
    bpl @copy
    clc
    rts
.endproc
.assert COLUMNS = 28, error, "link_line multiplies by 28"

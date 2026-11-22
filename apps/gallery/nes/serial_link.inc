; The link: a nesp32 on controller port 2, with its COMMONS service.
;
; Provides link_search, link_status, link_caption, link_open, link_data,
; link_keys, link_text and the link_nmi_hook macro.
;
; The link itself is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md):
; one firmware serves every ROM, and this one asks it for COMMONS. Every use
; of the link is one exchange: a request goes out, and one reply comes back
; or does not. The NMI is the timeout: an exchange that has not ended by
; the next vblank is dropped there and reported as failed, and the caller
; asks again in a later frame.
;
; The nesp32 knows this ROM by its hello, which goes out from the search
; screen, before the first search, and again whenever the nesp32 says it
; has no such service in use: it was switched off and on, and has forgotten
; the hello with the pictures. The hello asks for KBD besides COMMONS, so
; that what is typed on a Bluetooth keyboard paired with the nesp32 comes
; to the search; a nesp32 without KBD is used all the same.
;
; NESpedia's serial_link.inc (apps/wiki), with COMMONS's requests in place
; of WIKI's.

NESP_RX_MASK = $7F              ; replies of up to 127 bytes: DATA's is 68
NESP_TX_MAX  = 1 + QUERY_MAX    ; a search: its id and its words
HELLO_EVERY  = 15               ; link_keys says hello at once, then every 16th call until answered
HELLO_MISSES = 2                ; hellos unanswered before the search is DEFAULT_QUERY
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a reply is checked in the frame it arrives in
.define NESP_APP "GALL"
NESP_APP_VERSION = 1
NESP_KEY_PAD = 1                ; the keyboard's keys as the controller's buttons

.include "nesp.inc"

link_key_queue = nesp_key_queue
link_key_next = nesp_key_next

; COMMONS's replies (nesp32's docs/PROTOCOL.md).
SEARCH_STATE = nesp_reply       ; to a search: its state, its id, the pictures found,
SEARCH_ID    = nesp_reply + 1   ; and with FAILED words for the screen
SEARCH_COUNT = nesp_reply + 2
link_text    = nesp_reply + 3   ; a failed search's message, or a picture's
CAPTION_STATE = nesp_reply      ; to a caption: the state, the picture, the line, the words
CAPTION_INDEX = nesp_reply + 1
CAPTION_LINE  = nesp_reply + 2
CAPTION_TEXT  = nesp_reply + 3
OPEN_STATE   = nesp_reply       ; to an open: the picture's state, the id, the picture
OPEN_ID      = nesp_reply + 1
OPEN_INDEX   = nesp_reply + 2
DATA_STATE   = nesp_reply       ; to DATA: the state, the picture, the offset, the bytes
DATA_INDEX   = nesp_reply + 1
DATA_OFFSET  = nesp_reply + 2
DATA_BYTES   = nesp_reply + 4

.assert HOST_READY = NESP_ALBUM_READY && HOST_FAILED = NESP_ALBUM_FAILED, error, "the ROM's states are COMMONS's"
.assert HOST_SEARCHING = NESP_ALBUM_SEARCHING && HOST_NOT_FOUND = NESP_ALBUM_NOT_FOUND, error, "the ROM's states are COMMONS's"
.assert HOST_NO_WIFI = NESP_ALBUM_NO_WIFI && HOST_IDLE = NESP_ALBUM_IDLE, error, "the ROM's states are COMMONS's"
.assert PHOTO_FETCHING = NESP_PHOTO_FETCHING && PHOTO_READY = NESP_PHOTO_READY, error, "the ROM's states are COMMONS's"
.assert PHOTO_FAILED = NESP_PHOTO_FAILED && PHOTO_NO_WIFI = NESP_PHOTO_NO_WIFI, error, "the ROM's states are COMMONS's"
.assert KEY_BACKSPACE = NESP_KEY_BACKSPACE, error, "the keyboard's keys are KBD's"
.assert KEY_ENTER = NESP_KEY_ENTER, error, "the keyboard's keys are KBD's"
.assert KEY_ESCAPE = NESP_KEY_ESCAPE, error, "the keyboard's keys are KBD's"
.assert KEY_UP = NESP_KEY_UP && KEY_DOWN = NESP_KEY_DOWN, error, "the keyboard's keys are KBD's"
.assert KEY_LEFT = NESP_KEY_LEFT && KEY_RIGHT = NESP_KEY_RIGHT, error, "the keyboard's keys are KBD's"
.assert KEY_START = NESP_KEY_START && KEY_SELECT = NESP_KEY_SELECT, error, "the keyboard's keys are KBD's"
.assert COLUMNS = NESP_COMMONS_COLUMNS, error, "a line is as wide as the nesp32's"
.assert QUERY_MAX = NESP_COMMONS_QUERY_MAX, error, "a search is as long as the nesp32 takes"
.assert CAPTION_LINES = NESP_COMMONS_LINES, error, "a picture has as many lines as the nesp32 gives"

.segment "ZEROPAGE"
search_id:  .res 1              ; which search this is: a new one, a new id
open_id:    .res 1              ; which showing of a picture: a new one, a new id
greeted:    .res 1              ; the nesp32 has answered this ROM's hello
typing:     .res 1              ; and has KBD: what is typed comes to the search
kbd_asked:  .res 1              ; and has said whether a keyboard is paired
hello_wait: .res 1              ; link_keys's calls until its next hello
hello_missed: .res 1            ; hellos in a row with no answer

.segment "RODATA"
old_stick_text:                 ; COLUMNS wide, as the nesp32's own messages are
    .byte " THE NESP32 NEEDS AN UPDATE "
.assert * - old_stick_text = COLUMNS, error, "a message is a line wide"

.segment "CODE"

.macro link_nmi_hook
    nesp_nmi_hook
.endmacro

; Search for query (query_len characters). Nothing is sent here: the next
; link_status sends it, and goes on sending it until the answer is in.
.proc link_search
    inc search_id
    rts
.endproc

; How is the search going? Carry clear and A = HOST_*; when it is
; HOST_READY, `count` is how many pictures it found, and with HOST_FAILED
; link_text says why. Carry set if the nesp32 did not answer.
.proc link_status
    lda greeted
    bne @search
    jsr link_hello              ; hello first; the next poll searches
    bcc @old
@silent:
    sec
    rts
@old:                           ; a firmware with no COMMONS, or another protocol
    ldx #COLUMNS - 1
@text:
    lda old_stick_text,x
    sta link_text,x
    dex
    bpl @text
    lda #HOST_FAILED
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
    lda #NESP_SVC_COMMONS
    ldx #NESP_COMMONS_SEARCH
    jsr nesp_call
    bcs @silent
    cmp #NESP_ST_OK
    bne @refused
    lda SEARCH_ID               ; about this search, or an older one?
    cmp search_id
    bne @silent
    lda SEARCH_COUNT
    sta count
    lda SEARCH_STATE
    clc
    rts
@refused:                       ; the nesp32 has forgotten the hello: say it again
    lda #0
    sta greeted
    sec
    rts
.endproc

; Line Y of picture `index`'s words, staged in draw_buf for its row of the
; info page. Carry set if it did not come; A = HOST_IDLE if it came and
; the nesp32 no longer has the search.
.proc link_caption
    sty tmp
    lda index
    sta nesp_request
    sty nesp_request + 1
    lda #NESP_SVC_COMMONS
    ldx #NESP_COMMONS_CAPTION
    ldy #2
    jsr nesp_call
    bcs @failed
    cmp #NESP_ST_OK
    bne @forgot
    lda CAPTION_INDEX
    cmp index
    bne @failed
    lda CAPTION_LINE
    cmp tmp
    bne @failed
    lda CAPTION_STATE
    bmi @lost                   ; no such line: the search is gone
    ldx #COLUMNS - 1
@copy:
    lda CAPTION_TEXT,x
    sta draw_buf,x
    dex
    bpl @copy
    ldy tmp
    lda caption_lo,y
    sta draw_addr
    lda caption_hi,y
    sta draw_addr + 1
    lda #COLUMNS
    sta draw_len
    clc
    rts
@forgot:
    lda #0
    sta greeted
@lost:
    lda #HOST_IDLE
    clc
    rts
@failed:
    sec
    rts
.endproc
.assert NESP_ALBUM_NO_LINE = $80, error, "link_caption tests bit 7 for a line not held"

; How is picture `index` going? The first call after a new open_id starts
; it on the nesp32. Carry clear and A = PHOTO_*, with PHOTO_FAILED's words
; in link_text; carry set if the nesp32 did not answer.
.proc link_open
    lda open_id
    sta nesp_request
    lda index
    sta nesp_request + 1
    lda #NESP_SVC_COMMONS
    ldx #NESP_COMMONS_OPEN
    ldy #2
    jsr nesp_call
    bcs @failed
    cmp #NESP_ST_OK
    bne @forgot
    lda OPEN_ID
    cmp open_id
    bne @failed
    lda OPEN_INDEX
    cmp index
    bne @failed
    lda OPEN_STATE
    clc
    rts
@forgot:
    lda #0
    sta greeted
    lda #PHOTO_IDLE
    clc
    rts
@failed:
    sec
    rts
.endproc

; The picture's bytes from load_at. Carry clear and A = how many there are
; at DATA_BYTES, 0 if the nesp32 has none for it (the picture is no longer
; ready); carry set if no good answer came.
.proc link_data
    lda index
    sta nesp_request
    lda load_at
    sta nesp_request + 1
    lda load_at + 1
    sta nesp_request + 2
    lda #NESP_SVC_COMMONS
    ldx #NESP_COMMONS_DATA
    ldy #3
    jsr nesp_call
    bcs @failed
    cmp #NESP_ST_OK
    bne @none
    lda DATA_INDEX
    cmp index
    bne @failed
    lda DATA_OFFSET
    cmp load_at
    bne @failed
    lda DATA_OFFSET + 1
    cmp load_at + 1
    bne @failed
    lda DATA_STATE
    bmi @none                   ; no bytes: the picture is not ready
    lda nesp_reply_len
    sec
    sbc #DATA_BYTES - nesp_reply
    clc
    rts
@none:
    lda #0
    clc
    rts
@failed:
    sec
    rts
.endproc
.assert NESP_PHOTO_NO_DATA = $80, error, "link_data tests bit 7 for no bytes"

; Hello, with COMMONS and KBD. Carry set, and greeted, if the nesp32
; answered with both, or with COMMONS alone, which leaves typing 0. Carry
; clear if the nesp32 is one this ROM cannot use; carry set and nothing
; changed if it said nothing. Whatever says there is no keyboard to type
; with puts DEFAULT_QUERY in the search.
.proc link_hello
    lda #NESP_SVC_COMMONS
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
    cmp #NESP_ST_NO_SERVICE     ; only KBD missing is a nesp32 to use
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
    jsr link_hello              ; an old nesp32 is for link_status to find out
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
@forgot:                        ; the nesp32 was switched off and on
    lda #0
    sta greeted
    sec
    rts
.endproc

; Is there newer firmware than the Stick's? The status screen asks the web
; site, once it has a Stick on Wi-Fi whose hello had HTTP: it fetches the
; flash page's manifest (tools/gen_web.py writes it, for ESP Web Tools),
; whose "version" is the latest release's, and compares it with the version
; the Stick's hello gave. If the site's is newer, FIRMWARE UPDATE AVAILABLE
; goes under the title, in red, in the header, which no screen clears. Red is
; the title's palette's second colour, so the line is in the font's tiles in
; the second colour (ALT).
;
; One request a frame, on the status screen's frames that nothing else has
; (status_frame): the address in pieces, GET until the fetch is over, then
; READ from the start of the body until "version" has gone by. If anything
; goes wrong (no Wi-Fi in the end, no answer from the site, a status that is
; not 200, no version near the start) the check gives up until Setup is run
; again, and says nothing rather than something wrong. The line is staged on
; the same frames, when nothing else is.

UPDATE_IDLE = 0                 ; not begun: waiting for a Stick on Wi-Fi with HTTP
UPDATE_URL  = 1                 ; sending the address
UPDATE_GET  = 2                 ; fetching it
UPDATE_READ = 3                 ; reading the body
UPDATE_OVER = 4                 ; the latest is known, or the check gave up

UPDATE_PIECE = NESP_TX_MAX - 1  ; of the address a request takes, after AT
UPDATE_CHUNK = NESP_RX_MASK - 3 ; of the body a READ's reply takes, after its fixed part
UPDATE_LOOK  = 200              ; how far into the body "version" may be

; Where update_byte is in the body.
PHASE_KEY = 0                   ; looking for "version"
PHASE_SEP = 1                   ; past it: a colon and spaces, to the opening quote
PHASE_NUM = 2                   ; in the number: major.minor.patch

.segment "BSS"
update_step:    .res 1          ; UPDATE_*
update_id:      .res 1          ; the GET's id: another for every check begun
update_at:      .res 1          ; how much of the address is sent, or of the body read
update_count:   .res 1          ; bytes in this READ's reply, or in this piece
update_index:   .res 1
update_phase:   .res 1          ; PHASE_*
update_match:   .res 1          ; how much of "version" has matched
update_part:    .res 1          ; which of the version's numbers
update_digit:   .res 1
update_tmp:     .res 1
latest_known:   .res 1          ; latest_version is the site's
latest_version: .res 3          ; major, minor, patch
update_want:    .res 1          ; 1 if the line should be up
update_drawn:   .res 1          ; and whether it is

.segment "RODATA"
update_url_text: .byte "https://nesp32.retrobits.tv/flash/manifest.json"
UPDATE_URL_LEN = * - update_url_text
.assert UPDATE_URL_LEN < 256, error, "the address's AT is a byte"
update_key:      .byte '"', "version", '"'
UPDATE_KEY_LEN = * - update_key
.define UPDATE_TEXT "FIRMWARE UPDATE AVAILABLE"
update_says:
.repeat .strlen(UPDATE_TEXT), index
    .byte .strat(UPDATE_TEXT, index) | ALT
.endrepeat
UPDATE_SAYS_LEN = * - update_says
UPDATE_COLUMN = (32 - UPDATE_SAYS_LEN) / 2  ; centred on the screen, as the title is

.segment "CODE"

; The status screen is up, or the Stick has just answered a hello: a check
; that was under way begins again, since a hello forgets the address and
; another screen may have had the link, and newer firmware is said again.
.proc update_open
    lda update_step
    cmp #UPDATE_OVER
    beq update_show
    lda #UPDATE_IDLE
    sta update_step
    ; fall through
.endproc

; Whether FIRMWARE UPDATE AVAILABLE should be up: if the site's firmware is newer
; than the Stick's. Only once both are known; update_frame draws it.
.proc update_show
    lda latest_known
    beq @done
    lda linked
    beq @done
    ldy #0
    ldx #0
@compare:
    lda stick_version,x
    cmp latest_version,x
    bcc @newer
    bne @want                   ; the Stick's is newer: one being made
    inx
    cpx #3
    bne @compare
    beq @want
@newer:
    iny
@want:
    sty update_want
@done:
    rts
.endproc

; The line, or blanks where it was, staged for the next NMI.
.proc update_draw
    ldx #0
@char:
    lda #TILE_BLANK
    ldy update_want
    beq @put
    lda update_says,x
@put:
    sta draw_buf,x
    inx
    cpx #UPDATE_SAYS_LEN
    bne @char
    at UPDATE_ROW, UPDATE_COLUMN
    stx draw_len
    lda update_want
    sta update_drawn
    rts
.endproc

; The status screen's turn for the check: one request, or none.
.proc update_frame
    lda update_drawn
    cmp update_want
    beq @check
    lda draw_len
    bne @check
    jmp update_draw
@check:
    lda linked
    beq @done
    lda stick_http
    beq @done
    ldx update_step
    beq @idle
    cpx #UPDATE_URL
    bne @get
    jmp update_url
@get:
    cpx #UPDATE_GET
    bne @read
    jmp update_get
@read:
    cpx #UPDATE_READ
    bne @done
    jmp update_read
@idle:
    lda STICK_WIFI
    cmp #NESP_WIFI_JOINED
    bne @done
    lda #0
    sta update_at
    inc update_id               ; a new GET, not the last one again
    lda #UPDATE_URL
    sta update_step
@done:
    rts
.endproc

.proc update_give_up
    lda #UPDATE_OVER
    sta update_step
    sec
    rts
.endproc

; The address, a piece at a time, each at the length sent so far. A piece
; that has no answer is sent again.
.proc update_url
    lda #UPDATE_URL_LEN
    sec
    sbc update_at
    cmp #UPDATE_PIECE + 1
    bcc @fits
    lda #UPDATE_PIECE
@fits:
    sta update_count
    ldx update_at
    stx nesp_request
    ldy #0
@copy:
    lda update_url_text,x
    sta nesp_request + 1,y
    inx
    iny
    cpy update_count
    bne @copy
    iny                         ; and AT
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_URL
    jsr call
    bcs @done
    lda nesp_status
    bne update_give_up
    lda update_at
    clc
    adc update_count
    sta update_at
    cmp #UPDATE_URL_LEN
    bne @done
    lda #UPDATE_GET
    sta update_step
@done:
    rts
.endproc

; GET, the same one again until the fetch is over.
.proc update_get
    lda update_id
    sta nesp_request
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_GET
    ldy #1
    jsr call
    bcs @done
    lda nesp_status
    bne update_give_up
    lda nesp_reply              ; the fetch's state
    cmp #NESP_FETCH_NO_WIFI
    beq @offline
    cmp #NESP_FETCH_FAILED
    beq update_give_up
    cmp #NESP_FETCH_DONE
    bne @done
    lda nesp_reply + 2          ; the site's status, low byte first
    cmp #<200
    bne update_give_up
    lda nesp_reply + 3
    bne update_give_up
    lda #0
    sta update_at
    sta update_phase
    sta update_match
    lda #UPDATE_READ
    sta update_step
@done:
    rts
@offline:                       ; it left the network: again once it is back
    lda #UPDATE_IDLE
    sta update_step
    rts
.endproc

; The body, from its start, a reply at a time, each byte to update_byte.
.proc update_read
    lda update_at
    sta nesp_request
    lda #0
    sta nesp_request + 1
    lda #UPDATE_CHUNK
    sta nesp_request + 2
    lda #NESP_SVC_HTTP
    ldx #NESP_HTTP_READ
    ldy #3
    jsr call
    bcs @done
    lda nesp_status
    bne @give_up
    lda nesp_reply_len
    sec
    sbc #3
    beq @give_up                ; the body is over, and no version in it
    bcc @give_up
    sta update_count
    ldx #0
@byte:
    stx update_index
    lda nesp_reply + 3,x
    jsr update_byte
    bcs @done                   ; found, or not a version
    ldx update_index
    inx
    cpx update_count
    bne @byte
    lda update_at
    clc
    adc update_count
    sta update_at
    cmp #UPDATE_LOOK
    bcs @give_up
@done:
    rts
@give_up:
    jmp update_give_up
.endproc

; One byte of the body, A. Carry set once the check is over.
.proc update_byte
    ldx update_phase
    beq @key
    dex
    beq @sep
    cmp #'.'
    beq @dot
    sec
    sbc #'0'
    cmp #10
    bcs @end
    sta update_digit
    ldx update_part
    lda latest_version,x        ; times ten, and the digit
    asl a
    sta update_tmp
    asl a
    asl a
    clc
    adc update_tmp
    adc update_digit
    sta latest_version,x
    clc
    rts
@dot:
    inc update_part
    lda update_part
    cmp #3
    bcs @give_up
    clc
    rts
@end:                           ; the number is over: a quote, or -rc.1 and the like
    lda update_part
    cmp #2
    bne @give_up
    lda #1
    sta latest_known
    lda #UPDATE_OVER
    sta update_step
    jsr update_show
    sec
    rts
@give_up:
    jmp update_give_up

@key:
    ldx update_match
    cmp update_key,x
    bne @mismatch
    inx
    stx update_match
    cpx #UPDATE_KEY_LEN
    bne @more
    lda #PHASE_SEP
    sta update_phase
@more:
    clc
    rts
@mismatch:                      ; a quote may begin it again
    ldx #0
    cmp #'"'
    bne @from
    inx
@from:
    stx update_match
    clc
    rts

@sep:
    cmp #' '
    beq @more
    cmp #':'
    beq @more
    cmp #'"'
    bne @not
    lda #PHASE_NUM
    sta update_phase
    lda #0
    sta update_part
    sta latest_version
    sta latest_version + 1
    sta latest_version + 2
    clc
    rts
@not:                           ; "version" was something else's
    lda #PHASE_KEY
    sta update_phase
    lda #0
    sta update_match
    clc
    rts
.endproc

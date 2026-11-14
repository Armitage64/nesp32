; Is the firmware, or the cartridge, older than it should be? Three versions
; are compared: the cartridge's own (VERSION, as tools/version.py put it in
; nesp_version.inc), the firmware's, which the nesp32's hello gives, and the
; latest release's, which the web site has. Whichever is the newest, the
; firmware or the cartridge that is older than it needs an update, and the
; line under the title says which:
;
;   FIRMWARE UPDATE AVAILABLE
;   CARTRIDGE UPDATE AVAILABLE
;   UPDATES AVAILABLE
;
; The firmware and the cartridge are released together, with one number, so
; the two alone say when one was updated and the other was not: that needs
; no network. The web site says when both are behind. Its version is the
; flash page's manifest's (tools/gen_web.py writes it, for ESP Web Tools),
; fetched with HTTP once the nesp32's hello has it and it is on Wi-Fi: the
; address in pieces, GET until the fetch is over, then READ from the start
; of the body until "version" has gone by. If anything goes wrong (no
; answer from the site, a status that is not 200, no version near the
; start) the menu gives up on the site until it comes up again, and says
; only what the other two say. GET finding no Wi-Fi is asked again a little
; later. One request a frame, on the frames the keyboard's are not on
; (link_frame).
;
; The line is in the font's tiles in the second colour (ALT): red, in the
; title's palette (apps/setup/tools/gen_screen.py). update_draw stages it
; and the NMI writes it.

UPDATE_IDLE = 0                 ; not begun: waiting for a hello with HTTP
UPDATE_URL  = 1                 ; sending the address
UPDATE_GET  = 2                 ; fetching it
UPDATE_READ = 3                 ; reading the body
UPDATE_WAIT = 4                 ; no Wi-Fi: GET again later
UPDATE_OVER = 5                 ; the latest is known, or the check gave up

UPDATE_PIECE = NESP_TX_MAX - 1  ; of the address a request takes, after AT
UPDATE_CHUNK = NESP_RX_MASK - 3 ; of the body a READ's reply takes, after its fixed part
UPDATE_LOOK  = 200              ; how far into the body "version" may be
UPDATE_RETRY = 60               ; the check's turns between GETs with no Wi-Fi: about 2 s

; Where update_byte is in the body.
PHASE_KEY = 0                   ; looking for "version"
PHASE_SEP = 1                   ; past it: a colon and spaces, to the opening quote
PHASE_NUM = 2                   ; in the number: major.minor.patch

; In versions: each major, minor, patch.
VERSION_CART   = 0
VERSION_STICK  = 3
VERSION_SITE   = 6
VERSION_NEWEST = 9

; update_want's bits: what is out of date.
WANT_FIRMWARE  = 1
WANT_CART      = 2

.segment "BSS"
update_step:    .res 1          ; UPDATE_*
update_id:      .res 1          ; the GET's id: another for every one begun
update_at:      .res 1          ; how much of the address is sent, or of the body read
update_count:   .res 1          ; bytes in this READ's reply, or in this piece; turns to wait
update_index:   .res 1
update_phase:   .res 1          ; PHASE_*
update_match:   .res 1          ; how much of "version" has matched
update_part:    .res 1          ; which of the version's numbers
update_digit:   .res 1
update_tmp:     .res 1
stick_http:     .res 1          ; the nesp32's hello had HTTP
stick_known:    .res 1          ; versions + VERSION_STICK is the firmware's
site_known:     .res 1          ; and + VERSION_SITE the web site's
versions:       .res 12         ; VERSION_*
update_want:    .res 1          ; WANT_*: the line that should be up
update_drawn:   .res 1          ; and the one that is, or is staged

.segment "RODATA"
update_url_text: .byte "https://nesp32.retrobits.tv/flash/manifest.json"
UPDATE_URL_LEN = * - update_url_text
.assert UPDATE_URL_LEN < 256, error, "the address's AT is a byte"
update_key:      .byte '"', "version", '"'
UPDATE_KEY_LEN = * - update_key
cart_version:    .byte NESP_VERSION_MAJOR, NESP_VERSION_MINOR, NESP_VERSION_PATCH

; A line of WIDTH tiles from LEFT, its text centred on the screen as the
; title is, in the second colour.
.macro update_line text
    .local column
    column = (32 - .strlen(text)) / 2
    .assert column >= LEFT, error, "the line is wider than the screen's safe part"
    .res column - LEFT, TILE_BLANK
    .repeat .strlen(text), index
        .byte .strat(text, index) | ALT
    .endrepeat
    .res LEFT + WIDTH - column - .strlen(text), TILE_BLANK
.endmacro

update_lines:                   ; by update_want
    .res WIDTH, TILE_BLANK
    update_line "FIRMWARE UPDATE AVAILABLE"
    update_line "CARTRIDGE UPDATE AVAILABLE"
    update_line "UPDATES AVAILABLE"
.assert * - update_lines = 4 * WIDTH, error, "each line is WIDTH tiles"

.segment "CODE"

; At reset: the cartridge's version, and the newest known so far.
.proc update_init
    ldx #2
@copy:
    lda cart_version,x
    sta versions + VERSION_CART,x
    dex
    bpl @copy
    rts
.endproc

; The nesp32 has answered a hello, which forgets the address: a check that
; was under way begins again. Then what is out of date, with its version.
.proc update_greeted
    lda update_step
    cmp #UPDATE_OVER
    beq update_show
    lda #UPDATE_IDLE
    sta update_step
    ; fall through
.endproc

; update_want, from the versions that are known.
.proc update_show
    ldx #2                      ; the newest: the cartridge's,
@cart:
    lda versions + VERSION_CART,x
    sta versions + VERSION_NEWEST,x
    dex
    bpl @cart
    lda stick_known             ; the firmware's if that is newer,
    beq @site
    ldx #VERSION_STICK
    jsr newest
@site:
    lda site_known              ; and the site's if that is
    beq @compare
    ldx #VERSION_SITE
    jsr newest
@compare:
    lda #0
    sta update_tmp
    lda stick_known
    beq @cart_old
    ldx #VERSION_STICK
    jsr older
    bcs @cart_old
    lda #WANT_FIRMWARE
    sta update_tmp
@cart_old:
    ldx #VERSION_CART
    jsr older
    bcs @want
    lda update_tmp
    ora #WANT_CART
    sta update_tmp
@want:
    lda update_tmp
    sta update_want
    rts
.endproc

; Carry clear if the version at versions + X is older than the newest.
.proc older
    ldy #VERSION_NEWEST
    lda #3
    sta update_count
@part:
    lda versions,x
    cmp versions,y
    bne @done                   ; carry: clear if older, set if newer
    inx
    iny
    dec update_count
    bne @part
    sec                         ; the same
@done:
    rts
.endproc

; The version at versions + X is the newest, if it is newer.
.proc newest
    stx update_index
    jsr older
    bcc @done
    ldx update_index
    ldy #0
@copy:
    lda versions,x
    sta versions + VERSION_NEWEST,y
    inx
    iny
    cpy #3
    bne @copy
@done:
    rts
.endproc

; Once a frame: the line that should be up, staged for the NMI, if it is
; not the one that is and the NMI has written the last.
.proc update_draw
    lda line_staged
    bne @done
    lda update_want
    cmp update_drawn
    beq @done
    sta update_drawn
    tax
    lda #<update_lines
    sta line_ptr
    lda #>update_lines
    sta line_ptr + 1
@line:                          ; WIDTH times update_want on
    dex
    bmi @staged
    lda line_ptr
    clc
    adc #WIDTH
    sta line_ptr
    bcc @line
    inc line_ptr + 1
    bne @line
@staged:
    lda #1
    sta line_staged
@done:
    rts
.endproc

; The check's turn: one request, or none.
.proc update_frame
    lda stick_http
    beq @done
    ldx update_step
    beq @begin
    cpx #UPDATE_URL
    bne @get
    jmp update_url
@get:
    cpx #UPDATE_GET
    bne @read
    jmp update_get
@read:
    cpx #UPDATE_READ
    bne @wait
    jmp update_read
@wait:
    cpx #UPDATE_WAIT
    bne @done
    dec update_count
    bne @done
    inc update_id               ; a new GET, not the last one again
    lda #UPDATE_GET
    sta update_step
@done:
    rts
@begin:
    lda #0
    sta update_at
    inc update_id
    lda #UPDATE_URL
    sta update_step
    rts
.endproc

; A request of the check's: carry clear if the nesp32 said OK. No reply is
; one more miss, and it is sent again; anything else ends the check.
.proc update_call
    jsr nesp_call
    bcs @missed
    ldx #0
    stx misses
    cmp #NESP_ST_OK
    bne update_give_up
    clc
    rts
@missed:
    jsr missed
    sec
    rts
.endproc

.proc update_give_up
    lda #UPDATE_OVER
    sta update_step
    sec
    rts
.endproc

; The address, a piece at a time, each at the length sent so far.
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
    jsr update_call
    bcs @done
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
    jsr update_call
    bcs @done
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
@offline:                       ; not on a network yet: again in a while
    lda #UPDATE_RETRY
    sta update_count
    lda #UPDATE_WAIT
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
    jsr update_call
    bcs @done
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
    lda versions + VERSION_SITE,x   ; times ten, and the digit
    asl a
    sta update_tmp
    asl a
    asl a
    clc
    adc update_tmp
    adc update_digit
    sta versions + VERSION_SITE,x
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
    sta site_known
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
    sta versions + VERSION_SITE
    sta versions + VERSION_SITE + 1
    sta versions + VERSION_SITE + 2
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

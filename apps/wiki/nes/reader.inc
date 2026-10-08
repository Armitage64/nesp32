; The reader: an article in a window of WINDOW_ROWS lines, scrolled by the
; pixel.
;
;   Up, Down         scroll, SCROLL_STEPS pixels a frame while held
;   Right or A       a page down, gliding at GLIDE_STEPS pixels a frame
;   Left or B        a page up
;   Start            back to the top of the article
;   Select           back to the search screen
;
; Nametable 0 is a ring of RING_ROWS lines: line n of the article is in row
; n mod RING_ROWS, and the ring holds lines lo to hi - 1. The window shows
; lines top to top + WINDOW_ROWS (the last only while `fine` is not 0), so
; RING_ROWS - WINDOW_ROWS - 1 = 7 rows are spare, and they hold lines
; fetched ahead of the window in the direction it last moved and a couple
; behind it.
;
; Two rules keep the screen right whatever the host does:
;
;   - The window only moves onto lines the ring holds. With a slow host or
;     a lost reply the scroll waits; it never shows an old row.
;   - A line is only fetched into a row outside the window, so nothing is
;     seen changing. reader_fetch's limits make that so; see there.
;
; At most one line is fetched a frame, and the window moves at most
; GLIDE_STEPS = 4 pixels a frame, so it needs a line every other frame.
;
; An article shorter than the window is followed by blank lines up to
; `limit`, made here and not asked for, so the window is always full.

SCROLL_STEPS = 2
GLIDE_STEPS  = 4
PAGE_PIXELS  = 8 * (WINDOW_ROWS - 2)    ; a page keeps two lines in view
AHEAD  = 5                      ; lines wanted beyond the window, the way it moves
BEHIND = 2                      ; and the other way
.assert WINDOW_ROWS + 1 + AHEAD + BEHIND = RING_ROWS, error, "the ring's spare rows"

GROWTH_POLL  = $0F              ; frames between asking how long a growing article is

STEP_MOVED   = 0                ; what step_down and step_up return
STEP_WAITING = 1                ; the next line is not in the ring yet
STEP_END     = 2                ; the article goes no further

.segment "ZEROPAGE"
total:     .res 2               ; lines in the article; the link sets it
limit:     .res 2               ; total, or WINDOW_ROWS + 1 if that is more
max_top:   .res 2               ; the largest `top`: the last line at the bottom
top:       .res 2               ; the line at the top of the window
fine:      .res 1               ; pixels of it scrolled off: 0-7
lo:        .res 2               ; the ring holds lines lo .. hi - 1
hi:        .res 2
lo_row:    .res 1               ; lo mod RING_ROWS
hi_row:    .res 1
held:      .res 1               ; hi - lo
going_up:  .res 1               ; the way the window last moved
glide:     .res 1               ; pixels of a page still to go
glide_up:  .res 1
want:      .res 2               ; the line being fetched
want_row:  .res 1
thumb_top: .res 2               ; `top` when the thumb was last placed
steps:     .res 1
product:   .res 3
factor:    .res 1

.segment "CODE"

; The link has an article of `total` lines. Start at its top with an empty
; ring; opening_frame fills it.
.proc reader_open
    jsr reader_resize
    lda #0
    sta top
    sta top + 1
    sta fine
    sta ring_y
    sta lo
    sta lo + 1
    sta hi
    sta hi + 1
    sta lo_row
    sta hi_row
    sta held
    sta going_up
    sta glide
    sta stall
    sta stall + 1
    lda #STATUS_LOADING
    jsr set_status
    lda #STATE_OPENING
    sta state
    rts
.endproc

; Work out `limit` and `max_top` from `total`: when an article opens, and
; each time one that is still arriving turns out longer.
.proc reader_resize
    lda #$FF                    ; no line: the thumb is placed afresh
    sta thumb_top
    sta thumb_top + 1
    lda total
    sta limit
    sta max_top
    lda total + 1
    sta limit + 1
    sta max_top + 1
    bne @long
    lda total
    cmp #WINDOW_ROWS + 1
    bcs @long
    lda #WINDOW_ROWS + 1        ; a short article: blank lines fill the window
    sta limit
    lda #0
    sta max_top
    rts
@long:
    sec                         ; max_top = total - WINDOW_ROWS
    lda max_top
    sbc #WINDOW_ROWS
    sta max_top
    bcs @done
    dec max_top + 1
@done:
    rts
.endproc

.proc reader_frame
    lda host_state
    cmp #HOST_READY
    beq @select
    jmp lost_article
@select:
    lda pad_new
    and #PAD_SELECT
    beq @start
    lda #STATUS_NONE
    jmp back_to_search
@start:
    lda pad_new
    and #PAD_START
    beq @page
    lda top
    ora top + 1
    ora fine
    beq @page                   ; there already
    lda #SPRITE_HIDDEN
    sta THUMB_OAM
    jmp reader_open
@page:
    lda pad_new
    and #PAD_A | PAD_RIGHT
    beq @page_up
    lda #0
    beq @glide
@page_up:
    lda pad_new
    and #PAD_B | PAD_LEFT
    beq @move
    lda #1
@glide:
    sta glide_up
    lda #PAGE_PIXELS
    sta glide

@move:
    lda pad
    and #PAD_UP | PAD_DOWN
    beq @gliding
    lda #0                      ; scrolling by hand ends a glide
    sta glide
    ldx #SCROLL_STEPS
    stx steps
    lda pad
    and #PAD_UP
    beq @down
@up:
    jsr step_up
    bne @fetch
    dec steps
    bne @up
    beq @fetch
@down:
    jsr step_down
    bne @fetch
    dec steps
    bne @down
    beq @fetch

@gliding:
    lda glide
    beq @fetch
    lda #GLIDE_STEPS
    sta steps
@glide_step:
    lda glide_up
    beq @glide_down
    jsr step_up
    jmp @stepped
@glide_down:
    jsr step_down
@stepped:
    beq @glided
    cmp #STEP_END
    bne @fetch                  ; waiting for a line: go on next frame
    lda #0
    sta glide
    beq @fetch
@glided:
    dec glide
    beq @fetch
    dec steps
    bne @glide_step

@fetch:
    jsr reader_fetch
    jmp thumb_update
.endproc

; Move the window a pixel down the article. A = STEP_*, and the flags are
; set for it.
.proc step_down
    cmp16 top, max_top
    bcc @room
    lda #STEP_END
    rts
@room:
    lda fine
    bne @go
    ; Line top + WINDOW_ROWS comes into view: it must be in the ring.
    clc
    lda top
    adc #WINDOW_ROWS + 1
    sta tmp
    lda top + 1
    adc #0
    sta tmp + 1
    cmp16 hi, tmp
    bcs @go
    lda #STEP_WAITING
    rts
@go:
    lda #0
    sta going_up
    inc ring_y
    lda ring_y
    cmp #8 * RING_ROWS
    bcc @fine
    lda #0
    sta ring_y
@fine:
    inc fine
    lda fine
    cmp #8
    bcc @moved
    lda #0
    sta fine
    inc16 top
@moved:
    lda #STEP_MOVED
    rts
.endproc

; Move the window a pixel up the article. A = STEP_*, and the flags are set
; for it.
.proc step_up
    lda fine
    bne @go
    lda top
    ora top + 1
    bne @line
    lda #STEP_END
    rts
@line:
    ; Line top - 1 comes into view: it must be in the ring.
    cmp16 lo, top
    bcc @go
    lda #STEP_WAITING
    rts
@go:
    lda #1
    sta going_up
    lda ring_y
    bne @row
    lda #8 * RING_ROWS
    sta ring_y
@row:
    dec ring_y
    dec fine
    bpl @moved
    lda #7
    sta fine
    dec16 top
@moved:
    lda #STEP_MOVED
    rts
.endproc

; Fetch one line into the ring, if one is wanted. Carry set if a line was
; wanted and did not come.
;
; Going down, the ring should reach AHEAD lines past the window and BEHIND
; before it; going up, the other way round. The far side is filled first.
; When the ring is full, a line added at one end pushes one off the other:
; on the far side only, so the two sides cannot push each other's lines
; off in turn. Lines lo and hi stay at least BEHIND + 1 rows from the
; window, so the row a line is fetched into is never one in view.
.proc reader_fetch
    lda draw_len                ; the staging buffer is taken
    bne @idle
    lda going_up
    bne @upward
    lda #WINDOW_ROWS + 1 + AHEAD
    jsr wants_below
    bcs @append
    lda held
    cmp #RING_ROWS
    bcs @nothing
    lda #BEHIND
    jsr wants_above
    bcs @prepend
@nothing:
    ; No line is wanted. While the article is still arriving, ask now and
    ; then for the line after its last: the answer says how long it has
    ; become, which is what lets the window go on past what was its end.
    lda more
    beq @idle
    lda frame_count
    and #GROWTH_POLL
    bne @idle
    lda total
    sta want
    lda total + 1
    sta want + 1
    jsr link_line               ; for the length; the line is not used
@idle:
    clc
    rts
@upward:
    lda #AHEAD
    jsr wants_above
    bcs @prepend
    lda held
    cmp #RING_ROWS
    bcs @nothing
    lda #WINDOW_ROWS + 1 + BEHIND
    jsr wants_below
    bcc @nothing

@append:
    lda hi
    sta want
    lda hi + 1
    sta want + 1
    lda hi_row
    sta want_row
    jsr fetch_line
    bcs @failed
    inc16 hi
    ldx hi_row
    jsr next_row
    stx hi_row
    inc held
    lda held
    cmp #RING_ROWS + 1
    bcc @fetched
    dec held                    ; the ring was full: its first line goes
    inc16 lo
    ldx lo_row
    jsr next_row
    stx lo_row
@fetched:
    clc
@failed:
    rts

@prepend:
    sec
    lda lo
    sbc #1
    sta want
    lda lo + 1
    sbc #0
    sta want + 1
    ldx lo_row
    jsr previous_row
    stx want_row
    jsr fetch_line
    bcs @failed
    lda want
    sta lo
    lda want + 1
    sta lo + 1
    lda want_row
    sta lo_row
    inc held
    lda held
    cmp #RING_ROWS + 1
    bcc @fetched
    dec held                    ; the ring was full: its last line goes
    dec16 hi
    ldx hi_row
    jsr previous_row
    stx hi_row
    clc
    rts
.endproc

; Carry set if the ring should grow downward: hi < limit and hi < top + A.
.proc wants_below
    clc
    adc top
    sta tmp
    lda top + 1
    adc #0
    sta tmp + 1
    cmp16 hi, tmp
    bcs @no
    cmp16 hi, limit
    bcs @no
    sec
    rts
@no:
    clc
    rts
.endproc

; Carry set if the ring should grow upward: lo > 0 and lo + A > top.
.proc wants_above
    clc
    adc lo
    sta tmp
    lda lo + 1
    adc #0
    sta tmp + 1
    lda lo
    ora lo + 1
    beq @no
    cmp16 top, tmp
    bcs @no
    sec
    rts
@no:
    clc
    rts
.endproc

.proc next_row
    inx
    cpx #RING_ROWS
    bcc @done
    ldx #0
@done:
    rts
.endproc

.proc previous_row
    dex
    bpl @done
    ldx #RING_ROWS - 1
@done:
    rts
.endproc

; Stage line `want` for row want_row. Carry set if the host did not
; deliver it. A line past the article's end is blank and needs no host.
.proc fetch_line
    cmp16 want, total
    bcc @ask
    ldx #COLUMNS - 1
    lda #' '
@blank:
    sta draw_buf,x
    dex
    bpl @blank
    bmi @stage
@ask:
    jsr link_line               ; fills draw_buf
    bcs @done
@stage:
    ldx want_row
    lda ring_lo,x
    sta draw_addr
    lda ring_hi,x
    sta draw_addr + 1
    lda #COLUMNS
    sta draw_len
    clc
@done:
    rts
.endproc

; Put the thumb where the window is in the article: THUMB_TRAVEL * top /
; max_top pixels down. Only when `top` has changed, and no thumb for an
; article that fits the window.
.proc thumb_update
    lda max_top
    ora max_top + 1
    bne @some
    lda #SPRITE_HIDDEN
    sta THUMB_OAM
    rts
@some:
    lda top
    cmp thumb_top
    bne @place
    lda top + 1
    cmp thumb_top + 1
    bne @place
    rts
@place:
    lda top
    sta thumb_top
    lda top + 1
    sta thumb_top + 1
    ; product = top * THUMB_TRAVEL, 24 bits.
    lda #0
    sta product
    sta product + 1
    sta product + 2
    lda #THUMB_TRAVEL
    sta factor
    ldx #8
@multiply:
    asl product
    rol product + 1
    rol product + 2
    asl factor
    bcc @next_bit
    clc
    lda product
    adc top
    sta product
    lda product + 1
    adc top + 1
    sta product + 1
    bcc @next_bit
    inc product + 2
@next_bit:
    dex
    bne @multiply
    ; product / max_top: at most THUMB_TRAVEL, so 8 bits. The quotient
    ; shifts into the low byte as the remainder leaves the top two.
    ldx #8
@divide:
    asl product
    rol product + 1
    rol product + 2
    bcs @subtract
    lda product + 1
    cmp max_top
    lda product + 2
    sbc max_top + 1
    bcc @next_digit
@subtract:
    lda product + 1
    sbc max_top                 ; carry is set either way here
    sta product + 1
    lda product + 2
    sbc max_top + 1
    sta product + 2
    inc product
@next_digit:
    dex
    bne @divide
    clc
    lda product
    adc #THUMB_TOP
    sta THUMB_OAM
    rts
.endproc

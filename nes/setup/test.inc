; The link test: requests as fast as the console makes them, one a frame,
; each checked byte for byte, and the Stick's own count of how long it takes
; to answer.
;
;   B    back
;
; Two kinds of request take turns, so that both directions carry a
; pattern only the other end can check (DIAG, docs/PROTOCOL.md):
;
;   PATTERN   the Stick sends TEST_DOWN bytes of the pattern for a seed, and
;             this compares them with its own
;   SINK      this sends TEST_UP bytes of it, and the Stick says how many
;             were wrong
;
; Every 64th frame asks for the Stick's counters in their place. The
; numbers on the screen are redrawn one a frame, from a copy of the counts
; made as each round of drawing begins, so that what is on the screen at
; one time adds up.

TEST_DOWN  = 48                 ; bytes of pattern asked for
TEST_UP    = 16                 ; bytes of pattern sent
STATS_MASK = $3F
TEST_LINES = 6

.segment "ZEROPAGE"
test_seed:   .res 2
test_line:   .res 1             ; the next number to draw
; 16 bits each, in the order they are shown.
test_counts: .res 2 * TEST_LINES
TEST_SENT    = test_counts
TEST_GOOD    = test_counts + 2
TEST_SILENT  = test_counts + 4
TEST_WRONG   = test_counts + 6
TEST_LAST    = test_counts + 8  ; the Stick's time to answer, in microseconds
TEST_SLOWEST = test_counts + 10
test_shown:  .res 2 * TEST_LINES    ; the counts as they are being drawn

.segment "RODATA"
test_screen:
    text  HEADING_ROW, LEFT, "LINK TEST"
    label BODY_ROW, LEFT, "REQUESTS"
    label BODY_ROW + 1, LEFT, "GOOD"
    label BODY_ROW + 2, LEFT, "NO REPLY"
    label BODY_ROW + 3, LEFT, "WRONG"
    text  BODY_ROW + 5, LEFT, "THE STICK'S TIME TO REPLY"
    label BODY_ROW + 6, LEFT, "LAST"
    label BODY_ROW + 7, LEFT, "SLOWEST"
    text  HELP_ROW, LEFT, "B:BACK"
    .byte 0

test_rows: .byte 0, 1, 2, 3, 6, 7
test_lo:
.repeat 8, line
    .byte <($2000 + 32 * (BODY_ROW + line) + TEST_VALUE_COLUMN)
.endrepeat
test_hi:
.repeat 8, line
    .byte >($2000 + 32 * (BODY_ROW + line) + TEST_VALUE_COLUMN)
.endrepeat
us_text: .byte " US", 0

.segment "CODE"

.proc open_test
    lda #<test_screen
    ldx #>test_screen
    jsr show_screen
    ldx #2 * TEST_LINES - 1
    lda #0
@clear:
    sta test_counts,x
    dex
    bpl @clear
    sta test_seed
    sta test_seed + 1
    lda #TEST_LINES - 1         ; the first number drawn begins a round
    sta test_line
    lda #STATE_TEST
    sta state
    rts
.endproc

.proc test_frame
    lda pad_new
    and #PAD_B
    beq @go
    jmp open_status
@go:
    lda frame_count
    and #STATS_MASK
    bne @trial
    jsr test_stats
    jmp @drawn
@trial:
    inc16 test_seed             ; a new pattern each time, and never seed 0
    lda test_seed
    ora test_seed + 1
    bne @seeded
    inc test_seed
@seeded:
    lda test_seed
    sta nesp_request
    sta nesp_rng
    lda test_seed + 1
    sta nesp_request + 1
    sta nesp_rng + 1
    inc16 TEST_SENT
    lda frame_count
    lsr a
    bcs @up
    jsr test_down
    jmp @count
@up:
    jsr test_up
@count:                         ; carry: no reply. Else A: 0 if it was right
    bcc @heard
    lda state                   ; the Stick has gone, and the status screen is up
    cmp #STATE_TEST
    bne @done
    inc16 TEST_SILENT
    jmp @drawn
@heard:
    bne @wrong
    inc16 TEST_GOOD
    jmp @drawn
@wrong:
    inc16 TEST_WRONG
@drawn:
    jmp test_draw
@done:
    rts
.endproc

; Ask for the pattern and compare. Carry set if no reply came; else A is 0
; if every byte was right.
.proc test_down
    lda #TEST_DOWN
    sta nesp_request + 2
    lda #NESP_SVC_DIAG
    ldx #NESP_DIAG_PATTERN
    ldy #3
    jsr call
    bcs @done
    lda nesp_status
    bne @wrong
    lda nesp_reply_len
    cmp #TEST_DOWN
    bne @wrong
    ldx #0
@byte:
    jsr nesp_pattern            ; preserves X
    cmp nesp_reply,x
    bne @wrong
    inx
    cpx #TEST_DOWN
    bne @byte
    lda #0
    clc
    rts
@wrong:
    lda #1
    clc
@done:
    rts
.endproc

; Send the pattern and hear how it arrived. Carry and A as test_down's.
.proc test_up
    ldx #0
@byte:
    jsr nesp_pattern            ; preserves X
    sta nesp_request + 2,x
    inx
    cpx #TEST_UP
    bne @byte
    lda #NESP_SVC_DIAG
    ldx #NESP_DIAG_SINK
    ldy #TEST_UP + 2
    jsr call
    bcs @done
    lda nesp_status
    bne @wrong
    lda nesp_reply              ; bytes that were wrong
    bne @wrong
    lda nesp_reply + 1          ; of how many
    cmp #TEST_UP
    bne @wrong
    lda #0
    clc
    rts
@wrong:
    lda #1
    clc
@done:
    rts
.endproc

; The Stick's counters: only its times to answer are shown.
.proc test_stats
    lda #NESP_SVC_DIAG
    ldx #NESP_DIAG_STATS
    ldy #0
    jsr call
    bcs @done
    lda nesp_status
    bne @done
    ldx #3
@copy:
    lda nesp_reply + 8,x
    sta TEST_LAST,x
    dex
    bpl @copy
@done:
    rts
.endproc

; The next number, if nothing else is staged.
.proc test_draw
    lda state
    cmp #STATE_TEST
    bne @done
    lda draw_len
    bne @done
    ldx test_line
    inx
    cpx #TEST_LINES
    bcc @line
    ldx #2 * TEST_LINES - 1     ; a new round: the counts as they are now
@copy:
    lda test_counts,x
    sta test_shown,x
    dex
    bpl @copy
    inx
@line:
    stx test_line
    ldy test_rows,x
    lda test_lo,y
    sta draw_addr
    lda test_hi,y
    sta draw_addr + 1
    txa
    asl a
    tay
    lda test_shown,y
    sta tmp
    lda test_shown + 1,y
    sta tmp + 1
    ldx #0
    jsr put_dec16
    lda test_line
    cmp #4
    bcc @stage
    point us_text
    jsr put_text
@stage:
    ldy #LEFT + WIDTH - TEST_VALUE_COLUMN
    jmp stage_pad
@done:
    rts
.endproc

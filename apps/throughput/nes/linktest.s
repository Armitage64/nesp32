; Throughput test ROM: how fast can the controller-port link go?
;
; The link to a nesp32 runs at one rate, 85227 baud. This ROM finds out how
; fast the same wiring can go each way: it has a receive routine for each
; rate of one ladder and a send routine for each of another (rates.inc,
; generated), and tries them from the slowest up until one fails.
;
; The far side is nesp32's firmware, and everything is asked of it in
; frames, over nesp32's link (its nes/lib/nesp.inc and docs/PROTOCOL.md).
; A trial's bytes go with framing off, as runs of its RAW service:
;
;   RAW SEND      the nesp32 sends the test pattern at a rate, and this ROM
;                 counts the bytes that came wrong
;   RAW LISTEN    this ROM sends it, and the nesp32 counts
;   RAW RESULT    how the run went, as the nesp32 saw it
;
; A block is 256 bytes, one run. A trial is TRIAL_BLOCKS of them at one
; rate, and ends early at a block with a bad byte. Each direction is
; climbed by itself (README.md).
;
; A frame: the NMI writes what has been staged for the screen, and the main
; program then makes one exchange, with most of the frame left for the
; reply. The NMI is also what ends an exchange that got no reply
; (nesp.inc).
;
; Nothing may take cycles from the block routines, so the NMI is off from
; the reply that agrees to a run until the block is over, and nothing is
; drawn meanwhile. The receivers have no timeout: a nesp32 that loses its
; power in the middle of a run to the console leaves this ROM waiting, and
; Reset is the way out.
;
; The controller is read only while the ROM waits to be started. A read is
; a low on the line to the nesp32, which a UART listening for a run would
; take for a byte of it.
;
; Wiring is nesp32's. The nesp32 drives D0 (bit 0 of $4017, inverted by the
; port's buffer) and reads OUT0 (bit 0 of $4016 writes), which idles at
; mark.

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

FRAME_IRQ_INHIBIT = $40
PPUCTRL_NMI = $80
PPUMASK_BACKGROUND = $0A        ; background on, left column included
NAMETABLE = $2000
PALETTE   = $3F00
OUT0_MARK = $01
PAD_START = $10

TRIAL_BLOCKS = 4                ; a trial: 1024 bytes
; For finding out what a line cannot do: `make TX_FIRST=8` builds a ROM that
; begins the climb from the console at that rate of its ladder (8 is the
; link's own, 85227 baud), not at the slowest.
.ifndef TX_FIRST
TX_FIRST = 0
.endif
NO_RATE = $FF
ASK_TRIES = 90                  ; frames a request is made for before the nesp32 is given up
DRAW_MAX = 96                   ; bytes staged for one NMI: what it writes well inside vblank
SETTLE_LOOP = 1286              ; cycles of one pass of settle's outer loop

; What this ROM asks of the link.
NESP_RX_MASK = $1F              ; replies of up to 31 bytes
NESP_TX_MAX  = 8                ; the hello, with its one service
.define NESP_APP "THRU"
NESP_APP_VERSION = 1

rx_buf  = $0400                 ; the block routines index these with X, so
tx_buf  = $0500                 ; each is a whole page

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM), horizontal mirroring
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1
served_frame: .res 1
pad:          .res 1            ; controller 1 as the NMI read it: A B Select Start Up Down Left Right
testing:      .res 1            ; a test is under way: the controller is not read
draw_end:     .res 1            ; bytes of draw_buf the next NMI writes
draw_at:      .res 1            ; where the field being staged takes its next tile
draw_stop:    .res 1            ; and where it ends
field_row:    .res 1
field_column: .res 1
field_width:  .res 1
ptr:          .res 2
num:          .res 2
digits:       .res 1
tries:        .res 1
count:        .res 1
ran:          .res 1            ; a test has run, and its results are up
start_up:     .res 1            ; Start has been seen up since the ROM last waited for it
port:         .res 1            ; what JOY2 read with the line at rest
base:         .res 1            ; the direction under test: its first row in the tables
half:         .res 1            ; and its title's row on the screen
limit:        .res 1            ; how many rates it has
first:        .res 1            ; and the one its climb begins at
rate:         .res 1            ; the rate under test, from 0
row:          .res 1            ; its row in the tables: base + rate
best:         .res 1            ; the fastest that passed, or NO_RATE
blocks:       .res 1            ; blocks of this trial so far
bad:          .res 2            ; bytes of them that came wrong
seed:         .res 2            ; the next block's
skip:         .res 1            ; bytes at the start of a block that are not the pattern's
vector:       .res 2            ; the block routine to call
rx_ptr:       .res 2            ; where the tracking receiver stores

.segment "BSS"
draw_buf:     .res DRAW_MAX     ; fields: address (high, low), width, tiles

.include "nesp.inc"
.include "screen.inc"
.include "rates.inc"

SETTLE_LOOPS = (NESP_RAW_SETTLE_MS * (NESP_CPU_HZ / 1000) + SETTLE_LOOP - 1) / SETTLE_LOOP
.assert SETTLE_LOOPS < 256, error, "settle counts in X"
.assert NESP_TX_MAX = NESP_HELLO_FIXED + 1, error, "the hello names one service"
.assert TX_FIRST < TX_COUNT, error, "TX_FIRST is a rate of the ladder from the console"

.segment "RODATA"

palette:
    .incbin "palette.bin"       ; the jukebox's: white text, the logo's blues
screen_data:
    .incbin "screen.bin"

; The tests run short trials by changing this.
trial_blocks: .byte TRIAL_BLOCKS

; A value's width on the screen, by its row under the title.
row_width:
    .byte WIDTH_STATUS, WIDTH_SPEED, WIDTH_SENT, WIDTH_BAD, WIDTH_CPU, WIDTH_FASTEST
    .byte WIDTH_FAILED
ROWS = * - row_width

tens_lo: .lobytes 10000, 1000, 100, 10, 1
tens_hi: .hibytes 10000, 1000, 100, 10, 1

waiting_text:  .byte "WAITING FOR THE NESP32", 0
update_text:   .byte "UPDATE THE NESP32", 0
press_text:    .byte "PRESS START", 0
again_text:    .byte "DONE. PRESS START", 0
testing_text:  .byte "TESTING", 0
idle_text:     .byte "WAITING", 0
climbing_text: .byte "CLIMBING", 0
done_text:     .byte "DONE", 0
none_text:     .byte "NONE", 0
bytes_text:    .byte " BYTES", 0
comma_text:    .byte ", ", 0
bad_text:      .byte " BAD", 0
port_text:     .byte "$4017 READS $", 0

; Add a text to the field being staged.
.macro put text
    lda #<(text)
    sta ptr
    lda #>(text)
    sta ptr + 1
    ldy #0
    jsr put_str
.endmacro

; Put a text on the line that says what the test is doing.
.macro say text
    lda #STATE_ROW
    ldx #STATE_COLUMN
    ldy #STATE_WIDTH
    jsr field
    put text
    jsr field_end
.endmacro

; Give one of the direction's values a text: which is a ROW_.
.macro show which, text
    lda #which
    jsr value
    put text
    jsr field_end
.endmacro

.segment "CODE"

.proc reset
    sei
    cld
    ldx #FRAME_IRQ_INHIBIT
    stx APU_FRAME
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx APU_DMC                 ; DMC IRQ off
    stx APU_STATUS
    lda #OUT0_MARK              ; the line to the nesp32 leaves break
    sta JOY1
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

    jsr screen_init
    lda #$E1                    ; any seed but 0
    sta seed
    lda #$AC
    sta seed + 1
    ; fall through
.endproc

; Where the test begins, and where it comes back to from wherever it was
; when the nesp32 stopped answering, or answered that it does not know this
; ROM: it was switched off and on. The stack is dropped, and the hello is
; said until it is answered.
.proc start
    ldx #$FF
    txs
    lda #0
    sta testing
    bit PPUSTATUS               ; a vblank that came and went is not an NMI now
    lda #PPUCTRL_NMI
    sta PPUCTRL
    say waiting_text
@hello:
    jsr next_frame
    lda #NESP_SVC_RAW
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs @hello
    cmp #NESP_ST_OK
    beq @greeted
    say update_text             ; it has no RAW, or speaks another protocol
    jmp @hello

@greeted:
    ; A press of the nesp32's button from before now is not for this.
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_EVENT
    ldy #0
    jsr ask
    lda nesp_reply
    bne @greeted
    sta start_up                ; nor is a Start that is still down
    lda ran
    bne @again
    say press_text
    jmp @idle
@again:
    say again_text

    ; Wait to be started: Start on controller 1, or button A on the nesp32.
    ; A request a frame keeps watch on the nesp32 meanwhile.
@idle:
    lda pad
    and #PAD_START
    bne @down
    lda #1
    sta start_up
    bne @watch
@down:
    lda start_up
    bne @go
@watch:
    lda #NESP_SVC_RAW
    ldx #NESP_RAW_RESULT
    ldy #0
    jsr ask
    lda nesp_attention
    beq @idle
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_EVENT
    ldy #0
    jsr ask
    lda nesp_reply
    cmp #NESP_EVENT_BUTTON_A
    bne @idle
@go:
    jsr run_test
    lda #0
    sta testing
    lda #1
    sta ran
    jmp @greeted
.endproc

; Wait for an NMI that has not had its turn. The comparison is with the
; last frame served, not for a change: an NMI that cuts off an exchange has
; already counted the new frame, and that frame is the one to ask again in.
; Preserves X and Y.
;
; The tests skip the clock ahead to the next NMI whenever the CPU sits at
; main_wait with frame_count equal to served_frame, so it is a plain label.
next_frame:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    rts

; A request and its reply: A = the service, X = the op, Y = the payload's
; length, with the payload in nesp_request. It is made right after the next
; NMI, and again after each one until a reply comes; the nesp32 does
; nothing twice for that (nesp_again). Returns with the reply in
; nesp_reply. If none comes, or one that is not OK, the test is over: see
; start.
.proc ask
    pha
    jsr next_frame
    pla
    jsr nesp_call
    bcc @came
    lda #ASK_TRIES - 1
    sta tries
@again:
    jsr next_frame
    jsr nesp_again
    bcc @came
    dec tries
    bne @again
@lost:
    jmp start
@came:
    cmp #NESP_ST_OK
    bne @lost
    rts
.endproc

; --- the test ------------------------------------------------------------------

; Both directions, from a screen with no figures on it.
.proc run_test
    lda #1
    sta testing
    lda #0
    sta pad
    jsr paint
    say testing_text
    ; The receivers count on what the port's unused bits read (rates.inc).
    ; The line is at rest here: the nesp32 only sends when asked. On a
    ; console that reads something else, nothing is run to it.
    ldx #RX_COUNT
    lda JOY2
    sta port
    cmp #PORT_IDLE
    beq @port
    ldx #0
@port:
    stx limit
    lda #0
    sta base
    sta first
    lda #HALF_RX
    sta half
    jsr search
    lda #TX_COUNT
    sta limit
    lda #RX_COUNT
    sta base
    lda #TX_FIRST
    sta first
    lda #HALF_TX
    sta half
    ; fall through
.endproc

; Find one direction's fastest stable rate: try each once, from the
; slowest up, until a trial fails, and go back to the one before it. No
; rate is tried twice. Leaves it in best.
.proc search
    lda #NO_RATE
    sta best
    lda first
    sta rate
@next:
    lda rate
    cmp limit
    bcs @top
    jsr trial
    lda bad
    ora bad + 1
    bne @failed
    lda rate
    sta best
    inc rate
    bne @next

@failed:                        ; what stopped the climb stays on the screen
    jsr rate_texts
    lda #ROW_FAILED
    jsr value
    ldy #TEXT_SPEED
    jsr put_str
    put comma_text
    lda bad
    sta num
    lda bad + 1
    sta num + 1
    jsr put_dec
    put bad_text
    jsr field_end
    jmp @done
@top:
    lda limit
    beq @port
    show ROW_FAILED, none_text  ; nothing did: it passed every rate there is
    jmp @done
@port:
    lda #ROW_FAILED
    jsr value
    put port_text
    lda port
    jsr put_hex
    jsr field_end

@done:
    show ROW_STATUS, done_text
    lda best
    cmp #NO_RATE
    bne @held
    show ROW_FASTEST, none_text
    rts
@held:
    ; The last trial was the rate above failing, if any did. Go back to the
    ; figures of the one that held: all of its blocks, and none bad.
    sta rate
    jsr show_rate
    lda trial_blocks
    sta blocks
    jsr show_sent
    lda #0
    sta bad
    sta bad + 1
    jsr show_bad
    jsr rate_texts
    lda #ROW_FASTEST
    jsr value
    ldy #TEXT_FASTEST
    jsr put_str
    jmp field_end
.endproc

; A trial: blocks at one rate, stopping after the first that is not clean.
; Leaves the bytes that came wrong in bad. The screen follows it.
.proc trial
    lda #0
    sta bad
    sta bad + 1
    sta blocks
    show ROW_STATUS, climbing_text
    jsr show_rate
    jsr show_sent
    jsr show_bad
@block:
    jsr block
    inc blocks
    jsr show_sent
    lda bad
    ora bad + 1
    bne @over
    lda blocks
    cmp trial_blocks
    bcc @block
@over:
    jmp show_bad
.endproc

; One block at the rate under test, as a run of RAW's (nesp32's
; docs/PROTOCOL.md). Adds the bytes that came wrong to bad.
.proc block
    lda base
    clc
    adc rate
    sta row
    tax
    lda rate_period,x
    sta nesp_request
    lda base
    bne @from_console

    ; To the console: the period, bytes of $FF first, the seed, bytes of
    ; the pattern.
    lda rate_lead,x
    sta nesp_request + 1
    sta skip
    lda seed
    sta nesp_request + 2
    lda seed + 1
    sta nesp_request + 3
    lda rate_count_lo,x
    sta nesp_request + 4
    lda rate_count_hi,x
    sta nesp_request + 5
    ldx #NESP_RAW_SEND
    ldy #6
    bne @ask

    ; From it: the period, the seed, a block.
@from_console:
    lda seed
    sta nesp_request + 1
    lda seed + 1
    sta nesp_request + 2
    lda #<BLOCK
    sta nesp_request + 3
    lda #>BLOCK
    sta nesp_request + 4
    jsr fill
    ldx #NESP_RAW_LISTEN
    ldy #5
@ask:
    lda #NESP_SVC_RAW
    jsr ask

    ; The nesp32 has agreed. It listens for a moment in case this console
    ; did not hear and asks again, then changes its UART's rate; the wait
    ; before the block covers both. An NMI would take cycles from the
    ; block's routine, so it is off until the block is over, and with it
    ; the controller's read: the line is silent, which is how the nesp32
    ; knows that the console heard.
    lda #0
    sta PPUCTRL
    ldx row
    lda block_lo,x
    sta vector
    lda block_hi,x
    sta vector + 1
    jsr settle
    jsr call_vector
    bit PPUSTATUS               ; a vblank that came and went is not an NMI now
    lda #PPUCTRL_NMI
    sta PPUCTRL

    ; The run may not be over, and the nesp32 changes its rate back when it
    ; is. Then ask how it went: the run must be this one, and done.
    ldx row
    lda rate_rest,x
    sta count
@rest:
    jsr next_frame
    dec count
    bne @rest
    lda #NESP_SVC_RAW
    ldx #NESP_RAW_RESULT
    ldy #0
    jsr ask
    lda nesp_reply
    cmp #NESP_RUN_DONE
    bne @lost
    ldx row
    lda nesp_reply + 1
    cmp rate_period,x
    bne @lost

    lda base
    bne @heard
    jsr decode_block            ; the receivers leave their bytes scrambled
    jsr count_bad
    jmp @seed

    ; What the nesp32 heard: the bytes that were not the pattern's, and
    ; those that never came.
@heard:
    clc
    lda bad
    adc nesp_reply + 4
    sta bad
    lda bad + 1
    adc nesp_reply + 5
    sta bad + 1
    sec
    lda #<BLOCK
    sbc nesp_reply + 2
    tax
    lda #>BLOCK
    sbc nesp_reply + 3
    tay
    clc
    txa
    adc bad
    sta bad
    tya
    adc bad + 1
    sta bad + 1

    ; The next block's seed is where this one's pattern stopped: never 0.
@seed:
    lda nesp_rng
    sta seed
    lda nesp_rng + 1
    sta seed + 1
    rts
@lost:
    jmp start
.endproc

.proc call_vector
    jmp (vector)
.endproc

; From the reply that agrees to a run to the console's part in it:
; NESP_RAW_SETTLE_MS.
.proc settle
    ldx #SETTLE_LOOPS
@outer:
    ldy #0
@inner:
    dey
    bne @inner
    dex
    bne @outer
    rts
.endproc

; nesp_rng = the seed of the block in hand.
.proc reseed
    lda seed
    sta nesp_rng
    lda seed + 1
    sta nesp_rng + 1
    rts
.endproc

; tx_buf = a block of the pattern.
.proc fill
    jsr reseed
    ldx #0
@byte:
    jsr nesp_pattern            ; preserves X
    sta tx_buf,x
    inx
    bne @byte
    rts
.endproc

; Put right a block as a receiver stored it: each byte arrived bit-reversed,
; inverted, and with the port's other bits in it (rates.inc).
.proc decode_block
    ldy #0
@byte:
    ldx rx_buf,y
    lda rx_decode,x
    sta rx_buf,y
    iny
    bne @byte
    rts
.endproc

; Add to bad the bytes of rx_buf, past the first `skip`, that are not the
; pattern's.
.proc count_bad
    jsr reseed
    ldy skip
@byte:
    jsr nesp_pattern            ; preserves Y
    cmp rx_buf,y
    beq @same
    inc bad
    bne @same
    inc bad + 1
@same:
    iny
    bne @byte
    rts
.endproc

; --- the screen ----------------------------------------------------------------
;
; The screen comes up whole (screen.bin), and the program only writes
; figures to it, a field at a time: a run of tiles in one row, staged in
; draw_buf for the next NMI. A field is always written to its whole width,
; so nothing of what it held before is left.

; ptr = the texts of the rate under test (rates.inc).
.proc rate_texts
    lda base
    clc
    adc rate
    tax
    lda rate_text_lo,x
    sta ptr
    lda rate_text_hi,x
    sta ptr + 1
    rts
.endproc

; The rate under test: its speed, and the share of the CPU it takes.
.proc show_rate
    jsr rate_texts
    lda #ROW_SPEED
    jsr value
    ldy #TEXT_SPEED
    jsr put_str
    jsr field_end
    lda #ROW_CPU
    jsr value
    ldy #TEXT_CPU
    jsr put_str
    jmp field_end
.endproc

; The bytes of this trial so far: a block is 256.
.proc show_sent
    lda #ROW_SENT
    jsr value
    lda #0
    sta num
    lda blocks
    sta num + 1
    jsr put_dec
    put bytes_text
    jmp field_end
.endproc
.assert BLOCK = 256, error, "show_sent counts blocks of 256"

.proc show_bad
    lda #ROW_BAD
    jsr value
    lda bad
    sta num
    lda bad + 1
    sta num + 1
    jsr put_dec
    put bytes_text
    jmp field_end
.endproc

; Both halves as a test starts from them: waiting, and no figures.
.proc paint
    lda #HALF_RX
    jsr @half
    lda #HALF_TX
@half:
    sta half
    show ROW_STATUS, idle_text
    lda #ROW_STATUS + 1
@row:
    pha
    jsr value
    jsr field_end
    pla
    clc
    adc #1
    cmp #ROWS + 1
    bne @row
    rts
.endproc

; Begin one of the values of the direction under test: A = which (ROW_*).
; Preserves ptr.
.proc value
    tay
    clc
    adc half
    pha
    lda row_width - 1,y
    tay
    pla
    ldx #VALUE_COLUMN
    ; fall through
.endproc

; Begin a field: A = its row, X = its column, Y = its width in tiles. If
; draw_buf has no room for it, the NMI gets what is staged first.
.proc field
    sta field_row
    stx field_column
    sty field_width
@room:
    lda draw_end
    clc
    adc field_width
    adc #3
    cmp #DRAW_MAX + 1
    bcc @fits
    jsr next_frame
    jmp @room
@fits:
    ldx draw_end
    lda field_row
    lsr a
    lsr a
    lsr a
    ora #>NAMETABLE
    sta draw_buf,x
    lda field_row
    asl a
    asl a
    asl a
    asl a
    asl a
    ora field_column
    sta draw_buf + 1,x
    lda field_width
    sta draw_buf + 2,x
    inx
    inx
    inx
    stx draw_at
    txa
    clc
    adc field_width
    sta draw_stop
    rts
.endproc

; Add the text at ptr, from its character Y to a 0, to the field.
.proc put_str
    ldx draw_at
@char:
    lda (ptr),y
    beq @done
    sta draw_buf,x
    inx
    iny
    bne @char
@done:
    stx draw_at
    rts
.endproc

; Add num in decimal to the field. Destroys num.
.proc put_dec
    ldx draw_at
    ldy #0                      ; which power of ten
    sty digits                  ; not 0 once a digit has been written
@power:
    lda #'0'
    sta draw_buf,x
@subtract:
    lda num
    sec
    sbc tens_lo,y
    pha
    lda num + 1
    sbc tens_hi,y
    bcc @under
    sta num + 1
    pla
    sta num
    inc draw_buf,x
    bne @subtract
@under:
    pla
    lda draw_buf,x
    cmp #'0'
    bne @keep
    lda digits
    bne @keep
    cpy #4                      ; the last digit is written even if it is 0
    bne @next
@keep:
    inc digits
    inx
@next:
    iny
    cpy #5
    bne @power
    stx draw_at
    rts
.endproc

; Add A as two hexadecimal digits to the field.
.proc put_hex
    pha
    lsr a
    lsr a
    lsr a
    lsr a
    jsr @digit
    pla
    and #$0F
@digit:
    cmp #10
    bcc @decimal
    adc #'A' - '9' - 2          ; and the carry
@decimal:
    adc #'0'
    ldx draw_at
    sta draw_buf,x
    inc draw_at
    rts
.endproc

; The field is whole: blanks to its end, and the next NMI writes it. An NMI
; that comes while a field is being staged writes only those before it, and
; may write them again with it; they say what they said.
.proc field_end
    ldx draw_at
    lda #' '
@blank:
    cpx draw_stop
    bcs @done
    sta draw_buf,x
    inx
    bne @blank
@done:
    stx draw_end
    rts
.endproc

; The palette and the whole screen, with rendering off, and then on.
.proc screen_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda palette,x
    sta PPUDATA
    inx
    cpx #16
    bne @palette

    lda #>NAMETABLE
    sta PPUADDR
    lda #<NAMETABLE
    sta PPUADDR
    ldx #0
@page0:
    lda screen_data,x
    sta PPUDATA
    inx
    bne @page0
@page1:
    lda screen_data + $100,x
    sta PPUDATA
    inx
    bne @page1
@page2:
    lda screen_data + $200,x
    sta PPUDATA
    inx
    bne @page2
@page3:
    lda screen_data + $300,x
    sta PPUDATA
    inx
    bne @page3

    bit PPUSTATUS
@vblank:
    bit PPUSTATUS
    bpl @vblank
    lda #0
    sta PPUCTRL
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_BACKGROUND
    sta PPUMASK
    rts
.endproc

.proc nmi
    pha
    txa
    pha
    tya
    pha
    bit PPUSTATUS               ; reset the PPU's address latch
    ldx #0
@field:
    cpx draw_end
    bcs @drawn
    lda draw_buf,x
    sta PPUADDR
    lda draw_buf + 1,x
    sta PPUADDR
    ldy draw_buf + 2,x
    inx
    inx
    inx
@tile:
    lda draw_buf,x
    sta PPUDATA
    inx
    dey
    bne @tile
    beq @field
@drawn:
    lda #0
    sta draw_end
    lda #PPUCTRL_NMI            ; after writing through PPUADDR, the scroll
    sta PPUCTRL                 ; goes back to the top left
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL

    ; Controller 1 shares its strobe with the line to the nesp32: OUT0 must
    ; rest at mark, which keeps the controller loading its buttons, so
    ; taking it low for the 8 reads is all the strobe there is. The nesp32
    ; sees one low pulse of 94 cycles a frame, which its UART takes for a
    ; byte and its decoder passes over. Not during a test.
    lda testing
    bne @read
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #OUT0_MARK
    sta JOY1
@read:

    inc frame_count
    nesp_nmi_hook
    pla
    tay
    pla
    tax
    pla
    rti
.endproc

.proc irq
    rti
.endproc

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

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
; Up in place of Start sweeps the direction to the console instead:
; every rate of its ladder from SWEEP_FIRST up, each a whole trial however
; many bytes come wrong, with no climb that stops at the first to fail. The
; screen's two halves become a table of them, and the next climb puts the
; halves back.
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
; On nesp32's cartridge, B while the ROM waits to be started is the
; cartridge's menu again.
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
PAD_UP    = $08                 ; a sweep
PAD_START = $10
PAD_SELECT = $20                ; the cartridge's menu
PAD_A     = $80
; The cartridge's reset stub (nesp32's nes/cart/gen_cart.py) is at the same
; place in every program's bank: an `inc` of itself, which resets the
; mapper and puts the menu's bank at $C000, and a jump to the menu. Built by
; itself, this ROM has padding there. As Weather's Select does.
CART_STUB = $FFDA
CART_STUB_FIRST = $EE           ; inc absolute

TRIAL_BLOCKS = 4                ; a trial: 1024 bytes
; For finding out what a line cannot do: `make TX_FIRST=8` builds a ROM that
; begins the climb from the console at that rate of its ladder (8 is the
; link's own, 85227 baud), not at the slowest.
.ifndef TX_FIRST
TX_FIRST = 0
.endif
NO_RATE = $FF
; The sweep's rates: the last of the ladder to the console, 14 cycles a bit
; to 5. The tests check that they are.
SWEEP_RATES = 10
ASK_TRIES = 90                  ; frames a request is made for before the nesp32 is given up
DRAW_MAX = 96                   ; bytes staged for one NMI: what it writes well inside vblank
SETTLE_LOOP = 1286              ; cycles of one pass of settle's outer loop

; What this ROM asks of the link.
NESP_RX_MASK = $1F              ; replies of up to 31 bytes
NESP_TX_MAX  = 9                ; the hello, with its two services
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
start_up:     .res 1            ; Start, Select and B have been seen up since the ROM last waited
swept:        .res 1            ; the halves of the screen have a sweep's table over them
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
on_cart:      .res 1            ; this is on nesp32's cartridge, which has a menu
keys_ok:      .res 1            ; the hello had KBD: what is typed is asked for
key_at:       .res 1            ; the next key of a KEYS reply
pressed:      .res 1            ; what the wait goes by: controller 1 or a key

.segment "BSS"
draw_buf:     .res DRAW_MAX     ; fields: address (high, low), width, tiles

NESP_KEY_PAD = 1                ; the Bluetooth keyboard's keys as the controller's buttons
.include "nesp.inc"
.include "screen.inc"
.include "rates.inc"

SETTLE_LOOPS = (NESP_RAW_SETTLE_MS * (NESP_CPU_HZ / 1000) + SETTLE_LOOP - 1) / SETTLE_LOOP
.assert SETTLE_LOOPS < 256, error, "settle counts in X"
.assert NESP_TX_MAX = NESP_HELLO_FIXED + 2, error, "the hello names two services"
.assert TX_FIRST < TX_COUNT, error, "TX_FIRST is a rate of the ladder from the console"

SWEEP_FIRST = RX_COUNT - SWEEP_RATES
; The table: a title, a heading, and a row a rate under it, in the rows the
; halves have, from HALF_RX to the last of HALF_TX's.
SWEEP_LAST_ROW = HALF_TX + ROW_FAILED
SWEEP_TOP = HALF_RX + 2
SWEEP_CYCLES = TEXT_COLUMN + 1     ; its columns, and their widths
SWEEP_SPEED = TEXT_COLUMN + 5
SWEEP_BAD = TEXT_COLUMN + 16
.assert SWEEP_TOP + SWEEP_RATES - 1 <= SWEEP_LAST_ROW, error, "the sweep's table fits"
.assert SWEEP_BAD + 12 = TEXT_COLUMN + TEXT_WIDTH, error, "the sweep's rows are the halves' width"

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

; A text for the line that says what the test is doing: centered on it.
.macro state_text label, text
label:
.if (STATE_WIDTH - .strlen(text)) / 2
    .res (STATE_WIDTH - .strlen(text)) / 2, ' '
.endif
    .byte text, 0
.assert .strlen(text) <= STATE_WIDTH, error, "a state's text fits its line"
.endmacro

state_text waiting_text, "WAITING FOR THE NESP32"
state_text update_text, "UPDATE THE NESP32"
state_text press_text, "PRESS START"
state_text again_text, "A : RE-TEST"
state_text again_cart_text, "A : RE-TEST   SELECT : MENU"    ; on the cartridge, Select is its menu
state_text testing_text, "TESTING"
state_text sweep_state, "SWEEPING"
idle_text:     .byte "WAITING", 0
climbing_text: .byte "CLIMBING", 0
done_text:     .byte "DONE", 0
none_text:     .byte "NONE", 0
bytes_text:    .byte " BYTES", 0
comma_text:    .byte ", ", 0
bad_text:      .byte " BAD", 0
port_text:     .byte "$4017 READS $", 0
sweeping_text: .byte "SWEEPING", 0
sweep_title:   .byte "NESP32 TO NES, EVERY RATE", 0
sweep_heading: .byte " CYC SPEED      BAD OF SENT", 0
of_text:       .byte " OF ", 0

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

    lda CART_STUB
    cmp #CART_STUB_FIRST
    bne @alone
    inc on_cart
@alone:
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
    lda #NESP_SVC_RAW           ; and KBD, for the keys that stand for the
    sta nesp_request + NESP_HELLO_FIXED ; controller's buttons, and so that the
    lda #NESP_SVC_KBD           ; keyboard stays connected from one program
    sta nesp_request + NESP_HELLO_FIXED + 1 ; on the cartridge to the next
    ldy #2
    jsr nesp_hello
    bcs @hello
    ldx #1
    cmp #NESP_ST_OK
    beq @keys
    cmp #NESP_ST_NO_SERVICE     ; only KBD missing is a nesp32 to use
    bne @update
    lda nesp_reply + 6
    cmp #1
    bne @update
    lda nesp_reply + 7
    cmp #NESP_SVC_KBD
    bne @update
    dex
@keys:
    stx keys_ok
    jmp @greeted
@update:
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
    lda on_cart
    bne @again_cart
    say again_text
    jmp @idle
@again_cart:
    say again_cart_text

    ; Wait to be started: Start or A on controller 1, or button A on the
    ; nesp32. On the cartridge, Select is its menu; B, which is only ever
    ; back a step, has none to go back to here. A request a frame keeps
    ; watch on the nesp32 meanwhile, and every other one asks what is typed
    ; on the Bluetooth keyboard, whose keys stand for the buttons
    ; (nesp_key_queue): a key is a press, never one held from before.
@idle:
    jsr nesp_key_next
    and #PAD_START | PAD_A | PAD_SELECT | PAD_UP
    bne @pressed
    lda pad
    and #PAD_START | PAD_A | PAD_SELECT | PAD_UP
    bne @down
    lda #1
    sta start_up
    bne @watch
@down:
    ldx start_up
    beq @watch
@pressed:
    sta pressed
    and #PAD_SELECT
    beq @start
    lda on_cart
    beq @watch
    jmp quit
@start:
    lda pressed
    and #PAD_UP
    beq @go
    jsr sweep
    jmp @ran
@watch:
    lda keys_ok
    beq @result
    lda frame_count
    lsr a
    bcc @result
    jsr ask_keys
    jmp @idle
@result:
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
@ran:
    lda #0
    sta testing
    lda #1
    sta ran
    jmp @greeted
.endproc

; Back to the cartridge's menu, as reset would go: through its stub, with
; the NMI off first, since the stub's `inc` puts the menu's bank, and its
; NMI, under this. The menu says hello to the nesp32 (KBD alone), and the
; next program's hello is what tells it which one runs.
.proc quit
    lda #0
    sta PPUCTRL
    sta PPUMASK
    jmp CART_STUB
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
; What has been typed on the Bluetooth keyboard, kept as presses
; (nesp_key_queue).
.proc ask_keys
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS
    ldy #0
    jsr ask
    lda #0
    sta key_at
@key:
    ldx key_at
    cpx nesp_reply
    bcs @done
    lda nesp_reply + 1,x
    jsr nesp_key_queue
    inc key_at
    bne @key
@done:
    rts
.endproc

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
    jsr begin
    lda swept
    beq @paint
    jsr restore_halves
@paint:
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

; A test is under way: the controller is not read, and what it last read
; is let go of.
.proc begin
    lda #1
    sta testing
    lda #0
    sta pad
    rts
.endproc

; Every rate to the console from SWEEP_FIRST, each a whole trial, and a row
; of the table for each: its cycles a bit, its speed, and the bytes of the
; trial that came wrong of those it checked.
.proc sweep
    jsr begin
    say sweep_state
    lda #1
    sta swept
    jsr sweep_table
    lda JOY2                    ; the receivers count on it, as in run_test
    sta port
    cmp #PORT_IDLE
    beq @port
    lda #SWEEP_TOP
    ldx #TEXT_COLUMN
    ldy #TEXT_WIDTH
    jsr field
    put port_text
    lda port
    jsr put_hex
    jmp field_end
@port:
    lda #0
    sta base
    lda #SWEEP_FIRST
    sta rate
@rate:
    jsr sweep_row
    put sweeping_text
    jsr field_end
    lda #0
    sta bad
    sta bad + 1
    sta blocks
@block:
    jsr block
    inc blocks
    lda blocks
    cmp trial_blocks
    bcc @block
    jsr sweep_row
    lda bad
    sta num
    lda bad + 1
    sta num + 1
    jsr put_dec
    put of_text
    ; Bytes checked: a block's, less the ones the receiver settles on.
    ldx rate
    sec
    lda #<BLOCK
    sbc rate_lead,x
    sta ptr
    lda #>BLOCK
    sbc #0
    sta ptr + 1
    lda #0
    sta num
    sta num + 1
    ldx trial_blocks
@sent:
    clc
    lda num
    adc ptr
    sta num
    lda num + 1
    adc ptr + 1
    sta num + 1
    dex
    bne @sent
    jsr put_dec
    jsr field_end
    inc rate
    lda rate
    cmp #RX_COUNT
    bcc @rate
    rts
.endproc
.assert BLOCK = 256, error, "sweep takes BLOCK as its high byte and low"

; The rate's row of the table: its cycles and its speed written, and its
; last column begun.
.proc sweep_row
    lda rate
    clc
    adc #<(SWEEP_TOP - SWEEP_FIRST)  ; mod 256: the row is rate + SWEEP_TOP - SWEEP_FIRST
    pha
    ldx #SWEEP_CYCLES
    ldy #SWEEP_SPEED - SWEEP_CYCLES
    jsr field
    ldx rate
    lda rate_period,x
    sta num
    lda #0
    sta num + 1
    jsr put_dec
    jsr field_end
    pla
    pha
    ldx #SWEEP_SPEED
    ldy #SWEEP_BAD - SWEEP_SPEED
    jsr field
    jsr rate_texts
    ldy #TEXT_SPEED
    jsr put_str
    jsr field_end
    pla
    ldx #SWEEP_BAD
    ldy #TEXT_COLUMN + TEXT_WIDTH - SWEEP_BAD
    jmp field
.endproc

; The halves' rows blanked, and the table's title and heading over them.
.proc sweep_table
    lda #HALF_RX
    sta row
@row:
    lda row
    ldx #TEXT_COLUMN
    ldy #TEXT_WIDTH
    jsr field
    lda row
    cmp #HALF_RX
    bne @heading
    put sweep_title
    jmp @end
@heading:
    cmp #HALF_RX + 1
    bne @end
    put sweep_heading
@end:
    jsr field_end
    inc row
    lda row
    cmp #SWEEP_LAST_ROW + 1
    bcc @row
    rts
.endproc

; The halves' rows as the screen came up with them, from screen_data.
.proc restore_halves
    lda #0
    sta swept
    lda #HALF_RX
    sta row
@row:
    lda row
    ldx #TEXT_COLUMN
    ldy #TEXT_WIDTH
    jsr field
    ; ptr = screen_data + 32 * row + TEXT_COLUMN
    lda row
    sta ptr
    lda #0
    sta ptr + 1
    ldy #5
@times32:
    asl ptr
    rol ptr + 1
    dey
    bne @times32
    clc
    lda ptr
    adc #<(screen_data + TEXT_COLUMN)
    sta ptr
    lda ptr + 1
    adc #>(screen_data + TEXT_COLUMN)
    sta ptr + 1
    ldx draw_at
    ldy #0
@tile:
    lda (ptr),y
    sta draw_buf,x
    inx
    iny
    cpy #TEXT_WIDTH
    bne @tile
    stx draw_at
    jsr field_end
    inc row
    lda row
    cmp #SWEEP_LAST_ROW + 1
    bcc @row
    rts
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

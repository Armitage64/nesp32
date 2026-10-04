; Throughput test ROM for the NES Jukebox's controller-port link.
;
; The jukebox's link runs at one rate, 38400 baud. This ROM finds out how
; fast the same wiring can go: it has a receive routine for each rate of one
; ladder and a send routine for each of another (rates.inc, generated), and
; does what a host tells
; it to with them. The host, an M5Stack Stick (../stick), decides which
; rates to try and puts the results on this screen.
;
; The host is in charge, the reverse of the jukebox: this ROM waits for a
; command, carries it out, and answers (README.md, "Protocol"). Commands
; and replies always travel at the control rate, 9622 baud, which is slow
; enough to be taken as given.
;
;   ping   answer with the number of rates each way
;   draw   write text to the screen at the next vblank
;   rx     receive a 256-byte block at a rate; answer with the number of
;          bytes that differ from the pattern the command's seed makes
;   tx     send that pattern as a 256-byte block at a rate; no answer
;   port   answer with what $4017 reads, which the fastest receive routines
;          count on
;
; Nothing may take cycles from the bit-banged routines, so the NMI is never
; enabled and there are no interrupts at all. The screen is static and is
; only written by a draw command, which waits for vblank by polling. There
; are no timeouts either: a block that loses bytes leaves this ROM waiting
; for the rest, and the host sends filler until it answers.
;
; Wiring is the jukebox's. The host drives D0 (bit 0 of $4017, inverted by
; the port's buffer) and reads OUT0 (bit 0 of $4016 writes), which idles at
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
PPUMASK_BACKGROUND = $0A        ; background on, left column included
NAMETABLE = $2000
PALETTE   = $3F00
OUT0_MARK = $01

CMD_MARKER   = $C5
REPLY_MARKER = $9A
OP_PING = 1
OP_DRAW = 2
OP_RX   = 3
OP_TX   = 4
OP_PORT = 5
DRAW_MAX = 32                   ; tiles in one draw
CMD_MAX = DRAW_MAX + 2          ; the longest payload: an address and the tiles
SETTLE_LOOPS = 42               ; settle's length: 42 * 1286 cycles, 30.2 ms

cmd_buf = $0300
rx_buf  = $0400                 ; the block routines index these with X, so
tx_buf  = $0500                 ; each is a whole page

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM), horizontal mirroring
    .res 8, 0

.segment "ZEROPAGE"
rx_data:  .res 1
tx_data:  .res 1
vector:   .res 2                ; the block routine to call
rx_ptr:   .res 2                ; where the tracking receiver stores
skip:     .res 1                ; bytes at the start of a block not to count
crc_hi:   .res 1
crc_lo:   .res 1
rng:      .res 2                ; low, high
bad:      .res 2                ; bytes of a block that arrived wrong
cmd_seq:  .res 1
cmd_op:   .res 1
cmd_len:  .res 1
cmd_crc:  .res 2
reply:    .res 7

.include "rates.inc"

.segment "RODATA"
.include "crc16_table.inc"

palette:
    .byte $0F, $00, $10, $30    ; text: white on black
    .byte $0F, $0A, $1A, $2A    ; the title: green
    .byte $0F, $00, $10, $30
    .byte $0F, $00, $10, $30
screen_data:
    .incbin "screen.bin"

.segment "CODE"

.proc reset
    sei
    cld
    ldx #FRAME_IRQ_INHIBIT
    stx APU_FRAME
    ldx #$FF
    txs
    inx
    stx PPUCTRL                 ; NMI off, and it stays off
    stx PPUMASK
    stx APU_DMC                 ; DMC IRQ off
    stx APU_STATUS
    lda #OUT0_MARK              ; the line to the host leaves break
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
    ; fall through
.endproc

.proc main
    jsr recv_command
    lda cmd_op
    cmp #OP_PING
    beq ping
    cmp #OP_DRAW
    beq draw
    cmp #OP_PORT
    beq port
    cmp #OP_RX
    beq rx_test
    cmp #OP_TX
    bne @refuse
    jmp tx_test
@refuse:
    jmp refuse

ping:
    lda #RX_COUNT
    ldx #TX_COUNT
    jsr send_reply
    jmp main

draw:
    lda cmd_len
    cmp #2
    bcc refuse
    jsr draw_text
    lda #0
    tax
    jsr send_reply
    jmp main

port:
    lda JOY2
    ldx #0
    jsr send_reply
    jmp main

    ; Both tests wait before they touch the line, and rx again before it
    ; answers: the host changes its UART's rate in those gaps, and whatever
    ; that does to the line is not taken for a start bit.
rx_test:
    lda #RX_COUNT
    jsr test_setup
    bcs refuse
    lda rx_block_lo,x
    sta vector
    lda rx_block_hi,x
    sta vector + 1
    jsr settle
    jsr call_vector
    jsr decode_block            ; the receivers leave their bytes scrambled
    ldy #0
    ldx cmd_buf
    cpx #RX_TRACK_FIRST         ; the tracking one settles on a preamble,
    bcc @whole                  ; which is not counted
    ldy #PREAMBLE
@whole:
    sty skip
    jsr count_bad
    jsr settle
    lda bad
    ldx bad + 1
    jsr send_reply
    jmp main

tx_test:
    lda #TX_COUNT
    jsr test_setup
    bcs refuse
    lda tx_block_lo,x
    sta vector
    lda tx_block_hi,x
    sta vector + 1
    ldx #0
@fill:
    jsr prng_next               ; preserves X
    sta tx_buf,x
    inx
    bne @fill
    jsr settle
    jsr call_vector
    jmp main

refuse:
    lda #$FF
    tax
    jsr send_reply
    jmp main
.endproc

.proc call_vector
    jmp (vector)
.endproc

; A test command's payload is the rate, then the seed. A = the number of
; rates there are that way. Leaves the rate in X and the seed in rng. Carry
; set if the command is not one this ROM can do.
.proc test_setup
    sta bad                     ; free until a block is counted
    lda cmd_len
    cmp #3
    bne @bad
    ldx cmd_buf
    cpx bad
    bcs @bad
    lda cmd_buf + 1
    sta rng
    lda cmd_buf + 2
    sta rng + 1
    ora rng
    beq @bad                    ; a seed of 0 never leaves 0
    clc
    rts
@bad:
    sec
    rts
.endproc

; The next byte of the test pattern, in A: a 16-bit xorshift (7, 9, 8).
; proto.pattern in the host's code does the same steps. Preserves X and Y.
.proc prng_next
    lda rng + 1
    lsr a
    lda rng
    ror a
    eor rng + 1
    sta rng + 1
    ror a
    eor rng
    sta rng
    eor rng + 1
    sta rng + 1
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

; bad = the number of bytes in rx_buf, past the first `skip`, that differ
; from the pattern.
.proc count_bad
    ldy #0
    sty bad
    sty bad + 1
@byte:
    jsr prng_next
    cpy skip
    bcc @same
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

; About 30 ms.
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

; --- commands and replies ------------------------------------------------------

; Wait for a whole command with a good CRC. Anything else on the line is
; passed over, a byte at a time.
.proc recv_command
@marker:
    jsr ctl_rx_byte
    cmp #CMD_MARKER
    bne @marker
    jsr ctl_rx_byte
    sta cmd_seq
    jsr ctl_rx_byte
    sta cmd_op
    jsr ctl_rx_byte
    sta cmd_len
    cmp #CMD_MAX + 1
    bcs @marker
    ldx #0
@payload:
    cpx cmd_len
    beq @crc
    jsr ctl_rx_byte             ; preserves X
    sta cmd_buf,x
    inx
    bne @payload
@crc:
    jsr ctl_rx_byte
    sta cmd_crc
    jsr ctl_rx_byte
    sta cmd_crc + 1

    jsr crc_start
    lda cmd_seq
    jsr crc_update
    lda cmd_op
    jsr crc_update
    lda cmd_len
    jsr crc_update
    ldy #0
@sum:
    cpy cmd_len
    beq @check
    lda cmd_buf,y
    jsr crc_update              ; preserves Y
    iny
    bne @sum
@check:
    lda crc_hi
    cmp cmd_crc
    bne @marker
    lda crc_lo
    cmp cmd_crc + 1
    bne @marker
    rts
.endproc

; Answer the command just received with the 16-bit value in A (low) and X.
.proc send_reply
    sta reply + 3
    stx reply + 4
    lda #REPLY_MARKER
    sta reply
    lda cmd_seq
    sta reply + 1
    lda cmd_op
    sta reply + 2
    jsr crc_start
    ldy #1
@sum:
    lda reply,y
    jsr crc_update
    iny
    cpy #5
    bne @sum
    lda crc_hi
    sta reply + 5
    lda crc_lo
    sta reply + 6
    ldx #0
@send:
    lda reply,x
    jsr ctl_tx_byte             ; preserves X
    inx
    cpx #7
    bne @send
    rts
.endproc

; CRC-16/CCITT-FALSE, as on the jukebox's link.
.proc crc_start
    lda #$FF
    sta crc_hi
    sta crc_lo
    rts
.endproc

.proc crc_update
    eor crc_hi
    tax
    lda crc_lo
    eor crc_table_hi,x
    sta crc_hi
    lda crc_table_lo,x
    sta crc_lo
    rts
.endproc

; --- screen --------------------------------------------------------------------

.proc wait_vblank
    bit PPUSTATUS
@wait:
    bit PPUSTATUS
    bpl @wait
    rts
.endproc

; After writing through PPUADDR, put the scroll back at the top left.
.proc reset_scroll
    lda #0
    sta PPUCTRL
    sta PPUSCROLL
    sta PPUSCROLL
    rts
.endproc

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

    jsr wait_vblank
    jsr reset_scroll
    lda #PPUMASK_BACKGROUND
    sta PPUMASK
    rts
.endproc

; A draw command: a PPU address, high byte first, then the tiles. At most
; DRAW_MAX tiles, about 500 cycles of the 2273 vblank lasts.
.proc draw_text
    jsr wait_vblank
    lda cmd_buf
    sta PPUADDR
    lda cmd_buf + 1
    sta PPUADDR
    ldx #2
@tile:
    cpx cmd_len
    bcs @done
    lda cmd_buf,x
    sta PPUDATA
    inx
    bne @tile
@done:
    jmp reset_scroll
.endproc

.proc nmi
    rti
.endproc

irq = nmi

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

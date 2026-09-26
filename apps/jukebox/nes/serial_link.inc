; Serial link: NES-paced requests and bursts over controller port 2
; (docs/PROTOCOL.md, part 3).
;
; Wiring is nes-radar's. The host drives D0 (read as bit 0 of $4017, inverted
; by the port's buffer) and reads OUT0 (bit 0 of $4016 writes). Both
; directions run at 38400 baud, bit-banged: the host sends 8N2, the NES 8N1.
;
; Once per frame, right after the NMI, link_service asks for a burst with a
; 4-byte request and receives it straight into the ring. If the host is late,
; the next NMI still plays its frame on time and then abandons the receive
; (link_nmi_hook), and the same burst is requested again.
;
; Provides link_init, link_service and the link_nmi_hook macro.

.include "crc16_table.inc"

OP_DATA   = $4A                 ; 'J'
OP_HELLO  = $48                 ; 'H'
REQUEST_SEED = $A5
BURST_MARKER = $A5
CREDIT_MAX = 24                 ; payload bytes per burst; sized in PLAN.md
CREDIT_MIN = 8                  ; don't bother asking for less
OUT0_MARK = $01

.segment "ZEROPAGE"
link_seq:    .res 1             ; burst the NES wants next
credit:      .res 1
rx_data:     .res 1
rx_seq:      .res 1
rx_len:      .res 1
rx_crc:      .res 2
tx_data:     .res 1
request:     .res 4
crc_hi:      .res 1
crc_lo:      .res 1
crc_count:   .res 1
crc_ptr:     .res 2

.segment "BSS"
rx_active:   .res 1             ; the NMI may abandon the receive
rx_sp:       .res 1             ; stack pointer to return to when it does
link_bursts: .res 2             ; committed bursts
link_aborts: .res 2             ; receives cut off by the NMI
link_rejects: .res 2            ; framing, length or sequence failures
link_crc_errors: .res 2

; Anonymous labels only: a named one would end the caller's @-label scope.
.macro inc16 counter
    inc counter
    bne :+
    inc counter + 1
:
.endmacro

; In the NMI, after the frame has played. If a receive is in flight, make the
; NMI return to rx_abort instead of into it. The stack holds, from the top:
; Y, X, A (pushed by nmi), then P, PCL, PCH (pushed by the CPU).
.macro link_nmi_hook
    .local done
    lda rx_active
    beq done
    lda #0
    sta rx_active
    tsx
    lda #<rx_abort
    sta $0105,x
    lda #>rx_abort
    sta $0106,x
done:
.endmacro

.segment "CODE"

; Idle OUT0 at mark, give the host's UART a moment to leave break, and say
; hello so the host starts the track from the beginning.
.proc link_init
    lda #OUT0_MARK
    sta JOY1
    ldx #0
@guard:                         ; about 1.3 ms of mark
    nop
    nop
    dex
    bne @guard
    lda #OP_HELLO
    ldx #0
    ldy #0
    jmp send_request
.endproc

; Request a burst sized to the free ring space, receive it, and commit it.
.proc link_service
    jsr ring_free
    bne @use_max
    lda free
    cmp #CREDIT_MAX
    bcc @have_credit
@use_max:
    lda #CREDIT_MAX
@have_credit:
    cmp #CREDIT_MIN
    bcc @done
    sta credit
    lda #OP_DATA
    ldx link_seq
    ldy credit
    jsr send_request
    jsr rx_burst
    bcs @done
    jsr commit_tail
    inc link_seq
    inc16 link_bursts
    lda rx_len
    bne @done
    lda #1                      ; the host only sends empty bursts once the
    sta link_done               ; track has ended, so play what we have
@done:
    rts
.endproc

; A = op, X = seq, Y = arg. Sends the 4-byte request.
.proc send_request
    sta request
    stx request + 1
    sty request + 2
    eor request + 1
    eor request + 2
    eor #REQUEST_SEED
    sta request + 3
    ldx #0
@next:
    lda request,x
    jsr tx_byte                 ; preserves X
    inx
    cpx #4
    bne @next
    rts
.endproc

; Receive one burst into the ring at tail. Carry clear when it arrived intact
; for the sequence and credit asked for; the caller then commits it.
;
; Between bytes there are about 50 cycles before the next start bit can
; arrive (the host sends 2 stop bits), so the per-byte work below is kept
; short and page wraps are handled inline.
.proc rx_burst
    tsx
    stx rx_sp
    jsr begin_write
    lda #1
    sta rx_active
marker:
    jsr rx_byte
    bcs marker                  ; noise: keep looking
    cmp #BURST_MARKER
    bne marker
    jsr rx_byte
    bcs reject
    sta rx_seq
    jsr rx_byte
    bcs reject
    sta rx_len
    tax
    beq crc_bytes
payload:
    jsr rx_byte
    bcs reject
    ldy #0
    sta (wptr),y
    advance_wptr
    dex
    bne payload
crc_bytes:
    jsr rx_byte
    bcs reject
    sta rx_crc
    jsr rx_byte
    bcs reject
    sta rx_crc + 1
    lda #0
    sta rx_active               ; everything is in; the NMI may not abort now

    lda rx_seq
    cmp link_seq
    bne reject
    lda credit
    cmp rx_len
    bcc reject                  ; more than the credit
    jsr burst_crc
    lda crc_hi
    cmp rx_crc
    bne crc_error
    lda crc_lo
    cmp rx_crc + 1
    bne crc_error
    clc
    rts
crc_error:
    inc16 link_crc_errors
    sec
    rts
reject:
    lda #0
    sta rx_active
    inc16 link_rejects
    sec
    rts
.endproc

; The NMI returns here when it cuts off a receive. Unwind to rx_burst's
; caller as a failed receive.
.proc rx_abort
    ldx rx_sp
    txs
    inc16 link_aborts
    sec
    rts
.endproc

; CRC-16/CCITT-FALSE over SEQ, LEN and the payload now in the ring at tail.
.proc burst_crc
    lda #$FF
    sta crc_hi
    sta crc_lo
    lda rx_seq
    jsr crc_update
    lda rx_len
    jsr crc_update
    lda rx_len
    beq @done
    sta crc_count
    lda tail
    sta crc_ptr
    lda tail + 1
    sta crc_ptr + 1
@byte:
    ldy #0
    lda (crc_ptr),y
    jsr crc_update
    inc crc_ptr
    bne @same_page
    inc crc_ptr + 1
    lda crc_ptr + 1
    cmp #RING_END_PAGE
    bne @same_page
    lda #>RING
    sta crc_ptr + 1
@same_page:
    dec crc_count
    bne @byte
@done:
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

; --- cycle-timed routines ----------------------------------------------------
;
; A bit at 38400 baud is 46.61 CPU cycles (NTSC, 1.789773 MHz), so bits are
; spaced 47, 46, 47, ... cycles to stay within half a cycle of ideal. The
; routines live on their own pages so no branch pays the page-crossing
; cycle, and tests/test_serial_timing.py measures every read and write they
; make against the ideal bit centers.

; Burn exactly n cycles (n >= 6) with Y.
.macro delay n
    .local loop
    .if ((n - 1) .mod 5) = 1
        ldy #(n - 1) / 5 - 1
        nop
        nop
        nop
    .else
        ldy #(n - 1) / 5
        .if ((n - 1) .mod 5) = 2
            nop
        .elseif ((n - 1) .mod 5) = 3
            bit $00
        .elseif ((n - 1) .mod 5) = 4
            nop
            nop
        .endif
    .endif
loop:
    dey
    bne loop
.endmacro

.segment "RXTX"

; Receive one byte. Waits for a start bit, samples the 8 data bits and the
; stop bit at their centers, and returns the byte in A. Carry set means the
; stop bit was low (a framing error). Destroys Y.
;
; t0 is the cycle on which the hunt's lda read the start bit. The edge fell
; somewhere in the 9 cycles before it, 4.5 on average, so bit k's center is
; t0 - 4.5 + 46.61 * (1.5 + k), and each sampling lda starts 3 cycles before
; its read.
.proc rx_byte
::rx_hunt:                      ; tests fast-forward while this sees mark
    lda JOY2
    lsr                         ; carry = inverted D0: set while the line is low
    bcc rx_hunt
                                ; t0 + 5
    delay 57                    ; bit 0 lda at t0 + 62
    lda JOY2
    lsr
    ror rx_data
    delay 36                    ; bit 1 at t0 + 109
    lda JOY2
    lsr
    ror rx_data
    delay 36                    ; bit 2 at t0 + 156
    lda JOY2
    lsr
    ror rx_data
    delay 35                    ; bit 3 at t0 + 202
    lda JOY2
    lsr
    ror rx_data
    delay 36                    ; bit 4 at t0 + 249
    lda JOY2
    lsr
    ror rx_data
    delay 35                    ; bit 5 at t0 + 295
    lda JOY2
    lsr
    ror rx_data
    delay 36                    ; bit 6 at t0 + 342
    lda JOY2
    lsr
    ror rx_data
    delay 36                    ; bit 7 at t0 + 389
    lda JOY2
    lsr
    ror rx_data
    delay 35                    ; stop bit at t0 + 435
    lda JOY2
    lsr                         ; carry set if the stop bit is low
    lda rx_data
    eor #$FF                    ; the bits arrived inverted; carry survives
    rts
.endproc

.align 256

; Send A as 8N1. OUT0 must be at mark. Each bit is written by the last cycle
; of a sta, the data bit reaching A without a branch (lsr, then rol into a
; cleared A), so every bit costs the same. Returns after holding the stop bit
; for a full bit, so back-to-back calls keep one stop bit between bytes.
; Destroys A, Y. Preserves X.
.proc tx_byte
    sta tx_data
    lda #0
    sta JOY1                    ; start bit at W
    delay 34
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 0 at W + 47
    delay 33
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 1 at W + 93
    delay 34
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 2 at W + 140
    delay 33
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 3 at W + 186
    delay 34
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 4 at W + 233
    delay 34
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 5 at W + 280
    delay 33
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 6 at W + 326
    delay 34
    lsr tx_data
    lda #0
    rol a
    sta JOY1                    ; bit 7 at W + 373
    delay 40
    lda #OUT0_MARK
    sta JOY1                    ; stop bit at W + 419
    delay 47
    rts
.endproc

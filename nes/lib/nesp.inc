; nesp: the console's side of the link to a Stick on controller port 2
; (docs/PROTOCOL.md). Every ROM that uses a Stick includes this.
;
; Before including it, a ROM defines
;
;   NESP_RX_MASK    $1F, $3F or $7F: the longest reply payload it takes.
;                   Its hello says so, and no reply can be stored past it.
;   NESP_TX_MAX     the longest request payload it sends
;   JOY1, JOY2, OUT0_MARK
;   NESP_CRC_TABLE  optional. Defined, the CRC is worked out from a table:
;                   512 bytes of ROM, and 35 cycles a byte where the code
;                   without one takes 66
;   NESP_TIMEOUT    only if link.inc was made with --timeout, for exchanges
;                   made inside the NMI: how long to wait for a reply, in
;                   passes of 256 looks of 13 cycles (1.86 ms each)
;
; and has the segments ZEROPAGE, BSS, CODE and RXTX (aligned to a page).
;
; Every use of the link is one exchange: a request goes out, and one reply
; comes back or does not.
;
;   nesp_request    the request's payload goes here
;   nesp_call       A = service, X = op, Y = the payload's length. Carry
;                   clear and A = the reply's status if a good reply came;
;                   carry set if none did
;   nesp_again      the same request once more, byte for byte. The Stick
;                   answers it with the same reply, and does nothing twice
;   nesp_reply      the reply's payload, nesp_reply_len bytes of it
;   nesp_attention  not 0 if the Stick has an event waiting (SYS EVENT)
;
; The serial routines count CPU cycles (link.inc, generated), so nothing
; may interrupt them, and the receiver waits for a start bit with no timeout
; of its own. The NMI is the timeout: while an exchange is under way
; (nesp_active), the NMI handler does its work as always and then, in place
; of going back into the middle of a bit, returns to nesp_abort, which drops
; the exchange and reports it failed. The handler must end with
; nesp_nmi_hook, and an exchange must not be made with the NMI off. An
; exchange that does not fit before the next vblank costs nothing but
; itself, and the caller asks again in a later frame.
;
; The Stick drives D0 (bit 0 of JOY2, inverted by the port's buffer) and
; reads OUT0 (bit 0 of JOY1 writes), which rests at mark: a ROM writes
; OUT0_MARK to JOY1 at reset, and reads its controller by dropping OUT0 for
; the reads and raising it again, with no separate strobe pulse.

.include "nesp_proto.inc"

.segment "ZEROPAGE"
nesp_rx_data:   .res 1
nesp_tx_data:   .res 1
nesp_rx_end:    .res 1          ; where the frame being received ends
nesp_active:    .res 1          ; an exchange is under way: the NMI ends it
nesp_sp:        .res 1          ; the stack as the exchange's caller left it
nesp_seq:       .res 1          ; the last request's sequence number
nesp_tx_len:    .res 1          ; the whole of the request, in bytes
nesp_count:     .res 1
nesp_index:     .res 1
nesp_crc_hi:    .res 1
nesp_crc_lo:    .res 1
nesp_ptr:       .res 2
nesp_status:    .res 1          ; the last good reply's, less the attention bit
nesp_attention: .res 1
.ifdef NESP_TIMEOUT
nesp_tries:     .res 1
.endif

; After the zero page's names, so that the routines use them as zero page.
.include "link.inc"

.segment "BSS"
nesp_rx:        .res NESP_RX_MASK + 1 + NESP_OVERHEAD
nesp_tx:        .res NESP_TX_MAX + NESP_OVERHEAD
nesp_request   = nesp_tx + NESP_HEADER
nesp_reply     = nesp_rx + NESP_HEADER
nesp_reply_len = nesp_rx + NESP_HEADER - 1

.segment "CODE"

; Last thing in the NMI. The stack holds Y, X and A above the flags and the
; address the NMI interrupted, which is replaced.
.macro nesp_nmi_hook
    lda nesp_active
    beq :+
    tsx
    lda #<nesp_abort
    sta $0105,x
    lda #>nesp_abort
    sta $0106,x
:
.endmacro

; A new request: service A, op X, Y bytes of payload already in
; nesp_request. See the top of the file.
.proc nesp_call
    sta nesp_tx + 1
    stx nesp_tx + 2
    sty nesp_tx + 4
    inc nesp_seq
    lda nesp_seq
    sta nesp_tx + 3
    lda #NESP_REQUEST_MARKER
    sta nesp_tx
    lda #<nesp_tx
    sta nesp_ptr
    lda #>nesp_tx
    sta nesp_ptr + 1
    jsr nesp_sum
    lda nesp_crc_hi
    sta (nesp_ptr),y
    iny
    lda nesp_crc_lo
    sta (nesp_ptr),y
    iny
    sty nesp_tx_len
    ; fall through
.endproc

.proc nesp_again
    tsx
    stx nesp_sp
    lda #1
    sta nesp_active             ; from here the NMI may end this
    ldx #0
@send:
    lda nesp_tx,x
    jsr nesp_tx_byte            ; preserves X
    inx
    cpx nesp_tx_len
    bne @send
.ifdef NESP_TIMEOUT
    lda #NESP_TIMEOUT
    sta nesp_tries
.endif
    jsr nesp_rx_frame
    lda #0
    sta nesp_active
    bcs @bad                    ; the wait for it ran out

    ; A reply to this request, and whole?
    lda nesp_rx
    cmp #NESP_REPLY_MARKER
    bne @bad
    lda nesp_rx + 1
    cmp nesp_tx + 1
    bne @bad
    lda nesp_rx + 3
    cmp nesp_tx + 3
    bne @bad
    lda nesp_rx + 4
    cmp #NESP_RX_MASK + 1
    bcs @bad
    lda #<nesp_rx
    sta nesp_ptr
    lda #>nesp_rx
    sta nesp_ptr + 1
    jsr nesp_sum
    lda (nesp_ptr),y
    cmp nesp_crc_hi
    bne @bad
    iny
    lda (nesp_ptr),y
    cmp nesp_crc_lo
    bne @bad
    lda nesp_rx + 2
    and #NESP_ST_ATTENTION
    sta nesp_attention
    lda nesp_rx + 2
    and #<~NESP_ST_ATTENTION
    sta nesp_status
    clc
    rts
@bad:
    sec
    rts
.endproc

; Where the NMI returns to when it cuts an exchange off: back to the
; exchange's caller, with carry set. OUT0 may have been left low in the
; middle of a byte.
.proc nesp_abort
    ldx nesp_sp
    txs
    lda #0
    sta nesp_active
    lda #OUT0_MARK
    sta JOY1
    sec
    rts
.endproc

; The CRC of the frame at nesp_ptr, from the byte after its marker to the
; end of its payload, into nesp_crc_hi and nesp_crc_lo. Leaves Y at the
; first of the frame's own two check bytes.
.proc nesp_sum
    ldy #NESP_HEADER - 1
    lda (nesp_ptr),y            ; the payload's length
    clc
    adc #NESP_HEADER
    sta nesp_count              ; where the payload ends
    lda #>NESP_CRC_INIT
    sta nesp_crc_hi
    lda #<NESP_CRC_INIT
    sta nesp_crc_lo
    ldy #1
@byte:
    lda (nesp_ptr),y
    sty nesp_index
    jsr nesp_crc
    ldy nesp_index
    iny
    cpy nesp_count
    bne @byte
    rts
.endproc

; Take A into the CRC: CRC-16/CCITT-FALSE, polynomial $1021.
.ifdef NESP_CRC_TABLE

; nesp_crc_table_hi and _lo (link.inc) hold, for each value of the
; register's high byte, the register after that byte has been through
; eight rounds. Preserves Y.
.proc nesp_crc
    eor nesp_crc_hi
    tax
    lda nesp_crc_lo
    eor nesp_crc_table_hi,x
    sta nesp_crc_hi
    lda nesp_crc_table_lo,x
    sta nesp_crc_lo
    rts
.endproc

.else

; With no table: the polynomial's three terms, x^12, x^5 and 1, shifted
; into place from the byte. 66 cycles. After Greg Cook's routine
; (6502.org, "CRC-16 without tables"). Destroys X and Y.
.proc nesp_crc
    eor nesp_crc_hi
    sta nesp_crc_hi
    lsr a
    lsr a
    lsr a
    lsr a
    tax                         ; the top of the x^12 term
    asl a                       ; the top of the x^5 term
    eor nesp_crc_lo
    sta nesp_crc_lo
    txa
    eor nesp_crc_hi
    sta nesp_crc_hi
    asl a
    asl a
    asl a
    tax                         ; the bottom of the x^12 term
    asl a
    asl a
    eor nesp_crc_hi             ; the bottom of the x^5 term
    tay
    txa
    rol a                       ; the bottom of x^12 and the middle of x^5
    eor nesp_crc_lo
    sta nesp_crc_hi             ; and the two bytes change places
    sty nesp_crc_lo
    rts
.endproc

.endif

; Say hello: who this ROM is and the services it needs. Before the call,
; nesp_request + NESP_HELLO_FIXED on holds the services' ids, Y of them.
; The ROM defines NESP_APP as a string of NESP_APP_ID characters, and
; NESP_APP_VERSION. Carry clear and A = the status if the Stick answered;
; then nesp_reply holds its protocol, its version (3 bytes), its board, the
; longest request payload it takes, and the services asked for that it does
; not have: how many, then their ids.
NESP_HELLO_FIXED = 3 + NESP_APP_ID

.proc nesp_hello
    tya
    clc
    adc #NESP_HELLO_FIXED
    tay
    lda #NESP_PROTOCOL
    sta nesp_request
    ldx #NESP_APP_ID - 1
@id:
    lda nesp_app_id,x
    sta nesp_request + 1,x
    dex
    bpl @id
    lda #NESP_APP_VERSION
    sta nesp_request + 1 + NESP_APP_ID
    lda #NESP_RX_MASK
    sta nesp_request + 2 + NESP_APP_ID
    lda #NESP_SVC_SYS
    ldx #NESP_SYS_HELLO
    jmp nesp_call
.endproc

nesp_app_id:
    .byte NESP_APP
.assert * - nesp_app_id = NESP_APP_ID, error, "NESP_APP must be NESP_APP_ID characters"

; The next byte of the test pattern (DIAG PATTERN and SINK) in A: a 16-bit
; xorshift (7, 9, 8) kept in nesp_rng, which must not be 0. Preserves X
; and Y.
.segment "ZEROPAGE"
nesp_rng:       .res 2
.segment "CODE"
.proc nesp_pattern
    lda nesp_rng + 1
    lsr a
    lda nesp_rng
    ror a
    eor nesp_rng + 1
    sta nesp_rng + 1
    ror a
    eor nesp_rng
    sta nesp_rng
    eor nesp_rng + 1
    sta nesp_rng + 1
    rts
.endproc

; Serial link: NES-paced requests and bursts over controller port 2
; (docs/PROTOCOL.md, part 3).
;
; Wiring is nes-radar's. The host drives D0 (read as bit 0 of $4017, inverted
; by the port's buffer) and reads OUT0 (bit 0 of $4016 writes). Both
; directions run at 38400 baud, bit-banged: the host sends 8N2, the NES 8N1.
;
; Right after an NMI, link_service asks for a burst with a 4-byte request and
; receives it straight into the ring. While it waits for the burst's marker,
; NMIs play their frames and return to the wait, so a host that answers a
; frame or two late still gets through. Only two things end a receive early
; (link_nmi_hook): an NMI landing in the middle of a burst, since the bytes
; that arrive during the NMI are lost, and HUNT_TIMEOUT_FRAMES of waiting
; with no marker. Either way the same burst is requested again.
;
; A host whose reply time is steady but slow would otherwise land every
; resend across the NMI at the same point in the frame, forever. So after a
; receive is cut off or times out, the next request waits longer after the NMI, stepping
; request_delay through 0-9 units of about 1.3 ms, three at a time. A
; delay that works is kept, so a steady host settles within a few tries and
; a fast one never moves off zero.
;
; A press on the controller (ui.inc) goes to the host as a button request,
; in place of one frame's data request. The host acts on it; what comes back
; is the stream it then sends, usually starting with a flush burst.
;
; Sampled sound (docs/PROTOCOL.md, part 4) takes the link over. When the
; NMI plays a sound record, link_service asks for the sound in place of
; data, and the host answers with a go burst. From there the console does
; nothing but receive: the NMI is off, the screen stands still, and one of
; the routines in pcm_rates.inc writes each byte to $4011 as it arrives, at
; a rate several times the link's own, until a byte marked as the last.
; Then the NMI goes back on and the link carries on where it was.
;
; Provides link_init, link_service, link_button and the link_nmi_hook macro.

.include "crc16_table.inc"
.include "pcm_rates.inc"

OP_DATA   = $4A                 ; 'J'
OP_HELLO  = $48                 ; 'H'
OP_STATS  = $53                 ; 'S'
OP_BUTTON = $42                 ; 'B'
OP_SOUND  = $50                 ; 'P'
STATS_EVERY = 16                ; frames between counter reports; a power of 2
REQUEST_SEED = $A5
BURST_MARKER = $A5
FLUSH_MARKER = $5A              ; a burst that first drops what is buffered
PAUSE_MARKER = $3C              ; an empty burst: hold the music where it is
SOUND_MARKER = $C3              ; a go burst: sound follows, at the rate it names
SOUND_REFUSED = $FF             ; a sound request's rate when the console cannot play it
SOUND_SETTLE = 116              ; units of 1.3 ms before listening for sound: 150 ms,
                                ; while the host makes sure and changes its rate
SOUND_REST = 23                 ; and after it, while the host changes back: 30 ms
CREDIT_MAX = 24                 ; payload bytes per burst; sized in PLAN.md
CREDIT_MIN = 8                  ; don't bother asking for less
HUNT_TIMEOUT_FRAMES = 4         ; frames to wait for a marker before asking again
DELAY_STEPS = 10                ; request_delay runs 0 .. DELAY_STEPS - 1
DELAY_STRIDE = 3                ; units to move after a burst is cut off
OUT0_MARK = $01

.segment "ZEROPAGE"
link_seq:    .res 1             ; burst the NES wants next
credit:      .res 1
rx_data:     .res 1
rx_marker:   .res 1             ; BURST_MARKER, FLUSH_MARKER or PAUSE_MARKER
rx_seq:      .res 1
rx_len:      .res 1
rx_crc:      .res 2
tx_data:     .res 1
request:     .res 4
crc_hi:      .res 1
crc_lo:      .res 1
crc_count:   .res 1
crc_ptr:     .res 2
sound_vector: .res 2            ; the routine for the rate

.segment "BSS"
req_op:      .res 1             ; the request this frame sends: OP_DATA or OP_SOUND
req_arg:     .res 1             ; its credit, or its rate
rx_hunting:  .res 1             ; waiting for a burst's marker
hunt_frames: .res 1             ; NMIs seen while waiting
rx_active:   .res 1             ; a burst is arriving; an NMI must abandon it
rx_sp:       .res 1             ; stack pointer to return to when it does
rx_missed:   .res 1             ; the last receive was cut off or timed out
request_delay: .res 1           ; units of about 1.3 ms to wait before asking
stats_index: .res 1             ; which counter the next report carries
button_pending: .res 1          ; EVENT_* bits the host has not been told yet
link_bursts: .res 2             ; committed bursts
link_aborts: .res 2             ; bursts cut off by an NMI
link_timeouts: .res 2           ; waits with no marker for HUNT_TIMEOUT_FRAMES
link_rejects: .res 2            ; framing, length or sequence failures
link_crc_errors: .res 2

; Anonymous labels only: a named one would end the caller's @-label scope.
.macro inc16 counter
    inc counter
    bne :+
    inc counter + 1
:
.endmacro

; In the NMI, after the frame has played. To end a receive, make the NMI
; return to rx_abort instead of into it. The stack holds, from the top:
; Y, X, A (pushed by nmi), then P, PCL, PCH (pushed by the CPU).
.macro link_nmi_hook
    .local hunting, abort, done
    lda rx_active
    beq hunting
    inc16 link_aborts
    jmp abort
hunting:
    lda rx_hunting
    beq done
    inc hunt_frames
    lda hunt_frames
    cmp #HUNT_TIMEOUT_FRAMES
    bcc done
    inc16 link_timeouts
    lda #LINK_WAITING
    sta link_state
abort:
    lda #1
    sta rx_missed
    lda #0
    sta rx_active
    sta rx_hunting
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

; The controller asked for something (EVENT_* bits in A). Called from the
; NMI; the main loop sends it with its next request.
.proc link_button
    ora button_pending
    sta button_pending
    rts
.endproc

; Request a burst sized to the free ring space, receive it, and commit it.
.proc link_service
    ldy button_pending          ; a button press goes first, in place of this
    beq @no_button              ; frame's request; the host does not answer it
    lda #0
    sta button_pending
    lda #OP_BUTTON
    ldx #0
    jmp send_request
@no_button:
    lda frame_count             ; every STATS_EVERY frames, a counter report
    and #STATS_EVERY - 1        ; takes the place of the data request
    bne @data
    jmp send_stats
@data:
    lda sound_wanted
    beq @music
    ; A sound record has played. Ask for the sound, once every line the
    ; record's frame changed is on the screen and the bars are off it: it
    ; will not be drawn again until the sound is over. The answer may be a flush burst
    ; instead (a host that was stopped, or changed track), so there is
    ; credit for one.
    lda text_pending
    bne @idle
    lda ui_status
    cmp status_drawn
    bne @idle
    ldx #BAR_COUNT - 1          ; and every bar is down, on the screen too
@bar:
    lda ui_drawn,x
    ora ui_level,x
    bne @idle
    dex
    bpl @bar
    jsr sound_rate
    sta req_arg
    lda #OP_SOUND
    sta req_op
    lda #CREDIT_MAX
    sta credit
    bne @delay
@idle:
    jmp @done
@music:
    lda #OP_DATA
    sta req_op
    jsr ring_free
    bne @use_max
    lda free
    cmp #CREDIT_MAX
    bcc @have_credit
@use_max:
    lda #CREDIT_MAX
@have_credit:
    cmp #CREDIT_MIN
    bcs @credit
    ldx paused                  ; paused, keep asking with whatever room there
    bne @credit                 ; is, even none: the answer says when to go on
    jmp @done
@credit:
    sta credit
    sta req_arg
@delay:
    ldx request_delay
    beq @ask
@wait:
    jsr wait_unit
    dex
    bne @wait
@ask:
    lda req_op
    ldx link_seq
    ldy req_arg
    jsr send_request
    jsr rx_burst
    bcc @received
    lda rx_missed
    bne @missed
    jmp @done
@missed:
    lda #0
    sta rx_missed
    lda request_delay           ; move the next request later in the frame
    clc
    adc #DELAY_STRIDE
    cmp #DELAY_STEPS
    bcc @moved
    sbc #DELAY_STEPS
@moved:
    sta request_delay
    rts
@received:
    ; A pause burst holds the music: the NMI stops decoding and the APU is
    ; silenced, with everything buffered kept. Any other burst lets it go
    ; on, with the channel enables put back from the screen's copy.
    lda rx_marker
    cmp #SOUND_MARKER
    bne @not_go
    jsr sound_go
    jmp @done
@not_go:
    cmp #PAUSE_MARKER
    bne @not_pause
    lda paused
    bne @commit
    lda #1
    sta paused
    lda #0
    sta APU_STATUS
    beq @commit
@not_pause:
    lda paused
    beq @running
    lda apu_shadow + $15
    sta APU_STATUS
    lda #0
    sta paused
@running:
    lda rx_marker
    cmp #FLUSH_MARKER
    bne @commit
    lda tail                    ; a flush burst: the NMI moves head to here,
    sta flush_head              ; the start of this burst's payload, and
    lda tail + 1                ; stops playback until the ring refills.
    sta flush_head + 1          ; flush_head is whole before the flag is set.
    lda #0
    sta link_done
    sta sound_wanted            ; a sound that was due went with the rest
    lda #1
    sta flush_pending
@commit:
    jsr commit_tail
    inc link_seq
    inc16 link_bursts
    ldx #LINK_STREAMING
    lda rx_len
    bne @state
    lda rx_marker               ; an empty flush burst means "stopped": stay
    cmp #FLUSH_MARKER           ; quiet and keep asking
    bne @ended
    ldx #LINK_STOPPED
@state:
    stx link_state
    jmp @done
@ended:
    stx link_state
    lda #1                      ; the host only sends empty bursts once the
    sta link_done               ; track has ended, so play what we have
@done:
    ; A burst that came a frame late ends partway through a frame. Count
    ; that frame as served, so the next request waits for the next NMI. Sent
    ; from here, its reply would run into that NMI and be cut off, and a
    ; slow host would lose every other burst. (A receive that was cut off
    ; returns above without this: it ends at an NMI, and that frame still
    ; needs its request.)
    lda frame_count
    sta served_frame
    rts
.endproc

; A = the rate to ask for sound at: the one its record named, or
; SOUND_REFUSED if this console cannot play it. That is a rate it has no
; routine for, or a port that does not read as the routines count on (the
; line is at rest here: the host only sends when asked). A refusal stays
; refused until the host's flush burst takes it away.
.proc sound_rate
    ldx sound_wanted
    dex
    cpx #PCM_COUNT
    bcs @refuse
    lda JOY2
    cmp #PORT_IDLE
    bne @refuse
    txa
    rts
@refuse:
    lda #SOUND_REFUSED
    sta sound_wanted
    rts
.endproc

; A go burst arrived: play the sound it announces, if it is the one asked
; for. The host listens for a moment in case this console missed the burst
; and asks again, then changes its UART's rate and sends the samples; the
; wait before listening for them covers both. An NMI would take cycles from
; the receiver, so it is off until the sound is over.
.proc sound_go
    inc link_seq
    inc16 link_bursts
    ldx sound_wanted
    dex
    cpx #PCM_COUNT
    bcs @out                    ; none was asked for
    lda rx_len
    cmp #1
    bne @out
    txa
    ldy #0
    cmp (tail),y                ; its payload, the rate, is in the ring uncommitted
    bne @out
    lda #0
    sta PPUCTRL
    sta APU_STATUS
    sta sound_wanted
    lda pcm_stream_lo,x
    sta sound_vector
    lda pcm_stream_hi,x
    sta sound_vector + 1
    ldx #SOUND_SETTLE
    jsr wait_units
    jsr @play
    ldx #SOUND_REST
    jsr wait_units
    bit PPUSTATUS               ; a vblank that came and went is not an NMI now
    lda #PPUCTRL_NMI
    sta PPUCTRL
@out:
    rts
@play:
    jmp (sound_vector)
.endproc

; X units of about 1.3 ms.
.proc wait_units
@unit:
    jsr wait_unit
    dex
    bne @unit
    rts
.endproc

; Tell the host one of the link counters (its low byte), taking them in
; turn. The console has no screen for them, and they are the only way to
; tell a cut-off from a timeout from a damaged burst on real hardware.
.proc send_stats
    ldx stats_index
    lda stats_lo,x
    sta crc_ptr
    lda stats_hi,x
    sta crc_ptr + 1
    ldy #0
    lda (crc_ptr),y
    tay
    lda #OP_STATS
    jsr send_request
    ldx stats_index
    inx
    cpx #STATS_COUNT
    bcc @store
    ldx #0
@store:
    stx stats_index
    rts
.endproc

.define STATS_TABLE link_aborts, link_timeouts, link_rejects, link_crc_errors, request_delay, underruns, link_bursts
stats_lo: .lobytes STATS_TABLE
stats_hi: .hibytes STATS_TABLE
STATS_COUNT = * - stats_hi

; About 1.3 ms (2306 cycles). Preserves X.
.proc wait_unit
    ldy #0
@loop:
    nop
    nop
    dey
    bne @loop
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
    lda #0
    sta hunt_frames
    lda #1
    sta rx_hunting
marker:
    jsr rx_byte
    bcs marker                  ; noise: keep looking
    cmp #BURST_MARKER
    beq found
    cmp #PAUSE_MARKER
    beq found
    cmp #SOUND_MARKER
    beq found
    cmp #FLUSH_MARKER
    bne marker
found:
    sta rx_marker
    lda #1                      ; set before clearing rx_hunting, so an NMI
    sta rx_active               ; in between still ends the receive
    lda #0
    sta rx_hunting
    jsr rx_byte
    bcs reject
    sta rx_seq
    jsr rx_byte
    bcs reject
    sta rx_len
    lda credit                  ; a length beyond the credit is damage, and
    cmp rx_len                  ; storing it would run past the free space
    bcc reject                  ; into music that has not played yet
    ldx rx_len
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

; The NMI returns here when it ends a receive, having counted why. Unwind
; to rx_burst's caller as a failed receive.
.proc rx_abort
    ldx rx_sp
    txs
    sec
    rts
.endproc

; CRC-16/CCITT-FALSE over SEQ, LEN and the payload now in the ring at tail.
; A flush or pause burst's CRC covers its marker as well, so a damaged
; ordinary burst cannot pass for one.
.proc burst_crc
    lda #$FF
    sta crc_hi
    sta crc_lo
    lda rx_marker
    cmp #BURST_MARKER
    beq @body
    jsr crc_update
@body:
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

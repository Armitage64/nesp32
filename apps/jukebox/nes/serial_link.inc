; Serial link: a nesp32 on controller port 2 holds the music. The link ROM's
; host, in place of fake_link.inc.
;
; Provides link_init, link_service, link_button and the link_nmi_hook macro.
;
; The link itself is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md):
; one firmware on the nesp32 serves every ROM, and this one asks it for the
; JUKE service, and for RAW, which carries sampled sound. Every use of the
; link is one exchange: a request goes out, and one reply comes back or does
; not. The NMI is the timeout: an exchange that has not ended by the next
; vblank is dropped there and reported as failed.
;
; Right after an NMI, link_service makes the frame's one exchange. Most
; frames that is JUKE STREAM: "this is where I have got to in the stream,
; and I have room for this much more", answered with the bytes from there,
; which go into the ring. Nothing needs asking twice in any special way: a
; reply that was lost is the same question again a frame later, with the
; same position, and the same bytes come.
;
; The reply says which epoch its bytes belong to. An epoch is a stretch of
; the stream with no jump in it; a reply from another one than the ring's
; (another track, stop, the music after a sound) means that what the ring
; holds is not wanted, and it is dropped before the reply's bytes go in.
;
; A press on the controller (ui.inc) goes out as JUKE BUTTON, in place of
; one frame's stream request, and is sent again until it is answered. The
; nesp32 does it once however often it hears it, and what comes of it is
; the stream it then sends, usually in a new epoch.
;
; Sampled sound (docs/PROTOCOL.md, part 4) takes the line over. When the
; NMI plays a sound record, link_service asks for the sound (JUKE SOUND) in
; place of the stream. If the answer is GO, the console does nothing but
; receive from there: the NMI is off, the screen stands still, and one of
; the routines in pcm_rates.inc writes each byte to $4011 as it arrives, at
; a rate several times the link's own, until a byte marked as the last.
; Then the NMI goes back on and the link carries on where it was.
;
; Button A is all of the controller that is looked at during a sound, and
; it pauses: the console leaves the sound, tells the nesp32 so, and is back
; with the NMI on and the whole controller read. The sound is still wanted,
; and the nesp32 says the music is paused, so the stream is asked for until
; it says otherwise; then the sound is, and goes on from where it was left.
;
; The nesp32 knows this ROM by its hello, which goes out before anything
; else and again whenever the nesp32 says it has no such service in use: it
; was switched off and on, and has forgotten the hello.

OUT0_MARK = $01

NESP_RX_MASK = $3F              ; replies of up to 63 bytes
NESP_TX_MAX  = 9                ; the hello, with its two services
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a reply is checked and in the
                                ; ring well inside the frame it arrived in
.define NESP_APP "JUKE"
NESP_APP_VERSION = 2

.include "nesp.inc"
.include "pcm_rates.inc"

.assert NESP_TX_MAX = NESP_HELLO_FIXED + 2, error, "the hello names two services"

; JUKE STREAM's reply (nesp32's docs/PROTOCOL.md): the state of the music,
; the epoch its bytes belong to, and the bytes.
STREAM_STATE = nesp_reply
STREAM_EPOCH = nesp_reply + 1
STREAM_BYTES = nesp_reply + 2
STREAM_HEAD  = 2
; JUKE SOUND's: the state, and whether the sound is coming.
SOUND_ANSWER = nesp_reply + 1

; The most a reply brings: a frame of 65 bytes is 15015 cycles on the line,
; and with the request before it and the NMI before that it leaves the nesp32
; some 4 ms to answer in (docs/PROTOCOL.md, "Timing").
CREDIT_MAX = 56
.assert CREDIT_MAX + STREAM_HEAD <= NESP_RX_MASK, error, "a reply must fit its buffer"

BUTTON_TRIES = 30               ; frames a press is sent for before it is given up
MISSED_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is not there

; wait_unit is 2306 cycles. A run of RAW's is listened for from
; NESP_RAW_SETTLE_MS after the reply that agreed to it, while the nesp32
; makes sure and changes its rate, and NESP_RAW_REST_MS pass after its last
; byte, while it changes back.
UNIT_CYCLES = 2306
SOUND_SETTLE = NESP_RAW_SETTLE_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
SOUND_REST = NESP_RAW_REST_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
.assert SOUND_SETTLE > 0 && SOUND_SETTLE < 256 && SOUND_REST > 0, error, "waits are counted in X"

.segment "ZEROPAGE"
credit:      .res 1             ; bytes of room this frame's request says there are
rx_count:    .res 1             ; bytes of the stream in the reply
sound_vector: .res 2            ; the routine for the rate

.segment "BSS"
greeted:     .res 1             ; the nesp32 has answered this ROM's hello
link_epoch:  .res 1             ; the epoch of what the ring holds
link_pos:    .res 1             ; how many of its bytes have been taken, less a multiple of 256
link_fresh:  .res 1             ; a hello has been said since the last reply's bytes
button_pending: .res 1          ; EVENT_* bits not yet sent
button_sending: .res 1          ; a press is out and unanswered: the frames it has left
link_missed: .res 1             ; exchanges in a row with no reply, up to MISSED_MAX
link_failed: .res 2             ; every exchange with none, for a debugger's watch list

.segment "CODE"

.macro link_nmi_hook
    nesp_nmi_hook
.endmacro

; OUT0 rests at mark, which is also what keeps the controller loading its
; buttons (ui.inc). The hello waits for link_service.
.proc link_init
    lda #OUT0_MARK
    sta JOY1
    rts
.endproc

; The controller asked for something (EVENT_* bits in A). Called from the
; NMI; the main loop sends it with its next exchange.
.proc link_button
    ora button_pending
    sta button_pending
    rts
.endproc
.assert EVENT_NEXT = NESP_PRESS_NEXT, error, "the controller's bits are JUKE's"
.assert EVENT_PREV = NESP_PRESS_PREVIOUS, error, "the controller's bits are JUKE's"
.assert EVENT_PLAY = NESP_PRESS_PLAY, error, "the controller's bits are JUKE's"

; The frame's exchange. An exchange that the next NMI cut off comes back
; here with carry set and frame_count moved on, so the main loop serves the
; new frame at once; one that ended inside its frame, good or not, leaves
; the next for the next NMI.
.proc link_service
    lda greeted
    bne @greeted
    jmp say_hello
@greeted:
    lda button_sending
    beq @no_resend
    jsr nesp_again              ; the same request, byte for byte: done once
    jmp button_answer           ; however often it is heard
@no_resend:
    lda button_pending
    beq @no_button
    sta nesp_request
    lda #0
    sta button_pending
    lda #BUTTON_TRIES
    sta button_sending
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_BUTTON
    ldy #1
    jsr nesp_call
    jmp button_answer
@no_button:
    lda sound_wanted
    beq @music
    lda paused                  ; held: the stream's reply says when it is not
    bne @music
    lda pad                     ; A still down would end the sound as it began
    and #PAD_A
    bne @music
    jmp ask_sound
@music:
    jmp ask_stream
.endproc

; Hello: this is the jukebox, and it needs JUKE and RAW. A nesp32 that
; lacks either, or speaks another protocol, has older firmware than this
; ROM, and the screen says so.
.proc say_hello
    lda #NESP_SVC_JUKE
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_RAW
    sta nesp_request + NESP_HELLO_FIXED + 1
    ldy #2
    jsr nesp_hello
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    bne @old
    lda #1
    sta greeted
    sta link_fresh              ; whatever the ring holds, the nesp32 knows nothing of it
    lda #0
    sta link_pos
    sta button_sending
    jmp link_heard
@old:
    lda #LINK_OLD
    sta link_state
    jmp link_heard
.endproc

; A reply came. The next exchange waits for the next NMI: sent from here,
; partway through a frame, its reply could run into that NMI.
.proc link_heard
    lda #0
    sta link_missed
    lda frame_count
    sta served_frame
    rts
.endproc

; None came, or not a good one.
.proc link_silent
    inc link_failed
    bne @counted
    inc link_failed + 1
@counted:
    lda link_missed
    cmp #MISSED_MAX
    bcs @gone
    inc link_missed
    rts
@gone:
    lda #LINK_WAITING
    sta link_state
    rts
.endproc

; The nesp32 answered, and not with OK: it no longer has the service in
; use. Say hello again.
.proc link_refused
    lda #0
    sta greeted
    sta button_sending
    jmp link_heard
.endproc

.proc button_answer
    bcs @silent
    cmp #NESP_ST_OK
    bne @refused
    lda #0
    sta button_sending          ; the stream will say what came of it
    jmp link_heard
@refused:
    jmp link_refused
@silent:
    dec button_sending
    jmp link_silent
.endproc

; Ask for more of the stream, sized to the room in the ring, and take what
; comes. It is asked every frame, room or no room: the reply is also how
; the console hears that the music was stopped, paused or changed.
.proc ask_stream
    jsr ring_free
    bne @use_max
    lda free
    cmp #CREDIT_MAX
    bcc @have_credit
@use_max:
    lda #CREDIT_MAX
@have_credit:
    sta credit
    sta nesp_request + 2
    lda link_epoch
    sta nesp_request
    lda link_pos
    sta nesp_request + 1
    lda underruns               ; the nesp32 keeps the total, for its own screen
    sta nesp_request + 3
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_STREAM
    ldy #4
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    sec
    sbc #STREAM_HEAD
    bcc @bad                    ; not a reply to this at all
    sta rx_count
    lda credit                  ; more than was asked for would run past the
    cmp rx_count                ; free space, into music that has not played
    bcs @fits
@bad:
    jmp link_heard
@fits:
    lda STREAM_EPOCH
    cmp link_epoch
    bne @flush
    lda link_fresh
    beq @same
@flush:
    ; Another epoch: the NMI moves head to here, where this reply's bytes
    ; begin, and stops playback until the ring has refilled. flush_head is
    ; whole before the flag is set.
    lda STREAM_EPOCH
    sta link_epoch
    lda #0
    sta link_pos
    sta link_fresh
    sta link_done
    sta sound_wanted            ; a sound that was due went with the rest
    lda tail
    sta flush_head
    lda tail + 1
    sta flush_head + 1
    lda #1
    sta flush_pending
@same:
    jsr take_state
    ldx rx_count
    beq @copied
    jsr begin_write
    ldx #0
@byte:
    lda STREAM_BYTES,x
    ldy #0
    sta (wptr),y
    advance_wptr                ; preserves A, X and Y
    inx
    cpx rx_count
    bne @byte
    jsr commit_tail
    clc
    lda link_pos
    adc rx_count
    sta link_pos
@copied:
    lda STREAM_STATE
    and #NESP_PLAYER_DRAIN
    beq @more
    lda #1                      ; no more is coming for now, so play what there
    sta link_done               ; is, however little
@more:
    jmp link_heard
.endproc

; What the nesp32 says of the music, from any of JUKE's replies: for the
; screen's status line, and paused or not. Paused, the NMI stops decoding
; and the APU is silenced, with everything buffered kept; when it goes on,
; the channel enables are put back from the screen's copy.
.proc take_state
    lda nesp_reply
    and #NESP_PLAYER_STATE
    ldx #LINK_STOPPED
    cmp #NESP_PLAYER_STOPPED
    beq @state
    ldx #LINK_EMPTY
    cmp #NESP_PLAYER_NO_TRACKS
    beq @state
    ldx #LINK_STREAMING
@state:
    stx link_state
    cmp #NESP_PLAYER_PAUSED
    bne @running
    lda paused
    bne @done
    lda #1
    sta paused
    lda #0
    sta APU_STATUS
    rts
@running:
    lda paused
    beq @done
    lda apu_shadow + $15
    sta APU_STATUS
    lda #0
    sta paused
@done:
    rts
.endproc

; A sound record has played. Ask for the sound, once every line the
; record's frame changed is on the screen and the bars are off it: it will
; not be drawn again until the sound is over.
.proc ask_sound
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
    lda link_epoch
    sta nesp_request
    jsr sound_rate
    sta nesp_request + 1
    lda #NESP_SVC_JUKE
    ldx #NESP_JUKE_SOUND
    ldy #2
    jsr nesp_call
    bcc @came
    jmp link_silent
@idle:
    rts
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    jsr take_state
    lda SOUND_ANSWER
    cmp #NESP_SOUND_GO
    bne @not_go
    jsr sound_go
    jmp link_heard
@not_go:
    cmp #NESP_SOUND_WAIT        ; paused: ask again
    beq @heard
    lda #0                      ; gone: the stream has what comes next, in an
    sta sound_wanted            ; epoch that is not this one
@heard:
    jmp link_heard
.endproc

; A = the rate to ask for sound at: the one its record named, or
; NESP_JUKE_SOUND_REFUSED if this console cannot play it. That is a rate it
; has no routine for, or a port that does not read as the routines count on
; (the line is at rest here: the nesp32 only sends when asked).
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
    lda #NESP_JUKE_SOUND_REFUSED
    rts
.endproc
.assert PCM_COUNT = NESP_JUKE_SOUND_RATES, error, "a routine for every rate the nesp32 may send at"

; The nesp32 has agreed to send the sound. It listens for a moment in case
; this console did not hear and asks again, then changes its UART's rate
; and sends the samples; the wait before listening for them covers both. An
; NMI would take cycles from the receiver, so it is off until the sound is
; over, and with it the controller's read: the line is silent, which is how
; the nesp32 knows that the console heard.
;
; A routine that comes back with carry set was left because button A is
; down. The nesp32 is told (pcm_hush), and pauses; the sound is still
; wanted, for when it is played again. The press was this, and is not to
; be taken for another by the NMI's next read.
.proc sound_go
    ldx sound_wanted
    dex
    cpx #PCM_COUNT
    bcs @out                    ; none was asked for
    lda #0
    sta PPUCTRL
    sta APU_STATUS
    lda pcm_stream_lo,x
    sta sound_vector
    lda pcm_stream_hi,x
    sta sound_vector + 1
    ldx #SOUND_SETTLE
    jsr wait_units
    jsr @play
    bcc @ended
    jsr pcm_hush
    lda pad_prev
    ora #PAD_A
    sta pad_prev
    bne @back
@ended:
    lda #0
    sta sound_wanted
    ldx #SOUND_REST
    jsr wait_units
@back:
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

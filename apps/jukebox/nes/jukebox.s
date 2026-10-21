; NES Jukebox player.
;
; The NMI is the timebase. Each vblank it decodes exactly one frame of the
; .jbs stream (docs/PROTOCOL.md) from a 1 KB ring buffer at $0400-$07FF and
; writes it to the APU, the way the original game's sound engine ran from
; its NMI. The main loop is the producer: after each NMI it asks the link to
; top up the ring. Two links build from this file:
;
;   fake_link.inc     copies a song built into PRG ROM (the default)
;   serial_link.inc   asks a nesp32 on controller port 2 for it (-D LINK)
;
; Sharing the ring between the NMI and the main loop:
;
; - The NMI owns head and the main loop owns tail. Each is two bytes, and an
;   NMI can land between the two stores of an update.
; - The main loop reads head high byte first, so a torn read can only make
;   head look older, which understates free space. It retries anyway.
; - The NMI cannot retry, because the main loop never runs while it waits.
;   So commit_tail copies tail to tail_prev, raises tail_busy, writes tail,
;   and lowers tail_busy. The NMI reads tail_prev while tail_busy is set, and
;   tail otherwise. Either way it sees a consistent value, at worst one
;   commit old.
;
; A frame is decoded into a staging list first and written to the APU only
; once all of it is in the ring. If the ring runs dry partway through, the
; NMI writes nothing, leaves head alone and counts an underrun. The notes
; hold for a frame instead of playing half a frame's writes.
;
; The screen (ui.inc) is drawn from the NMI as well: the PPU writes first,
; while vblank lasts, then the frame's music, then the bars for the next
; vblank. All of it comes before the main loop's request, so the link sees
; only a later start to its frame.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
PPUADDR   = $2006
PPUDATA   = $2007
APU       = $4000
APU_DMC   = $4010
APU_DMC_LEVEL = $4011           ; the sample channel's 7-bit DAC
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80
FRAME_IRQ_INHIBIT = $40

RING      = $0400
RING_END_PAGE = $08
RING_INDEX_HI = $03             ; ring positions are 10 bits
PREFILL   = 768                 ; bytes buffered before playback starts
STAGE_MAX = 64                  ; writes per frame; vgm2jbs enforces it

OP_CHAIN   = $00
OP_CONTROL = $80
CTRL_END   = $00
CTRL_INIT  = $01
CTRL_TITLE = $02
CTRL_GAME  = $03
CTRL_LENGTH = $04
CTRL_SOUND = $05                ; the link ROM only

; link_state: what the link last heard, for the screen's status line. The
; numbers are places in status_text; 3 to 6 are the player's own (ui.inc).
LINK_WAITING   = 0              ; no answer from a host
LINK_STOPPED   = 1              ; the host is stopped
LINK_STREAMING = 2
LINK_OLD       = 7              ; the host's firmware is older than this ROM
LINK_EMPTY     = 8              ; the host has no music

; Bits of the A that link_button gets: what the controller asked for.
EVENT_NEXT = $01
EVENT_PREV = $02
EVENT_PLAY = $04                ; play or pause
EVENT_STOP = $08                ; the link ROM's: back to its menu

; Indices into group_regs for the registers the control records write.
REG_INDEX_STATUS = 0
REG_INDEX_FRAME  = 19

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM), horizontal mirroring
    .res 8, 0

.segment "ZEROPAGE"
; NMI-only
cursor:      .res 2             ; decode position, committed to head at the end
limit:       .res 2             ; tail as the NMI saw it
rec_header:  .res 1
rec_mask:    .res 1
rec_bits:    .res 1             ; header bits still to walk
avail:       .res 1             ; ring bytes left to decode, capped at 255
stage_count: .res 1
wait_pending: .res 1
end_pending: .res 1
; shared, see the header comment
head:        .res 2
tail:        .res 2
tail_prev:   .res 2
tail_busy:   .res 1
frame_count: .res 1
; main-loop-only
served_frame: .res 1
wptr:        .res 2             ; where the link writes next, uncommitted
head_snap:   .res 2
free:        .res 2
flush_head:  .res 2             ; where head goes when a flush is pending

.segment "BSS"
playing:      .res 1
ended:        .res 1
wait_left:    .res 1
link_done:    .res 1            ; the link has nothing more to give
flush_pending: .res 1           ; the link asks the NMI to drop what is buffered
stream_error: .res 1
link_state:   .res 1            ; LINK_*, set by the link
paused:       .res 1            ; held: the host says paused, or the standalone ROM's Start
sound_wanted: .res 1            ; a sound record played: its rate + 1, or SOUND_REFUSED
underruns:    .res 2
stage_reg:    .res STAGE_MAX
stage_val:    .res STAGE_MAX

.segment "RODATA"
; Register groups in apply order (docs/PROTOCOL.md).
; Indexed by group: 0 status, 1-5 pulse 1 to DMC (header bits 0-4), 6 frame
; counter.
group_first: .byte 0, 1, 5, 9, 12, 15, 19   ; index of the first register
group_limit: .byte 2, 16, 16, 8, 8, 16, 2   ; first invalid submask
group_regs:
    .byte $15
    .byte $00, $01, $02, $03
    .byte $04, $05, $06, $07
    .byte $08, $0A, $0B
    .byte $0C, $0E, $0F
    .byte $10, $11, $12, $13
    .byte $17

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
    bit PPUSTATUS
@vblank1:
    bit PPUSTATUS
    bpl @vblank1

    txa
@clear:
    sta $0000,x
    sta $0100,x
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

    jsr ui_init                 ; rendering is off; the first NMI turns it on

    lda #<RING
    sta head
    sta tail
    sta tail_prev
    lda #>RING
    sta head + 1
    sta tail + 1
    sta tail_prev + 1
    jsr link_init
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through
.endproc

; Serve the link once per frame, starting right after the NMI. The main loop
; compares against the last frame it served rather than waiting for the next
; change, because an NMI that cuts off a receive has already counted the new
; frame, and that frame still needs its request.
;
; The tests fast-forward the emulated clock to the next NMI whenever the
; CPU sits at main_wait with frame_count equal to served_frame, so keep it a
; plain label.
main_loop:
main_wait:
    lda frame_count
    cmp served_frame
    beq main_wait
    sta served_frame
    jsr link_service
    jsr start_when_buffered
    jmp main_loop

; Playback starts once PREFILL bytes are buffered, or once the link has
; delivered everything it has (a song shorter than PREFILL).
.proc start_when_buffered
    lda flush_pending           ; head is about to move: decide next frame
    bne @done
    lda playing
    bne @done
    lda link_done
    bne @start
    jsr read_head
    sec
    lda tail
    sbc head_snap
    lda tail + 1
    sbc head_snap + 1
    and #RING_INDEX_HI
    cmp #>PREFILL
    bcc @done
@start:
    lda #1
    sta playing
@done:
    rts
.endproc

; --- ring, main-loop side ------------------------------------------------------

; head is written by the NMI. Read it until the high byte is stable.
.proc read_head
retry:
    lda head + 1
    sta head_snap + 1
::head_read_low:                ; tests fire an NMI here
    lda head
    sta head_snap
    lda head + 1
    cmp head_snap + 1
    bne retry
    rts
.endproc

; free = (head - tail - 1) mod 1024. One slot stays empty so a full ring and
; an empty one look different. Leaves the high byte in A, with Z set on it.
.proc ring_free
    jsr read_head
    clc                         ; borrow in: subtracts the extra 1
    lda head_snap
    sbc tail
    sta free
    lda head_snap + 1
    sbc tail + 1
    and #RING_INDEX_HI
    sta free + 1
    rts
.endproc

; wptr = tail, where the link starts writing.
.proc begin_write
    lda tail
    sta wptr
    lda tail + 1
    sta wptr + 1
    rts
.endproc

; Step wptr to its next byte, wrapping $07FF to $0400. Preserves A, X, Y.
; Anonymous labels only: a named one would end the caller's @-label scope.
.macro advance_wptr
    inc wptr
    bne :++
    inc wptr + 1
    pha
    lda wptr + 1
    cmp #RING_END_PAGE
    bne :+
    lda #>RING
    sta wptr + 1
:   pla
:
.endmacro

; Publish wptr as the new tail. See the header comment.
.proc commit_tail
    lda tail
    sta tail_prev
    lda tail + 1
    sta tail_prev + 1
    lda #1
    sta tail_busy
    lda wptr
    sta tail
::tail_commit_high:             ; tests fire an NMI here
    lda wptr + 1
    sta tail + 1
    lda #0
    sta tail_busy
    rts
.endproc

.include "ui.inc"

.ifdef LINK
    .include "serial_link.inc"
.else
    .include "fake_link.inc"
.endif

; --- consumer (NMI) ----------------------------------------------------------

.segment "CODE"

.proc nmi
    pha
    txa
    pha
    tya
    pha
    jsr ui_vblank               ; PPU writes first, while vblank lasts
    lda flush_pending
    beq @play
    jsr apply_flush
    jmp @skip
@play:
    lda playing
    beq @skip
    lda paused
    bne @skip
    jsr decode_frame
@skip:
    jsr ui_update
    inc frame_count
    link_nmi_hook               ; from the link include
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

; The link has a reply from another epoch of the stream, which is a flush:
; drop everything not yet played, silence the APU, and wait for the buffer
; to fill again. head moves here, in the NMI, because the NMI owns it.
; flush_head is the tail from before that reply's own bytes, so they are
; the first thing in the ring.
.proc apply_flush
    lda flush_head
    sta head
    lda flush_head + 1
    sta head + 1
    lda #0
    sta APU_STATUS
    sta apu_shadow + $15
    sta playing
    sta ended
    sta wait_left
    sta stream_error
    sta flush_pending
    rts
.endproc

; Decode one frame and apply it, or apply nothing if the ring runs dry.
; After an end-of-track control the APU stays silent until more stream
; arrives, as it does when a playlist is restarted after its end. A stream
; error stops playback for good.
.proc decode_frame
    lda stream_error
    bne @out
    lda wait_left
    beq @decode
    dec wait_left
    inc ui_ticks                ; a frame played, for the screen's clock
@out:
    rts

@decode:
    lda tail_busy
    bne @use_prev
    lda tail
    sta limit
    lda tail + 1
    sta limit + 1
    jmp @have_limit
@use_prev:
    lda tail_prev
    sta limit
    lda tail_prev + 1
    sta limit + 1
@have_limit:
    lda head
    sta cursor
    lda head + 1
    sta cursor + 1
    ; avail = min((limit - head) mod 1024, 255). Counting down one byte per
    ; read is cheaper than comparing two 16-bit positions every time.
    sec
    lda limit
    sbc head
    sta avail
    lda limit + 1
    sbc head + 1
    and #RING_INDEX_HI
    beq @counted_avail
    lda #$FF
    sta avail
@counted_avail:
    lda ended
    beq @playing
    lda avail
    beq @out                    ; still nothing after the end
    lda #0
    sta ended
@playing:
    lda #0
    sta stage_count
    sta wait_pending
    sta end_pending
    jmp @next

    ; The failure exits sit here, between the setup and the decode loop, so
    ; every branch to them is in range.
@failed:
    lda stream_error
    beq @underrun
@bad:
    ; A malformed stream stops playback with the APU silenced. Phase 3's CRC
    ; keeps line noise out, so this means a converter or player bug.
    lda #1
    sta stream_error
    sta ended
    lda #0
    sta APU_STATUS
    sta apu_shadow + $15
    rts
@underrun:
    inc underruns
    bne @counted
    inc underruns + 1
@counted:
    rts

@next:
    jsr read_byte
    bcs @underrun
    cmp #OP_CONTROL
    beq @control
    bcs @record
    cmp #OP_CHAIN
    beq @chain
    ; wait n: this frame plus n - 1 idle ones
    sec
    sbc #1
    sta wait_pending
    jmp @commit

@chain:
    jsr read_byte
    bcs @underrun
    cmp #OP_CONTROL + 1
    bcc @bad
    jsr decode_record
    bcs @failed
    jmp @next

@record:
    jsr decode_record
    bcs @failed
    jmp @commit

@control:
    jsr read_byte
    bcs @underrun
    cmp #CTRL_INIT
    bne @not_init
    ldx #REG_INDEX_STATUS
    lda #0
    jsr stage_write
    bcs @failed
    ldx #REG_INDEX_FRAME
    lda #FRAME_IRQ_INHIBIT
    jsr stage_write
    bcs @failed
    jmp @next
@not_init:
    ldx #LINE_TITLE
    cmp #CTRL_TITLE
    beq @text
    ldx #LINE_GAME
    cmp #CTRL_GAME
    bne @not_text
@text:
    jsr read_title
    bcs @control_failed
    jmp @next
@control_failed:                ; @failed is out of a branch's reach from here
    jmp @failed
@not_text:
    cmp #CTRL_LENGTH
    bne @not_length
    jsr read_length
    bcs @control_failed
    jmp @next
@not_length:
.ifdef LINK
    ; A sound record: sampled sound is due here. The frame ends as a track
    ; does, with the APU silenced, and the link asks the host for the
    ; sound once the screen has caught up (serial_link.inc).
    cmp #CTRL_SOUND
    bne @not_sound
    jsr read_byte               ; the rate
    bcs @control_failed
    tax
    inx
    stx sound_wanted            ; a rate of 255 is refused later
    jsr time_alone              ; its length, and no clock
    ; The screen stands still while a sound plays, so the bars of the
    ; notes before it come down now and not at their own pace. The next
    ; two vblanks draw them; the link waits for that.
    ldx #BAR_COUNT - 1
    lda #0
@clear_bar:
    sta ui_level,x
    dex
    bpl @clear_bar
    bmi @end                    ; always
@not_sound:
.endif
    cmp #CTRL_END
    beq @end
    jmp @bad
@end:
    ldx #REG_INDEX_STATUS
    lda #0
    jsr stage_write
    bcs @control_failed
    lda #1
    sta end_pending
    ; fall through to commit

@commit:
    ldy #0
@apply:
    cpy stage_count
    beq @applied
    ldx stage_reg,y
    lda stage_val,y
    sta APU,x
    sta apu_shadow,x            ; for the screen's bars
    lda #1
    sta apu_fresh,x
    iny
    bne @apply
@applied:
    lda cursor
    sta head
    lda cursor + 1
    sta head + 1
    lda wait_pending
    sta wait_left
    lda end_pending
    sta ended
    inc ui_ticks
    rts

.endproc

; A = next ring byte, carry clear. Carry set when the frame has used up
; what is in the ring. N and Z do not reflect A. Preserves X.
.proc read_byte
    lda avail
    beq @empty
    dec avail
    ldy #0
    lda (cursor),y
    inc cursor
    bne @done
    jsr cursor_next_page
@done:
    clc
    rts
@empty:
    sec
    rts
.endproc

; Step cursor onto its next page, wrapping $07FF to $0400. Preserves A, X.
.proc cursor_next_page
    ldy cursor + 1
    iny
    cpy #RING_END_PAGE
    bne @no_wrap
    ldy #>RING
@no_wrap:
    sty cursor + 1
    rts
.endproc

; A = write record header. Stages its writes in apply order. Carry set on
; underrun, or on a malformed record with stream_error set.
;
; This is the hot path, a few dozen times per busy frame. X holds the flat
; index into group_regs throughout, and the per-register read and stage are
; inlined.
.proc decode_record
    sta rec_header
    and #$20                    ; $4015 applies first
    beq @channels
    ldx #REG_INDEX_STATUS
    jsr read_byte
    bcs @out
    jsr stage_write
    bcs @out
@channels:
    ; Header bits 0-4 are pulse 1, pulse 2, triangle, noise and DMC, which is
    ; also their apply order, so shift them out one at a time.
    lda rec_header
    sta rec_bits
    ldx #0
@channel:
    inx                         ; group 1..5
    lsr rec_bits
    bcc @next_channel
    jsr read_byte               ; submask
    bcs @out
    sta rec_mask
    tay                         ; read_byte's Z is not A's
    beq @bad
    cmp group_limit,x
    bcs @bad
    txa
    pha                         ; group index, back after the registers
    lda group_first,x
    tax
@register:
    lsr rec_mask
    bcc @skip_register
    lda avail
    beq @pull_out_empty
    dec avail
    ldy #0
    lda (cursor),y
    inc cursor
    bne @have_value
    jsr cursor_next_page
@have_value:
    ldy stage_count
    cpy #STAGE_MAX
    bcs @pull_bad
    sta stage_val,y
    lda group_regs,x
    sta stage_reg,y
    inc stage_count
@skip_register:
    inx
    lda rec_mask
    bne @register
    pla
    tax
@next_channel:
    cpx #5
    bne @channel

    lda rec_header
    and #$40                    ; $4017 applies last
    beq @done
    ldx #REG_INDEX_FRAME
    jsr read_byte
    bcs @out
    jmp stage_write             ; its carry is ours
@done:
    clc
@out:
    rts
@pull_out_empty:
    pla
    sec
    rts
@pull_bad:
    pla
@bad:
    lda #1
    sta stream_error
    sec
    rts
.endproc

; Stage A for the register group_regs[X]. Carry set, with stream_error,
; when the frame has more than STAGE_MAX writes. Preserves X.
.proc stage_write
    ldy stage_count
    cpy #STAGE_MAX
    bcs @overflow
    sta stage_val,y
    lda group_regs,x
    sta stage_reg,y
    iny
    sty stage_count
    clc
    rts
@overflow:
    lda #1
    sta stream_error
    sec
    rts
.endproc

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

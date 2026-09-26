; NES Jukebox player, phase 2: a built-in song through a fake link.
;
; The NMI is the timebase. Each vblank it decodes exactly one frame of the
; .jbs stream (docs/PROTOCOL.md) from a 1 KB ring buffer at $0400-$07FF and
; writes it to the APU, the way the original game's sound engine ran from
; its NMI. The main loop is the producer. After each NMI it tops up the ring,
; here by copying from the song in PRG ROM. Phase 3 replaces only that copy
; with the serial receiver; the ring, the decoder and the NMI stay as they
; are.
;
; Sharing the ring between the NMI and the main loop:
;
; - The NMI owns head and the main loop owns tail. Each is two bytes, and an
;   NMI can land between the two stores of an update.
; - The main loop reads head with a retry (high, low, high again), which is
;   enough because an NMI always finishes before the main loop resumes.
; - The NMI cannot retry, because the main loop never runs while it waits.
;   So the main loop copies tail to tail_prev, raises tail_busy, writes
;   tail, and lowers tail_busy. The NMI reads tail_prev while tail_busy is
;   set, and tail otherwise. Either way it sees a consistent value, at worst
;   one commit old.
;
; A frame is decoded into a staging list first and written to the APU only
; once all of it is in the ring. If the ring runs dry partway through, the
; NMI writes nothing, leaves head alone and counts an underrun. The notes
; hold for a frame instead of playing half a frame's writes.

.include "song.inc"

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
PPUADDR   = $2006
PPUDATA   = $2007
APU       = $4000
APU_DMC   = $4010
APU_STATUS = $4015
APU_FRAME = $4017

PPUCTRL_NMI = $80
FRAME_IRQ_INHIBIT = $40
BACKDROP_COLOR = $01            ; dark blue

RING      = $0400
RING_END_PAGE = $08
RING_INDEX_HI = $03             ; ring positions are 10 bits
PREFILL   = 768                 ; bytes buffered before playback starts
FEED_MAX  = 32                  ; bytes per top-up, standing in for a burst
STAGE_MAX = 64                  ; writes per frame; vgm2jbs enforces it

OP_CHAIN   = $00
OP_CONTROL = $80
CTRL_END   = $00
CTRL_INIT  = $01

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
src:         .res 2
wptr:        .res 2
head_snap:   .res 2
free:        .res 2
feed_count:  .res 1

.segment "BSS"
playing:      .res 1
ended:        .res 1
wait_left:    .res 1
source_done:  .res 1
stream_error: .res 1
underruns:    .res 2
stage_reg:    .res STAGE_MAX
stage_val:    .res STAGE_MAX

.segment "SONG"
song_data:
    .incbin "song.bin"
song_data_end:

.segment "RODATA"
; The song descriptor. Everything reads the song through it, so the tests
; can point it at other streams without rebuilding the ROM.
song_desc:
    .addr song_data
    .addr song_data_end
    .addr song_data + SONG_LOOP_OFFSET
    .byte SONG_LOOPS

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

    ; Rendering stays off, so the screen shows the backdrop color.
    lda #$3F
    sta PPUADDR
    lda #$00
    sta PPUADDR
    lda #BACKDROP_COLOR
    sta PPUDATA
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR

    jsr link_init
    jsr prefill
    lda #1
    sta playing
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through
.endproc

; The tests fast-forward the emulated clock to the next NMI whenever the
; CPU reaches main_wait, so keep it a plain label.
main_loop:
    lda frame_count
main_wait:
    cmp frame_count
    beq main_wait
    jsr feed
    jmp main_loop

; --- producer (main loop) ----------------------------------------------------

.proc link_init
    lda #<RING
    sta head
    sta tail
    sta tail_prev
    lda #>RING
    sta head + 1
    sta tail + 1
    sta tail_prev + 1
    lda song_desc
    sta src
    lda song_desc + 1
    sta src + 1
    rts
.endproc

; Feed until PREFILL bytes are buffered or the song has all been copied.
.proc prefill
@again:
    lda source_done
    bne @done
    jsr read_head
    sec
    lda tail
    sbc head_snap
    lda tail + 1
    sbc head_snap + 1
    and #RING_INDEX_HI
    cmp #>PREFILL
    bcs @done
    jsr feed
    jmp @again
@done:
    rts
.endproc

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

; Copy up to FEED_MAX bytes of song into the ring and commit them. This is
; the fake link; phase 3 puts the burst receiver here.
.proc feed
    lda source_done
    beq @run
    rts
@run:
    jsr read_head
    ; free = (head - tail - 1) mod 1024; one slot stays empty so a full ring
    ; and an empty one look different.
    clc                         ; borrow in: subtracts the extra 1
    lda head_snap
    sbc tail
    sta free
    lda head_snap + 1
    sbc tail + 1
    and #RING_INDEX_HI
    sta free + 1
    bne @use_max
    lda free
    cmp #FEED_MAX
    bcc @have_count
@use_max:
    lda #FEED_MAX
@have_count:
    sta feed_count
    cmp #0                      ; sta sets no flags; a full ring must not copy 256
    bne @start
    rts
@start:
    lda tail
    sta wptr
    lda tail + 1
    sta wptr + 1
    ldy #0
@copy:
    lda src + 1
    cmp song_desc + 3
    bne @byte
    lda src
    cmp song_desc + 2
    bne @byte
    lda song_desc + 6           ; at the end of the song: loop or stop
    beq @source_end
    lda song_desc + 4
    sta src
    lda song_desc + 5
    sta src + 1
@byte:
    lda (src),y
    sta (wptr),y
    inc src
    bne @src_done
    inc src + 1
@src_done:
    inc wptr
    bne @wptr_done
    ldx wptr + 1
    inx
    cpx #RING_END_PAGE
    bne @no_wrap
    ldx #>RING
@no_wrap:
    stx wptr + 1
@wptr_done:
    dec feed_count
    bne @copy
    beq @commit
@source_end:
    lda #1
    sta source_done
@commit:
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

; --- consumer (NMI) ----------------------------------------------------------

.proc nmi
    pha
    txa
    pha
    tya
    pha
    lda playing
    beq @skip
    jsr decode_frame
@skip:
    inc frame_count
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

; Decode one frame and apply it, or apply nothing if the ring runs dry.
.proc decode_frame
    lda ended
    bne @out
    lda wait_left
    beq @decode
    dec wait_left
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
    cmp #CTRL_END
    bne @bad
    ldx #REG_INDEX_STATUS
    lda #0
    jsr stage_write
    bcs @failed
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

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

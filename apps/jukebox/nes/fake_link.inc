; Fake link: copies a song built into PRG ROM into the ring, standing in for
; the serial link. Used by the standalone ROM and as a self-test.
;
; Provides link_init, link_service, link_button and the link_nmi_hook macro.

.include "song.inc"

FEED_MAX = 32                   ; bytes per top-up, standing in for a burst

.segment "ZEROPAGE"
src:         .res 2
feed_count:  .res 1

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

.segment "CODE"

.macro link_nmi_hook
.endmacro

; Start pauses and resumes; there is no host to change the track. The
; channel enables are put back from the screen's copy of $4015.
.proc link_button
    and #EVENT_PLAY
    beq @done
    lda paused
    eor #1
    sta paused
    beq @resume
    lda #0
    sta APU_STATUS
    rts
@resume:
    lda apu_shadow + $15
    sta APU_STATUS
@done:
    rts
.endproc

; Point at the song and fill the ring before NMI is enabled.
.proc link_init
    lda #LINK_STREAMING
    sta link_state
    lda song_desc
    sta src
    lda song_desc + 1
    sta src + 1
@prefill:
    lda link_done
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
    jsr link_service
    jmp @prefill
@done:
    rts
.endproc

; Copy up to FEED_MAX bytes of song into the ring and commit them.
.proc link_service
    lda link_done
    beq run
    rts
run:
    jsr ring_free
    bne use_max
    lda free
    cmp #FEED_MAX
    bcc have_count
use_max:
    lda #FEED_MAX
have_count:
    sta feed_count
    cmp #0                      ; sta sets no flags; a full ring must not copy 256
    bne start
    rts
start:
    jsr begin_write
    ldy #0
copy:
    lda src + 1
    cmp song_desc + 3
    bne byte
    lda src
    cmp song_desc + 2
    bne byte
    lda song_desc + 6           ; at the end of the song: loop or stop
    beq source_end
    lda song_desc + 4
    sta src
    lda song_desc + 5
    sta src + 1
byte:
    lda (src),y
    sta (wptr),y
    inc src
    bne src_done
    inc src + 1
src_done:
    advance_wptr
    dec feed_count
    bne copy
    jmp commit_tail
source_end:
    lda #1
    sta link_done
    jmp commit_tail
.endproc

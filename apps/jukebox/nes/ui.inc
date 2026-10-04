; The screen: the title, the game and the track's name, a clock, a status
; line, bars that follow the music, and the controller.
;
; Everything here runs in the NMI, in two parts. ui_vblank comes first and
; does all the PPU writes while vblank lasts: one line of text if one
; changed, or else half of the bars. ui_update comes after the frame's music
; and works out the bars for the next vblank. Nothing is left for the main
; loop, so the link's request still goes out at a fixed point after the NMI
; and nothing here can land in the middle of a burst.
;
; The bars are not a spectrum of the sound, which the console cannot hear.
; They are drawn from what the stream writes to the APU: each channel lights
; the bar for its pitch to the height of its volume, and the bars then fall
; by themselves. Length counters, envelopes and the triangle's linear counter
; are followed closely enough that a note which stops on the console stops
; here too. Sweeps are not followed.
;
; The controller is read by taking OUT0 low for the 8 reads, and OUT0 is
; also the serial line to the host. It rests at mark, which keeps the
; controller loading its buttons, so no strobe pulse is needed: the read is
; one low pulse of 94 cycles, about two bits at 38400 baud. The host's UART
; sees that as the byte $FE, once a frame, and its decoder expects it
; (docs/PROTOCOL.md). The read comes first in the NMI so that the byte is
; long over before the main loop sends its request.
;
; The clock counts the frames the NMI has played since the stream's last
; length record, which a host sends ahead of each track, so it shows what
; is being heard and stops with the music.
;
; Provides ui_init, ui_vblank, ui_update, read_title and read_length. The
; link include provides link_button.

.include "ui_data.inc"

PPUSCROLL = $2005
PPUCTRL_DOWN = $04              ; PPUDATA steps down a column, not along a row
PPUMASK_BACKGROUND = $0A        ; background on, left column included

NAMETABLE = $2000
PALETTE = $3F00

PAD_RIGHT = $01
PAD_LEFT  = $02
PAD_START = $10
PAD_A     = $80

; ui_status, an index into status_text.
STATUS_STOPPED = 1              ; 0 and 2 are LINK_WAITING and LINK_STREAMING
STATUS_PLAYING = 3
STATUS_PAUSED  = 4
STATUS_ENDED   = 5
STATUS_SOUND   = 6              ; sampled sound is about to play, or is playing

BAR_DECAY = 4                   ; pixels a bar falls each time it is drawn
TRIANGLE_VOLUME = 11            ; the triangle has no volume; draw it this loud
FRAMES_PER_SECOND = 60          ; of the stream's frames, for the clock

; Lines of text, as offsets into text_lines and as what read_title takes.
LINE_GAME  = 0
LINE_TITLE = TITLE_MAX
LINE_TIME  = 2 * TITLE_MAX
LINE_BLANK = LINE_TIME + TIME_WIDTH     ; the clock's line, blanked
; text_pending bits: lines the next vblanks must draw, lowest bit first.
PENDING_GAME  = $01
PENDING_TITLE = $02
PENDING_TIME  = $04
PENDING_BLANK = $08             ; draw blanks over the clock
FLASH_FRAMES  = 32              ; the clock's on and off times while stopped;
                                ; a power of 2
; time_buf's characters, as in time_template: " 0:00 / 0:00 ".
TIME_MIN_TENS = 0
TIME_MIN      = 1
TIME_COLON    = 2
TIME_SEC_TENS = 3
TIME_SEC      = 4

; The channels' first registers, which is how the routines below name them.
PULSE1   = $00
PULSE2   = $04
TRIANGLE = $08
NOISE    = $0C

.segment "ZEROPAGE"
ui_level:    .res BAR_COUNT     ; bar heights in pixels, 0 .. BAR_MAX
pad:         .res 1             ; A B Select Start Up Down Left Right
ui_volume:   .res 1

.segment "BSS"
ui_drawn:    .res BAR_COUNT     ; the heights on the screen
bar_phase:   .res 1             ; 0 or 1: which half of the bars is next
text_lines:                     ; the three lines, one after another
game_buf:    .res TITLE_MAX
title_buf:   .res TITLE_MAX
time_buf:    .res TIME_WIDTH    ; position / length; zero until a length comes
blank_buf:   .res TIME_WIDTH    ; stays zero, the blank tile
title_base:  .res 1             ; LINE_GAME or LINE_TITLE
title_len:   .res 1
title_left:  .res 1
text_pending: .res 1
line_next:   .res 1             ; the line whose turn it is to be drawn
ui_ticks:    .res 1             ; frames played, not yet counted by the clock
ui_status:   .res 1
status_drawn: .res 1
pad_prev:    .res 1
apu_shadow:  .res $18           ; the last value written to each APU register
apu_fresh:   .res $18           ; nonzero: written since ui_update last looked
ch_length:   .res NOISE + 1     ; length counters, by first register
ch_env:      .res NOISE + 1     ; envelope levels, in sixteenths
tri_linear:  .res 1
tri_reload:  .res 1

.segment "RODATA"
screen_data:
.ifdef LINK
    .incbin "screen.bin"
.else
    .incbin "screen_standalone.bin"
.endif

bar_addr_lo:
.repeat BAR_COUNT, column
    .byte <(BARS_ADDR + column)
.endrepeat

; By first register: the bit of the channel's first register that halts its
; length counter, and its enable bit in $4015.
halt_bit:   .byte $20, 0, 0, 0, $20, 0, 0, 0, $80, 0, 0, 0, $20
enable_bit: .byte $01, 0, 0, 0, $02, 0, 0, 0, $04, 0, 0, 0, $08

period_high_bits: .byte $00, $20, $40, $60, $80, $A0, $C0, $E0

; By line (game, title, time, time blanked): where it goes and what to write.
line_addr_hi: .byte >GAME_ADDR, >TITLE_ADDR, >TIME_ADDR, >TIME_ADDR
line_addr_lo: .byte <GAME_ADDR, <TITLE_ADDR, <TIME_ADDR, <TIME_ADDR
line_start:   .byte LINE_GAME, LINE_TITLE, LINE_TIME, LINE_BLANK
line_count:   .byte TITLE_MAX, TITLE_MAX, TIME_WIDTH, TIME_WIDTH
line_bit:     .byte PENDING_GAME, PENDING_TITLE, PENDING_TIME, PENDING_BLANK
LINE_COUNT = * - line_bit

.segment "CODE"

; Load the palette and the screen. Rendering must be off.
.proc ui_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda ui_palette,x
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

    lda #$FF                    ; no status line is on the screen yet
    sta status_drawn
    rts
.endproc

; First thing in the NMI: read the controller, then write to the PPU. A
; frame draws one line of text, or the status line, or half of the bars, so
; the writes always end well inside vblank.
.proc ui_vblank
    bit PPUSTATUS               ; reset the PPU's address latch

    ; See the header comment for why the read is here and shaped like this.
    lda #1
    sta JOY1                    ; already there on the link ROM
    lda #0
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #1
    sta JOY1                    ; back to mark
    lda pad
    eor pad_prev
    and pad                     ; buttons that went down this frame
    ldx pad
    stx pad_prev
    tax
    and #PAD_RIGHT | PAD_LEFT   ; these are EVENT_NEXT and EVENT_PREV
    tay
    txa
    and #PAD_START | PAD_A
    beq @no_play
    tya
    ora #EVENT_PLAY
    tay
@no_play:
    tya
    beq @draw
    jsr link_button

@draw:
    lda text_pending
    beq @status
    ; The next pending line, taking them in turn from the one after the
    ; last drawn, so a line that keeps changing cannot hold up the others.
    ldy line_next
@find:
    lda line_bit,y
    and text_pending
    bne @found
    iny
    cpy #LINE_COUNT
    bcc @find
    ldy #0
    beq @find
@found:
    eor text_pending
    sta text_pending
    tya
    tax
    inx
    cpx #LINE_COUNT
    bcc @turn
    ldx #0
@turn:
    stx line_next
    lda line_addr_hi,y
    sta PPUADDR
    lda line_addr_lo,y
    sta PPUADDR
    ldx line_start,y
    lda line_count,y
    tay
@char:
    lda text_lines,x
    sta PPUDATA
    inx
    dey
    bne @char
    beq @done

@status:
    lda ui_status
    cmp status_drawn
    beq @bars
    sta status_drawn
    asl a                       ; STATUS_WIDTH is 16
    asl a
    asl a
    asl a
    tax
    lda #>STATUS_ADDR
    sta PPUADDR
    lda #<STATUS_ADDR
    sta PPUADDR
    ldy #STATUS_WIDTH
@status_char:
    lda status_text,x
    sta PPUDATA
    inx
    dey
    bne @status_char
    beq @done

    ; The bars of this frame's half that changed, each one a column of
    ; BAR_ROWS tiles written top to bottom.
@bars:
    lda #PPUCTRL_NMI | PPUCTRL_DOWN
    sta PPUCTRL
    lda bar_phase
    clc
    adc #BAR_COUNT - 2
    tax
@bar:
    lda ui_level,x
    cmp ui_drawn,x
    beq @next_bar
    sta ui_drawn,x
    tay
    lda #>BARS_ADDR
    sta PPUADDR
    lda bar_addr_lo,x
    sta PPUADDR
    lda bar_row0,y
    sta PPUDATA
    lda bar_row1,y
    sta PPUDATA
    lda bar_row2,y
    sta PPUDATA
    lda bar_row3,y
    sta PPUDATA
    lda bar_row4,y
    sta PPUDATA
    lda bar_row5,y
    sta PPUDATA
    lda bar_row6,y
    sta PPUDATA
    lda bar_row7,y
    sta PPUDATA
@next_bar:
    dex
    dex
    bpl @bar

@done:
    lda #PPUCTRL_NMI            ; nametable 0, and PPUDATA steps along a row
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_BACKGROUND
    sta PPUMASK
    rts
.endproc

.assert BAR_ROWS = 8, error, "ui_vblank writes 8 tiles per bar"
.assert STATUS_WIDTH = 16, error, "ui_vblank multiplies by 16"
.assert >BARS_ADDR = >(BARS_ADDR + BAR_COUNT - 1), error, "the bars' top row crosses a page"

; After the frame's music: the status line, and the bars for the next vblank.
.proc ui_update
    ldx link_state
    lda playing
    beq @status
.ifdef LINK
    ldx #STATUS_STOPPED         ; the stream ended; Start plays it again
.else
    ldx #STATUS_ENDED
.endif
    lda ended
    bne @status
    ldx #STATUS_PLAYING
    lda paused
    beq @status
    ldx #STATUS_PAUSED
@status:
.ifdef LINK
    lda paused                  ; paused shows as stopped does
    beq @not_paused
    ldx #STATUS_STOPPED
@not_paused:
    lda sound_wanted            ; the screen stands still while sound plays,
    beq @no_sound               ; so this is drawn before it starts
    ldx #STATUS_SOUND
@no_sound:
.endif
    ; Stopped with a track on the screen: no "press Start", which the foot
    ; of the screen says already. The clock flashes instead, about once a
    ; second. Once the music plays again the clock is drawn every second.
    cpx #STATUS_STOPPED
    bne @show
    lda time_buf + TIME_COLON
    beq @show
    ldx #STATUS_PLAYING         ; a blank line
    lda frame_count
    and #FLASH_FRAMES - 1
    bne @show
    ldy #PENDING_TIME
    lda frame_count
    and #FLASH_FRAMES
    beq @flash
    ldy #PENDING_BLANK
@flash:
    tya
    ora text_pending
    sta text_pending
@show:
    stx ui_status

    ; The clock: a second for every FRAMES_PER_SECOND frames played.
    lda ui_ticks
    cmp #FRAMES_PER_SECOND
    bcc @bars
    sbc #FRAMES_PER_SECOND
    sta ui_ticks
    jsr clock_second
@bars:

    ; The other half of the bars falls, and is what the next vblank draws.
    lda bar_phase
    eor #1
    sta bar_phase
    clc
    adc #BAR_COUNT - 2
    tax
@fall:
    lda ui_level,x
    beq @next
    sec
    sbc #BAR_DECAY
    bcs @fell
    lda #0
@fell:
    sta ui_level,x
@next:
    dex
    dex
    bpl @fall

    lda paused
    bne @out
    ldx #PULSE1
    jsr pulse_bar
    ldx #PULSE2
    jsr pulse_bar
    jsr triangle_bar
    ; The noise channel's bar comes from its period index, not a pitch.
    ldx #NOISE
    jsr channel_length
    jsr channel_volume
    beq @out
    sta ui_volume
    lda apu_shadow + NOISE + 2
    and #$0F
    tay
    lda noise_col,y
    tay
    lda ui_volume
    jmp raise_bar
@out:
    rts
.endproc

; X = PULSE1 or PULSE2. Light the bar for its pitch to its volume.
.proc pulse_bar
    jsr channel_length
    jsr channel_volume
    beq @out
    sta ui_volume
    jsr period_column
    bcs @out
    lda ui_volume
    jmp raise_bar
@out:
    rts
.endproc

; The triangle sounds while both its length counter and its linear counter
; are running. The linear counter is clocked four times a frame.
.proc triangle_bar
    ldx #TRIANGLE
    jsr channel_length
    bcc @no_trigger
    lda #1
    sta tri_reload
@no_trigger:
    lda tri_reload
    beq @count
    lda apu_shadow + TRIANGLE
    and #$7F
    jmp @set
@count:
    lda tri_linear
    sec
    sbc #4
    bcs @set
    lda #0
@set:
    sta tri_linear
    lda apu_shadow + TRIANGLE
    bmi @control                ; the control flag keeps the reload flag set
    lda #0
    sta tri_reload
@control:
    lda ch_length + TRIANGLE
    beq @out
    lda tri_linear
    beq @out
    jsr period_column
    bcs @out
    tya                         ; an octave below a pulse with this period
    sec
    sbc #TRIANGLE_SHIFT
    bcs @column
    lda #0
@column:
    tay
    lda #TRIANGLE_VOLUME
    jmp raise_bar
@out:
    rts
.endproc

; A = volume 1-15, Y = bar. Raise the bar to that volume if it is lower.
.proc raise_bar
    asl a
    asl a
    adc #4                      ; carry is clear: 8 .. BAR_MAX
    cmp ui_level,y
    bcc @out
    sta ui_level,y
@out:
    rts
.endproc

.assert BAR_MAX = 64, error, "raise_bar scales a volume to 64 pixels"

; X = a channel's first register. Run its length counter for one frame: a
; write to its fourth register loads it, it counts down twice a frame unless
; halted, and a channel disabled in $4015 holds it at zero. Returns carry set
; if the channel was triggered this frame. Preserves X.
.proc channel_length
    lda apu_fresh + 3,x
    beq @count
    lda #0
    sta apu_fresh + 3,x
    lda apu_shadow + 3,x
    lsr a
    lsr a
    lsr a
    tay
    lda length_table,y
    sta ch_length,x
    lda #$F0                    ; the envelope starts again at 15
    sta ch_env,x
    sec
    bcs @enable
@count:
    lda apu_shadow,x
    and halt_bit,x
    bne @held
    lda ch_length,x
    beq @held
    sec
    sbc #2
    bcs @counted
    lda #0
@counted:
    sta ch_length,x
@held:
    clc
@enable:
    lda apu_shadow + $15
    and enable_bit,x
    bne @out
    sta ch_length,x
@out:
    rts
.endproc

; X = PULSE1, PULSE2 or NOISE. Returns its volume in A, 0-15, with Z set on
; it: zero if its length counter has run out, the constant volume if it has
; one, and otherwise an envelope that falls from 15 at the rate the console's
; would. Preserves X.
.proc channel_volume
    lda ch_length,x
    beq @out
    lda apu_shadow,x
    and #$10
    beq @envelope
    lda apu_shadow,x
    and #$0F
    rts
@envelope:
    lda apu_shadow,x
    and #$0F
    tay
    lda ch_env,x
    sec
    sbc envelope_step,y
    bcs @store
    lda apu_shadow,x            ; ran out: a looping envelope starts over
    and #$20
    beq @store
    lda #$F0
@store:
    sta ch_env,x
    lsr a
    lsr a
    lsr a
    lsr a
@out:
    rts
.endproc

; X = a channel's first register. Returns in Y the bar for its timer period
; as a pulse channel's pitch, carry clear. Carry set if the period is under
; 8, where a pulse channel is muted and a triangle is too high to hear.
; Preserves X.
.proc period_column
    lda apu_shadow + 3,x
    and #$07
    bne @high
    ldy apu_shadow + 2,x
    cpy #8
    bcc @mute
    lda period_col_low,y
    tay
    clc
    rts
@mute:
    sec
    rts
@high:
    tay
    lda apu_shadow + 2,x
    lsr a
    lsr a
    lsr a
    ora period_high_bits,y
    tay
    lda period_col_high,y
    tay
    clc
    rts
.endproc

; Add a second to the clock's position, which is kept as the characters
; on the screen. Nothing shows until a length record has set the line up.
.proc clock_second
    lda time_buf + TIME_COLON
    beq @out
    lda #PENDING_TIME
    ora text_pending
    sta text_pending
    inc time_buf + TIME_SEC
    lda time_buf + TIME_SEC
    cmp #'9' + 1
    bne @out
    lda #'0'
    sta time_buf + TIME_SEC
    inc time_buf + TIME_SEC_TENS
    lda time_buf + TIME_SEC_TENS
    cmp #'6'
    bne @out
    lda #'0'
    sta time_buf + TIME_SEC_TENS
    inc time_buf + TIME_MIN
    lda time_buf + TIME_MIN
    cmp #'9' + 1
    bne @out
    lda #'0'
    sta time_buf + TIME_MIN
    lda time_buf + TIME_MIN_TENS
    cmp #' '                    ; a blank stands for a leading zero
    bne @tens
    lda #'0'
@tens:
    clc
    adc #1
    sta time_buf + TIME_MIN_TENS
@out:
    rts
.endproc

; A name control record (docs/PROTOCOL.md): its length and text follow in
; the ring. X = LINE_GAME or LINE_TITLE. Copy the text, centered, to where a
; coming vblank draws it from. Called by decode_frame. Carry set if the ring
; does not hold all of it yet, or, with stream_error, if it is longer than
; the screen's line.
.proc read_title
    stx title_base
    jsr read_byte
    bcs @out
    cmp #TITLE_MAX + 1
    bcs @bad
    sta title_len
    lda avail
    cmp title_len
    bcc @out                    ; not all of it is here yet
    ldx title_base
    ldy #TITLE_MAX
    lda #' '
@clear:
    sta text_lines,x
    inx
    dey
    bne @clear
    sec
    lda avail
    sbc title_len
    sta avail
    sec
    lda #TITLE_MAX
    sbc title_len
    lsr a
    clc
    adc title_base
    tax
    lda title_len
    beq @drawn
    sta title_left
    ldy #0
@copy:
    lda (cursor),y
    sta text_lines,x
    inc cursor
    bne @same_page
    jsr cursor_next_page        ; preserves X, and leaves Y for the next page
    ldy #0
@same_page:
    inx
    dec title_left
    bne @copy
@drawn:
    ldx #PENDING_GAME
    lda title_base
    beq @pending
    ldx #PENDING_TITLE
@pending:
    txa
    ora text_pending
    sta text_pending
    clc
    rts
@out:
    sec
    rts
@bad:
    lda #1
    sta stream_error
    sec
    rts
.endproc

.assert LINE_GAME = 0, error, "read_title tells the lines apart by zero"

; A length control record: TIME_TOTAL_WIDTH characters follow, the track's
; length as text. Put them on the clock's line and start its position from
; zero.
; Called by decode_frame. Carry set if the ring does not hold them yet.
.proc read_length
    lda avail
    cmp #TIME_TOTAL_WIDTH
    bcc @out
    ldx #TIME_WIDTH - 1
@template:
    lda time_template,x
    sta time_buf,x
    dex
    bpl @template
    ldx #0
@total:
    jsr read_byte               ; preserves X
    sta time_buf + TIME_TOTAL,x
    inx
    cpx #TIME_TOTAL_WIDTH
    bne @total
    lda #0
    sta ui_ticks
    lda #PENDING_TIME
    ora text_pending
    sta text_pending
    clc
    rts
@out:
    sec
    rts
.endproc

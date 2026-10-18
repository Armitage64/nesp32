; NPR: a radio station on the console's sample channel.
;
; A nesp32 on controller port 2 fetches NPR's live stream from the Internet,
; decodes it, and sends it a byte a sample; this ROM writes each byte to
; $4011, the 7-bit DAC of the console's sample channel, as it arrives. The
; sound's routines and the way a sound takes the line over are the
; jukebox's (../jukebox/nes/serial_link.inc, and its docs/PROTOCOL.md, part
; 4); what is new is on the nesp32, its TUNER service (nesp32's
; docs/PROTOCOL.md).
;
; The link is nesp32's (its nes/lib/nesp.inc). Every use of it is one
; exchange, a request and its reply, made right after the NMI, one a
; frame, the first of these that applies:
;
;   SYS HELLO       until the nesp32 has answered it, and again whenever it
;                   says the service is not in use
;   TUNER PLAY      Start or A was pressed, and nothing is being fetched,
;                   or the station is paused: with the mode the menu has
;   TUNER STOP      or something is. Sent again until it is answered
;   TUNER SOUND     the station is ready, the screen says so, and A is up
;   TUNER STATE     otherwise: how it stands, for the status line
;
; There are two modes, and a menu in the middle of the screen to choose
; between them for as long as no station is tuned in: the station at 23244
; samples a second and nothing else, or at 11622 with the news headlines.
; Up, Down and Select move between them.
;
; When SOUND is answered with GO the console does nothing but receive: the
; NMI is off, the screen stands still, and of the controller only button A
; is looked at, which pauses: the console leaves the sound and tells the
; nesp32 so (pcm_hush, with the sound's routines), which holds the station
; where it is until PLAY. The button on the nesp32 ends the sound, with a
; byte that says it was the last; so does a stream that is lost. Then the
; NMI goes back on and STATE says what happened.
;
; With the headlines, the sound's routine is news_stream (news.inc, which
; tools/gen_news.py writes, and which says how): the nesp32 sends a page
; in the samples themselves, and the routine keeps it, draws it where it
; cannot be seen, on the other of the two nametables, and changes the two
; over. So the header and the status line are on both, and news_ctrl says
; which is shown. The menu, and the blank that takes its place when a
; station is tuned in, are drawn on the first, by the NMI, a line a frame.
;
; The NMI reads the controller, draws the status line when it has changed
; or a line of the middle of the screen when one is due, and nothing else: the
; exchange's request goes out at a fixed point after it.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
APU_DMC_LEVEL = $4011           ; the sample channel's 7-bit DAC
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80
PPUMASK_BACKGROUND = $0A        ; background on, left column included
FRAME_IRQ_INHIBIT = $40
NAMETABLE = $2000
NAMETABLE_2 = $2800             ; the other one: the mirroring is horizontal
PALETTE   = $3F00

PAD_START = $10
PAD_A     = $80
PAD_MOVE  = $2C                 ; Select, Up and Down: the menu's other choice

OUT0_MARK = $01

NESP_RX_MASK = $1F              ; replies of up to 31 bytes: a state, and why
NESP_TX_MAX  = 9                ; the hello, with its two services
.define NESP_APP "NPR "
NESP_APP_VERSION = 1

AREA_BLANK = 2                  ; area: 0 and 1 are the menu, with that mode chosen

TUNER_UNKNOWN = $FF             ; tuner: the nesp32 has not said how it stands
PRESS_TRIES = 30                ; frames a press is sent for before it is given up
MISSED_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is not there

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                     ; 2 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $00, $00              ; mapper 0 (NROM), horizontal mirroring
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1
text_ptr:     .res 2            ; the status line's text, for the NMI
pad:          .res 1            ; A B Select Start Up Down Left Right
news_shift:   .res 1            ; the sound's routine: a character as its bits come,
news_bits:    .res 1            ; how many it still wants,
news_at:      .res 1            ; and where in the page the next one goes
news_ctrl:    .res 1            ; PPUCTRL's bits for the nametable that is shown
news_nt:      .res 1            ; the other one, 0 or 1: where the next page is drawn
area_ptr:     .res 2            ; the NMI's: the line of the middle it draws

.segment "BSS"
pad_prev:     .res 1
pressed:      .res 1            ; Start or A went down: the main loop's to send
status:       .res 1            ; STATUS_*: what the status line says
status_dirty: .res 1            ; and it is not on the screen yet
greeted:      .res 1            ; the nesp32 has answered this ROM's hello
tuner:        .res 1            ; NESP_TUNER_*, as the nesp32 last said, or TUNER_UNKNOWN
press_op:     .res 1            ; the op a press became
press_tries:  .res 1            ; and the frames it has left to be answered in
link_missed:  .res 1            ; exchanges in a row with no reply, up to MISSED_MAX
link_failed:  .res 2            ; every exchange with none, for a debugger's watch list
sounds:       .res 1            ; times the sound has played, likewise
why_buf:      .res 28           ; the nesp32's words for a station that failed
mode:         .res 1            ; NESP_TUNER_MODE_*: the menu's choice
moved:        .res 1            ; Select, Up or Down went down: the main loop's to act on
area:         .res 1            ; what the middle of the screen is to show: AREA_*
area_row:     .res 1            ; lines of it that are on the screen: NEWS_ROWS is all

.include "screen.inc"
.include "nesp.inc"
.include "pcm_rates.inc"
.include "news.inc"

.assert NESP_TX_MAX = NESP_HELLO_FIXED + 2, error, "the hello names two services"
.assert STATUS_WIDTH = NESP_TUNER_TEXT_MAX, error, "why_buf holds what the nesp32 may say"
.assert NESP_TUNER_TEXT_MAX + 1 <= NESP_RX_MASK, error, "a reply must fit its buffer"
.assert NESP_TUNER_NEWS_RATE = NEWS_RATE, error, "news_stream is at the headlines' rate"
.assert NEWS_ROWS = NESP_TUNER_NEWS_ROWS && NEWS_COLUMNS = NESP_TUNER_NEWS_COLUMNS, error, "a page is the nesp32's"
.assert NESP_TUNER_MODE_HIGH = 0 && NESP_TUNER_MODE_NEWS = 1, error, "mode is the menu's line"
pcm_stream = .ident(.sprintf("pcm_stream_%d", NESP_TUNER_RATE))    ; the station alone

; wait_unit is 2306 cycles. A run of RAW's is listened for from
; NESP_RAW_SETTLE_MS after the reply that agreed to it, while the nesp32
; makes sure and changes its rate, and NESP_RAW_REST_MS pass after its last
; byte, while it changes back.
UNIT_CYCLES = 2306
SOUND_SETTLE = NESP_RAW_SETTLE_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
SOUND_REST = NESP_RAW_REST_MS * (NESP_CPU_HZ / 1000) / UNIT_CYCLES
.assert SOUND_SETTLE > 0 && SOUND_SETTLE < 256 && SOUND_REST > 0, error, "waits are counted in X"

.segment "RODATA"
palette_data:
    .incbin "palette.bin"
screen_data:
    .incbin "screen.bin"

; The status line's text, by STATUS_*.
status_lo:
.repeat STATUS_WHY, index
    .byte <(status_text + index * STATUS_WIDTH)
.endrepeat
    .byte <why_buf
status_hi:
.repeat STATUS_WHY, index
    .byte >(status_text + index * STATUS_WIDTH)
.endrepeat
    .byte >why_buf

; What the status line says for each of the nesp32's states but FAILED,
; which has words of its own.
state_status:
    .byte STATUS_OFF, STATUS_NO_WIFI, STATUS_TUNING, STATUS_ON_AIR
.assert NESP_TUNER_OFF = 0 && NESP_TUNER_NO_WIFI = 1 && NESP_TUNER_TUNING = 2, error, "state_status"
.assert NESP_TUNER_READY = 3 && NESP_TUNER_FAILED = 4, error, "state_status"

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

    jsr screen_init             ; rendering is off; the first NMI turns it on
    lda #NESP_TUNER_MODE_HIGH   ; the menu, with its first line chosen
    sta mode
    jsr show_area
    lda #TUNER_UNKNOWN
    sta tuner
    sta status                  ; nothing is on the status line yet
    lda #STATUS_WAITING
    jsr set_status
    lda #OUT0_MARK              ; the line rests at mark, which is also what keeps
    sta JOY1                    ; the controller loading its buttons
    lda #PPUCTRL_NMI
    sta PPUCTRL
    ; fall through
.endproc

; One exchange a frame, starting right after the NMI. The main loop
; compares against the last frame it served rather than waiting for the
; next change, because an NMI that cuts off a receive has already counted
; the new frame, and that frame still needs its request.
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
    jmp main_loop

; Load the palette and the screen, which is on both nametables. Rendering
; must be off.
.proc screen_init
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldx #0
@palette:
    lda palette_data,x
    sta PPUDATA
    inx
    cpx #16
    bne @palette

    lda #>NAMETABLE
    jsr @screen
    lda #>NAMETABLE_2
@screen:
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
    rts
.endproc

; The status line is to say A (STATUS_*). The NMI draws it; it is told only
; once the text's address is whole.
.proc set_status
    cmp status
    beq @done
    sta status
    tax
    lda #0
    sta status_dirty
    lda status_lo,x
    sta text_ptr
    lda status_hi,x
    sta text_ptr + 1
    lda #1
    sta status_dirty
@done:
    rts
.endproc

; --- the link ----------------------------------------------------------------------

; The frame's exchange. An exchange that the next NMI cut off comes back
; here with carry set and frame_count moved on, so the main loop serves the
; new frame at once; one that ended inside its frame, good or not, leaves
; the next for the next NMI.
.proc link_service
    lda greeted
    bne @greeted
    jmp say_hello
@greeted:
    lda moved
    beq @no_move
    lda #0
    sta moved
    lda area                    ; only while the menu is on the screen
    cmp #AREA_BLANK
    beq @no_move
    eor #1
    sta mode
    jsr show_area
@no_move:
    lda pressed
    beq @no_press
    lda #0
    sta pressed
    ; On, if nothing is being fetched; off, if something is.
    ldx #NESP_TUNER_STOP
    lda tuner
    cmp #NESP_TUNER_TUNING
    beq @op
    cmp #NESP_TUNER_READY
    beq @op
    ldx #NESP_TUNER_PLAY
@op:
    stx press_op
    lda #PRESS_TRIES
    sta press_tries
@no_press:
    lda press_tries
    beq @no_op
    jmp send_press
@no_op:
    lda tuner
    cmp #NESP_TUNER_READY
    bne @state
    lda status_dirty            ; the screen will not be drawn again until the
    bne @idle                   ; sound is over: it says so first,
    lda area_row                ; and the menu is off it
    cmp #NEWS_ROWS
    bne @state
    lda pad                     ; A still down would end the sound as it began
    and #PAD_A
    bne @state
    jmp ask_sound
@state:
    lda #NESP_SVC_TUNER
    ldx #NESP_TUNER_STATE
    ldy #0
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    jsr take_state
    jmp link_heard
@idle:
    rts
.endproc

; Hello: this is NPR, and it needs TUNER and RAW. A nesp32 that lacks
; either, or speaks another protocol, has older firmware than this ROM, and
; the screen says so.
.proc say_hello
    lda #NESP_SVC_TUNER
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
    lda #0
    sta press_tries
    lda #TUNER_UNKNOWN
    sta tuner
    jmp link_heard
@old:
    lda #STATUS_OLD
    jsr set_status
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
    lda #TUNER_UNKNOWN
    sta tuner
    lda #STATUS_WAITING
    jmp set_status
.endproc

; The nesp32 answered, and not with OK: it no longer has the service in
; use. Say hello again.
.proc link_refused
    lda #0
    sta greeted
    sta press_tries
    jmp link_heard
.endproc

; The press, as PLAY or STOP, until it is answered. Either done twice is
; done once.
.proc send_press
    ldy #0
    ldx press_op
    cpx #NESP_TUNER_PLAY
    bne @send
    lda mode                    ; PLAY says which
    sta nesp_request
    iny
@send:
    lda #NESP_SVC_TUNER
    jsr nesp_call
    bcc @came
    dec press_tries
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda #0
    sta press_tries
    lda #TUNER_UNKNOWN          ; a station that fails twice may say something new
    sta status
    jsr take_state
    jmp link_heard
.endproc

; How the station stands, from a reply of STATE's, PLAY's or STOP's: for
; the status line, and for what is asked next.
.proc take_state
    lda nesp_reply_len
    beq @done                   ; not a reply to this at all
    lda nesp_reply
    cmp #NESP_TUNER_FAILED
    beq @failed
    bcc @plain
    cmp #NESP_TUNER_PAUSED
    bne @done                   ; a state this ROM has not heard of
    sta tuner
    jsr tuned_or_not
    lda #STATUS_PAUSED
    jmp set_status
@plain:
    sta tuner
    pha
    jsr tuned_or_not
    pla
    tax
    lda state_status,x
    jmp set_status
@failed:
    sta tuner
    jsr tuned_or_not
    lda status
    cmp #STATUS_WHY
    beq @done                   ; its words are on the screen
    ; The nesp32's words, in the middle of the line.
    lda #0
    sta status_dirty            ; the NMI is not to draw them half made
    ldx #STATUS_WIDTH - 1
    lda #' '
@blank:
    sta why_buf,x
    dex
    bpl @blank
    ldy nesp_reply_len
    dey                         ; the words' length
    cpy #STATUS_WIDTH + 1
    bcc @fits
    ldy #STATUS_WIDTH
@fits:
    sty press_op                ; borrowed: no press is out
    lda #STATUS_WIDTH
    sec
    sbc press_op
    lsr a
    tax                         ; where they begin
    ldy #0
@char:
    cpy press_op
    beq @copied
    lda nesp_reply + 1,y
    sta why_buf,x
    inx
    iny
    bne @char
@copied:
    lda #STATUS_WHY
    jmp set_status
@done:
    rts
.endproc

; The middle of the screen follows the station: the menu while none is
; tuned in, and nothing while one is, where the headlines then go. A =
; NESP_TUNER_*, as the nesp32 has just said.
.proc tuned_or_not
    ldx #AREA_BLANK
    cmp #NESP_TUNER_TUNING
    beq @want
    cmp #NESP_TUNER_READY
    beq @want
    cmp #NESP_TUNER_PAUSED
    beq @want
    ldx mode
@want:
    txa
    eor area
    cmp #AREA_BLANK             ; the menu for the blank, or the blank for the menu?
    bcc @done                   ; neither: a paused station's page stays, and the menu
    txa
    jmp show_area
@done:
    rts
.endproc
.assert AREA_BLANK = 2, error, "tuned_or_not tells the menu's two from the blank by bit 1"

; The middle of the screen is to show A (AREA_*), from its first line, on
; the first nametable, which is the one shown from now on.
.proc show_area
    ldx #NEWS_ROWS
    stx area_row                ; the NMI draws nothing while it is changed
    sta area
    lda #0
    sta news_ctrl
    sta area_row
    lda #1
    sta news_nt
    rts
.endproc

; The station is ready, and the screen says it is on the air. Ask for the
; sound, at the one rate there is; or say that this console cannot play it,
; if its port does not read as the routines count on (the line is at rest
; here: the nesp32 only sends when asked).
.proc ask_sound
    ldx #NESP_TUNER_RATE
    lda mode
    beq @high
    ldx #NESP_TUNER_NEWS_RATE
@high:
    lda JOY2
    cmp #PORT_IDLE
    beq @rate
    ldx #NESP_JUKE_SOUND_REFUSED
@rate:
    stx nesp_request
    lda #NESP_SVC_TUNER
    ldx #NESP_TUNER_SOUND
    ldy #1
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    cmp #2
    bcc @asked
    lda nesp_reply + 1
    cmp #NESP_SOUND_GO
    bne @asked
    jsr sound_go
@asked:
    lda #TUNER_UNKNOWN          ; whatever came of it, STATE says how it stands now
    sta tuner
    jmp link_heard
.endproc

; The nesp32 has agreed to send the station. It listens for a moment in
; case this console did not hear and asks again, then changes its UART's
; rate and sends the samples; the wait before listening for them covers
; both. An NMI would take cycles from the receiver, so it is off until the
; sound is over, and with it the controller's read: the line is silent,
; which is how the nesp32 knows that the console heard.
;
; The routine comes back with carry set if it was left because button A is
; down. The nesp32 is told (pcm_hush), and pauses the station. The press
; was this, and is not to be taken for another by the NMI's next read.
.proc sound_go
    lda news_ctrl               ; the NMI off, and the nametable as it was
    sta PPUCTRL
    lda #0
    sta APU_STATUS
    inc sounds
    ldx #SOUND_SETTLE
    jsr wait_units
    lda mode
    bne @news
    jsr pcm_stream              ; until a byte that says it is the last, or A
    jmp @over
@news:
    ldx #$FF                    ; a sample whose eighth bit is nothing
    jsr news_stream             ; the same, with the headlines as they come
@over:
    bcc @ended
    jsr pcm_hush
    lda pad_prev
    ora #PAD_A
    sta pad_prev
    bne @back
@ended:
    ldx #SOUND_REST
    jsr wait_units
@back:
    bit PPUSTATUS               ; a vblank that came and went is not an NMI now
    lda #PPUCTRL_NMI
    ora news_ctrl
    sta PPUCTRL
    rts
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

; --- the NMI ------------------------------------------------------------------------

; The controller is read by taking OUT0 low for the 8 reads, and OUT0 is
; also the serial line to the nesp32. It rests at mark, which keeps the
; controller loading its buttons, so no strobe pulse is needed: the read is
; one low pulse, some four bits at the link's rate, which the nesp32's UART
; takes for a byte and its decoder passes over as noise. It comes first, so
; that the byte is long over before the main loop sends its request.
.proc nmi
    pha
    txa
    pha
    tya
    pha
    bit PPUSTATUS               ; reset the PPU's address latch
    lda #0
    sta JOY1
.repeat 8
    lda JOY1
    lsr a
    rol pad
.endrepeat
    lda #OUT0_MARK
    sta JOY1
    lda pad
    eor pad_prev
    and pad                     ; buttons that went down this frame
    ldx pad
    stx pad_prev
    tax
    and #PAD_START | PAD_A
    beq @no_press
    lda #1
    sta pressed
@no_press:
    txa
    and #PAD_MOVE
    beq @no_move
    lda #1
    sta moved
@no_move:
    lda status_dirty
    beq @drawn
    lda #>STATUS_ADDR           ; on both nametables: either may be the one shown
    jsr @status
    lda #>(STATUS_ADDR - NAMETABLE + NAMETABLE_2)
    jsr @status
    lda #0
    sta status_dirty
    beq @done                   ; a line of the headlines waits for the next frame
@drawn:
    ; The middle of the screen, a line a frame, when it is to change.
    ldx area_row
    cpx #NEWS_ROWS
    beq @done
    lda area                    ; its line: NEWS_ROWS of them to each
    asl a
    asl a
    asl a
    adc area                    ; times 9, and carry is clear
    adc area_row
    tay
    lda area_lo,y
    sta area_ptr
    lda area_hi,y
    sta area_ptr + 1
    lda area_screen_hi,x
    sta PPUADDR
    lda area_screen_lo,x
    sta PPUADDR
    ldy #0
@area:
    lda (area_ptr),y
    sta PPUDATA
    iny
    cpy #NEWS_COLUMNS
    bne @area
    inc area_row
@done:
    lda #PPUCTRL_NMI
    ora news_ctrl
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_BACKGROUND
    sta PPUMASK
    inc frame_count
    nesp_nmi_hook
    pla
    tay
    pla
    tax
    pla
    rti
@status:
    sta PPUADDR
    lda #<STATUS_ADDR
    sta PPUADDR
    ldy #0
@char:
    lda (text_ptr),y
    sta PPUDATA
    iny
    cpy #STATUS_WIDTH
    bne @char
    rts
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

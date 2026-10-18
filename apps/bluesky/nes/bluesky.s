; Bluesky: an account's latest posts on a NES, a card at a time.
;
; A nesp32 on controller port 2 asks Bluesky for an account's posts and
; lays each out as a card of lines; this ROM asks for the lines and draws
; them. It is ConnectedNES's idea (Rachel Simone Weil, 2016), which put
; tweets on a NES the same way through a Particle Photon, and it begins
; with her splash screen. What is new is on the nesp32, its BSKY service
; (nesp32's docs/PROTOCOL.md).
;
; There are four views:
;
;   the splash      hers, until the nesp32 has answered and Start is pressed
;   the favorites   handles the nesp32 keeps; A reads one, Select twice
;                   takes it off, and the last line is the way to the form
;   the form        a handle typed a letter at a time: Left and Right move,
;                   Up and Down change the letter, A reads it, Start saves
;                   it to the favorites, B goes back
;   a post          the nesp32's card for one of the account's posts: Left
;                   and Right go through them, Start saves the account to
;                   the favorites, B goes back
;
; The link is nesp32's (its nes/lib/nesp.inc). Every use of it is one
; exchange, a request and its reply, made right after the NMI, at most one
; a frame, the first of these that applies:
;
;   SYS HELLO       until the nesp32 has answered it, and again whenever it
;                   says the service is not in use
;   BSKY ADD/REMOVE a change to the favorites that has been asked for
;   BSKY FAVORITE   the favorites, one a frame, after a hello and a change
;   BSKY FEED       a post is the view: this handle, and how it stands.
;                   Until it is known, and every 8 frames while it is
;                   being fetched
;   BSKY LINE       the next line of the post on the screen, while there is
;                   one to draw
;
; The NMI reads the controller, copies the sprite to the PPU, and draws
; what the main loop has staged: the status line when it has changed, and
; one row of the middle of the screen or its foot (row_buf). Nothing else
; writes to the PPU while the screen is on. Going from the splash to the
; rest, the main loop turns it off, loads the other palette and nametable
; itself, and turns it on again.

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
OAMADDR   = $2003
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
APU_DMC   = $4010
OAMDMA    = $4014
APU_STATUS = $4015
JOY1      = $4016
JOY2      = $4017
APU_FRAME = $4017               ; writes; reads are JOY2

PPUCTRL_NMI = $80
PPUCTRL_BG_PAGE1 = $10          ; the background from the second page of tiles
PPUMASK_ON = $1E                ; background and sprites, left column included
FRAME_IRQ_INHIBIT = $40
NAMETABLE = $2000
PALETTE   = $3F00

PAD_A      = $80
PAD_B      = $40
PAD_SELECT = $20
PAD_START  = $10
PAD_UP     = $08
PAD_DOWN   = $04
PAD_LEFT   = $02
PAD_RIGHT  = $01
PAD_DIRECTIONS = PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
REPEAT_DELAY = 20               ; frames a direction is held before it repeats
REPEAT_EVERY = 5                ; and frames between repeats

OUT0_MARK = $01

NESP_RX_MASK = $3F              ; replies of up to 63 bytes: a line, and what it is of
NESP_TX_MAX  = 28               ; an id and a handle
.define NESP_APP "BSKY"
NESP_APP_VERSION = 1

VIEW_SPLASH = 0
VIEW_LIST   = 1
VIEW_FORM   = 2
VIEW_POST   = 3

PENDING_NONE   = 0
PENDING_ADD    = 1
PENDING_REMOVE = 2

FEED_UNKNOWN = $FF              ; feed_state: the nesp32 has not said how it stands
POLL_MASK = $07                 ; a feed being fetched is asked after every 8 frames
BLINK_MASK = $10                ; the form's mark is hidden for 16 frames in 32
MISSED_MAX = 8                  ; exchanges in a row with no reply: the nesp32 is not there
SPRITE_HIDDEN = $FF
SPACE = ' '

oam = $0200                     ; the sprite, copied to the PPU every NMI

.include "screen.inc"            ; the sizes the memory below is reserved by

.segment "HEADER"
    .byte "NES", $1A
    .byte 1                     ; 1 x 16 KB PRG
    .byte 1                     ; 1 x 8 KB CHR
    .byte $01, $00              ; mapper 0 (NROM), vertical mirroring
    .res 8, 0

.segment "ZEROPAGE"
frame_count:  .res 1            ; NMIs, for the main loop
served_frame: .res 1
text_ptr:     .res 2            ; the status line's text, for the NMI
src_ptr:      .res 2            ; the main loop's
dst_ptr:      .res 2
pad:          .res 1            ; A B Select Start Up Down Left Right
held:         .res 1            ; the NMI's: the directions that are down

.segment "BSS"
pad_prev:     .res 1
pad_new:      .res 1            ; buttons that went down, or repeated: the main loop's
repeat:       .res 1            ; frames until a direction held down counts again
presses:      .res 1            ; the main loop's copy of pad_new
screen_on:    .res 1            ; 0: the NMI leaves the PPU alone, and keeps it off
ppu_ctrl:     .res 1            ; what the NMI writes to PPUCTRL
status:       .res 1            ; STATUS_* or a SPLASH_*: what the status line says
status_dirty: .res 1            ; and it is not on the screen yet
status_addr:  .res 2            ; where the status line is, high byte first
greeted:      .res 1            ; the nesp32 has answered this ROM's hello
link_missed:  .res 1            ; exchanges in a row with no reply, up to MISSED_MAX
link_failed:  .res 2            ; every exchange with none, for a debugger's watch list
why_buf:      .res COLUMNS      ; the nesp32's words for what went wrong
count_buf:    .res COLUMNS      ; "POST 3 OF 25"
view:         .res 1            ; VIEW_*
paint_at:     .res 1            ; rows still to paint: from this one
paint_end:    .res 1            ; up to this one
row_buf:      .res COLUMNS      ; a row for the NMI to draw,
row_addr:     .res 2            ; where, high byte first,
row_dirty:    .res 1            ; and that it has not yet
; The favorites, as the nesp32 has them.
fav_count:    .res 1
fav_load:     .res 1            ; they are to be asked for again,
fav_next:     .res 1            ; from this one
fav_lens:     .res FAVORITES
favs:         .res FAVORITES * HANDLE_MAX
choice:       .res 1            ; the line the arrow is at: a favorite, or fav_count for the form
confirm:      .res 1            ; Select has been pressed once at it
pending:      .res 1            ; PENDING_*
pending_again: .res 1           ; it went, and no reply came: send it again as it was
pending_arg:  .res 1            ; REMOVE's number
from_form:    .res 1            ; an ADD is the form's: the favorites come up after
; The form: a letter a place, as its number in `letters`.
form_at:      .res HANDLE_MAX
form_cursor:  .res 1
; A post is the view: the handle, and the post on the screen.
handle:       .res HANDLE_MAX
handle_len:   .res 1
feed_id:      .res 1            ; one more with every choice
feed_state:   .res 1            ; NESP_FEED_*, or FEED_UNKNOWN
post_count:   .res 1            ; posts the nesp32 holds
post_index:   .res 1            ; the one on the screen
row_next:     .res 1            ; its next line to draw; POST_ROWS when it is all there

.include "nesp.inc"

.assert NESP_TX_MAX >= NESP_HELLO_FIXED + 1, error, "the hello must fit a request"
.assert NESP_TX_MAX = 1 + NESP_BSKY_HANDLE_MAX, error, "an id and a handle must fit a request"
.assert 4 + NESP_BSKY_COLUMNS <= NESP_RX_MASK, error, "a line must fit its buffer"
.assert COLUMNS = NESP_BSKY_COLUMNS && POST_ROWS = NESP_BSKY_ROWS, error, "a post is the nesp32's"
.assert HANDLE_MAX = NESP_BSKY_HANDLE_MAX && FAVORITES = NESP_BSKY_FAVORITES, error, "and so are the favorites"
.assert STATUS_WIDTH = COLUMNS, error, "why_buf holds what the nesp32 may say"

SPLASH_BASE = STATUS_COUNT + 1  ; the splash's words, after the app's in the tables

.segment "RODATA"
palette_data:
    .incbin "palette.bin"
splash_palette:
    .incbin "splash_palette.bin"
screen_data:
    .incbin "screen.bin"
splash_data:
    .incbin "splash.bin"

; The status line's text, by STATUS_*, then the splash's by SPLASH_*.
status_lo:
.repeat STATUS_WHY, index
    .byte <(status_text + index * COLUMNS)
.endrepeat
    .byte <why_buf, <count_buf
.repeat 3, index
    .byte <(splash_text + index * COLUMNS)
.endrepeat
status_hi:
.repeat STATUS_WHY, index
    .byte >(status_text + index * COLUMNS)
.endrepeat
    .byte >why_buf, >count_buf
.repeat 3, index
    .byte >(splash_text + index * COLUMNS)
.endrepeat

; Where a row of the middle begins in a template, and where a favorite is.
row_off_lo:
.repeat POST_ROWS, index
    .byte <(index * COLUMNS)
.endrepeat
row_off_hi:
.repeat POST_ROWS, index
    .byte >(index * COLUMNS)
.endrepeat
fav_lo:
.repeat FAVORITES, index
    .byte <(favs + index * HANDLE_MAX)
.endrepeat
fav_hi:
.repeat FAVORITES, index
    .byte >(favs + index * HANDLE_MAX)
.endrepeat

; The foot, by view.
foot_lo:
    .byte <foot_list, <foot_list, <foot_form, <foot_post
foot_hi:
    .byte >foot_list, >foot_list, >foot_form, >foot_post

; What the status line says of each of the nesp32's states, with no posts.
feed_status:
    .byte STATUS_NONE, STATUS_NO_WIFI, STATUS_FETCHING, STATUS_NO_POSTS, STATUS_NOT_FOUND
.assert NESP_FEED_IDLE = 0 && NESP_FEED_NO_WIFI = 1 && NESP_FEED_FETCHING = 2, error, "feed_status"
.assert NESP_FEED_READY = 3 && NESP_FEED_NOT_FOUND = 4 && NESP_FEED_FAILED = 5, error, "feed_status"

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
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @clear
    lda #SPRITE_HIDDEN
@hide:
    sta oam,x
    inx
    bne @hide

@vblank2:
    bit PPUSTATUS
    bpl @vblank2

    jsr load_splash             ; rendering is off; the first NMI turns it on
    lda #FEED_UNKNOWN
    sta feed_state
    sta status                  ; nothing is on the status line yet
    lda #PAINT_ROWS
    sta paint_at
    sta paint_end
    lda #REPEAT_DELAY
    sta repeat
    lda #1
    sta fav_load
    lda #SPLASH_BASE + SPLASH_WAITING
    jsr set_status
    lda #OUT0_MARK              ; the line rests at mark, which is also what keeps
    sta JOY1                    ; the controller loading its buttons
    lda #1
    sta screen_on
    lda ppu_ctrl
    sta PPUCTRL
    ; fall through
.endproc

; A frame: the buttons, a row to paint if one is due, the sprite, and one
; exchange, starting right after the NMI. The main loop compares against
; the last frame it served rather than waiting for the next change, because
; an NMI that cuts off a receive has already counted the new frame, and
; that frame still needs its request.
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
    jsr buttons
    jsr paint_step
    jsr place_sprite
    jsr link_service
    jmp main_loop

; --- the two screens -------------------------------------------------------------

; Her splash: its palettes, its nametable, from her page of tiles. Rendering
; must be off.
.proc load_splash
    lda #<splash_palette
    sta src_ptr
    lda #>splash_palette
    sta src_ptr + 1
    jsr load_palette
    lda #<splash_data
    sta src_ptr
    lda #>splash_data
    sta src_ptr + 1
    jsr load_nametable
    lda #PPUCTRL_NMI | PPUCTRL_BG_PAGE1
    sta ppu_ctrl
    lda #>SPLASH_STATUS_ADDR
    sta status_addr
    lda #<SPLASH_STATUS_ADDR
    sta status_addr + 1
    rts
.endproc

; The splash is left: the screen goes off at the next NMI, the app's
; palettes and nametable go in, and it comes on again with the favorites.
.proc go_app
    lda #0
    sta screen_on
    lda frame_count
@wait:
    cmp frame_count             ; an NMI with screen_on clear turns the picture off
    beq @wait
    lda #<palette_data
    sta src_ptr
    lda #>palette_data
    sta src_ptr + 1
    jsr load_palette
    lda #<screen_data
    sta src_ptr
    lda #>screen_data
    sta src_ptr + 1
    jsr load_nametable
    lda #PPUCTRL_NMI
    sta ppu_ctrl
    lda #>STATUS_ADDR
    sta status_addr
    lda #<STATUS_ADDR
    sta status_addr + 1
    lda #$FF
    sta status                  ; whatever the splash said, the line is drawn anew
    lda frame_count
    sta served_frame            ; the frames that went by are not to be served now
    lda #1
    sta screen_on
    jmp show_list
.endproc

; 32 bytes of palettes from src_ptr. Rendering must be off.
.proc load_palette
    lda #>PALETTE
    sta PPUADDR
    lda #<PALETTE
    sta PPUADDR
    ldy #0
@color:
    lda (src_ptr),y
    sta PPUDATA
    iny
    cpy #32
    bne @color
    rts
.endproc

; A nametable and its attributes, 1 KB from src_ptr. Rendering must be off.
.proc load_nametable
    lda #>NAMETABLE
    sta PPUADDR
    lda #<NAMETABLE
    sta PPUADDR
    ldx #4
    ldy #0
@byte:
    lda (src_ptr),y
    sta PPUDATA
    iny
    bne @byte
    inc src_ptr + 1
    dex
    bne @byte
    rts
.endproc

; --- the status line ---------------------------------------------------------------

; The status line is to say A (STATUS_*, or SPLASH_BASE + SPLASH_*). The
; NMI draws it; it is told only once the text's address is whole. The
; nesp32's words and the count are drawn again even when the line says them
; already: they may be new.
.proc set_status
    cmp #STATUS_WHY
    beq @new
    cmp #STATUS_COUNT
    beq @new
    cmp status
    beq @done
@new:
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

; The status line as it should be when nothing has gone wrong.
.proc settle_status
    lda view
    bne @app
    lda greeted
    beq @waiting
    lda #SPLASH_BASE + SPLASH_START
    jmp set_status
@waiting:
    lda #SPLASH_BASE + SPLASH_WAITING
    jmp set_status
@app:
    cmp #VIEW_POST
    bne @none
    lda #FEED_UNKNOWN           ; FEED will say
    sta feed_state
    rts
@none:
    lda #STATUS_NONE
    jmp set_status
.endproc

; --- painting ----------------------------------------------------------------------

; row_buf is whole, and is row X of what is painted (the middle's rows,
; then the foot): the NMI is to draw it there.
.proc stage_row
    lda paint_hi,x
    sta row_addr
    lda paint_lo,x
    sta row_addr + 1
    lda #1
    sta row_dirty
    rts
.endproc

; All of the middle and the foot are to be painted anew.
.proc repaint
    lda #0
    sta paint_at
    lda #PAINT_ROWS
    sta paint_end
    rts
.endproc

; Row X is to be painted anew, with any that already are.
.proc repaint_row
    lda paint_at
    cmp paint_end
    bne @busy
    stx paint_at
    inx
    stx paint_end
    rts
@busy:
    cpx paint_at
    bcs @not_before
    stx paint_at
@not_before:
    inx
    cpx paint_end
    bcc @done
    stx paint_end
@done:
    rts
.endproc

; A row for the NMI, if there is one to paint and the last has been drawn.
.proc paint_step
    lda row_dirty
    bne @done
    ldx paint_at
    cpx paint_end
    beq @done
    jsr fill_row
    ldx paint_at
    jsr stage_row
    inc paint_at
@done:
    rts
.endproc

; Row X of the view, into row_buf: the foot, or a row of the middle.
.proc fill_row
    cpx #POST_ROWS
    bne @middle
    ldx view
    lda foot_lo,x
    sta src_ptr
    lda foot_hi,x
    sta src_ptr + 1
    jmp copy_row
@middle:
    lda view
    cmp #VIEW_LIST
    beq @list
    cmp #VIEW_FORM
    beq @form
    ldy #COLUMNS - 1            ; a post: blank, for its lines to come
    lda #SPACE
@blank:
    sta row_buf,y
    dey
    bpl @blank
    rts
@list:
    txa
    pha
    lda #<list_text
    ldy #>list_text
    jsr template_row
    pla
    sec
    sbc #LIST_ROW
    bcc @done                   ; above the favorites
    cmp fav_count
    bcs @done                   ; below them
    tax
    lda fav_lo,x
    sta src_ptr
    lda fav_hi,x
    sta src_ptr + 1
    lda #'@'
    sta row_buf
    ldy fav_lens,x
    beq @done
@handle:
    dey
    lda (src_ptr),y
    sta row_buf + 1,y
    tya
    bne @handle
@done:
    rts
@form:
    txa
    pha
    lda #<form_text
    ldy #>form_text
    jsr template_row
    pla
    cmp #FORM_ROW
    bne @done
    ldx #HANDLE_MAX - 1
@letter:
    ldy form_at,x
    lda letters,y
    sta row_buf + 1,x
    dex
    bpl @letter
    rts
.endproc

; Row X of a template of the middle's rows at YA, into row_buf.
.proc template_row
    clc
    adc row_off_lo,x
    sta src_ptr
    tya
    adc row_off_hi,x
    sta src_ptr + 1
    ; fall through
.endproc

; A row from src_ptr into row_buf.
.proc copy_row
    ldy #COLUMNS - 1
@copy:
    lda (src_ptr),y
    sta row_buf,y
    dey
    bpl @copy
    rts
.endproc

; The sprite: the arrow at a favorite, the form's mark, which blinks, or
; nothing.
.proc place_sprite
    lda view
    cmp #VIEW_LIST
    beq @list
    cmp #VIEW_FORM
    beq @form
@hide:
    lda #SPRITE_HIDDEN
    sta oam
    rts
@list:
    ldx choice
    txa
    cpx fav_count
    bcc @favorite
    lda #OTHER_ROW - LIST_ROW
@favorite:
    clc
    adc #LIST_ROW
    asl a
    asl a
    asl a
    adc #BODY_Y - 1             ; a sprite is drawn a line below its Y
    sta oam
    lda #ARROW_TILE
    sta oam + 1
    lda #ARROW_X
    sta oam + 3
    lda #0
    sta oam + 2
    rts
@form:
    lda frame_count
    and #BLINK_MASK
    bne @hide
    lda #BODY_Y + 8 * FORM_ROW - 1
    sta oam
    lda #MARK_TILE
    sta oam + 1
    lda form_cursor
    asl a
    asl a
    asl a
    adc #MARK_X
    sta oam + 3
    lda #0
    sta oam + 2
    rts
.endproc

; --- the buttons -------------------------------------------------------------------

; What the controller asked for since the last frame.
.proc buttons
    lda pad_new
    bne @some
@done:
    rts
@some:
    ldx #0
    stx pad_new
    sta presses
    lda view
    beq splash_buttons
    cmp #VIEW_LIST
    beq list_buttons
    cmp #VIEW_FORM
    bne @post
    jmp form_buttons
@post:
    jmp post_buttons
.endproc

; The splash: Start, or A, once the nesp32 has answered.
.proc splash_buttons
    lda greeted
    beq @done
    lda presses
    and #PAD_START | PAD_A
    beq @done
    jmp go_app
@done:
    rts
.endproc

.proc list_buttons
    lda presses
    and #PAD_SELECT
    bne @select
    lda confirm                 ; anything but Select calls a removal off
    beq @move
    lda #0
    sta confirm
    lda #STATUS_NONE
    jsr set_status
@move:
    ldx choice
    lda presses
    and #PAD_UP
    beq @down
    dex
    bpl @down
    ldx fav_count
@down:
    lda presses
    and #PAD_DOWN
    beq @a
    inx
    cpx fav_count
    beq @a
    bcc @a
    ldx #0
@a:
    stx choice
    lda presses
    and #PAD_A
    beq @done
    cpx fav_count
    bcc @read
    jmp show_form
@read:
    jmp read_favorite
@select:
    ldx choice
    cpx fav_count
    bcs @done                   ; the way to the form is not a favorite
    lda confirm
    bne @remove
    lda #1
    sta confirm
    lda #STATUS_REMOVE
    jmp set_status
@remove:
    lda #0
    sta confirm
    stx pending_arg
    lda #PENDING_REMOVE
    sta pending
    lda #0
    sta pending_again
@done:
    rts
.endproc

.proc form_buttons
    lda presses
    and #PAD_B
    beq @a
    jmp show_list
@a:
    lda presses
    and #PAD_A
    beq @start
    jsr form_handle
    beq @empty
    jmp show_post
@start:
    lda presses
    and #PAD_START
    beq @move
    jsr form_handle
    beq @empty
    lda #1
    sta from_form
    jmp ask_to_add
@empty:
    lda #STATUS_EMPTY
    jmp set_status
@move:
    ldx form_cursor
    lda presses
    and #PAD_LEFT
    beq @right
    dex
    bpl @right
    ldx #HANDLE_MAX - 1
@right:
    lda presses
    and #PAD_RIGHT
    beq @letter
    inx
    cpx #HANDLE_MAX
    bne @letter
    ldx #0
@letter:
    stx form_cursor
    lda presses
    and #PAD_UP | PAD_DOWN
    beq @done
    and #PAD_UP
    beq @back
    inc form_at,x
    lda form_at,x
    cmp #LETTER_COUNT
    bne @changed
    lda #0
    sta form_at,x
    beq @changed
@back:
    dec form_at,x
    bpl @changed
    lda #LETTER_COUNT - 1
    sta form_at,x
@changed:
    lda #STATUS_NONE
    jsr set_status
    ldx #FORM_ROW
    jmp repaint_row
@done:
    rts
.endproc

.proc post_buttons
    lda presses
    and #PAD_B
    beq @start
    jmp show_list
@start:
    lda presses
    and #PAD_START
    beq @left
    lda #0
    sta from_form
    jmp ask_to_add
@left:
    lda presses
    and #PAD_LEFT
    beq @right
    lda post_index
    beq @done
    dec post_index
    jmp turn
@right:
    lda presses
    and #PAD_RIGHT
    beq @done
    ldx post_index
    inx
    cpx post_count
    bcs @done
    stx post_index
    jmp turn
@done:
    rts
.endproc

; --- the views ---------------------------------------------------------------------

.proc show_list
    lda #VIEW_LIST
    sta view
    lda #0
    sta confirm
    jsr clamp_choice
    lda #STATUS_NONE
    jsr set_status
    jmp repaint
.endproc

.proc show_form
    lda #VIEW_FORM
    sta view
    lda #STATUS_NONE
    jsr set_status
    jmp repaint
.endproc

; The arrow is never past the way to the form.
.proc clamp_choice
    lda choice
    cmp fav_count
    bcc @done
    lda fav_count
    sta choice
@done:
    rts
.endproc

; A: the favorite at the arrow is the handle whose posts are wanted.
.proc read_favorite
    ldx choice
    lda fav_lo,x
    sta src_ptr
    lda fav_hi,x
    sta src_ptr + 1
    lda fav_lens,x
    sta handle_len
    tay
    beq @done
@copy:
    dey
    lda (src_ptr),y
    sta handle,y
    tya
    bne @copy
    jmp show_post
@done:
    rts
.endproc

; The form's handle into `handle`, its spaces left out. Z set if it is
; empty.
.proc form_handle
    lda #0
    sta handle_len
    ldx #0
@letter:
    ldy form_at,x
    beq @space                  ; letter 0 is the space
    lda letters,y
    ldy handle_len
    sta handle,y
    inc handle_len
@space:
    inx
    cpx #HANDLE_MAX
    bne @letter
    lda handle_len
    rts
.endproc

; `handle`'s posts are the view: a new choice, from its first post.
.proc show_post
    lda #VIEW_POST
    sta view
    inc feed_id
    lda #FEED_UNKNOWN
    sta feed_state
    lda #0
    sta post_count
    sta post_index
    sta row_next
    lda #STATUS_FETCHING
    jsr set_status
    jmp repaint
.endproc

; Another post of the same handle: its lines, from the first.
.proc turn
    lda #0
    sta row_next
    jmp count_status
.endproc

; Start: `handle` onto the favorites.
.proc ask_to_add
    lda #PENDING_ADD
    sta pending
    lda #0
    sta pending_again
    rts
.endproc

; "POST 3 OF 25" on the status line, for the post on the screen.
.proc count_status
    ldx #COLUMNS - 1
    lda #SPACE
@blank:
    sta count_buf,x
    dex
    bpl @blank
    ; Its length: "POST ", the number, " OF ", the count. It is centered.
    ldx #9 + 2                  ; the words, and a digit of each number
    lda post_index
    cmp #9                      ; the number is one more: 10 or more has two
    bcc @one
    inx
@one:
    lda post_count
    cmp #10
    bcc @two
    inx
@two:
    stx dst_ptr
    lda #COLUMNS
    sec
    sbc dst_ptr
    lsr a
    tay
    ldx #0
@post:
    lda count_text,x
    sta count_buf,y
    iny
    inx
    cpx #5
    bne @post
    ldx post_index
    inx
    txa
    jsr put_number
    ldx #0
@of:
    lda of_text,x
    sta count_buf,y
    iny
    inx
    cpx #4
    bne @of
    lda post_count
    jsr put_number
    lda #STATUS_COUNT
    jmp set_status
.endproc

of_text:
    .byte " OF "

; A, 0 to 99, at count_buf + Y; Y moves on past it.
.proc put_number
    ldx #'0'
@tens:
    cmp #10
    bcc @units
    sbc #10
    inx
    bne @tens
@units:
    cpx #'0'
    beq @one
    pha
    txa
    sta count_buf,y
    iny
    pla
@one:
    ora #'0'
    sta count_buf,y
    iny
    rts
.endproc

; --- the link ----------------------------------------------------------------------

; The frame's exchange, if it has one. An exchange that the next NMI cut
; off comes back here with carry set and frame_count moved on, so the main
; loop serves the new frame at once; one that ended inside its frame, good
; or not, leaves the next for the next NMI.
.proc link_service
    lda screen_on
    beq @idle
    lda greeted
    bne @greeted
    jmp say_hello
@greeted:
    lda pending
    beq @favorites
    jmp ask_pending
@favorites:
    lda fav_load
    beq @post
    jmp ask_favorite
@post:
    lda view
    cmp #VIEW_POST
    bne @idle
    lda feed_state
    cmp #FEED_UNKNOWN
    bne @known
    jmp ask_feed
@known:
    lda row_next
    cmp #POST_ROWS
    beq @poll
    lda post_index
    cmp post_count
    bcs @poll                   ; not held yet
    lda row_dirty               ; a line at a time,
    bne @idle
    lda paint_at                ; and none over rows that are still being painted
    cmp paint_end
    bne @idle
    jmp ask_line
@poll:
    lda feed_state
    cmp #NESP_FEED_FETCHING
    bne @idle
    lda frame_count
    and #POLL_MASK
    bne @idle
    jmp ask_feed
@idle:
    rts
.endproc

; Hello: this is Bluesky, and it needs BSKY. A nesp32 that lacks it, or
; speaks another protocol, has older firmware than this ROM, and the screen
; says so.
.proc say_hello
    lda #NESP_SVC_BSKY
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    bne @old
    lda #1
    sta greeted
    sta fav_load                ; a nesp32 that was switched off and on has them anew
    lda #0
    sta fav_next
    sta pending_again           ; what went before the hello goes anew
    jsr settle_status
    jmp link_heard
@old:
    lda view
    bne @app
    lda #SPLASH_BASE + SPLASH_OLD
    .byte $2C                   ; bit abs: skips the next lda
@app:
    lda #STATUS_OLD
    jsr set_status
    jmp link_heard
.endproc

; A change to the favorites. One that went, and whose reply did not come, is
; sent again byte for byte, which the nesp32 answers with the reply it gave
; and does not act on twice.
.proc ask_pending
    lda pending_again
    beq @new
    jsr nesp_again
    jmp @sent
@new:
    lda pending
    cmp #PENDING_REMOVE
    beq @remove
    ldy handle_len
@copy:
    dey
    lda handle,y
    sta nesp_request,y
    tya
    bne @copy
    lda #NESP_SVC_BSKY
    ldx #NESP_BSKY_ADD
    ldy handle_len
    jsr nesp_call
    jmp @sent
@remove:
    lda pending_arg
    sta nesp_request
    lda #NESP_SVC_BSKY
    ldx #NESP_BSKY_REMOVE
    ldy #1
    jsr nesp_call
@sent:
    bcc @came
    lda #1
    sta pending_again
    jmp link_silent
@came:
    ldx #0
    stx pending_again
    cmp #NESP_ST_OK
    beq @done
    cmp #NESP_ST_BAD_ARG
    beq @bad
    jmp link_refused            ; and after the hello it goes again
@bad:
    stx pending
    lda #STATUS_BAD
    jsr set_status
    jmp link_heard
@done:
    stx pending
    lda #1
    sta fav_load                ; the favorites as they are now
    lda #0
    sta fav_next
    lda nesp_reply_len
    cmp #2
    bcc @removed
    lda from_form               ; ADD: from the form, the favorites come up
    beq @said
    jsr show_list
@said:
    lda nesp_reply + 1
    cmp #$FF
    beq @full
    lda #STATUS_SAVED
    .byte $2C                   ; bit abs: skips the next lda
@full:
    lda #STATUS_FULL
    jsr set_status
    jmp link_heard
@removed:
    lda #STATUS_REMOVED
    jsr set_status
    jmp link_heard
.endproc

; The next favorite, by its number. When they have all come, the list is
; painted anew, if it is the view.
.proc ask_favorite
    lda fav_next
    sta nesp_request
    lda #NESP_SVC_BSKY
    ldx #NESP_BSKY_FAVORITE
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
    bcc @heard
    lda nesp_reply + 1
    cmp fav_next
    bne @heard
    lda nesp_reply
    cmp #FAVORITES + 1
    bcc @count
    lda #FAVORITES
@count:
    sta fav_count
    lda fav_next
    cmp fav_count
    bcs @all                    ; there is no such one: that was all
    tax
    lda fav_lo,x
    sta dst_ptr
    lda fav_hi,x
    sta dst_ptr + 1
    lda nesp_reply_len
    sec
    sbc #2
    cmp #HANDLE_MAX + 1
    bcc @fits
    lda #HANDLE_MAX
@fits:
    sta fav_lens,x
    tay
    beq @next
@copy:
    dey
    lda nesp_reply + 2,y
    sta (dst_ptr),y
    tya
    bne @copy
@next:
    inc fav_next
    lda fav_next
    cmp fav_count
    bcc @heard
@all:
    lda #0
    sta fav_load
    jsr clamp_choice
    lda view
    cmp #VIEW_LIST
    bne @heard
    jsr repaint
@heard:
    jmp link_heard
.endproc

; This handle, and how it stands with its posts.
.proc ask_feed
    lda feed_id
    sta nesp_request
    ldy handle_len
@copy:
    dey
    lda handle,y
    sta nesp_request + 1,y
    tya
    bne @copy
    ldy handle_len
    iny
    lda #NESP_SVC_BSKY
    ldx #NESP_BSKY_FEED
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    cmp #NESP_ST_BAD_ARG
    bne @refused
    jsr show_form               ; the form's to put right
    lda #STATUS_BAD
    jsr set_status
    jmp link_heard
@refused:
    jmp link_refused
@ok:
    lda nesp_reply_len
    cmp #3
    bcc @heard                  ; not a reply to this at all
    lda nesp_reply + 1
    cmp feed_id
    bne @heard
    lda nesp_reply
    cmp #NESP_FEED_FAILED + 1
    bcs @heard                  ; a state this ROM has not heard of
    sta feed_state
    cmp #NESP_FEED_IDLE
    bne @state
    lda #FEED_UNKNOWN           ; the nesp32 has not got it: ask again
    sta feed_state
    jmp link_heard
@state:
    lda nesp_reply + 2
    jsr take_count
    lda post_count
    bne @heard                  ; the count is on the status line
    lda feed_state
    cmp #NESP_FEED_FAILED
    beq @failed
    tax
    lda feed_status,x
    jsr set_status
@heard:
    jmp link_heard
@failed:
    jsr take_why
    jmp link_heard
.endproc

; The next line of the post on the screen, into row_buf and onto it.
.proc ask_line
    lda post_index
    sta nesp_request
    lda row_next
    sta nesp_request + 1
    lda #NESP_SVC_BSKY
    ldx #NESP_BSKY_LINE
    ldy #2
    jsr nesp_call
    bcc @came
    jmp link_silent
@came:
    cmp #NESP_ST_OK
    beq @ok
    jmp link_refused
@ok:
    lda nesp_reply_len
    cmp #4
    bcc @heard
    lda nesp_reply + 1
    cmp post_index
    bne @heard
    lda nesp_reply + 2
    cmp row_next
    bne @heard
    lda nesp_reply + 3
    jsr take_count
    lda nesp_reply
    bmi @heard                  ; NO_LINE: not held after all
    lda nesp_reply_len
    cmp #4 + COLUMNS
    bne @heard
    ldx #COLUMNS - 1
@copy:
    lda nesp_reply + 4,x
    sta row_buf,x
    dex
    bpl @copy
    ldx row_next
    jsr stage_row
    inc row_next
@heard:
    jmp link_heard
.endproc
.assert NESP_FEED_NO_LINE = $80, error, "ask_line"

; How many posts the nesp32 holds, as A; the status line says which this
; is of them once there are any.
.proc take_count
    cmp post_count
    beq @done
    sta post_count
    lda post_count
    beq @done
    jmp count_status
@done:
    rts
.endproc

; The nesp32's words for what went wrong, on the status line.
.proc take_why
    ldx #COLUMNS - 1
@copy:
    lda nesp_reply + 3,x
    sta why_buf,x
    dex
    bpl @copy
    lda nesp_reply_len
    cmp #3 + COLUMNS
    beq @whole
    ldx #COLUMNS - 1            ; no words came with it
    lda #SPACE
@blank:
    sta why_buf,x
    dex
    bpl @blank
@whole:
    lda #STATUS_WHY
    jmp set_status
.endproc

; A reply came. The next exchange waits for the next NMI: sent from here,
; partway through a frame, its reply could run into that NMI.
.proc link_heard
    lda link_missed
    cmp #MISSED_MAX
    bcc @fine
    jsr settle_status           ; the line said it was waiting
@fine:
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
    lda link_missed
    cmp #MISSED_MAX
    bcs @say
    rts
@gone:
    rts
@say:
    lda view
    bne @app
    lda #SPLASH_BASE + SPLASH_WAITING
    jmp set_status
@app:
    lda #STATUS_WAITING
    jmp set_status
.endproc

; The nesp32 answered, and not with OK: it no longer has the service in
; use. Say hello again.
.proc link_refused
    lda #0
    sta greeted
    jmp link_heard
.endproc

; --- the NMI -----------------------------------------------------------------------

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
    and pad
    tax                         ; buttons that went down this frame
    ; A direction held down counts again after a while, and then often.
    lda pad
    and #PAD_DIRECTIONS
    beq @fresh
    sta held
    lda pad_prev
    and #PAD_DIRECTIONS
    cmp held
    bne @fresh
    dec repeat
    bne @counted
    lda #REPEAT_EVERY
    sta repeat
    txa
    ora held
    tax
    bne @counted
@fresh:
    lda #REPEAT_DELAY
    sta repeat
@counted:
    lda pad
    sta pad_prev
    txa
    ora pad_new
    sta pad_new

    lda screen_on
    bne @on
    sta PPUMASK                 ; the main loop has the PPU: off, and nothing else
    jmp @done
@on:
    bit PPUSTATUS               ; reset the PPU's address latch
    lda #0
    sta OAMADDR
    lda #>oam
    sta OAMDMA
    lda status_dirty
    beq @row
    lda status_addr
    sta PPUADDR
    lda status_addr + 1
    sta PPUADDR
    ldy #0
@char:
    lda (text_ptr),y
    sta PPUDATA
    iny
    cpy #STATUS_WIDTH
    bne @char
    lda #0
    sta status_dirty
@row:
    lda row_dirty
    beq @scroll
    lda row_addr
    sta PPUADDR
    lda row_addr + 1
    sta PPUADDR
    ldy #0
@tile:
    lda row_buf,y
    sta PPUDATA
    iny
    cpy #COLUMNS
    bne @tile
    lda #0
    sta row_dirty
@scroll:
    lda ppu_ctrl
    sta PPUCTRL
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUMASK_ON
    sta PPUMASK
@done:
    inc frame_count
    nesp_nmi_hook
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

.segment "CHARS"
    .incbin "chr.bin"

.segment "VECTORS"
    .addr nmi
    .addr reset
    .addr irq

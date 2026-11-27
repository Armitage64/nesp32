; Netplay: the title's choice, LOCAL GAME or NETWORK GAME, in place of its
; START GAME.
;
; The title's scene draws the two lines (NET_TITLE_SCRIPT, in bank 6's
; empty bytes, which its script calls in place of drawing START GAME), with
; its stars beside LOCAL GAME. Up, Down and Select move the stars to the
; other line, through the game's PPU buffer; Start or A takes the line
; they are beside: the game, as START GAME did, or the menu (net/menu.inc),
; as Select did before. The title's own code is in bank 16, at $8000 while
; the title's task runs, and so is this (net_title_move, in its empty
; bytes, with net_title_start, which LOCAL GAME is chosen by each time the
; title is drawn); Start or A is in the fixed bank (net_title_pick,
; net/cart.inc).

HAVE_FREE_6_BD0D  = 1
HAVE_FREE_16_9FC5 = 1


TITLE_STARS     = $2248         ; row 18, column 8: the stars beside LOCAL GAME
TITLE_LOCAL     = TITLE_STARS + 4   ; LOCAL GAME, where START GAME was
.assert >TITLE_LOCAL = $22, error, "the flash of LOCAL GAME is drawn at $22xx"
TITLE_STAR_1    = $1B           ; the title's stars, as they were beside START GAME
TITLE_STAR_2    = $1C
TITLE_STAR_3    = $19
TITLE_BLANK     = $00           ; the tile the scene draws for a space
TITLE_MOVE      = UP_DPAD | DOWN_DPAD | SELECT_BUTTON

.macro FILL_FREE_6_BD0D
; The title's two lines, a subscript of its scene (START_SCREEN_SCRIPT):
; each at a PPU address ($88 + its high byte - $20, then its low byte), its
; tiles, and back. Row 18 is LOCAL GAME, with the stars, where START GAME
; was; row 20 NETWORK GAME. Not row 17: the title's last split changes
; the background's CHR banks at row 18, and above it the stars' tiles are
; the logo's. Start on LOCAL GAME flashes it there (FLASH_START_GAME's
; script, in place of START GAME).
NET_TITLE_SCRIPT:
    .byte $88 + >TITLE_STARS - $20, <TITLE_STARS
    .byte TITLE_STAR_1, TITLE_STAR_2, TITLE_STAR_3, $20
    .byte "LOCAL GAME"
    .byte $88 + >(TITLE_STARS + 64) - $20, <(TITLE_STARS + 64)
    .byte $20, $20, $20, $20
    .byte "NETWORK GAME"
    .byte $FE                   ; RETURN_FROM_BG_SUBSCRIPT
.endmacro

.macro FILL_FREE_16_9FC5
; First in the title's test (net_title_pick): Up, Down or Select moves the
; stars to the other line.
net_title_move:
    lda JOY_PRESS_BOTH
    and #TITLE_MOVE
    beq @exit
    lda net_title_choice
    eor #$01
    sta net_title_choice
    asl a                       ; 8 bytes of script each
    asl a
    asl a
    adc #<net_title_stars       ; (carry clear: A was 0 or 1)
    sta ppu_data_addr
    lda #>net_title_stars
    sta ppu_data_addr+1
    ldy #<TITLE_STARS
    ldx #>TITLE_STARS
    jmp TRANSFER_TO_PPU_WITH_COMMANDS_VIA_BUFFER
@exit:
    rts

; The stars beside one line and blanks beside the other, as the game's PPU
; scripts are (TRANSFER_TO_PPU_WITH_COMMANDS_VIA_BUFFER): a count and its
; tiles, a tile repeated ($80 + the count), two rows down from the start
; ($A2), the end ($FF).
net_title_stars:
    .byte 3, TITLE_STAR_1, TITLE_STAR_2, TITLE_STAR_3, $A2, $83, TITLE_BLANK, $FF
    .byte $83, TITLE_BLANK, $A2, 3, TITLE_STAR_1, TITLE_STAR_2, TITLE_STAR_3, $FF
.assert >net_title_stars = >(net_title_stars + 15), error, "net_title_stars crosses a page"

; In place of the title's wait before its loop, once its scene is begun:
; LOCAL GAME chosen, as the scene draws it, and the wait.
net_title_start:
    lda #$00
    sta net_title_choice
    lda #$08
    jmp DELAY_TASK
.endmacro

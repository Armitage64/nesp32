; Netplay: the menu's screens, in the space bank 6 leaves at its end.
; bank6.asm includes it when NETPLAY is defined. The menu (menu.inc, in
; bank 5) has no room for them beside its own code once it has rooms as
; well as addresses, so they are here, and it reaches them through
; net_far_draw (net.inc), with bank 6 in place for the call: screen X,
; drawn whole with the picture off.
;
; Nothing here calls anything of bank 5's. The numbers the menu names a
; screen by are exported to it.

.include "ram.inc"

.exportzp SCREEN_MAIN, SCREEN_HOSTING, SCREEN_JOIN, SCREEN_ROOM, SCREEN_JOIN_ROOM

; The title's letters are ASCII by number, but for these two. Nothing
; follows this file in bank 6, so the map is left in force.
.charmap $20, $00               ; space
.charmap $2E, $40               ; .
FAR_BLANK       = $00
far_ptr         = nesp_ptr      ; menu.inc's menu_ptr

.macro far_text row, column, string
    .byte >($2000 + row * 32 + column), <($2000 + row * 32 + column)
    .byte .strlen(string), string
.endmacro

menu_far:
    lda menu_far_screens_lo,x
    sta far_ptr
    lda menu_far_screens_hi,x
    sta far_ptr+1
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ; 960 blank tiles, and 64 attributes: the one palette.
    ldy #$04
    ldx #$00

@tiles:
    sta PPUDATA
    dex
    bne @tiles
    dey
    bne @tiles
    ldy #$00

@string:
    lda (far_ptr),y
    beq @shown
    sta PPUADDR
    iny
    lda (far_ptr),y
    sta PPUADDR
    iny
    lda (far_ptr),y
    tax
    iny

@tile:
    lda (far_ptr),y
    sta PPUDATA
    iny
    dex
    bne @tile
    beq @string

@shown:
    ; The NMI on again, and not for a vblank that has already begun: the
    ; next one turns the picture on.
    lda PPUSTATUS
    lda #$00
    sta PPUSCROLL
    sta PPUSCROLL
    lda PPUCTRL_SETTINGS
    and #$fc
    sta PPUCTRL
    rts

.assert FAR_BLANK = 0, error, "a screen is cleared, and its attributes, with one value"

menu_far_screens_lo:
    .byte <menu_far_main, <menu_far_hosting, <menu_far_join, <menu_far_room
    .byte <menu_far_join_room
menu_far_screens_hi:
    .byte >menu_far_main, >menu_far_hosting, >menu_far_join, >menu_far_room
    .byte >menu_far_join_room
SCREEN_MAIN      = 0
SCREEN_HOSTING   = 1            ; by address
SCREEN_JOIN      = 2
SCREEN_ROOM      = 3            ; by room code
SCREEN_JOIN_ROOM = 4

menu_far_main:
    far_text 4, 10, "NETWORK GAME"
    far_text 9, 11, "HOST GAME"
    far_text 11, 11, "JOIN GAME"
    far_text 13, 11, "LOCAL GAME"
    far_text 18, 7, "THIS NESP32 IS AT"
    .byte 0

menu_far_hosting:
    far_text 4, 10, "NETWORK GAME"
    far_text 9, 6, "WAITING FOR PLAYER 2"
    far_text 12, 7, "PLAYER 2 JOINS AT"
    far_text 24, 12, "B   BACK"
    far_text 26, 5, "SELECT   BY ROOM CODE"
    .byte 0

menu_far_join:
    far_text 4, 10, "NETWORK GAME"
    far_text 9, 8, "JOIN THE GAME AT"
    far_text 22, 8, "START   CONNECT"
    far_text 24, 12, "B   BACK"
    far_text 26, 5, "SELECT   BY ROOM CODE"
    .byte 0

menu_far_room:
    far_text 4, 10, "NETWORK GAME"
    far_text 9, 6, "WAITING FOR PLAYER 2"
    far_text 12, 8, "THE ROOM CODE IS"
    far_text 24, 12, "B   BACK"
    far_text 26, 9, "SELECT   BY IP"
    .byte 0

menu_far_join_room:
    far_text 4, 10, "NETWORK GAME"
    far_text 9, 6, "JOIN THE ROOM OF CODE"
    far_text 22, 10, "START   JOIN"
    far_text 24, 12, "B   BACK"
    far_text 26, 9, "SELECT   BY IP"
    .byte 0

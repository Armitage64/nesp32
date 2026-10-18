; Netplay: Tetris for two, side by side. Only in the NETPLAY build.
;
; The game was written with a two-player game in it that it never offers:
; a second player's state at $80 and playfield at $0500, garbage sent to
; the other player for a double or more, and the pieces and the rows drawn
; at two places. It was never finished. This finishes it, much as TAUS's
; twoplayer mod does (github.com/ejona86/taus, Eric Anderson's, MIT), from
; which come the screen (net/twoplayer_game.nam), its tiles
; (net/twoplayer.chr), its places on the screen and most of what is here:
;
;   - a screen with both playfields, each player's score, level, lines
;     and next piece, and the rows drawn four at a time so that both fit
;     in a vblank
;   - each player's pieces from a generator of their own, both begun from
;     the same seed: the two get the same pieces, however far apart
;   - the level menu twice, once for each player
;   - a game that ends when either player's curtain is down, garbage being
;     on, and goes back to the level menu when a player presses Start
;   - Start from either player pauses
;   - the hole in the garbage moves every 10 rows, and is a hole: the
;     game's own made it a block nobody could see
;
; Only A-type: the B-type's goal, its height and its endings are left out.
; No high scores either. The game's own code calls these at the places
; patches/main.patch marks; the original single-player game is as it was.

; Where the two-player screen has each thing (TAUS's twoplayer.inc).
TP_P1_SCORE         = $2066
TP_P2_SCORE         = $2078
TP_P1_LEVEL         = $20EF
TP_P1_LINES         = $21CF
TP_P2_LEVEL         = $2250
TP_P2_LINES         = $2330
TP_P1_PREVIEW_X     = $78
TP_P1_PREVIEW_Y     = $53
TP_P2_PREVIEW_X     = $80
TP_P2_PREVIEW_Y     = $AB
; Each playfield's left column, from the one-player screen's
; (vramPlayfieldRows).
TP_P1_COLUMN        = <-$04
TP_P2_COLUMN        = $0E

; In the 32 bytes of a player's state that the game leaves unused: the
; player's own piece generator, as rng_seed, spawnID and spawnCount are
; laid out, and the garbage rows until the hole moves. The active player's
; copy, then player 1's and player 2's.
personal_rng            = tetriminoX + $1C      ; 4 bytes
garbageUntilResetHole   = tetriminoX + $1B
TP_STATE                = player1_tetriminoX - tetriminoX
player1_personal_rng    = personal_rng + TP_STATE
player2_personal_rng    = personal_rng + 2 * TP_STATE
player1_garbageUntilResetHole = garbageUntilResetHole + TP_STATE
player2_garbageUntilResetHole = garbageUntilResetHole + 2 * TP_STATE
TP_HOLE_ROWS        = 10

.assert player2_tetriminoX = player1_tetriminoX + TP_STATE, error
.assert spawnID = rng_seed + 2 && spawnCount = rng_seed + 3, error



; --- the pieces ---------------------------------------------------------------

; The pieces' generator of the game just begun, for both players: the
; game's, as it stands. From gameModeState_initGameState, before it chooses
; the first two pieces.
tp_seedPieces:
        ldx     #$03
@copy:  lda     rng_seed,x
        sta     personal_rng,x
        dex
        bpl     @copy
        rts

; And after: both players' generators where the first two pieces left it,
; and the hole to move after as many rows for both.
tp_seededPieces:
        ldx     #$03
@copy:  lda     personal_rng,x
        sta     player1_personal_rng,x
        sta     player2_personal_rng,x
        dex
        bpl     @copy
        lda     #TP_HOLE_ROWS
        sta     player1_garbageUntilResetHole
        sta     player2_garbageUntilResetHole
        rts

; The next piece of the active player, from their own generator. It is
; stepped three times, where the game's is stepped once a frame.
tp_chooseNextTetrimino:
        ldx     #personal_rng
        ldy     #$02
        jsr     generateNextPseudorandomNumber
        ldx     #personal_rng
        ldy     #$02
        jsr     generateNextPseudorandomNumber
        ldx     #personal_rng
        ldy     #$02
        jsr     generateNextPseudorandomNumber
        jsr     tp_swapRng
        jsr     pickRandomTetrimino
        pha
        jsr     tp_swapRng
        pla
        rts

tp_swapRng:
        ldx     #$03
@swap:  lda     rng_seed,x
        ldy     personal_rng,x
        sty     rng_seed,x
        sta     personal_rng,x
        dex
        bpl     @swap
        rts



; --- the screen -----------------------------------------------------------------

; The two-player screen, in place of the game's, with the PPU off.
tp_drawScreen:
        lda     currentPpuCtrl
        and     #$FB                    ; across, not down
        sta     currentPpuCtrl
        sta     PPUCTRL
        lda     #<tp_screen
        sta     tmp1
        lda     #>tp_screen
        sta     tmp2
        bit     PPUSTATUS
        lda     #$20
        sta     PPUADDR
        lda     #$00
        sta     PPUADDR
        tay
        ldx     #$04
@byte:  lda     (tmp1),y
        sta     PPUDATA
        iny
        bne     @byte
        inc     tmp2
        dex
        bne     @byte
        rts

; Four rows of a playfield from vramRow X, as copyPlayfieldRowToVRAM does
; one; X comes back as the next. A is the player: 0 the first, 1 the
; second. generalCounter is left alone: the code that waits for the NMI
; may be keeping something there (TAUS's note).
tp_copyFourRows:
        cpx     #$20
        bmi     @rows
        rts
@rows:  sta     tmp3
        tay
        lda     tp_columns,y
        sta     tmp2
        lda     #$04
        sta     tmp1
@row:   lda     tp_rowsHi,x
        sta     PPUADDR
        lda     tp_rowsLo,x
        clc
        adc     tmp2
        sta     PPUADDR
        ldy     multBy10Table,x
        lda     tmp3
        bne     @player2
        .repeat 10, i
        lda     playfield + i,y
        sta     PPUDATA
        .endrepeat
        jmp     @next
@player2:
        .repeat 10, i
        lda     playfieldForSecondPlayer + i,y
        sta     PPUDATA
        .endrepeat
@next:  inx
        cpx     #$14
        bpl     @done
        dec     tmp1
        beq     @RTS
        jmp     @row
@done:  ldx     #$20
@RTS:   rts

tp_columns:
        .byte   TP_P1_COLUMN, TP_P2_COLUMN
tp_rowsHi:
        .repeat 20, i
        .byte   >($20C6 + 32 * i)
        .endrepeat
tp_rowsLo:
        .repeat 20, i
        .byte   <($20C6 + 32 * i)
        .endrepeat

; Both players' levels and their colours, or, on another frame, both
; scores: the two together do not fit in a vblank with the rows. From
; render_mode_play_and_demo, in place of its one player's.
tp_renderLevelAndScore:
        lda     outOfDateRenderFlags
        eor     #RENDER_LEVEL
        and     #RENDER_LEVEL + RENDER_SCORE
        bne     @score                  ; not the level, or the score first
        lda     #>TP_P1_LEVEL
        sta     PPUADDR
        lda     #<TP_P1_LEVEL
        sta     PPUADDR
        ldx     player1_levelNumber
        lda     levelDisplayTable,x
        jsr     twoDigsToPPU
        lda     #>TP_P2_LEVEL
        sta     PPUADDR
        lda     #<TP_P2_LEVEL
        sta     PPUADDR
        ldx     player2_levelNumber
        lda     levelDisplayTable,x
        jsr     twoDigsToPPU
        lda     player1_levelNumber
        ldy     #$08                    ; player 1's colours: the third palettes
        jsr     tp_paletteForLevel
        lda     player2_levelNumber
        ldy     #$04                    ; player 2's: the second
        jsr     tp_paletteForLevel
        lda     outOfDateRenderFlags
        and     #<~RENDER_LEVEL
        sta     outOfDateRenderFlags
        rts
@score: lda     outOfDateRenderFlags
        and     #RENDER_SCORE
        beq     @RTS
        lda     #>TP_P1_SCORE
        sta     PPUADDR
        lda     #<TP_P1_SCORE
        sta     PPUADDR
        lda     player1_score+2
        jsr     twoDigsToPPU
        lda     player1_score+1
        jsr     twoDigsToPPU
        lda     player1_score
        jsr     twoDigsToPPU
        lda     #>TP_P2_SCORE
        sta     PPUADDR
        lda     #<TP_P2_SCORE
        sta     PPUADDR
        lda     player2_score+2
        jsr     twoDigsToPPU
        lda     player2_score+1
        jsr     twoDigsToPPU
        lda     player2_score
        jsr     twoDigsToPPU
        lda     outOfDateRenderFlags
        and     #<~RENDER_SCORE
        sta     outOfDateRenderFlags
@RTS:   rts

; The colours of level A, as updatePaletteForLevel sets them, into the
; background's and the sprites' palette at $3F00 + Y.
tp_paletteForLevel:
        sec
@mod10: sbc     #$0A
        bcs     @mod10
        adc     #$0A
        asl     a
        asl     a
        tax
@palette:
        lda     #$3F
        sta     PPUADDR
        sty     PPUADDR
        lda     colorTable,x
        sta     PPUDATA
        lda     colorTable+1,x
        sta     PPUDATA
        lda     colorTable+2,x
        sta     PPUDATA
        lda     colorTable+3,x
        sta     PPUDATA
        tya
        clc
        adc     #$10
        tay
        cmp     #$20
        bmi     @palette
        rts



; --- the sprites ----------------------------------------------------------------

; Player 2's state saved, and their pieces in their own colours. From
; gameModeState_updatePlayer2, in place of savePlayer2State.
tp_savePlayer2State:
        jsr     tp_lastSpritesToPlayer2
        jsr     savePlayer2State
        lda     displayNextPiece
        and     #$02
        bne     @flicker
        lda     #TP_P2_PREVIEW_X
        sta     spriteXOffset
        lda     #TP_P2_PREVIEW_Y
        sta     spriteYOffset
        ldx     twoPlayerPieceDelayPiece
        lda     orientationToSpriteTable,x
        sta     spriteIndexInOamContentLookup
        jsr     loadSpriteIntoOamStaging
        jsr     tp_lastSpritesToPlayer2
@flicker:
        ; Two sprites to the end, a different two each frame, so that where
        ; more than eight meet on a line all of them flicker.
        lda     frameCounter
        and     #$0F
        jsr     tp_spriteToEnd
        lda     frameCounter
        and     #$0F
        eor     #$08
        jmp     tp_spriteToEnd

; The last four sprites staged, from palette 2 to palette 1.
tp_lastSpritesToPlayer2:
        lda     oamStagingLength
        sec
        sbc     #4 * 4
        tax
@sprite:
        inx
        inx
        dec     oamStaging,x
        inx
        inx
        cpx     oamStagingLength
        bne     @sprite
        rts

; Staged sprite A to the end of what is staged.
tp_spriteToEnd:
        asl     a
        asl     a
        tax
        ldy     oamStagingLength
        lda     #$04
        sta     generalCounter
@byte:  lda     oamStaging,x
        sta     oamStaging,y
        lda     #$FF
        sta     oamStaging,x
        inx
        iny
        dec     generalCounter
        bne     @byte
        sty     oamStagingLength
        rts



; --- the title ------------------------------------------------------------------

; Where PUSH START was: 1 PLAYER and 2 PLAYERS, the one chosen between two
; arrows that flicker, as in the game's own menus. numberOfPlayers is the
; choice, which is 1 at power-on and 2 when a game for two has come back.
TP_TITLE_ARROW_Y    = $97       ; 1 PLAYER's row, 19, less the line a sprite is drawn down
TP_TITLE_LEFT_X     = $30       ; columns 6 and 18
TP_TITLE_RIGHT_X    = $90
TP_ARROW            = $27       ; the game type menu's

tp_titlePlayers:
        .byte   $22, $87, $40 | 10, $FF                         ; no PUSH START
        .byte   $22, $68, 8
        .byte   $01,$FF,$19,$15,$0A,$22,$0E,$1B                 ; 1 PLAYER
        .byte   $22, $A8, 9
        .byte   $02,$FF,$19,$15,$0A,$22,$0E,$1B,$1C             ; 2 PLAYERS
        .byte   $FF

; A frame of the title, with player 1's new buttons in A: Up, Down or
; Select to move between the two, and Start, which sets carry.
tp_titleMenu:
        cmp     #BUTTON_START
        beq     @start
        ldx     #$01
        cmp     #BUTTON_UP
        beq     @move
        inx
        cmp     #BUTTON_DOWN
        beq     @move
        cmp     #BUTTON_SELECT
        bne     @arrows
        lda     numberOfPlayers
        eor     #$03                    ; the other
        tax
@move:  cpx     numberOfPlayers
        beq     @arrows
        stx     numberOfPlayers
        lda     #$01
        sta     soundEffectSlot1Init
        lda     #$00
        sta     frameCounter+1          ; and the demo waits again
@arrows:
        lda     frameCounter
        and     #MENU_CURSOR_MASK
        beq     @done
        lda     #TP_TITLE_ARROW_Y
        ldx     numberOfPlayers
        cpx     #$02
        bne     @row
        lda     #TP_TITLE_ARROW_Y + 16
@row:   sta     oamStaging
        sta     oamStaging+4
        lda     #TP_ARROW
        sta     oamStaging+1
        sta     oamStaging+5
        lda     #$00
        sta     oamStaging+2
        lda     #$40                    ; the right one, turned round
        sta     oamStaging+6
        lda     #TP_TITLE_LEFT_X
        sta     oamStaging+3
        lda     #TP_TITLE_RIGHT_X
        sta     oamStaging+7
@done:  clc
        rts
@start: sec
        rts



; --- the menus ------------------------------------------------------------------

; Over the level menu's top line: whose level it is.
tp_bannerPlayer1:
        .byte   $20, $A4, 24
        .byte   $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        .byte   $19,$15,$0A,$22,$0E,$1B,$FF,$01         ; PLAYER 1
        .byte   $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        .byte   $FF
tp_bannerPlayer2:
        .byte   $20, $A4, 24
        .byte   $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        .byte   $19,$15,$0A,$22,$0E,$1B,$FF,$02         ; PLAYER 2
        .byte   $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        .byte   $FF

; Player 2 chooses a level, once player 1 has, with their own controller.
; From gameMode_levelMenu_processPlayer1Navigation, where player 1's Start
; would have started the game.
tp_levelMenuPlayer2:
        jsr     updateAudioWaitForNmiAndDisablePpuRendering
        jsr     disableNmi
        jsr     bulkCopyToPpu
        .addr   tp_bannerPlayer2
        jsr     waitForVBlankAndEnableNmi
        jsr     updateAudioWaitForNmiAndEnablePpuRendering
@loop:  lda     #$00
        sta     activePlayer
        lda     player2_startLevel
        sta     startLevel
        lda     player2_startHeight
        sta     startHeight
        lda     originalY
        sta     selectingLevelOrHeight
        lda     newlyPressedButtons_player2
        sta     newlyPressedButtons
        jsr     gameMode_levelMenu_handleLevelHeightNavigation
        lda     startLevel
        sta     player2_startLevel
        lda     startHeight
        sta     player2_startHeight
        lda     selectingLevelOrHeight
        sta     originalY
        lda     newlyPressedButtons_player2
        cmp     #BUTTON_START
        bne     @back
        lda     heldButtons_player2
        cmp     #BUTTON_A+BUTTON_START
        bne     @start
        lda     player2_startLevel
        clc
        adc     #$0A
        sta     player2_startLevel
@start: lda     #$00
        sta     gameModeState
        lda     #$02
        sta     soundEffectSlot1Init
        inc     gameMode
        rts
@back:  cmp     #BUTTON_B
        bne     @wait
        lda     #$02
        sta     soundEffectSlot1Init
        jsr     updateAudioWaitForNmiAndResetOamStaging
        jmp     gameMode_levelMenu      ; player 1 again
@wait:  jsr     updateAudioWaitForNmiAndResetOamStaging
        jmp     @loop



; --- the game -------------------------------------------------------------------

; A row of garbage is in: after TP_HOLE_ROWS of them the hole moves, to a
; column it was not in. Y is kept; X is not.
tp_garbageRowFilled:
        dec     garbageUntilResetHole
        bne     @RTS
        lda     #TP_HOLE_ROWS
        sta     garbageUntilResetHole
        tya
        pha
@hole:  ldx     #rng_seed
        ldy     #$02
        jsr     generateNextPseudorandomNumber
        lda     rng_seed
        and     #$0F
        cmp     #$0A
        bpl     @hole
        cmp     garbageHole
        beq     @hole
        sta     garbageHole
        pla
        tay
@RTS:   rts

; A player's curtain is down. With garbage the game is over for both: it
; waits for Start from either player, and the level menu comes next.
tp_curtainDown:
        lda     #$00
        sta     player1_playState
        sta     player2_playState
@wait:  jsr     updateAudioWaitForNmiAndResetOamStaging
        lda     newlyPressedButtons_player1
        ora     newlyPressedButtons_player2
        and     #BUTTON_START
        beq     @wait
        lda     #$00                    ; and the Start is not a pause
        sta     newlyPressedButtons_player1
        sta     newlyPressedButtons_player2
        rts

; Start from either player. Z clear if it was pressed.
tp_startPressed:
        lda     newlyPressedButtons_player1
        ora     newlyPressedButtons_player2
        and     #BUTTON_START
        rts

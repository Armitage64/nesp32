; The split: the header above, the article below.
;
; The NMI leaves the PPU at the top of nametable 1, the header. Sprite 0 is
; one pixel on the credit line (tools/gen_screen.py puts it there, in that
; line's own colour), and the PPU raises a flag in PPUSTATUS when it draws
; it. This waits for the flag, then for the hblank before the article's
; first scanline, and there points the PPU at the article's place in
; nametable 0.
;
; Only the last of the four writes changes what is drawn, and it must land
; in the hblank of scanline SPLIT_Y: after dot 256, where the PPU steps down
; a line, and before the next line's third tile is fetched (its first two
; columns are margin). That is 84 dots, 28 CPU cycles. The flag is seen up
; to 11 cycles after it rises (15 once in 256 looks), so SPLIT_DELAY aims
; the write at the middle of the window whichever look sees it.
; tests/test_split.py measures where it lands.
;
; Both waits are bounded. If the flag never clears or never rises (the
; sprite is hidden, rendering is off), this gives up within a frame and the
; article is not shown for that frame.

SPLIT_TRIES = 12                ; outer loops of 256 looks: more than a frame

.segment "ZEROPAGE"
ring_y: .res 1                  ; the article's scroll: 0-239 down nametable 0

.segment "RXTX"
.align 256

.proc split
    ldy #SPLIT_TRIES
    ldx #0
@clear:                         ; the last frame's hit stands until the
    bit PPUSTATUS               ; pre-render line
    bvc @hit
    dex
    bne @clear
    dey
    bne @clear
    rts
@hit:
    bit PPUSTATUS               ; the look
    bvs @found
    dex
    bne @hit                    ; 11 cycles a look
    dey
    bne @hit
    rts
@found:
    ; From the look to the last write: 5 * SPLIT_DELAY + 34 cycles.
    ldx #SPLIT_DELAY
@delay:
    dex
    bne @delay
    lda ring_y
    asl a
    asl a
    and #$E0                    ; coarse Y's low three bits, coarse X of 0
    tay
    lda ring_y
    stx PPUADDR                 ; nametable 0, and the latch to its second write
    sta PPUSCROLL               ; Y: fine and coarse
    stx PPUSCROLL               ; X: 0
    sty PPUADDR                 ; and the PPU takes all of it
    rts
.endproc
.assert >split = >(* - 1), error, "split crosses a page"

.segment "CODE"

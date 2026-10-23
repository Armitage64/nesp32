; Reading the controllers, from the PRG RAM: sub_FFC8's, which jumps here
; from its first bytes. The game calls it twice a frame and compares the
; two reads, against the sample channel's spoiling of one.
;
; The game's takes a button as bit 0 or bit 1 of a read (a Famicom's
; controller or one on its expansion port), a store, two shifts and an OR
; for each, in a loop: 45 cycles a button for both controllers. Here AND
; and CMP give the carry the same, in line: 28. The last button's reads
; are kept in ram_0004_t29 and ram_0005_t10, as the game's loop leaves
; them, and Y is 0. X is where the buttons go, as for the game's.

.macro fast_pad_bit last
    lda $4016
.if last
    sta ram_0004_t29
.endif
    and #$03
    cmp #$01                    ; the carry: either bit
    rol ram_0000_t32,x
    lda $4017
.if last
    sta ram_0005_t10
.endif
    and #$03
    cmp #$01
    rol ram_0000_t32 + $01,x
.endmacro

fast_read_pads:
    ldy #$01
    sty $4016
    dey
    sty $4016
.repeat 7
    fast_pad_bit 0
.endrep
    fast_pad_bit 1
    rts

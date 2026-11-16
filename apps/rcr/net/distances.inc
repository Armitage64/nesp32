; Netplay: the distances between objects, which the game works out at the
; start of each pass's objects ($DAA7, from bank 6's $8000), done in fewer
; cycles to the same bytes. It is in bank 6's 480 empty bytes at $BE1F
; (FREE_6_3E1F), which tools/convert.py has a place for this macro in: its
; only caller is bank 6, which is in when it runs.
;
; For each of the fighters 0-3 that is on ($48,x bit 7), and each other
; object 0-6 that is on, the game keeps the object's place less the
; fighter's, by $0405 + 7 * fighter + object: across ($83/$8C), at $0405;
; along ($9E/$A7), at $0421; up ($B9/$C2), at $043D; each held to -128..127
; ($80 and $7F where it is further); and at $0459 the two first's sizes
; added, $FF where they come to 256. Its scratch, $1A-$1E, nothing reads
; before writing it again.
;
; Two fighters' distances are each other's, less: the pair is worked out
; once and kept both ways. In -127..127 the other way is the same less;
; past it the one is $7F and the other $80 ($80 for -128 as for further,
; and $7F the other way: 128 is held to 127).

HAVE_FREE_6_3E1F = 1

DIST_ACROSS     = $0405
DIST_ALONG      = $0421
DIST_UP         = $043D
DIST_SIZE       = $0459

; Object Y's place less fighter X's on one axis, held, into fwd.
.macro NET_DIST_ONE lo, hi, fwd
    .local out, neg, past, done
    lda a:lo,y
    sec
    sbc lo,x
    sta fwd
    lda a:hi,y
    sbc hi,x
    bmi neg
    bne out
    lda fwd
    bpl done
out:
    lda #$7F
    bne done
neg:
    cmp #$FF
    bne past
    lda fwd
    bmi done
past:
    lda #$80
done:
    sta fwd
.endmacro

; The same into fwd, and fighter X's place less fighter Y's into back.
.macro NET_DIST_TWO lo, hi, fwd, back
    .local neg, near, far_down, far_up, far, done
    lda a:lo,y
    sec
    sbc lo,x
    sta fwd
    lda a:hi,y
    sbc hi,x
    bmi neg
    bne far_up
    lda fwd
    bpl near
far_up:
    lda #$7F
far:
    sta fwd
    eor #$FF                    ; $7F the one way, $80 the other
    sta back
    bne done
neg:
    cmp #$FF
    bne far_down
    lda fwd
    cmp #$81
    bcs near
far_down:
    lda #$80
    bne far
near:
    eor #$FF
    clc
    adc #$01
    sta back
done:
.endmacro

; The three into the tables at Y, and the first two's sizes added.
.macro NET_DIST_KEEP across, along, up
    .local plus, plus2, sum
    lda across
    sta DIST_ACROSS,y
    bpl plus
    eor #$FF
    clc
    adc #$01
plus:
    sta net_dist_size
    lda along
    sta DIST_ALONG,y
    bpl plus2
    eor #$FF
    clc
    adc #$01
plus2:
    clc
    adc net_dist_size
    bcc sum
    lda #$FF
sum:
    sta DIST_SIZE,y
    lda up
    sta DIST_UP,y
.endmacro

.macro FILL_FREE_6_3E1F
net_distances:
    ldx #$03
net_dist_fighter:
    lda $48,x
    bpl net_dist_next_fighter
    ldy #$06
net_dist_object:
    lda a:$0048,y
    bpl net_dist_next_object
    cpy #$04
    bcs net_dist_one_way
    stx $1A
    cpy $1A
    bcs net_dist_next_object    ; itself, or a pair done when Y was the fighter
    jmp net_dist_pair
net_dist_next_object:
    dey
    bpl net_dist_object
net_dist_next_fighter:
    dex
    bpl net_dist_fighter
    rts

net_dist_one_way:
    NET_DIST_ONE $83, $8C, $1C
    NET_DIST_ONE $9E, $A7, $1D
    NET_DIST_ONE $B9, $C2, $1E
    sty $1B
    tya
    clc
    adc net_dist_times7,x
    tay
    NET_DIST_KEEP $1C, $1D, $1E
    ldy $1B
    jmp net_dist_next_object

; Fighter X and the lower fighter Y, both ways.
net_dist_pair:
    NET_DIST_TWO $83, $8C, $1C, net_dist_back
    NET_DIST_TWO $9E, $A7, $1D, net_dist_back + 1
    NET_DIST_TWO $B9, $C2, $1E, net_dist_back + 2
    sty $1B
    txa
    clc
    adc net_dist_times7,y
    sta net_dist_other
    tya
    clc
    adc net_dist_times7,x
    tay
    NET_DIST_KEEP $1C, $1D, $1E
    ldy net_dist_other
    NET_DIST_KEEP net_dist_back, net_dist_back + 1, net_dist_back + 2
    ldy $1B
    jmp net_dist_next_object

net_dist_times7:
    .byte 0, 7, 14, 21
.endmacro

; Netplay: the numbers of a session, and the code both banks must have.
; Nothing here takes any room until a macro is used.

; A button press is used net_delay ticks after the frame it was read in.
; It is the time the press has to cross to the other console. Each console
; keeps its own, and changes it as its nesp32 advises (net/session.inc).
NET_DELAY       = 2             ; with no advice to begin with
NET_DELAY_MAX   = 5             ; the most the rings have room for
; A console's report to its nesp32, and the advice back, go with the
; exchange for one tick in 128: the one after this place in its buttons.
TUNE_AT         = $40
RING            = 8             ; ticks of buttons the console keeps, each way
PER_FRAME       = 2             ; ticks of buttons an exchange can carry
; Frames in a row with no tick before the console gives the session up.
SILENT_FRAMES   = 240
; One tick in 256 carries no buttons. In their place each console sends a
; digest of its game, and a console whose own differs from the other's
; gives the session up: the two are no longer playing the same game.
CHECK_TICK      = $FF
; The digest is taken at the start of this tick, on both consoles alike,
; and kept until each comes to send it: a few ticks later, by its delay.
CHECK_AT        = CHECK_TICK - 8
.assert NET_DELAY_MAX < CHECK_TICK - CHECK_AT, error
.assert NET_DELAY_MAX + PER_FRAME < RING, error

.assert RING & (RING - 1) = 0, error, "RING must be a power of two"

; Five writes: the MMC1 takes a register a bit at a time.
.macro net_mapper_write value, register
    LDA #value
    .repeat 4
    STA register
    LSR
    .endrepeat
    STA register
.endmacro

; The start of the reset code, and the jump between the banks. The same
; bytes at the same place in both banks (from FF00): at reset either bank
; may be the one at FF00, and in net_far the bank changes under the code.
; Both end in the game's bank at net_boot, or go through net_vector with
; A's bank in place (00 the game, 02 the menu).
.macro net_common
    CLD                         ; D8: the byte the INC below resets the mapper with
    SEI
    LDX #$00
    STX $2000
    STX $2001
    INC $FF00
    net_mapper_write $10, $9FFF ; control: 32 KB of PRG, 4 KB of CHR
    net_mapper_write $00, $FFF0 ; PRG: the game
    JMP net_boot
net_far:
    .repeat 4
    STA $FFF0
    LSR
    .endrepeat
    STA $FFF0
    JMP (net_vector)
.endmacro

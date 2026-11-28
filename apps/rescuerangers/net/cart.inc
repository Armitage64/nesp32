; Netplay: the cartridge, and what runs from the PRG RAM. rescuerangers.asm
; includes it when NETPLAY is defined, in the fixed bank, where SET_PRG's
; MMC1 writes were.
;
; The netplay ROM is on an MMC3 with 256 KB of PRG ROM and 8 KB of PRG RAM
; at $6000, where the game's own board is an MMC1 with 128 KB and none
; (net/rescuerangers_net.cfg). The game's 16 KB banks are the MMC3's 8 KB
; banks two by two, R6 at $8000 and R7 at $A000, and its fixed bank is the
; MMC3's last two, at $C000 and $E000, which the MMC3 keeps there in PRG
; mode 0. Banks 8 to 15 are new, between them in the file. The game's 4 KB
; CHR banks are the MMC3's: CHR bank 0 ($0000) is R0 and R1, of 2 KB, and
; CHR bank 1 ($1000) is R2 to R5, of 1 KB.
;
; The fixed bank has next to no room, so what has to be there whatever
; bank the game has in runs from the PRG RAM, which the reset copies from
; bank 9 before anything else (net_cart_start): the bank switches, the NMI's
; netplay, the controller read, the title's hooks, and net_call, which
; brings in bank 8, where the rest of the netplay is (net/net.asm).
;
; A write to an MMC3 register is two: $8000 picks the register, then $8001
; gives it its bank. An NMI between the two would leave the pick its own,
; and the rest of the switch would go to the NMI's register. So every
; pick is kept in net_select too, and the NMI keeps the one it found and
; puts it back, in net_select and in $8000, before it returns.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets, and the modes
MMC3_DATA       = $8001
MMC3_MIRRORING  = $A000         ; 0 vertical
MMC3_PRG_RAM    = $A001         ; $80 on and writable
MMC3_IRQ_OFF    = $E000

IMAGE_BANK      = 16            ; bank 9, the MMC3's 8 KB bank: where the image is
NET_IMAGE       = $8000         ; where it is in bank 9
NET_IMAGE_RUN   = $6000         ; and where it runs
.import __NETCODE_SIZE__
; The pages the reset copies: as many on the slow ROM (NET_SLOW, with no
; net/fast.inc) as on the netplay ROM, so that the two take as long to
; start the game, and tests/test_fast.py can hold them alike from power-on.
NET_IMAGE_PAGES = 10
.assert __NETCODE_SIZE__ <= NET_IMAGE_PAGES * $100, lderror, "NET_IMAGE_PAGES too few for the image"
.assert NET_IMAGE_RUN + NET_IMAGE_PAGES * $100 <= NET_RAM, lderror, "the image runs into net/net_ram.inc's memory"

; The reset vector. Until the first write to $8000 sets the MMC3's mode,
; $C000 may be any bank, but this is in the last 8 KB, which is always at
; $E000. The PRG RAM on, the mirroring vertical as the game's MMC1 has
; it, the scanline counter's IRQ off; then the image copied, from bank 9
; at $8000. The game's reset clears the console's RAM after, so its zero
; page is used for the copy. No session goes on past the reset button,
; and no menu; one asked for in net_boot is started (net_reset).
net_cart_start:
    sei
    cld
    ldx #$00
    stx MMC3_SELECT             ; PRG mode 0: the last two banks at $C000 and $E000
    stx MMC3_MIRRORING
    stx MMC3_IRQ_OFF
    lda #$80
    sta MMC3_PRG_RAM
    lda #$06
    sta MMC3_SELECT
    lda #IMAGE_BANK
    sta MMC3_DATA
    stx $00
    stx $02
    lda #>NET_IMAGE
    sta $01
    lda #>NET_IMAGE_RUN
    sta $03
    ldx #NET_IMAGE_PAGES
    ldy #$00

@copy:
    lda ($00),y
    sta ($02),y
    iny
    bne @copy
    inc $01
    inc $03
    dex
    bne @copy
    stx net_select              ; 0, as $8000 was given
    stx net_mode
    stx net_menu
    jmp RESET_MAIN
net_cart_end:
.assert <NET_IMAGE = 0 && <NET_IMAGE_RUN = 0, error, "net_cart_start copies whole pages"

.pushseg
.segment "NETCODE"

; --- the banks -----------------------------------------------------------------

; SET_PRG, once it has kept the bank: A, a bank of the game's from 0 to 6,
; at $8000. As the original, BANK_SWITCHING is set while the MMC3 is
; written, so that an NMI leaves the sound engine to this (SOUND_MISSED);
; then it runs it, with bank 3 in, and puts the bank wanted back. X and Y
; are kept, but for the sound engine's turn, as the original. A is 0.
net_set_prg:
    inc BANK_SWITCHING
    jsr net_prg
    lda #$00
    sta BANK_SWITCHING
    lda SOUND_MISSED
    bne @sound
    rts

@sound:
    lda #$03
    jsr net_prg

@queue:
    ldx SOUND_HEAD
    lda SOUND_QUEUE,x
    cmp #$88
    beq @run
    pha
    lda #$88
    sta SOUND_QUEUE,x
    inx
    txa
    and #$07
    sta SOUND_HEAD
    pla
    jsr SOUND_PLAY
    jmp @queue

@run:
    jsr SOUND_RUN
    lda #$00
    sta SOUND_MISSED
    lda PRG_BANK_WANTED
    jmp SET_PRG

; Bank A at $8000, as the game numbers its banks and the netplay's: R6 its
; first 8 KB, R7 its second. Banks 8 and up are a place earlier in the
; file than their number, for the game's fixed bank 7 is the last. X and Y
; kept; A is the second's number.
net_prg:
    asl a
    cmp #NET_BANK * 2
    bcc :+
    sbc #$02                    ; carry set
:
    pha
    lda #$06
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    ora #$01
    pha
    lda #$07
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    rts

; The game's 4 KB CHR bank A at $0000: R0 and R1, 2 KB each, numbered in
; 1 KB. X and Y kept.
net_chr0:
    asl a
    asl a
    pha
    lda #$00
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    ora #$02
    pha
    lda #$01
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
    rts

; The game's 4 KB CHR bank A at $1000: R2 to R5, 1 KB each. X and Y kept.
net_chr1:
    asl a
    asl a
.repeat 4, register
    pha
    lda #2 + register
    sta net_select
    sta MMC3_SELECT
    pla
    sta MMC3_DATA
  .if register < 3
    clc
    adc #$01
  .endif
.endrep
    rts

; Call routine X of the netplay's bank (net_entry, net/net.asm), with the
; bank in at $8000, and the game's own back after it. A, X, Y and the
; flags are not kept. From the NMI, or with the NMI off.
net_call:
    txa
    pha
    lda #NET_BANK
    jsr net_prg
    pla
    tax
    jsr NET_ENTRY
    lda PRG_BANK
    jmp net_prg

; --- the NMI -------------------------------------------------------------------

; The NMI vector. The pick in $8000 that the NMI broke in on is kept for
; net_nmi_leave. While the menu has the console the NMI is the menu's, and
; nothing of the game's runs. With no session it is the game's.
;
; In a session, an NMI that finds the game still at its work is a lag: it
; does nothing of the game, not even its writes to the PPU, whose lists
; the game may be filling, and runs the music alone (NMI_SOUND). The
; game's work in a frame depends on how many ticks there have been and on
; nothing else: where the frames fell is each console's own. The game is
; waiting when the NMI broke into SCHEDULE's look for a task to run
; ($FE90-$FEA5; the reset's own code runs before there is any task), and
; no task is ready, or running.
net_nmi:
    pha
    lda net_select
    sta net_select_nmi
    bit net_menu
    bmi @menu
    lda net_mode
    beq @game
    txa
    pha
    tsx                         ; X, A, the flags and the address the NMI returns to
    lda $0105,x
    cmp #>SCHEDULE
    bne @lag
    lda $0104,x
    cmp #<SCHEDULE
    bcc @lag
    cmp #<SCHEDULE_FOUND
    bcs @lag
    ldx #(TASK_COUNT - 1) * 4

@task:
    lda TASKS,x
    cmp #TASK_RUNNING
    bcs @lag
    dex
    dex
    dex
    dex
    bpl @task
    pla
    tax

@game:
    pla
    jmp NMI

@lag:
    inc net_lags
    pla
    tax
    pla
    php                         ; as NMI begins
    pha
    txa
    pha
    tya
    pha
    jmp NMI_SOUND

@menu:
    pla
    php
    pha
    txa
    pha
    tya
    pha
    ldx #NET_MENU
    jsr net_call
    jmp NMI_LEAVE

TASK_COUNT      = 4
TASK_RUNNING    = 2             ; and up: ready, or to start
SCHEDULE_FOUND  = SCHEDULE + $16    ; past the look: a task was found
.assert >SCHEDULE = >SCHEDULE_FOUND, error, "net_nmi looks at one page"

; The end of the game's NMI jumps here: the pick put back, and the game's
; return.
net_nmi_leave:
    lda net_select_nmi
    sta net_select
    sta MMC3_SELECT
    pla
    tay
    pla
    tax
    pla
    plp
    rti

; In the game's NMI, once the PPU has its writes (or with the picture off,
; none), in place of counting the frame and waking the tasks: in a session
; the exchange first, and with no buttons for the tick (a stall) the music
; alone, the tasks left asleep and the frame not counted.
net_nmi_tick:
    lda net_mode
    beq @tick
    ldx #NET_FRAME
    jsr net_call
    bit net_stalled
    bpl @tick
    jmp NMI_SOUND

@tick:
    inc FRAME_COUNT
    ldx #$FF
    jmp NMI_WAKE

; --- the controllers -----------------------------------------------------------

; CTRL_READ jumps here. In a session the tick's buttons (net_frame), player
; 1's and player 2's, go where the game's read would have put them; with
; none, the game's read, and OUT0 back to mark after it. The rest is the
; game's own (CTRL_EDGES).
net_ctrl_read:
    lda net_mode
    beq @read
    lda net_pads
    sta PAD_PRESSED
    lda net_pads+1
    sta PAD_PRESSED+1
    jmp CTRL_EDGES

@read:
    ldx #$01
    stx JOY1
    dex
    stx JOY1
    ldx #$08

@bit:
    lda JOY1
    lsr a
    rol PAD_PRESSED
    lsr a
    rol $00
    lda JOY2
    lsr a
    rol PAD_PRESSED+1
    lsr a
    rol $01
    dex
    bne @bit
    lda #OUT0_MARK
    sta JOY1
    lda $00
    ora PAD_PRESSED
    sta PAD_PRESSED
    lda $01
    ora PAD_PRESSED+1
    sta PAD_PRESSED+1
    jmp CTRL_EDGES

; --- the reset and the title ----------------------------------------------------

; In the reset, once the RAM is cleared and bank 6 is in, with the NMI
; off: the netplay's reset (net_reset).
net_reset_hook:
    ldx #NET_RESET
    jmp net_call

; Each frame of the title, in place of its look at Start (TITLE_LOOP). In a
; session that has just begun the title goes straight on to a game for
; two, as if Start had been pressed on 2 PLAYERS: Z clear, and TITLE_START
; takes the game for two.
net_title_frame:
    lda net_autostart
    beq @own
    lda #TITLE_2P
    sta TITLE_PLAYERS
    rts                         ; Z clear

@own:
    lda PAD_PRESSED
    and #BTN_START_
    rts

; Start at the title (TITLE_START). For one player, the game's own. For
; two with no session, the menu has the NMI from the next on, and the
; title sleeps until the menu is left for LOCAL GAME; then it goes on as
; the game's game for two, as it does in a session.
net_title_start:
    lda TITLE_PLAYERS
    bne :+
    jmp TITLE_1P
:
    lda #$00
    sta net_autostart
    lda net_mode
    bne @go
    lda #NET_MENU_FIRST
    sta net_menu

@wait:
    jsr TASK_YIELD
    bit net_menu
    bmi @wait

@go:
    jmp TITLE_GO

TITLE_2P        = $01           ; in TITLE_PLAYERS
BTN_START_      = $10
.popseg

.include "fast.inc"

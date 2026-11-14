; Netplay: a two-player game over two consoles, each with a nesp32 on
; controller port 2 and the nesp32s joined over the network. net/net.asm
; includes it. It is in the netplay's own bank (net/superbowl_net.cfg),
; which the fixed bank's hooks put in at $A000 for as long as they need it
; (net/cart.inc). It is Contra's (apps/contra/net/net.inc), whose game too
; runs all of its logic in its NMI, with Tecmo Super Bowl's tick.
;
; Both consoles run the whole game. What crosses the link is the buttons:
; one byte for each tick. A console takes a tick only when it holds both
; players' buttons for it, so the two games see the same buttons at the
; same tick and stay the same. Its own buttons are used net_delay ticks
; after they were read, which is the time they have to reach the other
; console. That delay is each console's own, and changes as its nesp32
; advises (nesp32's peer.c), from what the other console reports of how
; this one's buttons have been arriving.
;
; The game's logic is its tasks, which its NMI runs (UPDATE_ALL_TASKS):
; each wakes when its count of frames is out, runs, and sleeps again. The
; NMI reads the controllers and steps the random numbers before it runs
; them. Left alone, a task that runs past the next NMI is broken into by
; it: the controllers and the numbers change under it, and a task of more
; weight may be run in the middle of it. That depends on where the frame
; fell, which on two consoles in a session it does not do alike. So in a
; session an NMI is one of three things:
;
;   a lag     a task is still at work (or the scheduler is between two).
;             The NMI does what the game does when it finds the scheduler
;             busy: the scroll and the screen's splits, and no more. The
;             task goes on where it was.
;   a tick    every task is asleep, and both players' buttons for this
;             tick are here. The NMI is the game's, with the buttons
;             given it by the session (net_read).
;   a stall   every task is asleep, and the other console's buttons are
;             not here. The game's tasks are not run, and nor are the
;             controllers read or the numbers stepped.
;
; The NMI's writes to the PPU are the game's state too: the tasks wait for
; the buffer of writes to be empty, and a column of the field drawn in an
; NMI takes the place of the buffer's writes in it. So the PPU has them
; once between two ticks, at the first NMI after a tick that is not a lag,
; as it would with no stalls, and the NMIs of a stall after it write
; nothing but the sprites (net_owed). A tick's tasks always find the
; buffer as the last tick's NMI and one more left it.
;
; So the game's state depends on how many ticks there have been and on
; nothing else. The sound engine runs in every NMI that is not a lag, and
; keeps the frames' time: the game asks it for a sound, and the engine has
; always taken the ask by the next tick.
;
; The exchange with the nesp32 is made in the NMI after its writes to the
; PPU and the sound, where the game would read the controllers: PEER's
; TICKS as a short frame (nesp32's docs/PROTOCOL.md). The link is
; nesp32's library, whose cycle-timed serial routines nothing interrupts:
; the IRQ is held off for it.
;
; Ticks are counted from -NET_DELAY_MAX on both consoles, and the first
; byte of the stream that the nesp32s pass on is tick 0's. The ticks before
; it have no buttons.

.segment "NETCODE"

.define NESP_APP "TSBO"
NESP_APP_VERSION = 1

.pushseg
.include "nesp.inc"
.popseg

.assert PER_FRAME = NESP_PEER_PER_FRAME, error
.assert NET_DELAY_MAX = NESP_PEER_DELAY_MAX, error

; --- the save RAM ---------------------------------------------------------------

; The writes to the save RAM on, for the netplay's memory, having found
; whether the game had them on (net_probe): $A001 cannot be read. The game
; has the RAM itself on at all times but at its reset, before its NMI is.
net_sram_on:
    lda net_probe
    eor #$FF
    sta net_probe
    cmp net_probe
    bne @off
    eor #$FF                    ; they were on: the byte back as it was
    sta net_probe
    lda #MMC3_SRAM_WRITE
    sta net_a001                ; (written, now that they are)
    rts

@off:
    lda #MMC3_SRAM_WRITE
    sta MMC3_PRG_RAM
    lda #MMC3_SRAM_READ
    sta net_a001
    rts

; $A001 as net_sram_on found it.
net_sram_back:
    lda net_a001
    sta MMC3_PRG_RAM
    rts

; --- the reset ------------------------------------------------------------------

; From the game's reset, its RAM cleared and before its NMI is on, in place
; of its writes to PPUADDR there, which come at the end (net/cart.inc).
; OUT0 to mark, and into a session if net_start_session asked for one.
net_reset:
    lda #MMC3_SRAM_WRITE        ; the game has its save RAM off here
    sta MMC3_PRG_RAM
    lda #OUT0_MARK
    sta JOY1
    lda #$00
    sta net_mode
    sta net_menu
    sta nesp_fast               ; the link's rate, until a session asks for its own
    sta net_rate_ask
    sta net_rate_tries
    sta net_rate_misses
    lda net_boot
    cmp #NET_BOOT_MARK
    bne @exit
    lda net_boot+1
    eor net_boot+2
    eor #NET_BOOT_CHECK
    cmp net_boot+3
    bne @exit
    lda #$00
    sta net_boot
    lda net_boot+1
    sta net_role
    lda net_boot+2
    sta net_delay
    sta net_want
    ; The ticks before 0 have no buttons, and are as many on both consoles
    ; whatever the delay of each: a console begins to read when it comes
    ; to the tick that is its delay before 0.
    lda #<-NET_DELAY_MAX
    sta net_tick
    lda #$ff
    sta net_margin
    lda #$00
    sta net_read                ; tick 0's buttons are the first the stream has
    sta net_acked
    sta net_have
    sta net_silent
    sta net_late
    sta net_tune
    ldx #RING*2-1
:
    sta net_local,x
    dex
    bpl :-
    lda #$01
    sta net_owed                ; the PPU's first pass is the first NMI's
    sta net_rate_ask            ; the session's own rate, asked for in its first NMI
    lda #$80
    sta net_mode                ; last, when the rest is in place

@exit:
    lda #MMC3_SRAM_OFF          ; as the game left it
    sta MMC3_PRG_RAM
    ; The game's writes to PPUADDR that the hook took the place of.
    lda #$10
    tax
:
    sta NES_PPU_ADDR
    sta NES_PPU_ADDR
    eor #$10
    dex
    bne :-
    rts

; Start a session, as player 1 (A = 00) or player 2 (A = 01), with a delay
; of X ticks. Both consoles begin from the state of one just reset. Does
; not return.
net_start_session:
    sei
    pha
    lda #MMC3_SRAM_WRITE
    sta MMC3_PRG_RAM
    pla
    sta net_boot+1
    stx net_boot+2
    eor net_boot+2
    eor #NET_BOOT_CHECK
    sta net_boot+3
    lda #NET_BOOT_MARK
    sta net_boot

; The session is over: the other console is gone. Start again as a
; console that was reset.
net_drop:
    sei
    lda #$00
    sta NES_PPU_CTRL
    sta NES_PPU_MASK
    jmp (RESET_VECTOR)

; --- the title ------------------------------------------------------------------

; From the menu: LOCAL GAME, or B. The game starts again, as reset.
net_menu_local:
    jmp net_drop

; From the menu, in its own bank at $8000: an exchange. net_far_hello is
; nesp_hello; net_far_call is nesp_call for op X of PEER's, with Y bytes
; of payload. Carry set if no reply came.
net_far_hello:
    jmp nesp_hello

net_far_call:
    lda #NESP_SVC_PEER
    jmp nesp_call

; --- the NMI ---------------------------------------------------------------------

; An NMI with the menu up, or in a session (net_nmi_check, net/cart.inc),
; the game's TASK_BUSY_FLAG clear, A, X and Y saved.
net_nmi:
    bit net_menu
    bmi net_menu_nmi
    ; A lag unless the NMI came where the main thread waits with nothing
    ; to do: the scheduler's idle loop, where it looks for a task to run,
    ; or the reset's wait for a frame. (At the reset, before there are
    ; tasks, the main thread works with the NMI on.)
    tsx
    lda $0102,x                 ; the return address the NMI pushed
    ldy $0103,x
    cpy #>CHECK_TASKS
    bne @reset
    cmp #<CHECK_TASKS
    bcc @lag
    cmp #<UPDATE_CURRENT_TASK
    bcc @idle
@lag:
    ; As the game does when it finds the scheduler busy: the scroll and the
    ; screen's splits. And the game's banks back, from its shadows, as its
    ; NMI's end puts them: the task goes on where it was.
    lda #$00
    sta CUR_IRQ_INDEX
    ldy CURR_Y_SCROLL
    lda CURR_Y_SCROLL+1
    jsr UPDATE_IRQ_CHR_BANKS_SCROLL_LOC
    jmp RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS
@reset:
    cpy #>WAIT_NUM_FRAMES_RESET
    bne @lag
    cmp #<WAIT_NUM_FRAMES_RESET
    bcc @lag
    cmp #<(WAIT_NUM_FRAMES_RESET + 8)
    bcs @lag
@idle:
    .assert >CHECK_TASKS = >UPDATE_CURRENT_TASK, error
    .assert >WAIT_NUM_FRAMES_RESET = >(WAIT_NUM_FRAMES_RESET + 8), error
    ; And no task left to run: the idle loop may be on its way to one that
    ; has woken, or been made. (Its own test: RUNNING, WAITING or CREATED.)
    ldx #FIRST_TASK
:
    lda TASK_STATUS,x
    cmp #TASK_RUNNING
    bcs @lag
    txa
    clc
    adc #TASK_SIZE
    tax
    cpx #LAST_TASK_INDEX + TASK_SIZE
    bcc :-
    lda net_owed
    beq net_stalled             ; the PPU has had the last tick's writes
    lda #$00
    sta net_owed                ; it has them now
    jmp NMI_TASK_NOT_BUSY

; An NMI of a stall after the one that wrote to the PPU: the sprites, and
; the rest of the NMI from where the game's goes on after its writes to
; the PPU.
net_stalled:
    lda #<SPRITE_DMA_ADDR
    sta NES_OAM_ADDR
    lda #>SPRITE_DMA_ADDR
    sta NES_OAM_DMA
    lda SOFT_PPU_MASK
    sta NES_PPU_MASK
    lda NES_PPU_STATUS
    jmp UPDATE_BG_AND_SPR_BANKS

; The menu's NMI: its bank at $8000 too, and the game's handler does not
; run. The game's end of a busy NMI puts back the registers.
net_menu_nmi:
    lda SOFT_MODE_8000
    ora #$06
    sta MMC3_SELECT
    lda #MENU_BANK
    sta MMC3_DATA
    jsr menu_nmi
    jmp RETURN_FROM_NMI_TASK_BUSY

; --- the NMI's read -------------------------------------------------------------

; In place of the game's read of the controllers in its NMI
; (READ_JOYPAD_START), after its writes to the PPU and the sound. Carry
; clear: a tick, with CURR_JOY_RAW and CURR_JOY_PRESS as the game's read
; leaves them. Carry set: a stall, with no tick.
;
; With no session it is the game's read, and OUT0 back to mark after it:
; the game leaves it low, which the nesp32 would take for the start of a
; byte.
net_nmi_read:
    bit net_mode
    bmi @session
    jsr net_game_read
    lda #OUT0_MARK
    sta JOY1
    clc
    rts

@session:
    jsr net_sram_on
    ; The STACK_KEEP bytes below this one's place in the stack, kept: the
    ; first task's are among them.
    tsx
    ldy #$00
:
    lda $0100,x
    sta net_stack_copy,y
    dex
    iny
    cpy #STACK_KEEP
    bne :-
    ; And the game's LOCAL_1 to LOCAL_8, which the exchange works in: a task
    ; that starts finds them as the last one left them, and keeps them.
    ldx #$07
:
    lda LOCAL_1,x
    sta net_stack_copy+STACK_KEEP,x
    dex
    bpl :-
    jsr net_session
    lda #$00
    rol a
    sta net_carry               ; a tick or a stall, kept off the stack
    ldx #$07
:
    lda net_stack_copy+STACK_KEEP,x
    sta LOCAL_1,x
    dex
    bpl :-
    tsx
    ldy #$00
:
    lda net_stack_copy,y
    sta $0100,x
    dex
    iny
    cpy #STACK_KEEP
    bne :-
    jsr net_sram_back
    lda net_carry
    lsr a
    rts

; The game's read (READ_JOYPAD_START), as it is: each controller read until
; two reads in a row are alike, four times at the most, which a sample's
; fetch can spoil.
net_game_read:
    ldx #$02
    lda #TIMES_TO_CHECK_JOYPAD
    sta JOY_CHECK
@pad:
    lda CURR_JOY_RAW-1,x
@again:
    sta LAST_JOY
    lda #$01
    sta JOY1
    lda #$00
    sta JOY1
    ldy #NUM_BUTTONS_TO_READ
@bit:
    lda JOY1-1,x
    lsr
    rol TEMP_JOY_DATA
    and #$01
    ora TEMP_JOY_DATA
    sta TEMP_JOY_DATA
    dey
    bne @bit
    cmp LAST_JOY
    beq @alike
    dec JOY_CHECK
    bne @again
    jmp @next

@alike:
    lda CURR_JOY_RAW-1,x
    eor TEMP_JOY_DATA
    and TEMP_JOY_DATA
    sta CURR_JOY_PRESS-1,x
    lda TEMP_JOY_DATA
    sta CURR_JOY_RAW-1,x
@next:
    dex
    bne @pad
    jmp net_both

; JOY_RAW_BOTH and JOY_PRESS_BOTH, as the game's read leaves them.
net_both:
    lda JOY_RAW_1
    ora JOY_RAW_2
    sta JOY_RAW_BOTH
    lda JOY_PRESS_1
    ora JOY_PRESS_2
    sta JOY_PRESS_BOTH
    rts

; The session's part of the NMI's read: this console's controller for the
; tick net_delay from now, the exchange, and both players' buttons for
; this tick if they are here.
net_session:
    lda #OUT0_MARK
    sta JOY1
    lda net_rate_ask
    beq @ticks
    dec net_rate_ask
    bne @ticks
    jsr net_rate                ; in place of this NMI's exchange: a stall
    jmp net_stall

@ticks:
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    bne @exchange               ; read already: in an NMI that stalled, or a tick ago
    sec
    sbc net_acked
    cmp #RING-1
    bcs @exchange               ; no room until the nesp32 has taken some
    lda net_want
    cmp net_delay
    beq @read
    bcs @longer
    dec net_delay               ; a tick shorter: this tick's buttons went a tick ago,
    bne @exchange               ; and this read goes by

@longer:
    inc net_delay               ; a tick longer: the tick between has the buttons
    lda net_pad                 ; as they were last read
    jsr net_store

@read:
    jsr net_read_pad
    jsr net_store

@exchange:
    jsr net_exchange
    lda net_tick
    clc
    adc net_delay
    cmp net_read
    bne :+
    jmp net_stall               ; this console's own buttons are still to read: no room
:
    lda net_have
    cmp net_tick
    bne :+
    jmp net_late_stall          ; the other's are not here
:
    sec
    sbc net_tick                ; how many ticks of them are
    cmp net_margin
    bcs :+
    sta net_margin
:
    lda net_tick
    cmp #CHECK_AT
    bne :+
    jsr net_digest              ; for both consoles to send when they come to CHECK_TICK
    sta net_check
:
    lda net_tick
    and #RING-1
    tax
    lda net_tick
    cmp #CHECK_TICK
    bne @buttons
    ; A tick that carried the digests. If they are alike the game goes on
    ; with the buttons of the tick before, for both players.
    lda net_local,x
    cmp net_remote,x
    beq :+
    jmp net_drop
:
    dex
    txa
    and #RING-1
    tax

@buttons:
net_take:                       ; (a name for the tests: a tick taken)
    ; Player 1's and player 2's, each as the game's read leaves them: what
    ; is held, and what is held that was not at the last tick.
    lda net_local,x
    ldy net_role
    beq :+
    lda net_remote,x
:
    sta net_temp
    lda net_remote,x
    ldy net_role
    beq :+
    lda net_local,x
:
    sta net_temp+1
    ldx #$01
@player:
    lda net_temp,x
    eor CURR_JOY_RAW,x
    and net_temp,x
    sta CURR_JOY_PRESS,x
    lda net_temp,x
    sta CURR_JOY_RAW,x
    dex
    bpl @player
    jsr net_both
    inc net_tick
    lda #$00
    sta net_silent
    ; The scheduler's flag's low bits are what the idle loop has shifted out
    ; of it, one bit a time round: and the last is the carry a task wakes
    ; with (UPDATE_CURRENT_TASK's LSR). How many times round there were
    ; before this NMI is the frames' business, not the game's: so as many
    ; as empty it, as at the end of most frames alone. (Bit 7 is clear, in
    ; the idle loop.)
    sta TASK_BUSY_FLAG
    lda #$01
    sta net_owed                ; the PPU is to have this tick's writes
    clc
    rts

net_late_stall:
    inc net_late

net_stall:
    inc net_silent
    lda net_silent
    cmp #SILENT_FRAMES
    bcc :+
    jmp net_drop
:
    sec
    rts

; A into this console's buttons, for the next tick that has none: or, if
; that is the tick that carries the digest, the digest. One tick in 128 is
; the one whose exchange carries the report.
net_store:
    ldx net_read
    cpx #CHECK_TICK
    bne :+
    lda net_check
:
    pha
    txa
    and #RING-1
    tax
    pla
    sta net_local,x
    inc net_read
    lda net_read
    and #$7f
    cmp #TUNE_AT+1
    bne :+
    sta net_tune
:
    rts

; A digest of the game into A: of the zero page the game keeps, less the
; netplay's own ($3E-$45) and the sound engine's ($F0-$FF), which keeps the
; frames' time, and of the sprites. Both
; consoles work it out at the start of the same tick, CHECK_AT.
; Each byte goes in with A rotated, its bits round and not through the
; carry, and EORed: a step that loses nothing, so that one byte that
; differs always makes the digest differ.
DIGEST_FIRST    = LOCAL_8 + 1    ; past the netplay's own zero page
DIGEST_END      = $F0            ; the sound engine's from here on

net_digest:
    lda #$00
    ldx #DIGEST_FIRST
@zp:
    cmp #$80                    ; bit 7 into carry: a rotate of A alone
    rol a
    eor $00,x
    inx
    cpx #DIGEST_END
    bne @zp
    ldx #$00
@sprites:
    cmp #$80
    rol a
    eor SPRITE_DMA_ADDR,x
    inx
    bne @sprites
    rts

; This console's controller into A. While a sample plays it is read twice,
; and if a fetch spoiled one of the reads, it is as it was the last time
; both were alike. With none playing nothing spoils a read, and one does.
net_read_pad:
    jsr net_read_port
    sta net_temp
    lda APU_STATUS
    and #$10                    ; a sample has bytes still to fetch
    beq @once
    jsr net_read_port
    cmp net_temp
    beq @once
    lda net_pad
    rts

@once:
    lda net_temp
    sta net_pad
    rts

; Controller 1 into A. OUT0 is low for the reads and no longer: the nesp32
; takes it for a byte of noise. Port 2 is the line to the nesp32, and is
; not read.
net_read_port:
    ldx #$00
    stx JOY1
    ldy #$08
@bit:
    lda JOY1
    sta nesp_tx_data            ; (free outside an exchange)
    lsr
    ora nesp_tx_data
    lsr
    rol net_temp+1
    dey
    bne @bit
    ldx #OUT0_MARK
    stx JOY1
    lda net_temp+1
    rts

; A session's exchange: PEER's TICKS, as a short frame (nesp32's
; docs/PROTOCOL.md). Out: up to PER_FRAME ticks of this console's buttons,
; from the first the nesp32 has not said it holds, and the tick of the
; other console's that is wanted next, the two named by their low four
; bits in one byte. In: one tick of the other's, if it is there.
;
;   request   count, first tick and tick wanted, buttons (and buttons)
;   reply     count, buttons
;
; With net_tune set the request's count is NESP_PEER_TUNE: one tick of
; buttons and then this console's report, and the reply has the delay
; advised after its buttons. The IRQ is held off for it.
net_exchange:
    php
    sei
    jsr net_exchange_now
    plp
    rts

net_exchange_now:
    lda net_acked
    and #RING-1
    tax
    lda net_local,x
    sta nesp_tx+2
    inx
    txa
    and #RING-1
    tax
    lda net_local,x
    sta nesp_tx+3
    lda net_acked
    asl
    asl
    asl
    asl
    sta net_temp
    lda net_have
    and #$0f
    ora net_temp
    sta nesp_tx+1
    lda net_tune
    beq @plain
    ; The report, in place of a second tick of buttons: the delay, the
    ; NMIs that waited (7 at the most) and the fewest ticks held (3).
    lda #$00
    sta net_tune
    lda net_late
    cmp #$08
    bcc :+
    lda #$07
:
    asl
    asl
    sta net_temp
    lda net_margin
    cmp #$04
    bcc :+
    lda #$03
:
    ora net_temp
    sta net_temp
    lda net_delay
    asl
    asl
    asl
    asl
    asl
    ora net_temp
    sta nesp_tx+3
    ldx #$01                    ; one tick of buttons goes with it
    stx net_temp
    lda #NESP_PEER_TUNE
    ldy #$02
    jsr net_ask
    bcs @missed
    cmp #NESP_SHORT_NONE
    beq @drop
    pha
    lda #$00                    ; a new report begins
    sta net_late
    lda #$ff
    sta net_margin
    lda nesp_rx+4               ; the advice
    beq @acks
    cmp #NET_DELAY_MAX+1
    bcs @acks
    sta net_want
    bcc @acks

@plain:
    jsr net_unsent
    cmp #PER_FRAME+1
    bcc :+
    lda #PER_FRAME
:
    sta net_temp                ; how many ticks of buttons go
    ldy #$01
    jsr net_ask
    bcs @missed
    cmp #NESP_SHORT_NONE
    beq @drop                   ; the other console is gone, or the nesp32 was switched off and on
    pha                         ; whether one of the other's buttons came

@acks:
    lda #$00
    sta net_rate_misses
    lda net_acked               ; the nesp32 holds what it was sent
    clc
    adc net_temp
    sta net_acked
    pla
    beq @exit
    lda net_have
    sec
    sbc net_tick
    cmp #RING
    bcs @exit                   ; no room: it is asked for again
    lda net_have
    and #RING-1
    tax
    lda nesp_rx+3
    sta net_remote,x
    inc net_have

@exit:
    rts

@missed:
    jmp net_rate_missed

@drop:
    jmp net_drop

; A short request of count A, whose reply is to have Y bytes of data, and
; the same once more if no reply to it is heard: a sample's fetch takes
; cycles from the serial routines now and again, and a reply is misheard.
; Carry and A as nesp_short leaves them.
net_ask:
    pha
    jsr nesp_short
    bcc @heard
    pla
    ldy nesp_count              ; as it was asked
    jmp nesp_short

@heard:
    tax
    pla
    txa
    clc
    rts

; Ask the nesp32 for the session's line at its own rate, NESP_SHORT_PERIOD
; cycles a bit (PEER's RATE), at the link's rate. With its answer that it
; is at that rate, from its next request on, this console's exchanges are
; at it too. With any other answer, or none, the line stays the link's.
net_rate:
    php
    sei
    lda #$00
    sta net_rate_ask
    sta net_rate_misses
    inc net_rate_tries
    lda #NESP_SHORT_PERIOD
    sta nesp_request
    lda #NESP_SVC_PEER
    ldx #NESP_PEER_RATE
    ldy #$01
    jsr nesp_call
    bcs @exit
    cmp #NESP_ST_OK
    bne @exit
    lda nesp_reply_len
    cmp #$01
    bne @exit
    lda nesp_reply
    cmp #NESP_SHORT_PERIOD
    bne @exit
    lda #$80
    sta nesp_fast

@exit:
    plp
    rts

; An exchange at the session's own rate had no reply. Many in a row, and
; this console goes back to the link's rate, and asks again once the
; nesp32 will have, a few times a session at the most.
net_rate_missed:
    bit nesp_fast
    bpl @exit
    inc net_rate_misses
    lda net_rate_misses
    cmp #NET_RATE_MISSES
    bcc @exit
    lda #$00
    sta nesp_fast
    lda net_rate_tries
    cmp #NET_RATE_TRIES
    bcs @exit
    lda #NET_RATE_WAIT
    sta net_rate_ask

@exit:
    rts

; A = how many ticks of this console's buttons the nesp32 does not hold.
net_unsent:
    lda net_read
    sec
    sbc net_acked
    rts

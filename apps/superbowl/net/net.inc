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

; The very first of the game's reset (RESET_START), with this bank put in
; by it and the stack as the reset found it, but for the reset's 3 bytes
; and this call's 2: what the reset is to clear, kept (net_resets). On a
; real console, a session that stopped is told apart by it: a console
; that went to the title by no drop of the session's, or one that hung,
; and was then reset by its button, which keeps the RAM. Then the game's
; write to $A001, and its zero page counter for the clear of the RAM.
; OUT: X = $FF, for the stack; A, Y = 0.
net_reset_keep:
    lda #MMC3_SRAM_WRITE
    sta MMC3_PRG_RAM
    ldx #NET_KEEP - 1
:
    lda net_resets,x
    sta net_resets+NET_KEEP,x
    dex
    bpl :-
    tsx
    txa
    clc
    adc #5
    sta net_resets
    tax
    lda net_mode
    sta net_resets+1
    lda net_tick
    sta net_resets+2
    lda net_silent
    sta net_resets+3
    lda TASK_BUSY_FLAG
    sta net_resets+4
    lda net_nmi_busy
    sta net_resets+5
    lda SOFT_8000_BANK
    sta net_resets+6
    lda SOFT_A000_BANK
    sta net_resets+7
    .repeat 4, i
    lda $0101+i,x
    sta net_resets+8+i
    .endrepeat
    lda #MMC3_SRAM_OFF          ; the game's
    sta MMC3_PRG_RAM
    lda #$00
    sta $00
    sta $01
    tay
    ldx #$FF
    rts

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
    sta net_skip
    sta nesp_fast               ; the link's rate, until a session asks for its own
    sta net_rate_ask
    sta net_rate_tries
    sta net_rate_misses
    ; Past the intro, if the reset was the netplay's own. The mark is taken
    ; once: the console's Reset after it finds none.
    lda net_skip_mark
    eor #NET_SKIP_CHECK
    cmp net_skip_mark+1
    bne @no_skip
    lda net_skip_mark
    cmp #NET_SKIP_MENU + 1
    bcs @no_skip
    sta net_skip
@no_skip:
    lda #$00
    sta net_skip_mark
    sta net_skip_mark+1
    lda net_boot
    cmp #NET_BOOT_MARK
    bne @no_boot
    lda net_boot+1
    eor net_boot+2
    eor #NET_BOOT_CHECK
    cmp net_boot+3
    beq :+
@no_boot:
    jmp @exit
:
    lda #$00
    sta net_boot
    sta net_why                 ; no session over, yet
    lda #NET_WHY_CHECK
    sta net_why+1
    lda #NET_SKIP_MENU          ; a session begins at the main menu: both
    sta net_skip                ; consoles have shown the intro and the title
    ; The save RAM's scratch the same on both, as the save is (net/menu.inc).
    lda #<SAVE_SCRATCH
    sta nesp_ptr
    lda #>SAVE_SCRATCH
    sta nesp_ptr+1
    lda #$00
    tay
:
    sta (nesp_ptr),y
    iny
    bne :-
    inc nesp_ptr+1
    ldx nesp_ptr+1
    cpx #>SAVE_START
    bcc :-
:
    sta (nesp_ptr),y
    iny
    cpy #<SAVE_START
    bcc :-
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

; The session is over, and why (NET_WHY_*), kept for the menu to show
; (net_why): a console that stops before it comes here keeps none, as a
; session's start clears it (net_reset).
net_drop_why:
    pha
    lda #MMC3_SRAM_WRITE
    sta MMC3_PRG_RAM
    pla
    sta net_why
    eor #NET_WHY_CHECK
    sta net_why+1
    lda net_tick
    sta net_why+2

; The session is over: the other console is gone. Start again as a
; console that was reset, at the title (net_skip_mark): or at the main
; menu, for net_start_session.
net_drop:
    sei
    lda #MMC3_SRAM_WRITE
    sta MMC3_PRG_RAM
    lda #NET_SKIP_TITLE
    sta net_skip_mark
    eor #NET_SKIP_CHECK
    sta net_skip_mark+1
    lda #$00
    sta NES_PPU_CTRL
    sta NES_PPU_MASK
    jmp (RESET_VECTOR)

; --- the title ------------------------------------------------------------------

; From the menu: B. The game starts again, at the title.
net_menu_local:
    jmp net_drop

; --- the NMI ---------------------------------------------------------------------

; An NMI with the menu up, or in a session (net_nmi_check, net/cart.inc),
; the game's TASK_BUSY_FLAG clear, A, X and Y saved.
net_nmi:
    bit net_menu
    bpl :+
    jmp net_menu_nmi
:
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
    ; screen's splits. And the music, as the game's NMI does when a task is
    ; at work and not in the scheduler, which is most of the time: in every
    ; NMI, or it slows down by the lags. Then the game's banks back, from
    ; its shadows, as its NMI's end puts them: the task goes on where it was.
    lda #$00
    sta CUR_IRQ_INDEX
    ldy CURR_Y_SCROLL
    lda CURR_Y_SCROLL+1
    jsr UPDATE_IRQ_CHR_BANKS_SCROLL_LOC
    ; But not while a sound waits to be taken: the sound engine takes it
    ; (SOUND_ID_TO_PLAY to 0, or the song after an interception into it),
    ; and the game's tasks look (PLAY_SOUND waits a tick until it is
    ; taken). A lag comes in the middle of a tick, where it will on one
    ; console and not the other, and the games went apart. Taken only in a
    ; tick's NMI or a stall's, as before the lags had music, it is taken
    ; between ticks on both. With neither, the engine changes neither.
    lda SOUND_ID_TO_PLAY
    ora ON_FIELD_SONG_TO_PLAY_AFTER_INT
    beq :+
    jmp net_lag_waits
:
    lda SOFT_BANK_SELECT
    sta NMI_BANK_SELECT
    lda SOFT_MODE_8000
    ora #$06
    sta MMC3_SELECT
    lda #SOUND_BANK
    sta MMC3_DATA
    jmp net_lag_sound           ; from the fixed bank: the engine changes the bank at $A000
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
    ; This NMI's own work, until the tasks or its RTI (net_read_hook): an
    ; NMI that comes in it gives the registers back and nothing else
    ; (net_nmi_check). It gives them from NMI_A, X and Y, where this one
    ; kept the idle loop's: so this one goes back to the loop's start,
    ; which needs none of them, and not to the middle.
    lda #$80
    sta net_nmi_busy
    tsx
    lda $0103,x
    cmp #>CHECK_TASKS
    bne @owed                   ; the reset's wait
    lda $0102,x
    cmp #<CHECK_TASKS
    bcc @owed
    cmp #<UPDATE_CURRENT_TASK
    bcs @owed
    lda #<CHECK_TASKS
    sta $0102,x
@owed:
    lda net_owed
    beq net_stalled             ; the PPU has had the last tick's writes
    lda #$00
    sta net_owed                ; it has them now
    jmp NMI_TASK_NOT_BUSY

; A lag's NMI with a sound waiting to be taken: no music (net_nmi), the
; netplay's bank out.
net_lag_waits:
    jmp RETURN_FROM_NMI_ENABLE_INT_RESTORE_BANKS

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
    ; As RETURN_FROM_NMI_TASK_BUSY, but with the NMI on again only once X
    ; and Y are back, and A kept on the stack: an NMI that comes before the
    ; RTI saves the right X and Y, and leaves this one's A alone
    ; (menu_nmi_on).
    lda SOFT_BANK_SELECT
    sta MMC3_SELECT
    ldy NMI_Y
    ldx NMI_X
    lda NMI_A
    pha
    lda menu_nmi_want
    beq @quiet
    lda NES_PPU_STATUS          ; a vblank begun while at work brings no NMI
    lda #MENU_PPUCTRL
    sta NES_PPU_CTRL
@quiet:
    pla
    rti

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
    ; Where this NMI found the console (net_crumb), for one that stops.
    tsx
    stx net_crumb
    lda net_tick
    sta net_crumb+1
    lda SOFT_8000_BANK
    sta net_crumb+2
    lda SOFT_A000_BANK
    sta net_crumb+3
    .repeat 8, i
    lda a:$0101+i,x
    sta net_crumb+4+i
    .endrepeat
    ; The STACK_KEEP bytes below this one's place in the stack, kept: the
    ; first task's are among them. Unrolled, as it is in every tick's NMI
    ; (a loop was some 700 cycles each way). a: keeps $0100-i,x absolute:
    ; zero page,x would wrap in page 0.
    tsx
    .repeat STACK_KEEP, i
    lda a:$0100-i,x
    sta net_stack_copy+i
    .endrepeat
    ; And the game's LOCAL_1 to LOCAL_8, which the exchange works in: a task
    ; that starts finds them as the last one left them, and keeps them.
    .repeat 8, i
    lda LOCAL_1+i
    sta net_stack_copy+STACK_KEEP+i
    .endrepeat
    jsr net_session
    lda #$00
    rol a
    sta net_carry               ; a tick or a stall, kept off the stack
    .repeat 8, i
    lda net_stack_copy+STACK_KEEP+i
    sta LOCAL_1+i
    .endrepeat
    tsx
    .repeat STACK_KEEP, i
    lda net_stack_copy+i
    sta a:$0100-i,x
    .endrepeat
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
    ; For both consoles to send when they come to CHECK_TICK. Some 5,000
    ; cycles: with the IRQ on, so as not to hold the screen's splits back
    ; (the digest leaves out what the IRQ writes).
    cli
    jsr net_digest
    sei
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
    lda #NET_WHY_DIFFERED
    jmp net_drop_why
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
    lda #NET_WHY_STOPPED
    jmp net_drop_why
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
; netplay's own ($3E-$45), the sound engine's ($F0-$FF), which keeps the
; frames' time, and the IRQ's ($49-$4A), which depend on how far down the
; screen it has got, and of the sprites. Both consoles work it out at the
; start of the same tick, CHECK_AT, with the IRQ on.
; Each byte goes in with A rotated, its bits round and not through the
; carry, and EORed: a step that loses nothing, so that one byte that
; differs always makes the digest differ.
DIGEST_FIRST    = LOCAL_8 + 1    ; past the netplay's own zero page
.assert IRQ_NAMETABLE = IRQ_Y_SCROLL + 1 && IRQ_Y_SCROLL > DIGEST_FIRST, error
DIGEST_END      = $F0            ; the sound engine's from here on

net_digest:
    lda #$00
    ldx #DIGEST_FIRST
@zp:
    cpx #IRQ_Y_SCROLL
    bne :+
    ldx #IRQ_NAMETABLE + 1      ; the IRQ's own, which it writes at each split
:
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
    lda #NET_WHY_LEFT
    jmp net_drop_why

; A short request of count A, whose reply is to have Y bytes of data, and
; the same once more if no reply to it is heard: a sample's fetch takes
; cycles from the serial routines now and again, and a reply is misheard.
; Once more only if it is over before the screen's next split: the two hold
; the IRQ off for some 6,500 cycles from the vblank's, and the first split
; is at line 32 in most of play (some 6,000 cycles). If not, it is asked
; again at the next NMI, as when the second is misheard too.
; Carry and A as nesp_short leaves them.
; A split's IRQ comes some 2,250 + 114 * (line + 1) cycles from the
; vblank's. The exchange starts by 2,850 and takes up to 3,000; with a
; second, 8,850: line 58. Some to spare.
NET_ASK_AGAIN_LINE = 64

net_ask:
    pha
    jsr nesp_short
    bcc @heard
    ; Not asked again if none came in the time it waits (nesp_tries run
    ; out), only if one came misheard: a nesp32 that has not answered in
    ; 4.15 ms seldom does in the next, and the two waits made this NMI's
    ; own work some 22,700 cycles of the frame's 29,780.
    ldx nesp_tries
    beq @later
    ldx CUR_IRQ_INDEX
    inx
    beq @again                  ; $FF: no split left in this frame
    lda CURR_IRQ_COUNTER-6,x    ; the next split's line, as the NMI set it
    cmp #NET_ASK_AGAIN_LINE
    bcs @again
@later:
    pla
    sec                         ; not heard
    rts

@again:
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

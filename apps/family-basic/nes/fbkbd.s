; Family BASIC V3 with nesp32's Bluetooth keyboard in place of the
; Famicom's keyboard.
;
; The game is a 32 KB NROM, and full. This is the second 32 KB of an MMC1
; (mapper 1) that has the game, as it was but for a few bytes, in its
; first. `boot` copies the code below into $7000-$7FFF, the half of the
; cartridge's 8 KB of memory the game leaves alone, sets the MMC1 to give
; the game all of $8000-$FFFF, and starts the game.
;
; An MMC1 has its last 16 KB at $C000 at power-on, and there is `boot`.
; Not every board's does: one with its registers at 0 has the game's 32 KB,
; and the game's reset vector. So that, and the reset button, go to
; `reset_stub`, which is at the same place in the game's first 16 KB and
; in ours: it resets the MMC1, which puts the last 16 KB at $C000, and
; goes to `boot`.
;
; tools/build_rom.py makes the game call it, by these few bytes:
;
;   $FFFC         the game's reset vector: reset_stub
;   $B95E         reset_stub, in what was the rest of the game's scan
;   $80CD, $80D1  the NMI's address, which the game's reset puts in the
;                 jump at $00ED: fb_nmi, which runs the game's handler and
;                 then the link
;   $883A         the game's test for STOP while a program runs: fb_stop
;   $AD15         the game's reading of a controller: fb_pad, the same but
;                 for leaving OUT0 at mark
;   $B958         the game's scan of the keyboard's matrix: fb_scan, then
;                 the game's own reading of the matrix at $B9A1
;   $BF1F, $BF30  the game's writing of a header block and a data block to
;                 tape: fb_save_header and fb_save_data, which send them to
;                 the nesp32 (TAPE)
;   $9D9C         SAVE's jump to the second: fb_save_program, which says
;                 TP ERROR if it failed
;   $BE53         the game's reading of a header block: fb_find_program,
;                 which asks the nesp32 for the program LOAD names
;   $C56D         BG GRAPHIC's call of the same: fb_find_screen
;   $BE24, $BE1C  its reading of a data block, and its checking of one
;                 against memory (LOAD?): fb_load_data and fb_check_data
;
; Every exchange for the keyboard is made in the NMI, after the game's
; handler, so none is ever cut into by one. Those for SAVE and LOAD are made
; where the game's tape routines were, which turn the NMI off for as long
; as they take. The keys come from KBD KEYS as
; characters. Each is put into the matrix as the key that types it (with
; SHIFT if it is shifted) until the game has scanned it, then taken out
; until the game has scanned it gone, so that two of a letter are two
; presses.

JOY1            = $4016
JOY2            = $4017
OUT0_MARK       = $01

MMC1_CONTROL    = $8000
MMC1_CHR0       = $A000
MMC1_CHR1       = $C000
MMC1_PRG        = $E000
MMC1_RESET      = $80
MMC1_BOOT       = $0E           ; last 16 KB fixed at $C000, vertical mirroring
MMC1_GAME       = $02           ; 32 KB at a time, 8 KB of CHR, vertical mirroring
BASIC_RESET     = $80BA         ; the game's reset, which its vector pointed at

; The game's.
BASIC_NMI       = $8971         ; its NMI handler, which ends with an rti
MATRIX          = $0634         ; its keyboard's matrix: 9 rows, a bit a key, 1 down
ROWS            = 9
PAD_POINTER     = $19           ; and $1A: JOY1 or JOY2, for its controller reading
PAD_BITS        = $90           ; the buttons it read

; Keys in the matrix, as the game reads them (row, bit).
STOP_ROW        = 0
STOP_BIT        = $01
SHIFT_ROW       = 7             ; the left SHIFT, and CTR and GRPH
SHIFT_BIT       = $08
CTR_BIT         = $10
GRPH_BIT        = $04
FUNCTION_BIT    = 7             ; the keys in a row's bit 7 are F1 to F8 (and CLR HOME)

; A key is down until the game has scanned the matrix this many times and
; a frame has passed, and up until it has scanned it this many times again.
; The game takes a character key from one scan (a function key from five),
; and types it again only once it has seen it up. About four frames a
; character, which is 15 a second.
SCANS_DOWN      = 2
SCANS_FUNCTION  = 6             ; for a function key, which the game takes from five
SCANS_UP        = 2
FRAMES_DOWN     = 1             ; frames at the least, after the one it went down in
QUEUE           = 32            ; characters from KEYS not yet put in the matrix: a reply's,
                                ; each Delete two
HELLO_RETRY     = 60            ; frames after a hello with no answer
MISS_WAIT       = 30            ; frames after a KEYS with no answer
STOP_EVERY      = 7             ; mask: while only STOP is asked about, every 8th frame

; The game's data recorder, whose routines the nesp32's TAPE takes the place
; of. A header block is 128 bytes at $0500, and says where the data block
; after it goes in memory and how long it is.
TAPE_HEADER     = $0500
TAPE_TYPE       = TAPE_HEADER + NESP_TAPE_TYPE_AT
TAPE_LENGTH     = TAPE_HEADER + NESP_TAPE_LENGTH_AT
TYPE_PROGRAM    = 2
TYPE_SCREEN     = 3
WANTED          = $0580         ; the name LOAD asks for: 16 characters, spaces after it
NAMED           = $EA           ; not 0 if LOAD gave one
BLOCK_AT        = $AD           ; and $AE: where in memory the block is, as it goes
BLOCK_END       = $AF           ; and $B0: where it ends
SCREEN_PAGE     = $60           ; BG GRAPHIC's: the page of the screen saved or loaded,
SCREEN_FIRST    = $24           ; from this one, a pair each
BASIC_NMI_OFF   = $BE0E
BASIC_NMI_ON    = $BE14
BASIC_HEADER_BLOCK = $BDFD      ; BLOCK_AT and BLOCK_END for the header block,
BASIC_DATA_BLOCK = $BDE7        ; and for the data block, from the header
BASIC_ERROR     = $B237         ; the error A
ERROR_TP        = $11           ; TP ERROR: the tape
TAPE_FAILED     = 2             ; what the game's tape reading returns, with carry, when it fails
PIECE           = 120           ; bytes of a block in one PUT or GET
TAPE_TRIES      = 8             ; times a PUT or a GET is sent before it is given up
JOB_TRIES       = 8             ; and pages of 256 for a SAVE or a FIND: each a reply, or 4.15 ms

; The link's library (nesp32's nes/lib/nesp.inc).
NESP_RX_MASK    = $7F           ; a GET's reply is PIECE bytes
NESP_TX_MAX     = 2 + PIECE     ; and a PUT's request
NESP_TIMEOUT    = 1             ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY   = 1
NESP_OWN_MEMORY = 1
NESP_CRC_TABLE  = 1
.define NESP_APP "FBAS"
NESP_APP_VERSION = 1

; Zero page that the serial routines need, borrowed from the game for the
; length of the link's work in the NMI and given back as it was.
nesp_rx_data    = $F8
nesp_tx_data    = $F9
nesp_rx_end     = $FA
nesp_ptr        = $FB           ; and $FC
nesp_tries      = $FD
BORROWED        = $F8
BORROWED_LEN    = 6

.include "nesp.inc"

.segment "BSS"
nesp_seq:       .res 1
nesp_tx_len:    .res 1
nesp_count:     .res 1
nesp_index:     .res 1
nesp_crc_hi:    .res 1
nesp_crc_lo:    .res 1
nesp_status:    .res 1
nesp_attention: .res 1
nesp_rng:       .res 2          ; nesp_pattern's, which this does not use
nesp_rx:        .res NESP_RX_MASK + 1 + NESP_OVERHEAD
nesp_tx:        .res NESP_TX_MAX + NESP_OVERHEAD

fb_saved:       .res BORROWED_LEN
fb_matrix:      .res ROWS       ; what fb_scan gives the game
fb_changes:     .res 1          ; counts the NMI's changes to fb_matrix
fb_queue:       .res QUEUE
.assert QUEUE >= 2 * NESP_KBD_KEYS_MAX && (QUEUE & (QUEUE - 1)) = 0, error, "QUEUE holds a reply of Deletes, and is a power of two"
fb_head:        .res 1          ; the next character out of the queue
fb_count:       .res 1          ; how many are in it
fb_phase:       .res 1          ; PHASE_*
fb_with:        .res 1          ; CTR_BIT and GRPH_BIT, for the next key: KEY_WITH_CTRL and _ALT
fb_scans_down:  .res 1          ; scans the key down is held for
fb_scans:       .res 1          ; the game's scans since the phase began
fb_frames:      .res 1          ; and frames
fb_frame:       .res 1          ; frames since power-on
fb_hello:       .res 1          ; not 0 once the nesp32 has answered a hello
fb_wait:        .res 1          ; frames before the link is used again
fb_want_keys:   .res 1          ; the game has scanned the keyboard since the last KEYS
fb_want_stop:   .res 1          ; it has asked about STOP since then
fb_in_pad:      .res 1          ; it is reading a controller, with OUT0 low
fb_tape:        .res 1          ; not 0 if the nesp32 has TAPE
fb_job:         .res 1          ; the id of the last SAVE or FIND
fb_job_op:      .res 1          ; and its op,
fb_job_len:     .res 1          ; and its payload's length
fb_at:          .res 2          ; where in the pair the next piece is
fb_piece:       .res 1          ; bytes in it
fb_check:       .res 1          ; bit 7: a block read is checked against memory, not stored
fb_put_failed:  .res 1          ; not 0 if the last header block did not reach the nesp32
fb_tries:       .res 2

PHASE_IDLE      = 0
PHASE_DOWN      = 1
PHASE_UP        = 2

.include "keys.inc"

.import __COPY_START__, __RAMCODE_START__, __RAMCODE_SIZE__

; --- power-on ---------------------------------------------------------------

.macro mmc1_write register
    sta register
    .repeat 4
    lsr a
    sta register
    .endrepeat
.endmacro

.segment "BOOT"

.proc boot
    sei
    cld
    ldx #$FF
    txs
    lda #MMC1_RESET
    sta MMC1_CONTROL
    lda #MMC1_BOOT
    mmc1_write MMC1_CONTROL
    ; Each register's bit 4 clear before the cartridge's memory is used: on
    ; the PRG's an MMC1B's memory is on, and on the CHR's an SNROM board's
    ; (whose CHR lines turn it off), as a flash cartridge may be.
    lda #0
    mmc1_write MMC1_CHR0
    lda #0
    mmc1_write MMC1_CHR1
    lda #0
    mmc1_write MMC1_PRG
    ldy #0                      ; the copy, a page at a time, through $00-$03
    sty $00
    sty $02
    lda #>__COPY_START__
    sta $01
    lda #>__RAMCODE_START__
    sta $03
    ldx #>__RAMCODE_SIZE__
@page:
    lda ($00),y
    sta ($02),y
    iny
    bne @page
    inc $01
    inc $03
    dex
    bne @page
    jmp fb_start
.endproc

; The game's reset vector, and ours, at power-on with the MMC1's registers
; at 0 and at the reset button: the same bytes in the game's first 16 KB
; and in ours, so that whichever is at $8000 once the MMC1 is reset, this
; goes on to boot.
.segment "STUB"

.proc reset_stub
    sei
    lda #MMC1_RESET             ; the last 16 KB at $C000
    sta MMC1_CONTROL
    jmp boot
.endproc
.assert * - reset_stub <= 12, error, "reset_stub has 12 bytes of the game's"

.segment "BOOT"

; Never taken: the NMI is off until the game turns it on.
.proc boot_nmi
    rti
.endproc

.segment "VECTORS"
    .addr boot_nmi, boot, boot_nmi

; --- in $7000 from here -----------------------------------------------------

.segment "CODE"

; The game, from its own reset, with all of the PRG ROM it had.
.proc fb_start
    lda #MMC1_GAME
    mmc1_write MMC1_CONTROL
    lda #OUT0_MARK
    sta JOY1
    jmp BASIC_RESET
.endproc

; The NMI: the game's handler, and then the link. The game's ends with an
; rti, which comes back here.
.proc fb_nmi
    pha
    lda #>fb_after_basic
    pha
    lda #<fb_after_basic
    pha
    php
    jmp BASIC_NMI
.endproc

.proc fb_after_basic
    pla
    pha
    txa
    pha
    tya
    pha
    jsr fb_link
    jsr fb_present
    pla
    tay
    pla
    tax
    pla
    ; fall through
.endproc

.proc fb_nmi_done
    rti
.endproc

; The game's scan of its keyboard. X and Y are as the game's scan left
; them. An NMI that changes the matrix in the middle of the copy (a key and
; its SHIFT are in different rows) has it made again.
.proc fb_scan
@copy:
    lda fb_changes
    pha
    ldx #ROWS - 1
@row:
    lda fb_matrix,x
    sta MATRIX,x
    dex
    bpl @row
    pla
    cmp fb_changes
    bne @copy
    lda #1
    sta fb_want_keys
    ldx #ROWS
    ldy #0
    ; fall through
.endproc

.proc fb_scanned
    lda fb_scans
    cmp #$FF
    beq :+
    inc fb_scans
:   rts
.endproc

; The game's test for STOP: A and Z are 0 if it is down.
.proc fb_stop
    lda #1
    sta fb_want_stop
    jsr fb_scanned
    lda fb_matrix + STOP_ROW
    and #STOP_BIT
    eor #STOP_BIT               ; down: 0
    beq :+
    lda #$10                    ; what the game's own gave for up
:   rts
.endproc

; The game's reading of a controller, from where it has put JOY1 or JOY2's
; low byte in A, to the end, the same but for OUT0 at mark after.
.proc fb_pad
    sta PAD_POINTER
    lda #>JOY1
    sta PAD_POINTER + 1
    inc fb_in_pad
    lda #$05
    sta JOY1
    nop
    nop
    lda #$04
    sta JOY1
    nop
    nop
    ldx #8
    ldy #0
@bit:
    lda (PAD_POINTER),y
    lsr a
    rol PAD_BITS
    nop
    nop
    dex
    bne @bit
    lda #OUT0_MARK
    sta JOY1
    dec fb_in_pad
    rts
.endproc

; --- the link, once a frame -------------------------------------------------

.proc fb_link
    inc fb_frame
    lda fb_in_pad
    bne @done                   ; OUT0 is the controller's just now
    lda fb_wait
    beq @go
    dec fb_wait
@done:
    rts
@go:
    ldx #BORROWED_LEN - 1
@save:
    lda BORROWED,x
    sta fb_saved,x
    dex
    bpl @save
    lda #OUT0_MARK
    sta JOY1
    lda fb_hello
    bne @keys
    jsr fb_say_hello
    jmp @give_back
@keys:
    jsr fb_ask_keys
@give_back:
    ldx #BORROWED_LEN - 1
@restore:
    lda fb_saved,x
    sta BORROWED,x
    dex
    bpl @restore
    rts
.endproc

; A hello for KBD and TAPE. A firmware from before TAPE has the keyboard
; still, and SAVE and LOAD fail.
.proc fb_say_hello
    lda #NESP_SVC_KBD
    sta nesp_request + NESP_HELLO_FIXED
    lda #NESP_SVC_TAPE
    sta nesp_request + NESP_HELLO_FIXED + 1
    ldy #2
    jsr nesp_hello
    bcs @none
    ldx #1
    cmp #NESP_ST_OK
    beq @hello
    cmp #NESP_ST_NO_SERVICE
    bne @none
    lda nesp_reply + 6          ; how many it has not
    cmp #1
    bne @none
    lda nesp_reply + 7
    cmp #NESP_SVC_TAPE
    bne @none
    ldx #0
@hello:
    stx fb_tape
    lda #1
    sta fb_hello
    rts
@none:
    lda #HELLO_RETRY
    sta fb_wait
    rts
.endproc

; KEYS, when the game has asked about the keyboard and has had every key
; of the last reply. What is typed meanwhile waits on the nesp32, which
; keeps a key held down from repeating while anything waits: so a key's
; repeats come as fast as the game takes them, and stop when it is let go.
.proc fb_ask_keys
    lda fb_count
    bne @not_now
    lda fb_want_keys
    beq @stop_only
    lda fb_frame
    lsr a
    bcs @not_now                ; every other frame
    bcc @ask
@stop_only:
    lda fb_want_stop
    beq @not_now
    lda fb_frame
    and #STOP_EVERY
    bne @not_now
@ask:
    lda #0
    sta fb_want_keys
    sta fb_want_stop
    lda #NESP_SVC_KBD
    ldx #NESP_KBD_KEYS_ALL
    ldy #0
    jsr nesp_call
    bcs @missed
    cmp #NESP_ST_OK
    bne @again                  ; the nesp32 has forgotten the hello
    ldx #0
@char:
    cpx nesp_reply
    beq @not_now
    lda nesp_reply + 1,x
    cmp #NESP_KEY_DELETE
    bne @queue
    lda #NESP_KEY_RIGHT         ; the game's DEL takes the one before the cursor
    jsr fb_queue_char
    lda #NESP_KEY_BACKSPACE
@queue:
    jsr fb_queue_char
    inx
    bne @char
@again:
    lda #0
    sta fb_hello
@not_now:
    rts
@missed:
    lda #MISS_WAIT
    sta fb_wait
    rts
.endproc

; A into the queue. Preserves X.
.proc fb_queue_char
    pha
    lda fb_head
    clc
    adc fb_count
    and #QUEUE - 1
    tay
    pla
    sta fb_queue,y
    inc fb_count
    rts
.endproc

; --- the matrix -------------------------------------------------------------

; The key the game sees, a frame on.
.proc fb_present
    lda fb_frames
    cmp #$FF
    beq :+
    inc fb_frames
:   lda fb_phase
    cmp #PHASE_DOWN
    beq @down
    cmp #PHASE_UP
    beq @up
@idle:
    lda fb_count
    beq @done
    ldx fb_head
    lda fb_queue,x
    pha
    inx
    txa
    and #QUEUE - 1
    sta fb_head
    dec fb_count
    pla
    ldx #CTR_BIT
    cmp #NESP_KEY_WITH_CTRL
    beq @with
    ldx #GRPH_BIT
    cmp #NESP_KEY_WITH_ALT
    beq @with
    jsr fb_press
    bcs @idle                   ; no key types it
    lda #PHASE_DOWN
    bne @phase
@with:
    txa
    ora fb_with
    sta fb_with
    bne @idle
@down:
    lda fb_frames
    cmp #FRAMES_DOWN
    bcc @done
    lda fb_scans
    cmp fb_scans_down
    bcc @done
    ldx #ROWS - 1
    lda #0
@clear:
    sta fb_matrix,x
    dex
    bpl @clear
    lda #PHASE_UP
    bne @phase
@up:
    lda fb_scans
    cmp #SCANS_UP
    bcc @done
    lda #PHASE_IDLE
    sta fb_phase
    beq @idle                   ; and the next key at once
@phase:
    sta fb_phase
    inc fb_changes
    lda #0
    sta fb_scans
    sta fb_frames
@done:
    rts
.endproc

; The key for character A down in fb_matrix, and SHIFT with it if it is
; shifted, and CTR and GRPH if fb_with says so. Carry set if no key types
; it.
.proc fb_press
    cmp #$80
    bcs @none
    tax
    lda fb_keys,x
    cmp #KEY_NONE
    beq @none
    pha
    and #$07
    tax
    ldy #SCANS_DOWN
    cpx #FUNCTION_BIT
    bne :+
    ldy #SCANS_FUNCTION
:   sty fb_scans_down
    lda #$01
@bit:
    dex
    bmi @row
    asl a
    bne @bit
@row:
    sta nesp_count              ; free outside an exchange
    pla
    pha
    and #$7F
    lsr a
    lsr a
    lsr a
    tax
    lda fb_matrix,x
    ora nesp_count
    sta fb_matrix,x
    pla
    bpl @plain
    lda fb_matrix + SHIFT_ROW
    ora #SHIFT_BIT
    sta fb_matrix + SHIFT_ROW
@plain:
    lda fb_matrix + SHIFT_ROW
    ora fb_with
    sta fb_matrix + SHIFT_ROW
    lda #0
    sta fb_with
    clc
    rts
@none:
    lda #0
    sta fb_with
    sec
    rts
.endproc

; --- SAVE and LOAD ----------------------------------------------------------

; In place of the data recorder: each pair of blocks the game writes goes to
; the nesp32 in pieces (TAPE PUT) and is kept there as a file (SAVE), and
; LOAD finds one there (FIND) and has it back in pieces (GET). The game's
; own routines are left to do the rest, as they did with a tape: the
; messages, the checks of the type and the name, and what is done with a
; program once it is in memory.
;
; Each of these is where one of the game's routines was, and takes what it
; took and gives back what it gave: a read gives carry clear and A 0, or
; carry set and A TAPE_FAILED. The NMI is off from the start to the end,
; as it was, so the exchanges are made here, outside it, and the zero page
; the serial routines need is borrowed as the NMI's link borrows it.

; The game's writing of a header block, from $0500.
.proc fb_save_header
    jsr fb_tape_begin
    bcs @failed
    jsr BASIC_HEADER_BLOCK
    lda #0
    sta fb_at
    sta fb_at + 1
    jsr fb_put_block
@failed:
    lda #0
    rol a
    sta fb_put_failed
    jmp fb_tape_end
.endproc

; The game's writing of a data block: carry set if it was not kept. The
; first of a BG GRAPHIC's pairs starts its file, and each after it goes onto
; its end.
.proc fb_save_data
    jsr fb_tape_begin
    bcs @failed
    lda fb_put_failed
    bne @failed
    jsr BASIC_DATA_BLOCK
    lda #<NESP_TAPE_HEADER
    sta fb_at
    lda #>NESP_TAPE_HEADER
    sta fb_at + 1
    jsr fb_put_block
    bcs @failed
    jsr fb_pair
    sta nesp_request + 1
    lda TAPE_LENGTH
    sta nesp_request + 2
    lda TAPE_LENGTH + 1
    sta nesp_request + 3
    ldx #NESP_TAPE_SAVE
    ldy #4
    jsr fb_job_call
    bcs @failed
    cmp #NESP_DECK_DONE
    bne @failed
    clc
    bcc @end
@failed:
    sec
@end:
    php
    jsr fb_tape_end
    plp
    rts
.endproc

; SAVE's jump to the writing of its data block: TP ERROR if it failed,
; where the tape would have said nothing.
.proc fb_save_program
    jsr fb_save_data
    bcs @failed
    rts
@failed:
    lda #ERROR_TP
    jmp BASIC_ERROR
.endproc

; The game's reading of a header block into $0500, for LOAD: the program of
; the name it asked for, or with none the first the nesp32 has. Not found,
; and LOAD says TP ERROR, where the tape would have run on.
.proc fb_find_program
    lda #TYPE_PROGRAM
    ldx #0
    beq fb_find
.endproc

; And for BG GRAPHIC's LOAD, a pair of its screen at a time.
.proc fb_find_screen
    lda SCREEN_PAGE
    sec
    sbc #SCREEN_FIRST
    tax
    lda #TYPE_SCREEN
    ; fall through
.endproc

; A pair of type A, the X-th of its file.
.proc fb_find
    sta nesp_request + 1
    stx nesp_request + 2
    jsr fb_tape_begin
    bcs @failed
    ldy #3
    lda NAMED
    beq @ask
    ldx #NESP_TAPE_NAME - 1
@name:
    lda WANTED,x
    sta nesp_request + 3,x
    dex
    bpl @name
    ldy #3 + NESP_TAPE_NAME
@ask:
    ldx #NESP_TAPE_FIND
    jsr fb_job_call
    bcs @failed
    cmp #NESP_DECK_DONE
    bne @failed
    jsr BASIC_HEADER_BLOCK
    lda #0
    sta fb_at
    sta fb_at + 1
    sta fb_check
    jsr fb_get_block
    jmp fb_tape_read
@failed:
    sec
    jmp fb_tape_read
.endproc

; The game's reading of a data block into memory where the header says.
.proc fb_load_data
    lda #0
    beq fb_read_data
.endproc

; And its checking of one against memory, for LOAD?.
.proc fb_check_data
    lda #$80
    ; fall through
.endproc

.proc fb_read_data
    sta fb_check
    jsr fb_tape_begin
    bcs fb_tape_read
    jsr BASIC_DATA_BLOCK
    lda #<NESP_TAPE_HEADER
    sta fb_at
    lda #>NESP_TAPE_HEADER
    sta fb_at + 1
    jsr fb_get_block
    ; fall through
.endproc

; The end of a read: carry clear and A 0, or carry set and A TAPE_FAILED.
.proc fb_tape_read
    php
    jsr fb_tape_end
    plp
    lda #0
    bcc :+
    lda #TAPE_FAILED
:   rts
.endproc

; The NMI off, as the game's tape routines had it, and the zero page the
; link needs borrowed. Carry set if the nesp32 has no TAPE.
.proc fb_tape_begin
    jsr BASIC_NMI_OFF
    ldx #BORROWED_LEN - 1
@save:
    lda BORROWED,x
    sta fb_saved,x
    dex
    bpl @save
    lda #OUT0_MARK
    sta JOY1
    lda fb_hello
    beq @none
    lda fb_tape
    beq @none
    clc
    rts
@none:
    sec
    rts
.endproc

; And the zero page given back, and the NMI on again. Preserves carry.
.proc fb_tape_end
    ldx #BORROWED_LEN - 1
@restore:
    lda fb_saved,x
    sta BORROWED,x
    dex
    bpl @restore
    jmp BASIC_NMI_ON
.endproc

; Which of its file's pairs the one in $0500 is: a BG GRAPHIC screen's by
; its page, and a program's the only one.
.proc fb_pair
    lda TAPE_TYPE
    cmp #TYPE_SCREEN
    bne @first
    lda SCREEN_PAGE
    sec
    sbc #SCREEN_FIRST
    rts
@first:
    lda #0
    rts
.endproc

; The block from BLOCK_AT to BLOCK_END to the nesp32, from fb_at in the
; pair on. Carry set if it did not all get there.
.proc fb_put_block
@piece:
    jsr fb_next_piece
    beq @done
    lda fb_at
    sta nesp_request
    lda fb_at + 1
    sta nesp_request + 1
    ldx #0
@byte:
    ldy #0
    lda (BLOCK_AT),y
    sta nesp_request + 2,x
    jsr fb_step
    inx
    cpx fb_piece
    bne @byte
    inx
    inx
    txa
    tay
    ldx #NESP_TAPE_PUT
    jsr fb_tape_call
    bcs @failed
    cmp #NESP_ST_OK
    bne @failed
    jsr fb_piece_done
    jmp @piece
@done:
    clc
    rts
@failed:
    sec
    rts
.endproc

; The block from BLOCK_AT to BLOCK_END from the nesp32, from fb_at in the
; pair it found on: into memory, or checked against it if bit 7 of
; fb_check is set. Carry set if it did not all come, or was not the same.
.proc fb_get_block
@piece:
    jsr fb_next_piece
    beq @done
    lda fb_at
    sta nesp_request
    lda fb_at + 1
    sta nesp_request + 1
    lda fb_piece
    sta nesp_request + 2
    ldx #NESP_TAPE_GET
    ldy #3
    jsr fb_tape_call
    bcs @failed
    cmp #NESP_ST_OK
    bne @failed
    lda nesp_reply_len
    cmp fb_piece
    bne @failed                 ; the file is shorter than its header says
    ldx #0
@byte:
    ldy #0
    lda nesp_reply,x
    bit fb_check
    bmi @check
    sta (BLOCK_AT),y
    bpl @next
@check:
    cmp (BLOCK_AT),y
    bne @failed
@next:
    jsr fb_step
    inx
    cpx fb_piece
    bne @byte
    jsr fb_piece_done
    jmp @piece
@done:
    clc
    rts
@failed:
    sec
    rts
.endproc

; fb_piece: PIECE bytes, or what is left of the block if that is fewer.
; Z set if nothing is. Destroys X.
.proc fb_next_piece
    lda BLOCK_END
    sec
    sbc BLOCK_AT
    tax
    lda BLOCK_END + 1
    sbc BLOCK_AT + 1
    bne @whole
    txa
    cmp #PIECE
    bcc @last
@whole:
    lda #PIECE
@last:
    sta fb_piece
    tax                         ; Z for none
    rts
.endproc

.proc fb_piece_done
    lda fb_at
    clc
    adc fb_piece
    sta fb_at
    bcc :+
    inc fb_at + 1
:   rts
.endproc

; BLOCK_AT on a byte. Preserves X.
.proc fb_step
    inc BLOCK_AT
    bne :+
    inc BLOCK_AT + 1
:   rts
.endproc

; A TAPE request, op X with Y bytes of payload, sent again until it is
; answered, TAPE_TRIES times at the most: the nesp32 answers the same one
; again with the same reply, and does nothing twice. Carry clear and A =
; the status if a reply came.
.proc fb_tape_call
    lda #NESP_SVC_TAPE
    jsr nesp_call
    bcc @done
    lda #TAPE_TRIES
    sta fb_tries
@again:
    jsr nesp_again
    bcc @done
    dec fb_tries
    bne @again
@done:
    rts
.endproc

; A SAVE or a FIND, op X with Y bytes of payload after its id, asked again
; until it has ended: carry clear and A = how it ended (NESP_DECK_*), or
; carry set if the nesp32 said nothing of it. While the nesp32 writes or
; reads its flash, it answers nothing.
.proc fb_job_call
    inc fb_job
    lda fb_job
    sta nesp_request
    stx fb_job_op
    sty fb_job_len
    lda #0
    sta fb_tries
    lda #JOB_TRIES
    sta fb_tries + 1
@ask:
    lda #NESP_SVC_TAPE
    ldx fb_job_op
    ldy fb_job_len
    jsr nesp_call
    bcs @again
    cmp #NESP_ST_BUSY
    beq @again                  ; another job, ended and not yet said to be
    cmp #NESP_ST_OK
    bne @failed
    lda nesp_reply + 1
    cmp fb_job
    bne @again
    lda nesp_reply
    cmp #NESP_DECK_BUSY
    bne @ended
@again:
    dec fb_tries
    bne @ask
    dec fb_tries + 1
    bne @ask
@failed:
    sec
    rts
@ended:
    clc
    rts
.endproc

; Netplay: one exchange with the Stick. With the serial routines, in the
; space the game's unused samples had (net.inc has the rest).



; Send the frame in net_request (its first CHECKED bytes are set) and
; receive the reply into net_reply. Carry clear if a whole reply came and
; its check bytes are right.
net_exchange:
    LDX #<net_request
    JSR net_checks
    LDA net_check_lo
    STA net_request + CHECKED
    LDA net_check_hi
    STA net_request + CHECKED + 1
    LDX #$00
@send:
    LDA net_request,X
    JSR tx_byte                 ; keeps X
    INX
    CPX #FRAME_SIZE
    BNE @send
    LDA #RX_TRIES
    STA net_tries
    JSR rx_block
    BCS @RTS
    LDX #<net_reply
    JSR net_checks
    LDA net_check_lo
    CMP net_reply + CHECKED
    BNE @bad
    LDA net_check_hi
    CMP net_reply + CHECKED + 1
    BNE @bad
    CLC
    RTS
@bad:
    SEC
@RTS:
    RTS



; The check bytes of the frame at >net_request, X: a running sum of its
; first CHECKED bytes, and a running sum of that.
net_checks:
    LDA #$00
    STA net_check_lo
    STA net_check_hi
    LDY #CHECKED
@loop:
    LDA net_request & $FF00,X
    CLC
    ADC net_check_lo
    STA net_check_lo
    CLC
    ADC net_check_hi
    STA net_check_hi
    INX
    DEY
    BNE @loop
    RTS




.ifndef MENU_BANK
; To the menu, in its own bank. It comes back to net_menu_back, or starts a
; session and does not.
net_menu:
    LDA #$00
    STA $2000                   ; no NMI while the banks change
    LDA #<net_menu_back
    STA net_back
    LDA #>net_menu_back
    STA net_back + 1
    LDA #<net_start_session_y
    STA net_go
    LDA #>net_start_session_y
    STA net_go + 1
    LDA #<MENU_ENTRY
    STA net_vector
    LDA #>MENU_ENTRY
    STA net_vector + 1
    LDA #$02
    JMP net_far
net_menu_back:
    LDA ram_for_2000
    STA $2000
    RTS
.endif

.assert >net_request = >(net_reply + FRAME_SIZE - 1), error, "net_checks takes both frames from one page"

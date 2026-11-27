"""The netplay ROM's cartridge, an MMC3 (net/cart.inc): with no session,
it is the original game, tick for tick, on another board."""

from itertools import islice

import pytest

from drive import moves, play_ticks, title_script

GAME_TICKS = 6000


def test_the_same_game_as_the_original(console, net_console):
    """The same buttons, tick by tick from power-on through a level for
    two, make the same game on both ROMs, with the same CHR banks in. (The
    netplay ROM's reset copies its code first, so its ticks may fall in
    other frames: they are compared at each controller read.)

    But for FRAME_COUNT, which the NMI counts whether the game has done
    its frame or not: the MMC3's switches take longer than the MMC1's, and
    as the story's screen comes up the netplay ROM takes one more frame
    than the original, which leaves its count one ahead. Nothing seen so
    far reads it; a session will count it by the tick (README.md, "Not
    done")."""
    game = title_script(2) + list(islice(moves(3), GAME_TICKS))
    frame_count = 0x92

    def digest(nes):
        count = nes.ram[frame_count]
        nes.ram[frame_count] = 0
        state = nes.state()
        nes.ram[frame_count] = count
        return state, tuple(nes.chr_banks), nes.ram[0xF1]
    original, net = console(), net_console()
    assert play_ticks(original, game, digest) == play_ticks(net, game, digest)
    assert net.irq_enables == 0


def test_the_image_is_copied(net_console):
    """The reset puts net/cart.inc's code in the PRG RAM ($6000) as it is
    at the start of bank 8, and the game's reset comes after."""
    nes = net_console()
    nes.run(20)
    end = nes.labels["net_nmi_leave"] - 0x6000
    assert 0 < end < 0x1F00
    bank8 = 7 * 0x4000              # bank 8 is the file's eighth
    assert bytes(nes.bus.prg_ram[:end]) == nes.bus.prg[bank8:bank8 + end]
    assert nes.ram[0x80] != 0       # the game's reset has started task 0


DONE = 0x0FF0                       # a return address no code is at
CHR0_FROM_NMI, CHR1_FROM_NMI = 0x05, 0x16


@pytest.mark.parametrize("routine, value, nmi_chr", [
    ("SET_PRG", 5, (CHR0_FROM_NMI, CHR1_FROM_NMI)),
    ("SET_CHR0", 0x07, (None, CHR1_FROM_NMI)),
    ("SET_CHR1", 0x12, (CHR0_FROM_NMI, None)),
])
def test_an_nmi_that_breaks_into_a_switch_lets_it_finish(net_console, routine, value, nmi_chr):
    """A switch on the MMC3 is a register picked at $8000 and then its bank
    written to $8001, two or four times over, and the NMI, which switches
    CHR banks when asked and the PRG bank for the sound engine, may come
    between any two writes. Wherever it comes, the switch ends with the
    banks it was asked for, and the NMI's with its own."""
    nes = net_console()
    nes.run(300)                    # the title, with the NMI on
    labels = nes.labels
    mpu = nes.mpu
    ram = nes.ram
    sp = mpu.sp
    entry = labels[routine]
    prg_before = ram[labels["PRG_BANK"]]

    def begin():
        mpu.sp = sp
        nes.bus[0x100 + mpu.sp] = (DONE - 1) >> 8
        nes.bus[0x100 + mpu.sp - 1] = (DONE - 1) & 0xFF
        mpu.sp -= 2
        mpu.pc, mpu.a = entry, value
        ram[labels["PRG_BANK"]] = prg_before
        ram[labels["SOUND_MISSED"]] = 0
        ram[labels["BANK_SWITCHING"]] = 0

    def run_to_done():
        for _ in range(200000):
            if mpu.pc == DONE:
                return
            mpu.step()
        raise AssertionError("never returned")

    begin()
    starts = []
    while mpu.pc != DONE:
        starts.append(mpu.pc)
        mpu.step()
    want_prg = value if routine == "SET_PRG" else prg_before
    want_chr = list(nes.chr_banks)
    if routine == "SET_CHR0":
        want_chr[0] = value
    elif routine == "SET_CHR1":
        want_chr[1] = value
    for number, bank in enumerate(nmi_chr):
        if bank is not None:
            want_chr[number] = bank
    for start in starts:
        begin()
        while mpu.pc != start:
            mpu.step()
        for number, bank in enumerate(nmi_chr):
            if bank is not None:
                ram[labels["CHR%d_NEXT" % number]] = bank
        nes.nmi_depth += 1
        mpu.nmi()
        run_to_done()
        assert nes.banks[6:8] == [2 * want_prg, 2 * want_prg + 1], hex(start)
        assert nes.chr_banks == want_chr, hex(start)
        assert nes.banks[0:6] == [4 * want_chr[0], 4 * want_chr[0] + 2] + \
            [4 * want_chr[1] + k for k in range(4)], hex(start)

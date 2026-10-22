"""The game on the simulated console: that it runs, that the original is not
the same game on two consoles, and that the netplay ROM is."""

from itertools import islice

from console import FRAME_CYCLES
from drive import LEVEL_PLAYING, ROUTINE_LEVEL, moves, play, title_script

PLAY_TICKS = 1500


def game(seed, ticks=PLAY_TICKS):
    return title_script() + list(islice(moves(seed), ticks))


def first_difference(one, other):
    return next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]), None)


def test_reaches_a_two_player_game(console):
    nes = console()
    play(nes, game(1, 600))
    assert nes.byte("GAME_ROUTINE_INDEX") == ROUTINE_LEVEL
    assert nes.byte("LEVEL_ROUTINE_INDEX") == LEVEL_PLAYING
    assert nes.byte("PLAYER_MODE") == 1
    assert nes.samples > 0          # the music's drums are samples


def test_original_is_not_the_same_on_two_consoles(console):
    """The original stirs its random number in the idle loop, so a few
    cycles' difference in a frame makes another game. Here one console's
    samples take a cycle less from the CPU at each fetch."""
    one = play(console(stir_idle=True), game(1))
    other = play(console(stir_idle=True, dmc_steal=3), game(1))
    assert first_difference(one, other) is not None


def test_netplay_rom_is_the_same_on_two_consoles(net_console):
    """The netplay ROM's game hangs on the buttons alone: not on what the
    samples steal or when, nor on the length of the console's frames, which
    moves where each frame's work is cut by the next NMI."""
    one = play(net_console(), game(1))
    assert first_difference(one, play(net_console(dmc_steal=0), game(1))) is None
    assert first_difference(one, play(net_console(dmc_phase=200), game(1))) is None
    assert first_difference(
        one, play(net_console(frame_cycles=FRAME_CYCLES * 0.93), game(1))) is None


def test_other_buttons_other_game(net_console):
    assert play(net_console(), game(1))[-1] != play(net_console(), game(2))[-1]


def test_netplay_rom_starts_from_any_memory_with_the_nmi_left_on(net_console):
    """A cartridge that starts the game from a menu of its own may leave
    the NMI on and anything at all in memory. The reset turns the NMI off
    before the handler can act on what it finds there."""
    import random
    from drive import screen_text
    for seed in range(8):
        nes = net_console()
        rng = random.Random(seed)
        for address in range(len(nes.ram)):
            nes.ram[address] = rng.randrange(256) if seed else 0xFF
        nes.ctrl = 0x80
        nes.run(200)
        nes.run(3, pads=(0x10, 0))
        nes.run(60, pads=(0, 0))
        assert "PLAY SELECT" in screen_text(nes)
        assert nes.byte("net_menu") == 0 and nes.byte("net_mode") == 0


def test_netplay_rom_sets_up_its_mmc3_from_any_power_on(net_console):
    """The netplay ROM is on an MMC3 (net/cart.inc), whose registers are
    anything at power-on: $C000 may be any bank, and only $E000 on is the
    last. The reset vector sets the mode before it goes to the game's reset
    at $C000, lays the CHR banks over the CHR RAM in order, sets the
    mirroring vertical as the game's own board has it, turns the PRG RAM
    on, and copies netplay's code into it."""
    import random
    from drive import screen_text
    for seed in range(6):
        nes = net_console()
        rng = random.Random(seed)
        nes.bank_select = rng.randrange(256)
        nes.banks = [rng.randrange(256) for _ in range(8)]
        nes._map_mmc3()
        nes.bus.prg_ram[:] = bytes(rng.randrange(256) for _ in range(len(nes.bus.prg_ram)))
        nes.run(200)
        nes.run(3, pads=(0x10, 0))
        nes.run(60, pads=(0, 0))
        assert "PLAY SELECT" in screen_text(nes)
        assert nes.bank_select & 0xC0 == 0          # PRG mode 0, CHR mode 0
        assert nes.banks[:6] == [0, 2, 4, 5, 6, 7]
        assert nes.mirroring == 0 and nes.prg_ram_on
        image = nes.labels["NET_IMAGE"] + 7 * 0x4000 - 0x8000   # bank 8 is seventh in the file
        run = nes.labels["NET_IMAGE_RUN"]
        length = nes.labels["net_image_end"] - run
        copied = bytearray(nes.bus.prg_ram[:length])
        expected = bytearray(nes.prg[image:image + length])
        # The sprite pass writes into its own instructions (net/sprites.inc).
        for at in range(nes.labels["net_tiles_00"] - run, nes.labels["net_hide_order"] - run):
            copied[at] = expected[at] = 0
        assert copied == expected


def test_a_lag_frame_that_breaks_into_a_bank_switch_lets_it_finish(net_console):
    """On the MMC3 a switch is four writes (net/cart.inc), and a lag
    frame's NMI, which switches to bank 1 for the sound engine and back,
    can come between any two. Whichever it comes before, the switch ends
    with both halves of the bank it was asked for."""
    nes = net_console()
    nes.run(200)
    labels = nes.labels
    mpu = nes.mpu
    entry, done = labels["net_set_bank"], 0x0FF0     # a return address no code is at
    sp = mpu.sp

    def begin():
        """Bank 2 in, as the last switch left it, and a switch to bank 3 called."""
        nes.bank_select = 7
        nes.banks[6:8] = [4, 5]
        nes._map_mmc3()
        mpu.sp = sp
        nes.bus[0x100 + mpu.sp] = (done - 1) >> 8
        nes.bus[0x100 + mpu.sp - 1] = (done - 1) & 0xFF
        mpu.sp -= 2
        mpu.pc, mpu.y = entry, 3

    begin()
    starts = []
    while mpu.pc != done:
        starts.append(mpu.pc)
        mpu.step()
    assert nes.banks[6:8] == [6, 7]
    for start in starts:
        begin()
        while mpu.pc != start:
            mpu.step()
        nes.ram[labels["NMI_CHECK"]] = 1    # the NMI finds the game's work unfinished
        nes.nmi_depth = 2
        mpu.nmi()
        for _ in range(100000):
            if mpu.pc == done:
                break
            mpu.step()
        assert mpu.pc == done
        assert mpu.y == 3
        assert nes.banks[6:8] == [6, 7], "broken into at $%04X" % start
        assert nes.bus.bank == 3

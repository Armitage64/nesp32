"""The game on the simulated console: that it runs, that its game hangs on
the buttons alone, original and netplay ROM, and that the netplay ROM's
cartridge does what the game's did."""

import random
from itertools import islice

from console import FRAME_CYCLES, PAD_START
from drive import GAME_PLAYING, JEEPS_DOWN, local_script, moves, play, screen_text, title_script

PLAY_TICKS = 1500


def game(seed, ticks=PLAY_TICKS):
    return title_script() + list(islice(moves(seed), ticks))


def local_game(seed, ticks=PLAY_TICKS):
    """A game for two on the netplay ROM: by its menu's LOCAL GAME."""
    return local_script() + list(islice(moves(seed), ticks))


def one_player(seed, ticks=PLAY_TICKS):
    """A game for one, which goes the same way through the title on either
    ROM: either player's buttons drive the one jeep."""
    return title_script(two_players=False) + list(islice(moves(seed), ticks))


def first_difference(one, other):
    return next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]), None)


def test_reaches_a_two_player_game(console):
    nes = console()
    play(nes, game(1, 600))
    assert nes.byte("GameControlState") == GAME_PLAYING
    assert nes.byte("GamePlayMode") in JEEPS_DOWN
    assert nes.byte("Player2Active") == 1
    assert nes.samples > 0          # the music's drums are samples


def test_the_original_is_the_same_on_two_consoles(console):
    """Jackal's random number counts the frames of its game, not the
    picture's (subProcessGameControl), and a lag frame does nothing but the
    scroll and the sound: so even the original's game hangs on the buttons
    alone. Not on what the samples steal or when, nor on the length of the
    console's frames, which moves where each frame's work is cut by the
    next NMI, and how many frames a scene's load takes."""
    one = play(console(), game(1))
    assert first_difference(one, play(console(dmc_steal=0), game(1))) is None
    assert first_difference(
        one, play(console(frame_cycles=FRAME_CYCLES * 0.93), game(1))) is None


def test_netplay_rom_is_the_same_on_two_consoles(net_console):
    one = play(net_console(), local_game(1))
    assert first_difference(one, play(net_console(dmc_steal=0), local_game(1))) is None
    assert first_difference(one, play(net_console(dmc_phase=200), local_game(1))) is None
    assert first_difference(
        one, play(net_console(frame_cycles=FRAME_CYCLES * 0.93), local_game(1))) is None
    nes = net_console()
    play(nes, local_game(1, 600))
    assert nes.byte("GameControlState") == GAME_PLAYING
    assert nes.byte("Jeep1LifeCount") and nes.byte("Jeep2LifeCount")


def test_the_netplay_rom_with_no_session_is_the_original(console, net_console):
    """With no session the netplay ROM plays the original's game, tick for
    tick."""
    assert first_difference(play(console(), one_player(1)), play(net_console(), one_player(1))) is None


def test_other_buttons_other_game(net_console):
    assert play(net_console(), local_game(1))[-1] != play(net_console(), local_game(2))[-1]


def to_title_start(nes):
    """From power-on, through the title, and Start for one player."""
    nes.run(200)
    nes.run(3, pads=(PAD_START, 0))
    nes.run(3, pads=(0, 0))


def test_netplay_rom_starts_from_any_memory_with_the_nmi_left_on(net_console):
    """A cartridge that starts the game from a menu of its own may leave
    the NMI on and anything at all in memory and in the PRG RAM. The reset
    turns the NMI off before the handler can act on what it finds there."""
    for seed in range(6):
        nes = net_console()
        rng = random.Random(seed)
        for address in range(len(nes.ram)):
            nes.ram[address] = rng.randrange(256) if seed else 0xFF
        nes.bus.prg_ram[:] = bytes(rng.randrange(256) if seed else 0xFF
                                   for _ in range(len(nes.bus.prg_ram)))
        nes.ctrl = 0x80
        nes.run(200)
        assert "2 PLAYERS" in screen_text(nes)
        assert nes.byte("net_menu") == 0 and nes.byte("net_mode") == 0
        nes.run(3, pads=(PAD_START, 0))
        nes.run(300, pads=(0, 0))
        assert nes.byte("GameControlState") == GAME_PLAYING


def test_netplay_rom_sets_up_its_mmc3_from_any_power_on(net_console):
    """The netplay ROM is on an MMC3 (net/cart.inc), whose registers are
    anything at power-on: $C000 may be any bank, and only $E000 on is the
    last. The reset vector sets the mode before it goes to the game's reset
    at $C000, lays the CHR banks over the CHR RAM in order, sets the
    mirroring vertical as the game's own board has it, turns the PRG RAM
    on, and copies netplay's code into it."""
    for seed in range(6):
        nes = net_console()
        rng = random.Random(seed)
        nes.bank_select = rng.randrange(256)
        nes.banks = [rng.randrange(256) for _ in range(8)]
        nes._map_mmc3()
        nes.run(200)
        assert "2 PLAYERS" in screen_text(nes)
        assert nes.bank_select & 0xC0 == 0          # PRG mode 0, CHR mode 0
        assert nes.banks[:6] == [0, 2, 4, 5, 6, 7]
        assert nes.mirroring == 0 and nes.prg_ram_on
        labels = nes.labels
        run, end = labels["NET_IMAGE_RUN"], labels["NET_IMAGE_END"]
        image = 7 * 0x4000                          # bank 8 is seventh in the file
        # All but the serial routines' page, which a receive writes into,
        # and the hiding of the sprites' slots, which writes into its own
        # instructions (net/fast.inc).
        copied = bytearray(nes.bus.prg_ram[:end - run])
        expected = bytearray(nes.prg[image:image + end - run])
        for at in list(range(0x100)) + list(range(labels["net_sprites_hide"] - run,
                                                   labels["net_hide_run"] - run)):
            copied[at] = expected[at] = 0
        assert copied == expected


def test_a_lag_frame_that_breaks_into_a_bank_switch_lets_it_finish(net_console):
    """On the MMC3 a switch is four writes (net/cart.inc), and a lag
    frame's NMI, which switches to bank 0 for the sound engine and back,
    can come between any two. Whichever it comes before, the switch ends
    with both halves of the bank it was asked for: by Y, as subChangeBank
    asks, or by X, as subLoadNewPatternTable does."""
    nes = net_console()
    nes.run(200)
    labels = nes.labels
    mpu = nes.mpu
    done = 0x0FF0                                   # a return address no code is at
    sp = mpu.sp

    for entry, register in ((labels["net_set_bank"], "y"), (labels["net_set_bank_x"], "x")):
        def begin():
            """Bank 2 in, as the last switch left it, and a switch to bank 3 called."""
            nes.bank_select = 7
            nes.banks[6:8] = [4, 5]
            nes._map_mmc3()
            nes.ram[labels["CurrentBank"]] = 3
            mpu.sp = sp
            nes.bus[0x100 + mpu.sp] = (done - 1) >> 8
            nes.bus[0x100 + mpu.sp - 1] = (done - 1) & 0xFF
            mpu.sp -= 2
            mpu.pc = entry
            setattr(mpu, register, 3)

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
            nes.ram[labels["GameFrameLogicInProgress"]] = 1    # the NMI finds the game's work unfinished
            nes.ram[labels["SoundUpdateInProgress"]] = 0        # and runs the sound engine
            nes.nmi_depth = 2
            mpu.nmi()
            sound = False
            for _ in range(100000):
                if mpu.pc == done:
                    break
                sound |= mpu.pc == labels["subPlaySound_Music"] and nes.banks[6] == 0
                mpu.step()
            assert sound                                # in bank 0
            assert mpu.pc == done
            assert getattr(mpu, register) == 3
            assert nes.banks[6:8] == [6, 7], "broken into at $%04X" % start

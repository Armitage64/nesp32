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

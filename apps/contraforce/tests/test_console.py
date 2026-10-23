"""The simulation itself, on the original: that it plays the game as far as
the tests need it to."""

from drive import Player, playing


def test_the_menu_leads_to_a_game_for_one_and_for_two(console):
    for two_players in (False, True):
        nes = console()
        player = Player(nes, two_players)
        player.to_play()
        player.run(100)
        assert playing(nes)
        assert nes.ram[0x75] == 0                   # stage 1


def test_the_picture_is_split_by_the_scanline_irq(console):
    """In play the IRQ's handlers run every frame, at the lines the game
    asks for, and take their cycles: the status bar's split waits in a
    loop for the line's end."""
    nes = console()
    player = Player(nes, False)
    player.to_play()
    player.run(60)
    frames = nes.frames[-50:]
    assert all(frame.irq_cycles > 300 for frame in frames)


def test_a_tick_that_overruns_is_a_lag_frame(console):
    """Two players, running and shooting: the original overruns, and the
    NMI that breaks in is the game's short one, which reads no buttons."""
    nes = console()
    player = Player(nes, True, seed=7)
    player.to_play()
    player.run(300)
    frames = nes.frames[-400:]
    assert sum(frame.lag for frame in frames) > 100
    assert len(player.states) < len(nes.frames)

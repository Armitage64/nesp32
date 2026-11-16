"""Two consoles in a session play one game: the same at every tick, whatever
the network, the consoles' clocks, or the screens the game goes through."""

from drive import PAD_LEFT, PAD_RIGHT, moves, moves_with_pauses
from netplay import Table
from wire import ms


def rates(table):
    return [console.byte("nesp_fast") for console in table.consoles]


def test_a_session_plays_one_game(net_console):
    table = Table(net_console, delay=ms(10))
    table.start()
    table.to_game()
    table.play(3000, moves(1))
    ticks = table.same_game()
    print("ticks", ticks, "frames", table.frames(), "waits", table.waits(), table.waits(1),
          "delays", table.delays())
    assert ticks > 0.25 * table.frames()    # the game's 30 a second, less its own slowdown
    assert rates(table) == [0x80, 0x80]     # the session's line at its own rate


def test_the_pause_and_its_screens_in_a_session(net_console):
    """The pause's screens read the controllers with the NMI off: the
    exchange is made by the read itself (net_read_pads)."""
    table = Table(net_console, delay=ms(10))
    table.start()
    table.to_game()
    table.play(4000, moves_with_pauses(2, every=500))
    ticks = table.same_game()
    print("ticks", ticks, "frames", table.frames(), "waits", table.waits(), table.waits(1))
    # Less than in play: the pause's screens are loaded with no read for
    # tens of frames, and how often the buttons by the frame come back to
    # them is the game's: ticks were 28% of the frames, and 24% with
    # net_distances, which plays the same buttons into another game.
    assert ticks > 0.2 * table.frames()
    assert rates(table) == [0x80, 0x80]


def test_a_slow_network_and_a_fast_clock(net_console):
    """40 ms each way, and the second console's frames 0.5% short: the
    delay grows to cover it, and the game is the same."""
    table = Table(net_console, delay=ms(40), drift=-0.005)
    table.start(apart=0.7)
    table.to_game()
    table.play(3000, moves(3))
    ticks = table.same_game()
    print("ticks", ticks, "frames", table.frames(), "waits", table.waits(), table.waits(1),
          "delays", table.delays())
    assert ticks > 0.25 * table.frames()
    assert min(table.delays()) >= 2


CHECK_AT = 0xFF - 8              # net/net_ram.inc: the tick a digest is taken at


def test_games_that_differ_end_the_session(net_console):
    """A byte of the game changed on one console alone, as it takes the
    tick its digest is taken at: the digests differ, and both consoles give
    the session up within seconds."""
    table = Table(net_console, delay=ms(10))
    table.start()
    table.to_game()
    table.play(60, moves(4))
    tick = table.ticks(0)
    at = tick + (CHECK_AT - tick) % 256

    def differ(console):
        console.ram[0x0300] ^= 0x01
    table.at_tick(at, differ, sides=(1,))
    while table.consoles[0].byte("net_mode") and table.ticks(0) < at + 16:
        table.play(10, moves(4))
    table.run(300)
    assert all(console.byte("net_mode") == 0 for console in table.consoles)


HELD = 0xF0                     # player 1's buttons as the game holds them


def test_a_press_is_read_late_in_the_pass(net_console):
    """On a network like a home's (2.5 ms each way, a delay of 1), this
    console's controller is read for the next tick in the NMI before the
    pass ends (net_read_late), not at the top of the pass: a press made at
    a moment chosen at random is read by the game a frame or so later than
    alone (2.2 frames), where at the top of the pass it took 5.1."""
    table = Table(net_console, delay=ms(2.5))
    table.start()
    table.to_game()
    table.run(200)
    ram = table.consoles[0].ram
    took = []
    for trial in range(8):
        table.run(60 + trial)               # standing still, a new phase each time
        for frame in range(40):
            table.run(1, (PAD_RIGHT, 0))
            if ram[HELD] & PAD_RIGHT:
                took.append(frame + 1)
                break
        table.run(30, (PAD_LEFT, 0))
        table.run(30)
    print("frames from a press to the game's read", took)
    assert len(took) == 8
    assert sum(took) / len(took) < 3.6
    assert table.delays() == (1, 1)
    table.same_game()

"""Two consoles in a session play one game: the same at every tick, whatever
the network, the consoles' clocks, or the screens the game goes through."""

from drive import moves, moves_with_pauses
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
    assert ticks > 0.25 * table.frames()
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

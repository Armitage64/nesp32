"""The original game on the simulated console: that it runs to a game for
two, and that two consoles given the same buttons a tick at a time play
the same game."""

from itertools import islice

from console import FRAME_CYCLES
from drive import TITLE_2P_START, moves, play, play_ticks, title_script

PLAY_TICKS = 600


def game(seed, ticks=PLAY_TICKS, choice=TITLE_2P_START):
    return title_script(choice) + list(islice(moves(seed), ticks))


def first_difference(one, other):
    return next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]), None)


def test_reaches_a_two_player_game(console):
    nes = console()
    play(nes, game(1, 60))
    assert nes.byte("ROUND") == 1
    assert nes.byte("P1_LIVES") > 0 and nes.byte("P2_LIVES") > 0


def test_the_idle_count_is_up_long_before_the_title(console):
    """The main loop counts IDLE_COUNT up to $FF from the reset, and the
    game reads it as it plays: it is $FF from the first frames on."""
    nes = console()
    seen = []
    nes.on_vblank = lambda nes: seen.append(nes.byte("IDLE_COUNT"))
    play(nes, game(1, 60))
    assert seen[10:] == [0xFF] * len(seen[10:])


def test_the_game_is_the_buttons_alone_but_for_the_idle_count(console):
    """Two consoles given the same buttons a tick at a time play the same
    game, whatever their clocks: every byte of the RAM but the sound
    engine's, the flicker's and the stack's is alike at every tick, but at
    the first. There IDLE_COUNT is as far as the main loop got between the
    reset and the first NMI, which is a matter of cycles (the netplay ROM
    has it $FF from the reset)."""
    ticks = game(3, 1500)
    one = play_ticks(console(), ticks)
    for frame_cycles in (FRAME_CYCLES * 0.8, FRAME_CYCLES * 1.03):
        other = play_ticks(console(frame_cycles=frame_cycles), ticks)
        assert first_difference(one[1:], other[1:]) is None
    assert one[0] != play_ticks(console(frame_cycles=FRAME_CYCLES * 0.8), ticks[:1])[0]


def test_the_game_never_writes_the_links_zero_page(console):
    """$F1-$F4 and $64-$65, which the netplay ROM's link has: from the
    title on, through a game for two. (The reset clears all of the zero
    page, before the netplay's reset.)"""
    nes = console()
    play(nes, [(0, 0)] * 200)
    nes.watch_writes()
    play(nes, game(5, 3000)[200:])
    assert not set(nes.written()) & {0x64, 0x65, 0xF1, 0xF2, 0xF3, 0xF4}


def test_the_game_never_reads_the_netplays_space(console):
    """The end of bank 6, from $A5A8, is all $FF, and the netplay's code is
    there in its ROM. Bank 6 is in at $8000 for most of the game, which
    reads nothing of it there."""
    nes = console()
    reads = []
    bus_class = type(nes.bus)

    class Watched(bus_class):
        def __getitem__(self, address):
            if 0xA5A8 <= address < 0xC000 and self.windows[0] == 6 * 0x4000:
                reads.append((address, nes.mpu.pc))
            return bus_class.__getitem__(self, address)
    nes.bus.__class__ = Watched
    play(nes, game(1, 3000))
    assert reads == []

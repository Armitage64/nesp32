"""The original game on the simulated console: that it runs to a game for
two, what its IRQs do, and that it is not the same game on two consoles."""

from itertools import islice

from console import FRAME_CYCLES
from drive import STATE_LEVELS, moves, play, play_ticks, title_script

PLAY_TICKS = 600
# Level 1's splits: the status bar's foot, and three below the playfield.
LEVEL_1_SPLITS = (47, 188, 199, 202)


def game(seed, ticks=PLAY_TICKS, players=2):
    return title_script(players) + list(islice(moves(seed), ticks))


def first_difference(one, other):
    return next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]), None)


def test_reaches_a_two_player_game(console):
    nes = console()
    play(nes, game(1, 300))
    assert nes.byte("STATE_SWITCH_INITIAL_MENUS") == STATE_LEVELS
    assert nes.byte("TWO_PLAYERS_FLAG") == 1
    assert nes.byte("LEVEL_SCREEN_ON") == 0


def test_level_one_splits_the_screen_four_times_on_time(console):
    """The counter is set up in the NMI and the IRQs come where the game
    means them, each taken on the line it was raised on."""
    nes = console()
    play(nes, game(1, 300))
    frames = nes.frames[-200:]
    splits = [tuple(nes.scanline(raised) for raised, _ in frame.irqs) for frame in frames]
    # Some frames, as the level comes in, have none.
    assert set(splits) == {LEVEL_1_SPLITS, ()}
    assert splits.count(LEVEL_1_SPLITS) > 150
    late = [nes.scanline(taken) - nes.scanline(raised)
            for frame in frames for raised, taken in frame.irqs]
    assert max(late) == 0


def test_original_is_not_the_same_on_two_consoles(console):
    """The original stirs its random number in the idle loop, so a few
    cycles' difference in a frame makes another game. Here one console's
    frames are a little short."""
    one = play(console(stir_idle=True), game(1))
    other = play(console(stir_idle=True, frame_cycles=FRAME_CYCLES - 2), game(1))
    assert first_difference(one, other) is not None


def test_without_the_idle_loop_the_game_is_the_buttons_alone(console):
    """With the idle loop skipped, as the netplay ROM's will do nothing,
    two consoles given the same buttons a tick at a time play the same
    game: whatever the samples take, and whenever frames overrun (here the
    console whose frames are short has lag frames, the other none). The sound engine's
    memory is left out of the digest; the rest is the game's."""
    ticks = game(3, 600)
    one = play_ticks(console(), ticks)
    assert first_difference(one, play_ticks(console(dmc_steal=0), ticks)) is None
    assert first_difference(
        one, play_ticks(console(frame_cycles=FRAME_CYCLES * 0.97), ticks)) is None


def test_netplay_rom_is_the_same_on_two_consoles(net_console):
    """The netplay ROM's idle loop does nothing, and the random number is
    stirred once a tick instead: stepped, not skipped, the loop changes
    nothing, and two consoles given the same buttons a tick at a time play
    the same game whatever their clocks and the samples do. In a game for
    one on one console, with no session."""
    ticks = game(3, 600, players=1)
    one = play_ticks(net_console(stir_idle=True), ticks)
    assert first_difference(one, play_ticks(net_console(), ticks)) is None
    assert first_difference(
        one, play_ticks(net_console(stir_idle=True, dmc_steal=0,
                                    frame_cycles=FRAME_CYCLES * 0.97), ticks)) is None


def test_the_game_never_reads_the_netplays_space(console):
    """Bank 29 is all $FF, and the netplay's code is there in its ROM. The
    game does put it in, as the pair of bank 28, but reads nothing of it
    but its last byte: every odd bank ends with $20 and its number, as
    every even one begins with it, and the game reads them to note which
    banks are in. The netplay ROM keeps that byte."""
    nes = console()
    reads = []
    start_of_30 = []
    mapped = []
    bus_class = type(nes.bus)

    class Watched(bus_class):
        def __getitem__(self, address):
            if 0xA000 <= address < 0xC000 and self.windows[1] == 29 * 0x2000:
                reads.append((address, nes.mpu.pc))
            elif 0xC000 <= address < 0xC040:
                start_of_30.append((address, nes.mpu.pc))
            return bus_class.__getitem__(self, address)

        def map(self, r6, r7, swapped):
            bus_class.map(self, r6, r7, swapped)
            if self.windows[1] == 29 * 0x2000:
                mapped.append(len(nes.frames))
    nes.bus.__class__ = Watched
    play(nes, game(1, 600))
    assert mapped                       # the game had it in
    assert reads
    assert {address for address, _ in reads} == {0xBFFF}
    # Nor the 64 bytes of $FF that bank 30, fixed at $C000, begins with,
    # where the netplay ROM has what its menu needs of a fixed bank.
    assert start_of_30 == []

"""The unchanged game on the simulated console: that it runs, that it is the
same every time, and how much of a frame it leaves spare."""

from itertools import islice

from console import FRAME_CYCLES
from drive import BOOT_FRAMES, PLAYERS, moves, to_two_player_game

PLAY_FRAMES = 1500


def play(console, seed, frames=PLAY_FRAMES, menu=False):
    to_two_player_game(console, menu)
    states = []
    for pads in islice(moves(seed), frames):
        console.run(1, pads=pads)
        states.append(console.state())
    return states


def test_reaches_a_two_player_game(console):
    nes = console()
    to_two_player_game(nes)
    assert nes.ram[PLAYERS] == 2
    # Both bottles hold viruses: something in each playfield is not empty.
    assert any(cell != 0xFF for cell in nes.ram[0x400:0x480])
    assert any(cell != 0xFF for cell in nes.ram[0x500:0x580])


def test_same_buttons_same_game(console):
    assert play(console(), seed=1) == play(console(), seed=1)


def test_other_buttons_other_game(console):
    assert play(console(), seed=1)[-1] != play(console(), seed=2)[-1]


def test_a_frame_is_never_overrun(console):
    """Once it is up, the game finishes every frame's work before the next
    NMI, with some cycles over. (While it starts, with the picture off, it
    clears the nametables across two NMIs.) The link's exchange has to fit
    in what is left, or its frames have to be ones the game does not
    notice."""
    nes = console()
    play(nes, seed=1)
    busiest = max(frame.busy for frame in nes.frames[BOOT_FRAMES:])
    assert busiest < FRAME_CYCLES
    print("busiest frame: %d of %d cycles" % (busiest, FRAME_CYCLES))


def test_the_netplay_rom_is_the_same_game_with_no_session(net_console):
    """By its menu's LOCAL GAME the netplay ROM plays as the original does,
    with a controller in each port, and leaves OUT0 at mark between its
    reads."""
    nes = net_console()
    writes = []
    nes.on_joy1 = lambda cycle, level: writes.append(level)
    nes.count_calls("loc_D470")         # the sound engine
    first = play(nes, seed=1, menu=True)
    # Once a frame, as the original runs it; the menu has no music.
    assert 0.9 * len(nes.frames) < nes.calls_of("loc_D470") <= len(nes.frames)
    assert first == play(net_console(), seed=1, menu=True)
    assert first[-1] != play(net_console(), seed=2, menu=True)[-1]
    assert writes[-1] == 1
    # In the game, that is: the menu draws its screens with the NMI off.
    assert max(frame.busy for frame in nes.frames[-PLAY_FRAMES:]) < FRAME_CYCLES

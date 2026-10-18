"""The game on the simulated console: the original, that it runs and is the
same every time; and the netplay ROM's game for two, with no session."""

from itertools import islice

from console import FRAME_CYCLES, PAD_DOWN, VBLANK_CYCLES
from drive import (
    EMPTY,
    GAME_MODE,
    MODE_PLAY,
    PLAY_STATE,
    PLAYERS,
    PLAYFIELD,
    PLAYFIELD_SIZE,
    moves,
    to_one_player_game,
    to_two_player_game,
)

PLAY_FRAMES = 1500
SOUND_ENGINE = "updateAudio"


def play(console, seed, frames=PLAY_FRAMES, players=1):
    (to_one_player_game if players == 1 else to_two_player_game)(console)
    states = []
    for pads in islice(moves(seed), frames):
        console.run(1, pads=pads)
        states.append(console.state())
    return states


def playfield(console, player):
    start = PLAYFIELD[player]
    return bytes(console.ram[start:start + PLAYFIELD_SIZE])


def watch_ppu(console):
    """The latest cycle of a frame that the PPU's address or data was
    written with the picture on: it has to be in the vblank."""
    latest = [0]
    write_io = console.write_io

    def write(address, value):
        if address < 0x4000 and address & 0x2007 in (0x2006, 0x2007) and console.mask & 0x18:
            latest[0] = max(latest[0], console.now - console.frame.start)
        write_io(address, value)
    console.write_io = write
    return latest


def test_reaches_a_game(console):
    nes = console()
    to_one_player_game(nes)
    assert nes.ram[PLAYERS] == 1
    assert nes.ram[PLAY_STATE[0]] != 0


def test_same_buttons_same_game(console):
    assert play(console(), seed=1) == play(console(), seed=1)


def test_other_buttons_other_game(console):
    assert play(console(), seed=1)[-1] != play(console(), seed=2)[-1]


def test_a_frame_is_never_overrun(console):
    """Once a game is up, the game finishes every frame's work before the
    next NMI, with some cycles over. (Between screens, with the picture
    off, it draws a whole one in a frame.) The link's exchange has to fit
    in what is left, or its frames have to be ones the game does not
    notice."""
    nes = console()
    play(nes, seed=1)
    busiest = max(frame.busy for frame in nes.frames[-PLAY_FRAMES:])
    assert busiest < FRAME_CYCLES
    print("busiest frame: %d of %d cycles" % (busiest, FRAME_CYCLES))


def test_the_netplay_rom_plays_two_on_one_console(net_console):
    """By its menu's LOCAL GAME the netplay ROM plays the game for two,
    with a controller in each port: both playfields fill, the same buttons
    make the same game, and OUT0 is left at mark between its reads."""
    nes = net_console()
    writes = []
    nes.on_joy1 = lambda cycle, level: writes.append(level)
    nes.count_calls(SOUND_ENGINE)
    first = play(nes, seed=1, players=2)
    assert nes.ram[PLAYERS] == 2 and nes.ram[GAME_MODE] == MODE_PLAY
    for player in (0, 1):
        assert any(cell != EMPTY for cell in playfield(nes, player))
    assert playfield(nes, 0) != playfield(nes, 1)
    # Once a frame, as the original runs it; the menu has no music.
    assert 0.9 * len(nes.frames) < nes.calls_of(SOUND_ENGINE) <= len(nes.frames)
    assert first == play(net_console(), seed=1, players=2)
    assert first[-1] != play(net_console(), seed=2, players=2)[-1]
    assert writes[-1] == 1


def test_two_playfields_are_drawn_in_the_vblank(net_console):
    """Four rows of each playfield a frame, the scores and the levels: all
    of it before the picture starts, and every frame's work done before
    the next NMI."""
    nes = net_console()
    to_two_player_game(nes)
    latest = watch_ppu(nes)
    for pads in islice(moves(1), PLAY_FRAMES):
        nes.run(1, pads=pads)
    assert 0 < latest[0] < VBLANK_CYCLES
    assert max(frame.busy for frame in nes.frames[-PLAY_FRAMES:]) < FRAME_CYCLES
    print("last PPU write at %d of %d cycles" % (latest[0], VBLANK_CYCLES))


def test_both_players_get_the_same_pieces(net_console):
    """Each from a generator of their own, begun from one seed: however
    far apart they play, the pieces come in the same order."""
    nes = net_console()
    to_two_player_game(nes)
    next_pieces = (nes.labels["nextPiece"], nes.labels["twoPlayerPieceDelayPiece"])
    seen = ([nes.ram[next_pieces[0]]], [nes.ram[next_pieces[1]]])
    for frame in range(800):
        # Both drop their pieces, player 2 faster, and gets ahead. Down has
        # to be let go of for the next piece.
        nes.run(1, pads=(PAD_DOWN if frame % 62 < 15 else 0, PAD_DOWN if frame % 62 < 60 else 0))
        for player, address in enumerate(next_pieces):
            if seen[player][-1] != nes.ram[address]:
                seen[player].append(nes.ram[address])
    ones, twos = seen
    assert len(twos) > len(ones) > 3
    assert twos[:len(ones)] == ones


def test_garbage_has_a_hole_that_is_one(net_console):
    """Two rows sent to player 2 come up from the bottom of their
    playfield when their piece is down, each with one empty cell, which a
    piece can fill."""
    nes = net_console()
    to_two_player_game(nes)
    nes.run(10)
    # Player 1's double, as playState_checkForCompletedRows leaves it.
    nes.ram[nes.labels["pendingGarbageInactivePlayer"]] = 2
    nes.run(100, pads=(0, PAD_DOWN))
    rows = playfield(nes, 1)[-20:-10], playfield(nes, 1)[-10:]
    for row in rows:
        assert row.count(EMPTY) == 1
    assert rows[0].index(EMPTY) == rows[1].index(EMPTY)
    assert playfield(nes, 0) == bytes((EMPTY,)) * PLAYFIELD_SIZE    # player 1 has none

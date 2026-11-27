"""The original ROM on the simulated console: that it gets from power-on
to a level for two, that both controllers play, and that it leaves room
in its frames for the link."""

from itertools import islice

from drive import (PAD_RIGHT, PAD_SELECT, PAD_START, BOOT_FRAMES, moves, play,
                   press, screen_row, cursor_players, title_script)

TITLE_ROW = 17
# The tasks' state while a level is played: task 0 asleep, the rest none.
TASKS = "TASKS"


def test_title(console):
    nes = console()
    nes.run(BOOT_FRAMES)
    assert screen_row(nes, TITLE_ROW).split() == ["1", "PLAYER", "2", "PLAYERS"]
    assert cursor_players(nes) == 1
    for pads in press(PAD_SELECT):
        nes.run(1, pads=pads)
    assert cursor_players(nes) == 2


def test_both_controllers_play(console):
    """Right held on one controller and then on the other moves something
    different each time: two players."""
    after = []
    for pads in ((PAD_RIGHT, 0), (0, PAD_RIGHT), (0, 0)):
        nes = console()
        play(nes, title_script(2))
        play(nes, [pads] * 60)
        after.append(nes.state())
    assert len(set(after)) == 3


def test_same_game_twice(console):
    """The same buttons make the same game: nothing of the digest depends
    on anything but them."""
    game = title_script(2) + list(islice(moves(1), 2000))
    first, second = console(), console()
    assert play(first, game) == play(second, game)


def test_frames_have_room(console):
    """A level for two leaves room in nearly every frame. The link's
    exchange takes some 2500 to 4000 cycles (docs/MULTIPLAYER.md)."""
    nes = console()
    play(nes, title_script(2))
    start = len(nes.frames)
    play(nes, list(islice(moves(2), 3000)))
    frames = nes.frames[start:]
    busy = sorted(frame.busy for frame in frames)
    assert busy[len(busy) // 2] < 22000
    assert sum(frame.lag for frame in frames) < len(frames) // 50


def test_start_pauses(console):
    """In the pause, the players and everything else in pages 2 to 6 stand
    still, whatever is held. (The frame count and what is at $E4 go on.)"""
    nes = console()
    play(nes, title_script(2))
    play(nes, [(PAD_RIGHT, PAD_RIGHT)] * 30)
    play(nes, press(PAD_START, rest=30))
    paused = bytes(nes.ram[0x200:0x700])
    play(nes, [(PAD_RIGHT, PAD_RIGHT)] * 30)
    assert bytes(nes.ram[0x200:0x700]) == paused


def test_play_leaves_the_links_zero_page_alone(console):
    """The link's library keeps six bytes in the zero page, $AA-$AF
    (net/net_ram.inc), which nothing seen of the game uses past the reset,
    which clears them: the title, and a level for one and for two, the
    pause in it."""
    for players, seed in ((1, 4), (2, 5)):
        nes = console()
        bus = nes.bus
        touched = []
        get, put = type(bus).__getitem__, type(bus).__setitem__

        class Watched(type(bus)):
            def __getitem__(self, address):
                if 0xAA <= address < 0xB0 and len(nes.frames) > 10:
                    touched.append((address, nes.mpu.pc))
                return get(self, address)

            def __setitem__(self, address, value):
                if 0xAA <= address < 0xB0 and len(nes.frames) > 10:
                    touched.append((address, nes.mpu.pc))
                put(self, address, value)
        bus.__class__ = Watched
        play(nes, title_script(players) + list(islice(moves(seed), 4000)))
        play(nes, press(PAD_START, rest=30) + press(PAD_START, rest=30))
        assert touched == []

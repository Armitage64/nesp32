"""The netplay ROM's sprite pass (net/sprites.inc) against the game's own,
which tmnt2_net_slow.nes keeps: the same sprites and the same RAM, for
any object and on any memory, and in the game tick by tick; and the time
it saves."""

import random
import statistics
from itertools import islice

import pytest

from netplay import game_state
from drive import (CHOSEN_FRAMES, PAD_A, PAD_B, PAD_DOWN, PAD_RIGHT, PAD_START, SELECTED_FRAMES,
                   TITLE_FRAMES, moves, play_ticks)

SPRITE_PAGE = 0x200
DATA = 0x600                    # where the fuzz's sprite data is put
RETURN = 0x0FF0                 # a return address no code is at
# The zero page an object's sprites are made from (DISPLAY_OBJECTS_ROUTINE).
TMP = {name: number for number, name in enumerate(
    ("TMP_00", "TMP_01", "TMP_02", "TMP_03", "TMP_04", "TMP_05", "TMP_06", "TMP_07",
     "TMP_08", "TMP_09", "TMP_0A", "TMP_0B", "TMP_0C", "TMP_0D", "TMP_0E", "TMP_0F"))}
# The title's code for the level select: Down 5, Right 7, B, A.
LEVEL_CODE = [PAD_DOWN] * 5 + [PAD_RIGHT] * 7 + [PAD_B, PAD_A]


def call(nes, address, a):
    """Run the routine at address with A, until it returns."""
    mpu = nes.mpu
    mpu.a, mpu.pc, mpu.sp = a, address, 0xF0
    nes.bus[0x100 + mpu.sp] = (RETURN - 1) >> 8
    nes.bus[0x100 + ((mpu.sp - 1) & 0xFF)] = (RETURN - 1) & 0xFF
    mpu.sp = (mpu.sp - 2) & 0xFF
    for _ in range(100000):
        if mpu.pc == RETURN:
            return
        mpu.step()
    raise AssertionError("no return from $%04X" % address)


def an_object(rng):
    """The zero page and the data of one object, at random but within
    what the game gives the loop: its flags as the game masks them."""
    zero = {name: rng.randrange(256) for name in TMP}
    zero["TMP_07"] &= 0xE0
    zero["TMP_0C"] = rng.choice((0, 0, 1, 2, 3))
    zero["TMP_06"] = rng.randrange(4)
    zero["TMP_0B"] = rng.choice((rng.randrange(0x12), 0x0A, 0x0B, 0x0C, 0x0D, 0x09))
    zero["TMP_0F"] = 0
    zero["TMP_04"] = rng.choice((0, 0x80, 0xF0, 0xFC)) & ~3 if rng.random() < 0.5 \
        else rng.randrange(64) * 4
    flags = {"TMP_12": rng.choice((0, 0, 1)), "TMP_13": rng.choice((0, 0, 1)),
             "TMP_0E": rng.choice((0, 1)), "_4C_UNK": rng.choice((0, 0, 0x80, 0x01)),
             "LEVEL_SCREEN_ON": rng.choice((0, 3, 7, 7))}
    count = rng.choice((0, 1, 2, 5, 16, 40, 63))
    data = [count] + [rng.randrange(256) for _ in range(4 * count)]
    return zero, flags, data


def built(nes, entry, base, zero, flags, data, page):
    nes.ram[:] = base
    for name, value in zero.items():
        nes.bus[nes.labels[name]] = value
    for name, value in flags.items():
        nes.bus[nes.labels[name]] = value
    nes.bus[nes.labels["TMP_08"]] = DATA & 0xFF
    for offset, value in enumerate(data):
        nes.bus[DATA + offset] = value
    for offset, value in enumerate(page):
        nes.bus[SPRITE_PAGE + offset] = value
    call(nes, nes.labels[entry], DATA >> 8)
    return bytes(nes.ram[:0x800])


def test_any_object_makes_the_same_sprites_and_ram(net_console, slow_console):
    fast, slow = net_console(), slow_console()
    for nes in (fast, slow):
        nes.run(5)              # past the reset, which puts the loop in the PRG RAM
    hook = fast.labels["SPRITE_CREATE_FROM_PTR"]
    assert fast.bus[hook] == 0x4C               # JMP
    assert fast.bus[hook + 1] | fast.bus[hook + 2] << 8 == fast.labels["net_sprites"]
    base = bytes(slow.ram)      # both begin each object from the same memory
    rng = random.Random(7)
    for case in range(3000):
        zero, flags, data = an_object(rng)
        page = bytes(rng.randrange(256) for _ in range(256))
        mine = built(fast, "SPRITE_CREATE_FROM_PTR", base, zero, flags, data, page)
        theirs = built(slow, "SPRITE_CREATE_FROM_PTR", base, zero, flags, data, page)
        assert mine == theirs, "case %d: %r %r %r, first at $%03X" % (
            case, zero, flags, data[:9],
            next(i for i in range(0x800) if mine[i] != theirs[i]))


def test_the_whole_pass_on_any_memory_makes_the_same_sprites_and_ram(net_console, slow_console):
    """DISPLAY_OBJECTS_ROUTINE, the order of the objects and their sprites,
    on random memory. Its sprites' data comes from the ROM, which is the
    same in both but bank 29."""
    fast, slow = net_console(), slow_console()
    for nes in (fast, slow):
        nes.run(5)
    rng = random.Random(11)
    for case in range(400):
        base = bytearray(rng.randrange(256) for _ in range(0x800))
        if case % 2:            # fewer objects shown, as in most frames
            for slot in range(0x12):
                if rng.random() < 0.6:
                    base[fast.labels["OBJ_ANIMATION_DISPLAY"] + slot] = 0
        results = []
        for nes in (fast, slow):
            nes.ram[:] = base
            call(nes, nes.labels["DISPLAY_OBJECTS_ROUTINE"], 0)
            results.append(bytes(nes.ram))
        mine, theirs = results
        assert mine == theirs, "case %d, first at $%03X" % (
            case, next(i for i in range(0x800) if mine[i] != theirs[i]))


def level_script(rights, ticks):
    """One player, the level select's code at the title, `rights` presses
    of Right on its map, and play."""
    script = [(0, 0)] * TITLE_FRAMES
    for pad in LEVEL_CODE:
        script += [(pad, 0)] * 2 + [(0, 0)] * 2
    script += [(0, 0)] * 7 + [(PAD_START, 0)] * 2 + [(0, 0)] * CHOSEN_FRAMES
    script += [(PAD_A, PAD_A)] * 2 + [(0, 0)] * SELECTED_FRAMES
    for _ in range(rights):
        script += [(PAD_RIGHT, 0)] * 2 + [(0, 0)] * 4
    script += [(PAD_A, 0)] * 2 + [(0, 0)] * 400
    return script + list(islice(moves(rights), ticks))


def sprite_pass(nes):
    """Mark where the NMI's sprite pass begins and ends."""
    begin = nes.labels["DISPLAY_OBJECTS_ROUTINE"]
    call = next(at for at in range(nes.labels["NMI_HANDLER"], 0x10000)
                if nes.bus[at] == 0x20 and nes.bus[at + 1] | nes.bus[at + 2] << 8 == begin)
    nes.mark(begin)
    nes.mark(call + 3)
    return begin, call + 3


def sprite_cycles(nes, marks, since):
    """The median cycles of the sprite pass, in the frames from `since`."""
    begin, end = (dict((frame, cycle) for frame, cycle in nes.marks_of(mark) if frame >= since)
                  for mark in marks)
    return statistics.median(end[frame] - begin[frame] for frame in begin if frame in end)


# After Start at the title, while 1 TURTLE flashes: 2 TURTLES, past the
# netplay's menu, for a game for two on one console.
TWO_AT = TITLE_FRAMES + 4 * len(LEVEL_CODE) + 7 + 2 + 20


@pytest.mark.parametrize("rights, level, players", [(0, 0, 1), (2, 3, 1), (6, 7, 2), (0, 0, 2)])
def test_a_level_is_the_same_game_tick_by_tick(net_console, slow_console, rights, level,
                                                players):
    script = level_script(rights, 600)
    fast, slow = net_console(), slow_console()
    marks = [sprite_pass(nes) for nes in (fast, slow)]
    # Compared as a session compares them: the faster drops fewer frames,
    # and what keeps the frames' time is left out.
    states = []
    for nes in (fast, slow):
        if players == 2:
            ticks = play_ticks(nes, script[:TWO_AT], game_state)
            nes.bus[nes.labels["TITLE_PLAYERS_COUNT_CURSOR_0_1"]] = 1
            states.append(ticks + play_ticks(nes, script[TWO_AT:], game_state))
        else:
            states.append(play_ticks(nes, script, game_state))
    for nes in (fast, slow):
        assert nes.byte("LEVEL_SCREEN_ON") == level
        assert nes.byte("TWO_PLAYERS_FLAG") == players - 1
    one, other = states
    assert next((tick for tick, (a, b) in enumerate(zip(one, other)) if a != b), None) is None
    since = [len(nes.frames) - 600 for nes in (fast, slow)]
    mine, theirs = (sprite_cycles(nes, mark, frame)
                    for nes, mark, frame in zip((fast, slow), marks, since))
    print("level", level, "for", players, "sprite pass", mine, "cycles, the game's", theirs)
    if level == 7:
        assert mine < 0.85 * theirs

"""The netplay ROM's sprite pass (net/sprites.inc, from the PRG RAM)
against the original's: the same OAM buffer and the same RAM, on any
memory. And the netplay ROM against contra_net_slow.nes, which keeps bank
1's pass and the game's test of the bullets (net/collide.inc), in the game
tick by tick. The sprite pass's loop over a sprite's tiles works out once
a sprite what the game's works out for every tile, and it hides the unused
places with a run of stores; the bullets' test has the 16 places in line.
So a frame has more cycles to spare for the exchange."""

import random
import statistics
from itertools import islice

import pytest

from drive import moves, play, title_script

RETURN = 0x0FF0                 # a return address no code is at
SLOTS = 0x1A                    # CPU_SPRITE_BUFFER's sprites
STACK = range(0x100, 0x200)     # left out: a JSR made inline writes nothing there
POINTER = 0x08                  # and $09: where in a sprite's data the loop got to
SHARED = 0x06                   # the low byte of a shared sprite's data


def call(nes, address):
    """Run the routine at address with bank 1 in, until it returns."""
    mpu = nes.mpu
    nes.bus.map(1)
    mpu.pc, mpu.sp = address, 0xF0
    nes.bus[0x1F0] = (RETURN - 1) >> 8
    nes.bus[0x1EF] = (RETURN - 1) & 0xFF
    mpu.sp = 0xEE
    for _ in range(200000):
        if mpu.pc == RETURN:
            return
        mpu.step()
    raise AssertionError("no return from $%04X" % address)


def a_sprite(rng):
    """A sprite code the game's tables have: none, $01-$7F or $80-$CF."""
    return rng.choice((0, 0, rng.randrange(1, 0x80), rng.randrange(0x80, 0xD0)))


def test_any_sprites_make_the_same_oam_and_ram(console, net_console):
    """The sprites' data in bank 1 is where it was, but for being `moved`
    bytes on in the netplay ROM, so the loop's pointers into it are held to
    that."""
    original, mine = console(), net_console()
    mine.run(5)                 # past the reset, which puts the pass in the PRG RAM
    moved = mine.labels["sprite_ptr_tbl_0"] - original.labels["sprite_ptr_tbl_0"]
    rng = random.Random(5)
    for case in range(1500):
        base = bytearray(rng.randrange(256) for _ in range(0x800))
        labels = original.labels
        for slot in range(SLOTS):
            base[labels["CPU_SPRITE_BUFFER"] + slot] = a_sprite(rng) if rng.random() < 0.5 else 0
        base[labels["SPRITE_LOAD_TYPE"]] = rng.choice((0, 0, 1))
        # A whole sprite's place, as the game keeps it: one in between
        # would write past the buffer, into CPU_SPRITE_BUFFER.
        base[labels["OAMDMA_CPU_BUFFER_OFFSET"]] = rng.randrange(64) * 4
        # Player 1 or 2, demo or not: the HUD draws 8 sprites at the most.
        base[labels["PLAYER_MODE"]] = rng.randrange(2)
        base[labels["DEMO_MODE"]] = rng.randrange(2)
        results = []
        for nes in (original, mine):
            nes.ram[:] = base
            call(nes, nes.labels["draw_sprites"])
            results.append((bytearray(nes.ram), nes.mpu.x, nes.mpu.y))
        (theirs, *their_regs), (ours, *our_regs) = results
        assert our_regs == their_regs, "case %d" % case
        pointer = theirs[POINTER] | theirs[POINTER + 1] << 8
        if pointer != (base[POINTER] | base[POINTER + 1] << 8) \
                and original.labels["sprite_ptr_tbl_0"] <= pointer < 0xC000:
            pointer += moved            # into bank 1's data; a shared sprite's may be elsewhere
        assert ours[POINTER] | ours[POINTER + 1] << 8 == pointer, "case %d" % case
        assert ours[SHARED] in (theirs[SHARED], (theirs[SHARED] + moved) & 0xFF), "case %d" % case
        for ram in (theirs, ours):
            for address in list(STACK) + [POINTER, POINTER + 1, SHARED]:
                ram[address] = 0
        assert ours == theirs, "case %d, first at $%03X" % (
            case, next(i for i in range(0x800) if ours[i] != theirs[i]))


def test_the_bullets_test_on_any_memory_is_the_games(net_console, slow_console):
    """bullet_enemy_collision_test for any enemy, outdoors and indoors, on
    random memory: the same RAM, registers and flags after it as the
    game's, hits, lasers and near misses included."""
    fast, slow = net_console(), slow_console()
    for nes in (fast, slow):
        nes.run(5)
    labels = slow.labels
    routine = labels["PLAYER_BULLET_ROUTINE"]
    rng = random.Random(9)
    hits = 0
    for case in range(1500):
        base = bytearray(rng.randrange(256) for _ in range(0x800))
        for slot in range(16):          # most places empty, and most bullets flying
            if rng.random() < 0.6:
                base[labels["PLAYER_BULLET_SPRITE_CODE"] + slot] = 0
            elif rng.random() < 0.7:
                base[labels["PLAYER_BULLET_ROUTINE"] + slot] = 1
        enemy = rng.randrange(16)
        base[labels["ENEMY_CURRENT_SLOT"]] = enemy
        for slot in range(16):          # half the bullets near the enemy
            if rng.random() < 0.5:
                for axis in ("Y", "X"):
                    near = base[labels["ENEMY_%s_POS" % axis] + enemy] + rng.randrange(-24, 24)
                    base[labels["PLAYER_BULLET_%s_POS" % axis] + slot] = near & 0xFF
        results = []
        for nes in (fast, slow):
            nes.ram[:] = base
            nes.mpu.x = enemy
            call(nes, nes.labels["bullet_enemy_collision_test"])
            mpu = nes.mpu
            results.append((bytes(nes.ram[:0x100]) + bytes(nes.ram[0x200:]),
                            mpu.a, mpu.x, mpu.y, mpu.p))
        assert results[0] == results[1], "case %d" % case
        hits += any(slow.ram[routine + slot] == 2 and base[routine + slot] == 1
                    for slot in range(16))
    assert hits > 300                   # a bullet stopped by the enemy


def at_level(nes, level):
    """The game's own play, but for the stage it starts at."""
    labels = nes.labels
    state = nes.state

    def at():
        ram = nes.ram
        if (ram[labels["GAME_ROUTINE_INDEX"]] == 5 and ram[labels["LEVEL_ROUTINE_INDEX"]] == 0
                and ram[labels["CURRENT_LEVEL"]] != level):
            ram[labels["CURRENT_LEVEL"]] = level
        return state()
    nes.state = at
    return nes


@pytest.mark.parametrize("level", [0, 3, 5])
def test_a_stage_is_the_same_game_tick_by_tick_and_quicker(net_console, slow_console, level):
    """Two players from the start of stages 1, 4 (indoors) and 6, the same
    buttons on both ROMs: the same memory before every tick, and the frames
    some 900 cycles shorter at the median."""
    script = title_script() + list(islice(moves(2), 1500))
    fast, slow = at_level(net_console(), level), at_level(slow_console(), level)
    one, other = play(fast, script), play(slow, script)
    assert fast.byte("CURRENT_LEVEL") == level
    assert next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]),
                None) is None
    mine, theirs = (statistics.median(frame.busy for frame in nes.frames[-1000:]
                                      if frame.nmi_cycles and not frame.lag)
                    for nes in (fast, slow))
    print("stage", level + 1, "a frame's median", mine, "cycles, the slow ROM's", theirs)
    assert mine < theirs - 500

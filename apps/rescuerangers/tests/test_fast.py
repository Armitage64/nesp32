"""The netplay ROM's faster ways through the game's busiest routines
(net/fast.inc) do what the game's own do, as Bubble Bobble's tests have it.
The netplay ROM is held to rescuerangers_net_slow.nes, the same build with
the game's own routines: each routine from memory and registers at random,
and a game for two tick by tick."""

import random
from itertools import islice

import pytest

from console import Console
from drive import BOOT_FRAMES, LEVEL_FRAMES, STORY_FRAMES, PAD_A, PAD_DOWN, PAD_SELECT, PAD_START
from drive import moves, play_ticks, press

PASSES = 300
SENTINEL = 0x5000               # where the routine returns to: nothing is there
POINTS = 0xED34 - 0xEC97        # the points of L7_EC97 and L7_EBFA
OBJECTS = 16


def roms(build):
    """The netplay ROM and the slow one, both past their reset (the PRG
    RAM's code copied in)."""
    pair = []
    for name in ("rescuerangers_net", "rescuerangers_net_slow"):
        nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
        nes.run(20)
        pair.append(nes)
    return pair


def call(nes, address, ram, a, x, y, p):
    """Run the routine at an address from this memory and these registers
    until it returns. What it leaves: the memory, but for what is below the
    stack, which is dead, and the registers."""
    mpu = nes.mpu
    nes.ram[:] = ram
    # D clear: the NES's CPU has no decimal mode, and py65 does.
    mpu.a, mpu.x, mpu.y, mpu.p = a, x, y, (p | 0x20) & ~0x08
    mpu.sp = 0xFD
    mpu.stPushWord(SENTINEL - 1)
    mpu.pc = address
    for _ in range(100000):
        if mpu.pc == SENTINEL:
            ram = bytearray(nes.ram)
            ram[0x100:0x100 + mpu.sp + 1] = bytes(mpu.sp + 1)
            # Bit 4 of P is not in the CPU, but PLP leaves it in py65's.
            return bytes(ram), mpu.a, mpu.x, mpu.y, mpu.p & ~0x10, mpu.sp
        mpu.step()
    raise AssertionError("the routine at $%04X did not return" % address)


def registers(rng):
    return [rng.randrange(256) for _ in range(4)]


def test_hiding_the_sprites_is_the_games(build):
    """L7_C21E from every slot, as the game has it in $97 (a multiple of 4,
    or the game's own loop never ends)."""
    fast, slow = roms(build)
    address = slow.labels["L7_C21E"]
    rng = random.Random(1)
    for slot in range(0, 256, 4):
        for _ in range(4):
            ram = bytearray(rng.randrange(256) for _ in range(0x800))
            ram[0x97] = slot
            regs = registers(rng)
            assert call(fast, address, bytes(ram), *regs) == call(slow, address, bytes(ram), *regs)


def test_the_collision_maps_look_up_is_the_games(build):
    """fast_tile_at for L7_EB3B, at each of the game's points, for objects
    anywhere: in the level and off its pages, above and below the screen."""
    fast, slow = roms(build)
    rng = random.Random(2)
    for point in range(POINTS):
        for _ in range(PASSES // 30):
            ram = bytearray(rng.randrange(256) for _ in range(0x800))
            regs = registers(rng)
            regs[1] = rng.randrange(OBJECTS)
            regs[2] = point
            assert call(fast, fast.labels["fast_tile_at"], bytes(ram), *regs) == \
                call(slow, slow.labels["L7_EB3B"], bytes(ram), *regs)


def test_an_objects_look_at_the_map_is_the_games(build):
    """L7_EA8F, the one caller, which calls fast_tile_at on the netplay ROM:
    an object's run of points, and what it makes of them."""
    fast, slow = roms(build)
    address = slow.labels["L7_EA8F"]
    rng = random.Random(3)
    for _ in range(PASSES * 4):
        ram = bytearray(rng.randrange(256) for _ in range(0x800))
        ram[0x40] = rng.randrange(POINTS - 8)        # the first point
        ram[0x41] = rng.randrange(4)                 # and how many more
        regs = registers(rng)
        regs[1] = rng.randrange(OBJECTS)
        assert call(fast, address, bytes(ram), *regs) == call(slow, address, bytes(ram), *regs)


def menu_to_local_game():
    """From power-on: 2 PLAYERS on the title, the menu (no nesp32 answers),
    and LOCAL GAME, frame by frame."""
    rest = 16
    frames = [(0, 0)] * BOOT_FRAMES
    frames += press(PAD_SELECT, rest=6)
    frames += press(PAD_START, rest=3 * rest)
    frames += [(0, 0)] * (10 * rest)
    frames += press(PAD_DOWN, rest=6) * 2
    frames += press(PAD_A, rest=2)
    return frames


@pytest.mark.parametrize("seed", [3, 5])
def test_a_game_for_two_is_the_same_game_tick_by_tick(build, seed):
    """Both ROMs through the title and the menu to LOCAL GAME, alike frame
    by frame; then the story and the first level for two at random, the same
    game on both at every tick, however their frames fall."""
    game = ([(0, 0)] * STORY_FRAMES + press(PAD_START, rest=LEVEL_FRAMES)
            + list(islice(moves(seed), 2500)))
    states = []
    for name in ("rescuerangers_net", "rescuerangers_net_slow"):
        nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
        for pads in menu_to_local_game():
            nes.run(1, pads=pads)
        assert nes.byte("net_menu") == 0 and nes.byte("TITLE_PLAYERS") == 1
        start = nes.state()

        def digest(nes):
            return nes.state(), tuple(nes.chr_banks)
        states.append((start, play_ticks(nes, game, digest)))
    assert states[0][0] == states[1][0]
    fast, slow = states[0][1], states[1][1]
    for tick, (a, b) in enumerate(zip(fast, slow)):
        assert a == b, "the games differ at tick %d" % tick

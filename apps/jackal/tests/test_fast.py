"""The netplay ROM's faster ways through the game's busiest routines
(net/fast.inc) do what the game's own do: Bubble Bobble's test_fast, on Jackal. The
netplay ROM is held to jackal_net_slow.nes, the same build with the game's
own routines: each routine from memory and registers at random, and whole
levels tick by tick."""

import random
from itertools import islice

import pytest

from console import Console
from drive import GAME_PLAYING, keep_lives, local_script, moves

PASSES = 400
SENTINEL = 0x5000               # where the routine returns to: nothing is there
BANK_1 = (2, 3)                 # the MMC3's two 8 KB halves of the game's bank 1


@pytest.fixture
def pair(build):
    """The netplay ROM and the slow one, both past their reset."""
    def make():
        roms = []
        for name in ("jackal_net", "jackal_net_slow"):
            nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
            nes.run(30)
            roms.append(nes)
        return roms
    return make


def call(nes, address, ram, a, x, y, p):
    """Run the routine at an address from this memory and these registers,
    with bank 1 in at $8000 as the NMI has it, until it returns. What it
    leaves: the memory, but for what is below the stack, which is dead, and
    the registers."""
    mpu = nes.mpu
    nes.ram[:] = ram
    nes.bank_select = 7
    nes.banks[6:8] = list(BANK_1)
    nes._map_mmc3()
    # D clear: the NES's CPU has no decimal mode, and py65 does.
    mpu.a, mpu.x, mpu.y, mpu.p = a, x, y, (p | 0x20) & ~0x08
    mpu.sp = 0xFD
    mpu.stPushWord(SENTINEL - 1)
    mpu.pc = address
    for _ in range(200000):
        if mpu.pc == SENTINEL:
            ram = bytearray(nes.ram)
            ram[0x100:0x100 + mpu.sp + 1] = bytes(mpu.sp + 1)
            # Bit 4 of P is not in the CPU, but PLP leaves it in py65's.
            return bytes(ram), mpu.a, mpu.x, mpu.y, mpu.p & ~0x10, mpu.sp
        mpu.step()
    raise AssertionError("the routine at $%04X did not return" % address)


def objects(ram, rng):
    """Objects of every kind, in every state, flipped every way, at every
    place, and few or many of them: so the OAM is filled, or not."""
    many = rng.random() < 0.5
    for slot in range(32):
        present = rng.random() < (0.9 if many else 0.3)
        ram[0x500 + slot] = rng.randrange(1, 256) if present else 0     # SpriteTypeIndex
        ram[0x520 + slot] = rng.choice((0x00, 0x01, 0x05, 0x80, rng.randrange(256)))
        ram[0x6A + slot] = rng.choice((0x00, 0x40, 0x80, 0xC0, rng.randrange(256)))
    for label, values in ((0x18, (5, 5, 5, rng.randrange(256))),       # GameControlState
                          (0x2C, (3, 3, 3, rng.randrange(256))),       # GamePlayMode
                          (0x22, (0, 1))):                             # Player2Active
        ram[label] = rng.choice(values)
    ram[0x31] = rng.choice((0, 1, 5, rng.randrange(256)))              # the lives
    ram[0x32] = rng.choice((0, 1, 5, rng.randrange(256)))


def nothing(ram, rng):
    pass


# Each routine with a faster way: where the netplay ROM and the slow one are
# called (by the same name, but for the sprites, whose faster way is called
# in place of the game's), and how the memory at random is made to take
# the ways through it that matter.
ROUTINES = {
    "sprites": ("net_sprites", "subProcessSpriteUpdates", objects),
    "collision": ("fctGetCollisionTypeFromRAM300_4FF", None, nothing),
    "collision at": ("Label1210", None, nothing),
    "movement collision": ("fctTestForMovementCollision", None, nothing),
}


@pytest.mark.parametrize("name", sorted(ROUTINES))
def test_each_faster_way_does_what_the_games_does(pair, name):
    fast, slow = pair()
    fast_name, slow_name, prepare = ROUTINES[name]
    to_fast, to_slow = fast.labels[fast_name], slow.labels[slow_name or fast_name]
    rng = random.Random(name)
    full = 0
    for _ in range(PASSES):
        ram = bytearray(rng.randrange(256) for _ in range(0x800))
        prepare(ram, rng)
        registers = [rng.randrange(256) for _ in range(4)]
        left_fast = call(fast, to_fast, bytes(ram), *registers)
        assert left_fast == call(slow, to_slow, bytes(ram), *registers)
        oam = left_fast[0][0x200:0x300]
        full += all(oam[slot] != 0xF4 for slot in range(0, 256, 4))
    if name == "sprites":
        assert 0 < full < PASSES    # the OAM filled by the objects, and not


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_a_level_is_the_same_game_tick_by_tick(build, level):
    """Two players at random through a level, from the menu's LOCAL GAME:
    the same game on both ROMs at every tick from power-on, however their
    frames fall. The level is put in at a tick, before it loads."""
    script = local_script() + list(islice(moves(level), 900))
    states = []
    for name in ("jackal_net", "jackal_net_slow"):
        nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
        frame_logic = nes.labels["GameFrameLogicInProgress"]
        seen = []
        poked = []

        def on_vblank(console):
            if not console.ctrl & 0x80 or console.ram[frame_logic] or len(seen) > len(script):
                return
            if (not poked and console.byte("GameControlState") == GAME_PLAYING
                    and console.byte("GamePlayMode") <= 1):
                console.ram[console.labels["CurrentLevel"]] = level - 1
                poked.append(len(seen))
            keep_lives(console)
            seen.append(console.state())
            if len(seen) <= len(script):
                console.pads = list(script[len(seen) - 1])

        nes.on_vblank = on_vblank
        while len(seen) <= len(script):
            nes.run(1)
        assert poked
        states.append(seen)
    assert states[0] == states[1]

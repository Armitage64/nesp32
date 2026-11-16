"""The netplay ROM's faster ways through the game's busiest routines
(net/fast.inc) do what the game's own do: TMNT II's test_sprites, on
Bubble Bobble. The netplay ROM is held to bubblebobble_net_slow.nes, the
same build with the game's own routines: each routine from memory and
registers at random, and whole rounds tick by tick."""

import hashlib
import random
from itertools import islice

import pytest

from console import Console
from drive import BOOT_FRAMES, TITLE_2P_CONTINUE, moves, play, play_ticks, title_script

def crowd(ram, rng):
    """Objects close together, in states of every kind, so that pairs are
    near, and the near and the far both often found."""
    for at in range(0x68, 0xC4, 4):
        ram[at] = rng.choice((0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x80, 0xFF, rng.randrange(256)))
        ram[at + 2] = rng.choice((0x10, 0x00, rng.randrange(256)))
    for at in range(0x200, 0x300, 4):
        ram[at] = 0x60 + rng.randrange(0x30)
        ram[at + 3] = 0x60 + rng.randrange(0x30)


def push(ram, rng):
    crowd(ram, rng)
    if rng.random() < 0.8:
        ram[0x463] = 1                  # the countdown's last: it looks
    ram[0x21] = 0x60 + rng.randrange(0x30)
    ram[0x22] = 0x60 + rng.randrange(0x30)


# The game's routines that have a faster way, by the address the game
# calls, and how the memory at random is made to take the ways through
# them that matter.
ROUTINES = {
    "TILE_AT": (0xD0BE, None),
    "PUSH": (0xDAE4, push),
}
PASSES = 400
SENTINEL = 0x5000               # where the routine returns to: nothing is there
# What keeps the frames' time, which the faster ways change: the sound
# engine's memory and the scratch it shares ($00-$0F, $CA-$F0), the PPU's
# status ($20) and the flicker's start ($049F) as the NMI keeps them, the
# NMI's stack pointer as the tasks saw it ($1D), and page 1, the stacks.
NOT_GAME = ((0x00, 0x10), (0x1D, 0x1E), (0x20, 0x21), (0xCA, 0xF1), (0x100, 0x200), (0x49F, 0x4A0))


def game_state(console):
    ram = bytearray(console.ram)
    for start, end in NOT_GAME:
        ram[start:end] = bytes(end - start)
    return hashlib.sha1(ram).hexdigest()


@pytest.fixture
def pair(build):
    """The netplay ROM and the slow one, both past their reset."""
    def make():
        roms = []
        for name in ("bubblebobble_net", "bubblebobble_net_slow"):
            nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
            play(nes, [(0, 0)] * 30)
            roms.append(nes)
        return roms
    return make


def call(nes, address, ram, a, x, y, p):
    """Run the routine at an address from this memory and these
    registers, with the netplay's bank in at $8000, until it returns. What
    it leaves: the memory, but for what is below the stack, which is dead,
    and the registers."""
    mpu = nes.mpu
    nes.ram[:] = ram
    nes.prg_bank = 6
    nes.bus.map(nes.mmc1_control, 6)
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


@pytest.mark.parametrize("name", sorted(ROUTINES))
def test_each_faster_way_does_what_the_games_does(pair, name):
    fast, slow = pair()
    address, prepare = ROUTINES[name]
    rng = random.Random(name)
    for _ in range(PASSES):
        ram = bytearray(rng.randrange(256) for _ in range(0x800))
        if prepare:
            prepare(ram, rng)
        registers = [rng.randrange(256) for _ in range(4)]
        if name != "TILE_AT":
            # The object: one of the game's, its sprites where they go.
            registers[1] = rng.randrange(0x68, 0xC4) & ~3
            registers[2] = (0x10 + 2 * (registers[1] - 0x68)) & 0xFF
        assert call(fast, address, bytes(ram), *registers) == \
            call(slow, address, bytes(ram), *registers)


@pytest.mark.parametrize("round_", [1, 50, 66, 80, 91])
def test_a_round_is_the_same_game_tick_by_tick(build, round_):
    """Two players at random through a round, from the title's 2P CONTINUE:
    the same game on both ROMs at every tick from power-on, however their
    frames fall. The round is put in at a tick, not a frame."""
    ticks = ([(0, 0)] * BOOT_FRAMES + title_script(TITLE_2P_CONTINUE, boot=False)
             + list(islice(moves(round_), 900)))
    states = []
    for name in ("bubblebobble_net", "bubblebobble_net_slow"):
        nes = Console(str(build / (name + ".nes")), str(build / (name + ".dbg")))
        seen = []

        def digest(nes):
            if len(seen) == BOOT_FRAMES:
                nes.ram[nes.labels["ROUND"]] = round_
            seen.append(None)
            return game_state(nes)
        states.append(play_ticks(nes, ticks, digest=digest))
    assert states[0] == states[1]

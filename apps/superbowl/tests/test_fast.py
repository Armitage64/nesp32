"""The netplay ROM's quicker ways through the game's busy routines do what
the game's own do. The netplay ROM is held to superbowl_net_slow.nes, the same
build with the game's own routines: each routine from memory at random,
and a session's whole game tick by tick.

The sprites' flicker (net/flicker.inc) and the collision checks
(net/coll.inc)."""

import random

import pytest

from console import Console
from netplay import Table
from test_lockstep import moves
from wire import ms

ROMS = ("superbowl_net", "superbowl_net_slow")
SENTINEL = 0x5000               # where the routine returns to: nothing is there
PASSES = 300

# The game's names, as ram.inc has them, that the count works on.
CUR_SPRITE_Y = 0x0200
COUNTERS = 0x06E2               # SPRITE_PER_AREA_COUNTER_START, 16 bands
SPRITE_Y_OFFSET = 0x45
SPRITE_CYCLING_INDEX = 0x44
SOFT_BANKS = (0x34, 0x2E, 0x2F)  # SOFT_BANK_SELECT, SOFT_8000_BANK, SOFT_A000_BANK
SOFT_MODE_8000 = 0x33
FLICKER_TASK_BANK = 22          # at $8000 while the flicker task runs
# The game's dispatch on sprite_cycling_index, just past its INC (bank 22):
# the netplay ROM's JMP net_flicker, the slow one's LDA.
DISPATCH = 0x90F2


def make(build, name, **kwargs):
    return Console(str(build / (name + ".nes")), str(build / (name + ".dbg")), **kwargs)


FAST = [None]
SLOW_FIRST = {DISPATCH: 0xA5, 0x95E6: 0xA9}     # LDA zp, LDA #


@pytest.fixture
def pair(build):
    roms = [make(build, name) for name in ROMS]
    FAST[0] = roms[0]
    for nes in roms:
        assert nes.labels["SOFT_BANK_SELECT"] == SOFT_BANKS[0]
        assert nes.labels["SOFT_8000_BANK"] == SOFT_BANKS[1]
        assert nes.labels["SOFT_A000_BANK"] == SOFT_BANKS[2]
        assert nes.labels["SOFT_MODE_8000"] == SOFT_MODE_8000
        assert nes.labels["sprite_y_offset"] == SPRITE_Y_OFFSET
        assert nes.labels["SPRITE_PER_AREA_COUNTER_START"] == COUNTERS
    return roms


def call(nes, ram, a000_bank, select, start=DISPATCH, until=SENTINEL):
    """The game's code in bank 22 from `start` (the flicker's count from
    its dispatch, unless it says), with this memory, the task's bank at
    $8000 and another at $A000, until it returns or comes to `until`.
    What it leaves: the memory, but for what is below the stack, which is
    dead, the registers and flags (the task's next sleep keeps them), and
    the MMC3's banks and its register select."""
    mpu = nes.mpu
    nes.ram[:] = ram
    nes.ram[SOFT_BANKS[1]] = FLICKER_TASK_BANK
    nes.ram[SOFT_BANKS[2]] = a000_bank
    nes.ram[SOFT_BANKS[0]] = select
    nes.ram[SOFT_MODE_8000] = select & 0xC0
    nes.write_mapper(0x8000, 0x06)
    nes.write_mapper(0x8001, FLICKER_TASK_BANK)
    nes.write_mapper(0x8000, 0x07)
    nes.write_mapper(0x8001, a000_bank)
    nes.write_mapper(0x8000, select)
    # The netplay ROM's JMP to its quicker way, the slow one's own LDA.
    assert nes.bus[start] == (0x4C if nes is FAST[0] else SLOW_FIRST[start]), \
        "not the code expected at $%04X" % start
    mpu.a = mpu.x = mpu.y = 0
    mpu.p = 0x24
    mpu.sp = 0xFD
    mpu.stPushWord(SENTINEL - 1)
    mpu.pc = start
    for _ in range(100000):
        if mpu.pc in (until, SENTINEL):
            ram = bytearray(nes.ram)
            ram[0x100:0x100 + mpu.sp + 1] = bytes(mpu.sp + 1)
            # Bit 4 of P is not in the CPU, but PLP leaves it in py65's.
            return (bytes(ram), mpu.a, mpu.x, mpu.y, mpu.p & ~0x10,
                    nes.banks[6], nes.banks[7], nes.bank_select)
        mpu.step()
    raise AssertionError("the code from $%04X did not return" % start)


def sprites(rng):
    """A sprites' page crowded into a few bands, some off the screen, and
    counters already part way, as the indicators and the ball leave them."""
    ram = bytearray(rng.randrange(256) for _ in range(0x800))
    rows = [rng.randrange(256) for _ in range(rng.randint(1, 6))]
    for at in range(0x00, 0x100, 4):
        if rng.random() < 0.15:
            ram[CUR_SPRITE_Y + at] = rng.choice((0xF0, 0xF8, 0xFF))
        else:
            ram[CUR_SPRITE_Y + at] = (rng.choice(rows) + rng.randrange(-8, 9)) & 0xFF
    for band in range(16):
        ram[COUNTERS + band] = rng.choice((0, 0, 1, 2, 3, 7, 8, 9))
    ram[SPRITE_Y_OFFSET] = rng.randrange(16) if rng.random() < 0.85 else rng.randrange(256)
    ram[SPRITE_CYCLING_INDEX] = rng.randrange(256)
    return ram


def test_the_flicker_counts_as_the_games(pair):
    fast, slow = pair
    rng = random.Random(1990)
    offscreen = 0
    for _ in range(PASSES):
        ram = sprites(rng)
        a000_bank = rng.choice((21, 23, 28))
        select = rng.choice((0x06, 0x07, 0x46, 0x47))
        result = call(fast, bytes(ram), a000_bank, select)
        assert result == call(slow, bytes(ram), a000_bank, select)
        offscreen += sum(1 for at in range(0x10, 0xE0, 4)
                         if result[0][CUR_SPRITE_Y + at] == 0xF0 != ram[CUR_SPRITE_Y + at])
    assert offscreen > PASSES        # the counts did put sprites off the screen


# A session's buttons by tick, not by frame: the read for each tick gets
# that tick's, so the two ROMs, whose frames fall differently, play the
# same game. From the main menu: Table.to_game's presses, as ticks.
TO_GAME = [(90, 0, 0x80), (100, 0, 0x04), (40, 0, 0x80), (150, 0, 0x80),
           (60, 1, 0x01), (40, 1, 0x80)]


def tick_script(seed, play):
    script = []
    for wait, side, button in TO_GAME:
        script += [(0, 0)] * wait
        pads = [0, 0]
        pads[side] = button
        script += [tuple(pads)] * 3
    pads = moves(seed)
    script += [next(pads) for _ in range(play)]
    return script


class TickPads(Console):
    """A console whose controller, when the session reads it for a tick,
    has that tick's buttons for this console's player, whatever the table
    holds."""

    script = None

    def __init__(self, *args, **kwargs):
        self._tick_pads = None
        super().__init__(*args, **kwargs)
        self._read_tick = None
        self.watch("net_read_pad", TickPads._at_read)

    @property
    def pads(self):
        return self._tick_pads if self._tick_pads is not None else self._pads

    @pads.setter
    def pads(self, value):
        self._pads = value

    def _at_read(self):
        low = self.byte("net_read")
        if self._read_tick is None:
            self._read_tick = low
        self._read_tick += (low - self._read_tick) & 0xFF
        tick = self._read_tick
        player = self.byte("net_role")
        button = self.script[tick][player] if tick < len(self.script) else 0
        self._tick_pads = [button, 0]


@pytest.mark.parametrize("seed", [3])
def test_a_session_is_the_same_game_tick_by_tick(build, seed):
    """A session through the menus and a preseason game at random on each
    ROM, both players' buttons the same at each tick: the same game at
    every tick, however their frames fall."""
    play = 1500
    script = tick_script(seed, play)
    traces = []
    for name in ROMS:
        class Pads(TickPads):
            pass
        Pads.script = script

        def maker(**kwargs):
            return Pads(str(build / (name + ".nes")), str(build / (name + ".dbg")), **kwargs)
        table = Table(maker, delay=ms(10))
        table.start()
        table.run(len(script) + 200)
        assert table.same_game() > len(script) - 100
        for console in table.consoles:
            # In the game: Buffalo against Cleveland.
            assert (console.byte("P1_TEAM"), console.byte("P2_TEAM")) == (0x00, 0x06)
        traces.append(table.traces[0])
    shared = sorted(set(traces[0]) & set(traces[1]))
    assert len(shared) > len(script) - 100
    for tick in shared:
        assert traces[0][tick] == traces[1][tick], "the ROMs' games differ at tick %d" % tick


# The collision task's loop over the 11 defenders (bank 22): from where it
# sets their count (the netplay ROM's JMP net_coll) to its end.
COLL_START = 0x95E6
COLL_DONE = 0x9679
PLAYER_RAM = {1: 0x039F, 2: 0x04FF}     # PLAYER_1_RAM_START, PLAYER_2_RAM_START
PLAYER_SIZE = 0x20
X_POS, Y_POS = 0x13, 0x16
CURR_OFF_COLL_ADDR, CURR_DEF_COLL_ADDR = 0xBA, 0xBC
CURRENT_OFF_PLAYER = 0x41
CAN_COLLIDE = 0x068A                    # CAN_COLLIDE_STATUS_OFFENSE, 22 bytes each
COLLIDED = 0x06B6                       # COLLIDED_STATUS_OFFENSE


def players_close(rng):
    """Memory with the offense player at the pointer and the 11 defenders
    round it: some too far up or down, some too far across either way,
    some on it, across the high byte of X now and then."""
    ram = bytearray(rng.randrange(256) for _ in range(0x800))
    offense = rng.choice((1, 2))
    defense = 3 - offense
    player = rng.randrange(11)
    off = PLAYER_RAM[offense] + player * PLAYER_SIZE
    ram[CURR_OFF_COLL_ADDR:CURR_OFF_COLL_ADDR + 2] = off.to_bytes(2, "little")
    ram[CURR_DEF_COLL_ADDR:CURR_DEF_COLL_ADDR + 2] = PLAYER_RAM[defense].to_bytes(2, "little")
    ram[CURRENT_OFF_PLAYER] = 11 - player
    y = rng.randrange(256)
    x = rng.choice((rng.randrange(0x10000), rng.randrange(0xF8, 0x108) + 0x100 * rng.randrange(8)))
    ram[off + Y_POS + 1] = y
    ram[off + X_POS + 1:off + X_POS + 3] = (x & 0xFFFF).to_bytes(2, "little")
    for k in range(11):
        d = PLAYER_RAM[defense] + k * PLAYER_SIZE
        ram[d + Y_POS + 1] = (y + rng.randrange(-9, 10)) & 0xFF
        dx = x + rng.choice((rng.randrange(-10, 11), rng.randrange(-300, 300)))
        ram[d + X_POS + 1:d + X_POS + 3] = (dx & 0xFFFF).to_bytes(2, "little")
    for at in range(0x2C):
        ram[CAN_COLLIDE + at] = rng.choice((0xFF, 0x00, rng.randrange(256)))
        ram[COLLIDED + at] = rng.randrange(256)
    return ram


def test_the_collision_checks_check_as_the_games(pair):
    fast, slow = pair
    rng = random.Random(1991)
    met = 0
    for _ in range(PASSES):
        ram = players_close(rng)
        a000_bank = rng.choice((21, 23, 28))
        select = rng.choice((0x06, 0x07, 0x46, 0x47))
        result = call(fast, bytes(ram), a000_bank, select, COLL_START, COLL_DONE)
        assert result == call(slow, bytes(ram), a000_bank, select, COLL_START, COLL_DONE)
        met += sum(bin(result[0][COLLIDED + at] & ~ram[COLLIDED + at]).count("1")
                   for at in range(0x2C))
    assert met > PASSES // 2         # pairs did meet

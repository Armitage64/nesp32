"""The faster ROM against the original: the same game tick by tick, and
each of its passes (fast/) leaving what the game's leaves, on memory taken
from play and then shaken."""

import random

import pytest

from console import STACK
from drive import Player

RETURN = 0x0FF0                 # a return address no code is at
OBJECTS = 0x1A                  # the objects with sprites
ANIMATION_LO, ANIMATION_HI = 0x061A, 0x0634
POS_X, POS_Y = 0x064E, 0x0668


# The PPU's second buffer, its index and the upload's temporary: the IRQ
# at line 190 sends the buffer and empties it, once a frame, so a tick may
# find it sent or not by how long the last tick took; and the game reads
# the index (the scroll waits while the buffer is full), so its play
# depends on it. The original against itself with longer frames is
# another game from the first tick that finds it otherwise.
BUFFER_INDEX = 0x39
BUFFER = [BUFFER_INDEX, 0x56] + list(range(0x160, 0x1C0))


@pytest.mark.parametrize("two_players, seed, stage", [
    (False, 1, 0), (True, 2, 0), (False, 3, 2), (True, 4, 4)])
def test_the_same_game_tick_by_tick(console, fast_console, two_players, seed, stage):
    """From power-on, through the menu, into a stage: stage 1, which
    scrolls right, and stages 3 and 5, which scroll up. Before every tick
    the same RAM, less what runs to the picture's clock (the buffer
    among it where the two have sent it at other times, and then the
    faster ROM is given the original's); and the faster ROM no slower at
    the median."""
    original, fast = console(), fast_console()
    theirs, ours = (Player(nes, two_players, seed, stage=stage) for nes in (original, fast))
    hook = fast.on_vblank
    synced = []

    def given(nes):
        tick = len(ours.states)
        if nes.ctrl & 0x80 and not nes.ram[nes.labels["ram_nmi_flag_3"]] \
                and tick < len(their_rams):
            ram = their_rams[tick]
            # One of the two sent, the other not: the IRQ's, not the game's.
            if (ram[BUFFER_INDEX] == 0) != (nes.ram[BUFFER_INDEX] == 0):
                for address in BUFFER:
                    nes.ram[address] = ram[address]
                synced.append(tick)
        hook(nes)
    fast.on_vblank = given

    their_rams = []
    their_hook = original.on_vblank

    def kept(nes):
        before = len(theirs.states)
        their_hook(nes)
        if len(theirs.states) > before:
            their_rams.append(bytearray(nes.ram))
    original.on_vblank = kept

    theirs.to_play()
    theirs.run(500)
    ours.to_play()
    ours.run(len(theirs.states) - len(ours.states))
    assert ours.states == theirs.states[:len(ours.states)]
    assert len(synced) < len(ours.states) // 2
    played = [tick for tick, play in enumerate(theirs.played) if play][:-1]
    their_cycles, our_cycles = theirs.tick_cycles(), ours.tick_cycles()
    assert sorted(our_cycles[t] for t in played)[len(played) // 2] \
        < sorted(their_cycles[t] for t in played)[len(played) // 2]


def snapshots(nes, two_players, seed, every=7, count=40, stage=0):
    """The RAM, and the pair of banks in, at ticks of play, from a console
    of its own (`call` leaves one with the NMI off)."""
    player = Player(nes, two_players, seed, stage=stage)
    player.to_play()
    taken = []
    while len(taken) < count:
        player.run(every)
        taken.append((bytes(nes.ram), nes.ram[0x36]))
    return taken


def call(nes, address, ram, pair, x=0):
    """Run the routine at address on this RAM with this pair of banks in
    and X, until it returns: the game's switch first, which returns into
    the routine. The IRQ and the NMI are off. The RAM and the registers it
    leaves."""
    nes.ram[:] = ram
    mpu = nes.mpu
    mpu.p |= mpu.INTERRUPT
    nes.ctrl = 0
    nes.irq_on = False
    mpu.sp = 0xEF
    for target in (RETURN, address):
        nes.ram[0x100 + mpu.sp] = (target - 1) >> 8
        nes.ram[0x0FF + mpu.sp] = (target - 1) & 0xFF
        mpu.sp -= 2
    mpu.a, mpu.x = pair, x
    mpu.pc = nes.labels["sub_F34C_prg_bankswitch"]
    for _ in range(400000):
        if mpu.pc == RETURN:
            return bytearray(nes.ram), (mpu.a, mpu.x, mpu.y)
        mpu.step()
    raise AssertionError("no return from $%04X" % address)


def shaken(ram, rng):
    """The objects' places and looks moved about: X across the screen's
    edges, Y anywhere, flipped or not, in front of the background or
    behind, with and without their own palette; and the OAM's place, the
    frame (which object is first) and the characters."""
    ram = bytearray(ram)
    for slot in range(OBJECTS):
        ram[POS_X + slot] = rng.randrange(256)
        ram[POS_Y + slot] = rng.randrange(256)
        # In front or behind, and the palette: the sprite's own (0) or one
        # of three. The bits between pick the sprites' bank, kept.
        ram[ANIMATION_HI + slot] = (ram[ANIMATION_HI + slot] & 0x7C) \
            | rng.choice((0, 0x80)) | rng.randrange(4)
        if rng.random() < 0.2:
            ram[0x0600 + slot] = rng.randrange(256)     # another screen, most not shown
    ram[0x35] = rng.randrange(64) * 4
    ram[0x23] = rng.randrange(256)
    ram[0xC0] = rng.randrange(8)
    return ram


def test_the_sprite_pass_leaves_what_the_games_leaves(console, fast_console):
    original, fast = console(), fast_console()
    rng = random.Random(4)
    for two_players, seed in ((False, 3), (True, 4)):
        taken = snapshots(console(), two_players, seed)
        fast.run(5)                         # past the reset, which fills the PRG RAM
        for case, (ram, pair) in enumerate(taken * 8):
            ram = shaken(ram, rng)
            theirs, _ = call(original, original.labels["sub_D2D1"], ram, pair)
            ours, _ = call(fast, fast.labels["sub_D2D1"], ram, pair)
            for address in STACK:
                theirs[address] = ours[address] = 0
            assert ours == theirs, "case %d: %s" % (case, [
                "$%04X %02X/%02X" % (a, theirs[a], ours[a])
                for a in range(0x800) if theirs[a] != ours[a]][:12])


def test_the_background_test_leaves_what_the_games_leaves(console, fast_console):
    """sub_0x008FD0 at points about the screen, for an object of each kind
    (X), with bank 04's pair in as the game calls it, in every stage (each
    its own metatiles in the PRG RAM), and with what else it reads shaken:
    the picture's split (the indoor and the climbing stages'), the stage's
    scroll, and the background's CHR pair."""
    original, fast = console(), fast_console()
    rng = random.Random(5)
    probe = original.labels["sub_0x008FD0"]
    assert fast.labels["sub_0x008FD0"] == probe
    fast.run(5)
    for stage in range(5):
        taken = snapshots(console(), stage % 2 == 1, stage, every=11, count=12, stage=stage)
        for case, (ram, _) in enumerate(taken * 10):
            ram = bytearray(ram)
            ram[0x00] = rng.randrange(256)          # the point, from the object's place
            ram[0x01] = rng.randrange(256)
            if rng.random() < 0.5:
                ram[0x76] = rng.choice((1, 4, 5))   # ram_irq_handler
                ram[0xC5] = rng.choice((0, 0, rng.randrange(256)))
                for address in (0xA1, 0xAF, 0x61, 0xDD, 0x350, 0x351, 0x352):
                    ram[address] = rng.randrange(256)
                ram[0xA6] = rng.choice((0, 1, 2, rng.randrange(256)))
            if rng.random() < 0.2:
                ram[0x86] = rng.randrange(0x1B)     # ram_0086_table_index
            x = rng.choice((0, 1, 2, 5, 9, 12))
            results = [call(nes, probe, ram, 2, x) for nes in (original, fast)]
            (theirs, their_regs), (ours, our_regs) = results
            for address in STACK:
                theirs[address] = ours[address] = 0
            assert our_regs == their_regs, "stage %d case %d" % (stage + 1, case)
            assert ours == theirs, "stage %d case %d: %s" % (stage + 1, case, [
                "$%04X %02X/%02X" % (a, theirs[a], ours[a])
                for a in range(0x800) if theirs[a] != ours[a]][:12])

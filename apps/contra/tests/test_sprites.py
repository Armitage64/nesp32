"""The netplay ROM's sprite pass (bank 1, under NETPLAY) against the
original's: the same OAM buffer and the same RAM, on any memory. Its loop
over the sprite slots, its loop over a sprite's tiles and its hiding of
the unused ones do less for the same result, so that a frame has more
cycles to spare for the exchange."""

import random

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

"""The netplay ROM against the hack it is built from: the same game but for
the few places it changes, the same game for one on one console, and what
a session's exchange leaves of the frame."""

import pytest

from drive import MODE_GAME, PAD_START, moves, playing
from netplay import Table
from wire import ms

INES_HEADER = 16
BANK = 0x4000
FIXED_BANK = 3
SPLIT = 5900                    # about where the split under the status bar is raised


def prg_offset(bank, address, org):
    return INES_HEADER + bank * BANK + address - org


def test_the_netplay_rom_is_the_hack_but_for_its_hooks(build):
    """Every byte is the hack's but the header's, bank 1 (all $FF in the
    hack), the fixed bank's unused bytes (all 0), and the hooks, each the
    length of the instruction it replaces."""
    hack = (build / "baserom.nes").read_bytes()
    rom = (build / "smbx_net.nes").read_bytes()
    assert len(rom) == len(hack)
    labels = {}
    for line in (build / "smbx_net.dbg").read_text().splitlines():
        if line.startswith("sym\t") and ",val=" in line:
            fields = dict(field.split("=", 1) for field in line[4:].split(","))
            labels[fields["name"].strip('"')] = int(fields["val"], 16)
    allowed = set(range(4, INES_HEADER))
    allowed |= set(range(INES_HEADER + BANK, INES_HEADER + 2 * BANK))
    fixed = prg_offset(FIXED_BANK, labels["FIXED_FREE"], 0xC000)
    fixed_end = prg_offset(FIXED_BANK, labels["FIXED_FREE_END"], 0xC000)
    allowed |= set(range(fixed, fixed_end))
    hooks = (
        (2, labels["HOOK_TITLE_PAD"], 0x8000, 3),
        (FIXED_BANK, labels["HOOK_NMI_DRAW"], 0xC000, 3),
        (FIXED_BANK, labels["HOOK_NMI_PADS"], 0xC000, 9),
        (FIXED_BANK, labels["HOOK_RESET"], 0xC000, 3),
        (FIXED_BANK, labels["NMI_VECTOR"], 0xC000, 2),
    )
    for bank, address, org, length in hooks:
        start = prg_offset(bank, address, org)
        allowed |= set(range(start, start + length))
    changed = {offset for offset, (a, b) in enumerate(zip(hack, rom)) if a != b}
    assert changed and changed <= allowed
    assert set(hack[INES_HEADER + BANK:INES_HEADER + 2 * BANK]) == {0xFF}
    assert set(hack[fixed:fixed_end]) == {0}


def test_a_game_for_one_is_the_hacks(console, net_console):
    """With no session the netplay ROM is the hack: from power-on, through
    the title and a game for one, the game's memory is the same at every
    frame."""
    hack, ours = console(), net_console()
    script = [(0, 0)] * 100 + [(PAD_START, 0)] * 2
    buttons = moves(seed=2)
    script += [(next(buttons)[0], 0) for _ in range(900)]
    differ = []
    for frame, pads in enumerate(script):
        hack.run(1, pads=pads)
        ours.run(1, pads=pads)
        a, b = bytearray(hack.ram), bytearray(ours.ram)
        a[0x100:0x200] = b[0x100:0x200] = bytes(0x100)      # the stack
        if a != b:
            differ.append(frame)
    assert not differ
    assert ours.byte("OPER_MODE") == MODE_GAME


def test_the_exchange_is_over_well_before_the_split(net_console):
    """In a session the NMI makes the exchange with the IRQs held off, where
    the game read its controllers: it has to be over before the split
    under the status bar is raised, or the split would come late. On a
    nesp32 that answers at once, nearly every exchange, ticks and stalls
    alike, leaves a thousand cycles and more. The one in 128 that carries
    the console's report has a longer reply, and leaves less, but still
    some. The tick that takes the digest, once in 256, takes it with the
    IRQs let in, and goes on past the split, which comes when it
    should."""
    table = Table(net_console, delay=ms(20), input_delay=1)
    table.start()
    for _ in range(600):
        if all(playing(console) for console in table.consoles):
            break
        table.run(1)
    for console in table.consoles:
        console.mark("net_tick_sound")
        console.mark("net_nmi_stall")
        console.mark("net_digest")
    table.play(600, moves(seed=3))
    for console in table.consoles:
        digests = {frame for frame, _ in console.marks_of("net_digest")}
        assert digests
        ends = [cycle for frame, cycle in console.marks_of("net_tick_sound")
                if frame not in digests]
        ends += [cycle for _, cycle in console.marks_of("net_nmi_stall")]
        assert len(ends) > 500
        ends.sort()
        assert ends[int(len(ends) * 0.98)] < SPLIT - 900
        assert ends[-1] < SPLIT - 150
        for frame in digests:
            (raised, taken), = console.frames[frame].irqs
            assert console.scanline(taken) == console.scanline(raised)

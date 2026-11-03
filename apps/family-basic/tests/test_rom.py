"""Family BASIC V3 against nesp32's firmware, on a simulated console, typed
on through KBD."""

import nesp_proto as p
import pytest
from basic import RAM_OFF
from conftest import BASEROM
from console import MMC1_LAST_FIXED

import fbasic

RAM_CODE = 0x7000               # where fbkbd.s runs, in the cartridge's memory
RAM_END = 0x8000
BASIC_RAM = 0x6000              # the game's 4 KB


def started(b):
    b.run_until(lambda: "OK" in [row.strip() for row in b.rows()])
    return b


def link_cycles(frame):
    return getattr(frame, "link_cycles", 0)


def last_rows(b, count):
    """The last rows with anything on them."""
    return [row.strip() for row in b.rows() if row.strip()][-count:]


def test_it_starts_and_asks_for_the_keyboard(basic):
    b = started(basic())
    assert "NS-HUBASIC V3.0" in b.screen()
    assert "4086 BYTES FREE" in b.screen()
    assert b.stick.kbd_on
    hello = [payload for service, op, payload in b.requests()
             if service == p.NESP_SVC_SYS and op == p.NESP_SYS_HELLO]
    assert hello and hello[-1][1:5] == b"FBAS" and hello[-1][-1:] == bytes((p.NESP_SVC_KBD,))


def test_a_line_typed_is_run(basic):
    b = started(basic())
    b.enter("print 1+1")
    assert last_rows(b, 3) == ["PRINT 1+1", "2", "OK"]


def test_a_program_typed_lists_and_runs(basic):
    b = started(basic())
    b.enter('10 a$="hello":? a$;" world"')
    b.enter("20 for i=1 to 3:? i*11;:next")
    b.enter("list")
    assert last_rows(b, 5) == ['10 A$="HELLO":PRINT A$;" WOR', 'LD"',
                               "20 FOR I=1 TO 3:PRINT I*11;:", "NEXT", "OK"]
    b.enter("run", frames=30)
    assert last_rows(b, 3) == ["HELLO WORLD", "11 22 33", "OK"]


def test_every_sign_the_keyboard_has_is_typed_as_itself(basic):
    b = started(basic())
    signs = "!\"#$%&'()*+,-./:;<=>?@[]^_\\"
    b.type(signs)
    b.typed_out()
    b.run(2)
    assert last_rows(b, 1) == [signs]


def test_what_the_family_keyboard_has_no_key_for_is_dropped(basic):
    b = started(basic())
    b.type("a{|}~`b" + chr(p.NESP_KEY_TAB))
    b.typed_out()
    b.run(2)
    assert last_rows(b, 1) == ["AB"]


def test_backspace_deletes_and_the_arrows_move(basic):
    b = started(basic())
    # The game types over what is under the cursor.
    b.type("print 129" + chr(p.NESP_KEY_BACKSPACE) + "3")
    b.type(chr(p.NESP_KEY_LEFT) * 2 + "+" + chr(p.NESP_KEY_RIGHT) + "\n")
    b.typed_out()
    b.run(10)
    assert last_rows(b, 3) == ["PRINT 1+3", "4", "OK"]


def typed_line(b):
    """What is on the screen under BASIC's first OK: the line being typed."""
    rows = [row.strip() for row in b.rows()]
    return "".join(rows[rows.index("OK") + 1:])


def test_a_key_held_down_repeats_at_the_game_s_pace_and_stops_when_let_go(basic):
    b = started(basic())
    b.hold("x", 3000)
    let_go = typed_line(b)
    b.run(60)
    # 2.5 s of repeats, at the 15 a second the game takes, and no more than
    # one or two after the key is let go: the one the nesp32 kept, and the
    # one in the matrix.
    assert len(let_go) >= 30 and set(let_go) == {"X"}
    assert len(typed_line(b)) - len(let_go) <= 2


def test_backspace_held_down_stops_when_let_go(basic):
    b = started(basic())
    b.type("10 rem " + "abcdefghij" * 4)
    b.typed_out()
    b.hold(chr(p.NESP_KEY_BACKSPACE), 3000)
    let_go = typed_line(b)
    b.run(60)
    assert len(let_go) < 47 - 20
    assert len(let_go) - len(typed_line(b)) <= 2


def key(name):
    return chr(getattr(p, "NESP_KEY_" + name))


def test_the_function_keys_type_the_game_s_words(basic):
    b = started(basic())
    b.enter("10 ? 7*8")
    # F7 is LIST and F8 RUN, each with RETURN; a function key wants five
    # scans in a row.
    b.type(key("F7"))
    b.typed_out()
    b.run(10)
    assert last_rows(b, 3) == ["LIST", "10 PRINT 7*8", "OK"]
    b.type(key("F8"))
    b.typed_out()
    b.run(20)
    assert last_rows(b, 3) == ["RUN", "56", "OK"]


def test_delete_insert_home_and_shift_home(basic):
    b = started(basic())
    b.type("abcdef" + key("LEFT") * 3 + key("DELETE"))
    b.typed_out()
    b.run(3)
    assert last_rows(b, 1) == ["ABCEF"]         # the one under the cursor
    b.type(key("INSERT") + "x")
    b.typed_out()
    b.run(3)
    assert last_rows(b, 1) == ["ABCXEF"]
    b.type(key("HOME") + "q")
    b.typed_out()
    b.run(3)
    assert b.c.text(3, 2, 4) == "QS-H"         # CLR HOME: over the N of NS-HUBASIC
    b.type(key("SHIFT_HOME"))
    b.typed_out()
    b.run(5)
    assert b.screen().strip() == ""             # SHIFT and CLR HOME: the screen cleared


def test_f12_is_kana_and_alt_is_grph_in_it(basic):
    b = started(basic())
    b.type(key("F12") + "k" + key("WITH_ALT") + "a" + key("F12") + "k")
    b.typed_out()
    b.run(3)
    # K's kana, A's graphic with GRPH (the game has those in kana alone),
    # and K again.
    assert b.c.tiles(7, 2, 3) == bytes((0x80, 0x9C, ord("K")))


def test_ctrl_is_ctr(basic):
    b = started(basic())
    b.type(key("WITH_CTRL") + "l")             # CTR and L: the screen cleared
    b.typed_out()
    b.run(5)
    assert b.screen().strip() == ""


def test_escape_is_stop(basic):
    b = started(basic())
    b.enter("10 goto 10")
    b.enter("run", frames=30)
    assert "OK" not in last_rows(b, 1)
    b.type(chr(p.NESP_KEY_ESCAPE))
    b.typed_out()
    b.run(10)
    # The game's own "OK." after a break, as after a STOP in the program.
    assert last_rows(b, 2) == ["BREAK IN 10", "OK."]


def test_with_no_nesp32_it_starts_and_waits_for_one(basic):
    b = started(basic(attached=False))
    b.run(200)
    assert b.c.byte("fb_hello") == 0
    # A hello unanswered is tried again a second later, and each costs the
    # frame a receiver's wait.
    long = [frame for frame in b.c.frames[-200:] if link_cycles(frame) > 5000]
    assert 2 <= len(long) <= 5
    assert max(link_cycles(frame) for frame in b.c.frames[-200:]) < 15000


def test_the_link_costs_a_frame_little(basic):
    b = started(basic())
    b.run(60)
    idle = [link_cycles(frame) for frame in b.c.frames[-60:]]
    b.type("10 print 1234567890\n")
    b.typed_out()
    typing = [link_cycles(frame) for frame in b.c.frames[-60:]]
    # A KEYS with nothing typed is 7 bytes out and 8 back, and the
    # nesp32's time to answer: about 5000 cycles. One with keys is a byte
    # more for each. Asked every other frame while the game waits for a
    # key, so about 8% of the console's time.
    assert 3000 < max(idle) < 6000 and max(typing) < 9000
    assert sum(1 for cycles in idle if cycles > 1000) <= 31


def test_the_game_leaves_the_code_alone_and_only_boot_sets_the_mapper(basic):
    b = started(basic())
    c = b.c
    written = set()
    c.memory.subscribe_to_write(range(BASIC_RAM, RAM_END), lambda address, value: written.add(
        address) if not RAM_CODE <= c.mpu.pc < RAM_END else None)
    # Its 4 KB as full as it goes: two arrays of 961 numbers, and a 32nd
    # row of each is ?OM.
    b.enter("10 dim a(30,30),b(30,30):a(30,30)=-1:b(30,30)=-1:? \"full\"")
    b.enter("run", frames=40)
    assert last_rows(b, 2) == ["FULL", "OK"]
    assert 0x6F00 < max(written) < RAM_CODE
    labels = c.labels
    assert c.mapper_writes and all(
        labels["boot"] <= pc < labels["boot_nmi"] or labels["fb_start"] <= pc < labels["fb_nmi"]
        for pc, _, _ in c.mapper_writes)
    assert c.labels["fb_nmi_done"] < RAM_END and c.labels["fb_keys"] < RAM_END


@pytest.mark.parametrize("registers", [
    (MMC1_LAST_FIXED, RAM_OFF, RAM_OFF, RAM_OFF),     # the memory off
    (0, 0, 0, 0),                                     # the game's 32 KB, and its vector
    (0, RAM_OFF, RAM_OFF, 0),                         # and the memory off
], ids=["memory-off", "registers-0", "registers-0-memory-off"])
def test_it_starts_however_the_mmc1_comes_up(basic, registers):
    b = started(basic(registers=registers, ram_switch=True))
    b.enter("print 1+1")
    assert last_rows(b, 3) == ["PRINT 1+1", "2", "OK"]


def test_reset_is_the_game_s_with_the_keyboard_still_on(basic):
    b = started(basic())
    b.enter("10 ? 5")
    b.c.reset()
    b.run_until(lambda: "BASIC HOT START" in b.screen() and "OK" in last_rows(b, 1))
    assert "4079 BYTES FREE" in b.screen()     # the line kept
    b.enter("list")
    assert last_rows(b, 2) == ["10 PRINT 5", "OK"]


def test_the_patches_are_where_the_game_is_as_expected(rom):
    with open(rom[0], "rb") as handle:
        built = handle.read()
    prg = built[fbasic.INES_HEADER:fbasic.INES_HEADER + fbasic.PRG_SIZE]
    original = fbasic.Rom(BASEROM)
    changed = [fbasic.PRG_START + offset for offset in range(fbasic.PRG_SIZE)
               if prg[offset] != original.prg[offset]]
    sites = [range(address, address + len(old))
             for address, old in fbasic.PATCH_SITES.values()]
    assert changed and all(any(address in site for site in sites) for address in changed)
    assert built[fbasic.INES_HEADER + 2 * fbasic.PRG_SIZE:] == original.chr


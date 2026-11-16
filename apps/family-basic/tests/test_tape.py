"""SAVE and LOAD, to and from the nesp32's files (TAPE) in place of the
data recorder."""

import nesp_proto as p

HEADER = p.NESP_TAPE_HEADER
PROGRAM = 2
BASIC_RAM = 0x6000


def started(b):
    b.run_until(lambda: "OK" in [row.strip() for row in b.rows()])
    return b


def last_rows(b, count):
    return [row.strip() for row in b.rows() if row.strip()][-count:]


def until_ok(b, frames=600):
    """Run until the game has said OK after what was entered, as it does
    after an error too."""
    b.run_until(lambda: last_rows(b, 1) == ["OK"], frames=frames)


def saved(b, name="HELLO"):
    b.enter('10 a$="hello":? a$;" world"')
    b.enter("20 ? 6*7")
    b.enter('save "%s"' % name.lower())
    until_ok(b)
    return b.stick.file(name + ".fbp")


def test_save_keeps_the_program_as_a_file_named_for_it(basic):
    b = started(basic())
    kept = saved(b)
    assert last_rows(b, 3) == ['SAVE "HELLO"', "WRITING HELLO", "OK"]
    assert kept is not None and len(kept) > HEADER
    # The game ends a name shorter than 16 with a 0.
    assert kept[0] == PROGRAM and kept[1:17] == b"HELLO\0".ljust(16)
    length = kept[p.NESP_TAPE_LENGTH_AT] | kept[p.NESP_TAPE_LENGTH_AT + 1] << 8
    assert len(kept) == HEADER + length
    # The data block is the program as it is in memory, where the header says.
    start = kept[0x14] | kept[0x15] << 8
    assert BASIC_RAM <= start and bytes(b.c.memory[start:start + length]) == kept[HEADER:]


def test_load_has_it_back_after_a_power_off(basic):
    first = started(basic())
    kept = saved(first)
    b = started(basic())
    b.stick.put_file("HELLO.fbp", kept)
    b.enter('load "hello"')
    until_ok(b)
    assert last_rows(b, 3) == ['LOAD "HELLO"', "LOADING HELLO", "OK"]
    b.enter("run", frames=30)
    assert last_rows(b, 3) == ["HELLO WORLD", "42", "OK"]


def test_load_with_no_name_has_the_first_program(basic):
    b = started(basic())
    saved(b, "FIRST")
    b.enter("new")
    b.enter("load")
    until_ok(b)
    assert last_rows(b, 2) == ["LOADING FIRST", "OK"]
    b.enter("list")
    assert "20 PRINT 6*7" in last_rows(b, 3)


def test_load_of_a_name_there_is_none_of_is_tp_error(basic):
    b = started(basic())
    b.enter('load "none"')
    until_ok(b)
    assert last_rows(b, 2) == ["?TP ERROR", "OK"]


def test_load_question_checks_the_program_against_the_file(basic):
    b = started(basic())
    saved(b)
    b.enter('load? "hello"')
    until_ok(b)
    assert last_rows(b, 2) == ["LOADING HELLO", "OK"]
    b.enter("20 ? 6*8")
    b.enter('load? "hello"')
    until_ok(b)
    assert last_rows(b, 2) == ["?TP ERROR", "OK"]


def test_save_in_place_of_one_of_the_same_name(basic):
    b = started(basic())
    first = saved(b)
    b.enter("30 end")
    b.enter('save "hello"')
    until_ok(b)
    assert b.stick.file_names == ["HELLO.fbp"]
    assert len(b.stick.file("HELLO.fbp")) > len(first)


def test_save_that_cannot_be_written_is_tp_error(basic):
    b = started(basic())
    b.stick.fail_files()
    saved(b)
    assert last_rows(b, 3) == ["WRITING HELLO", "?TP ERROR", "OK"]


def test_the_keyboard_works_after_a_save(basic):
    b = started(basic())
    saved(b)
    b.enter("print 1+1")
    assert last_rows(b, 3) == ["PRINT 1+1", "2", "OK"]


def test_a_firmware_without_tape_has_the_keyboard_and_save_is_tp_error(basic):
    b = basic()
    b.stick.drop_service(p.NESP_SVC_TAPE)
    started(b)
    b.enter("print 1+1")
    assert last_rows(b, 3) == ["PRINT 1+1", "2", "OK"]
    assert b.c.byte("fb_tape") == 0
    b.enter("10 ? 1")
    b.enter('save "a"')
    until_ok(b)
    assert last_rows(b, 3) == ["WRITING A", "?TP ERROR", "OK"]

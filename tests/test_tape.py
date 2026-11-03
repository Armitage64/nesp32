"""TAPE, Family BASIC's data recorder as files, with no console: requests
in, replies out, and the test as the nesp32's flash."""

import nesp_proto as p
import pytest

TAPE = p.NESP_SVC_TAPE
HEADER = p.NESP_TAPE_HEADER
PROGRAM, SCREEN = 2, 3


@pytest.fixture
def tape(stick):
    assert stick.hello(services=[TAPE]).ok
    return stick


def header(kind, name, length):
    """A header block as the game writes one: its type, its name, and its
    data's length, and the rest whatever was in its buffer."""
    block = bytearray(b"\xEE" * HEADER)
    block[p.NESP_TAPE_TYPE_AT] = kind
    block[p.NESP_TAPE_NAME_AT:p.NESP_TAPE_NAME_AT + p.NESP_TAPE_NAME] = \
        name.ljust(p.NESP_TAPE_NAME)
    block[p.NESP_TAPE_LENGTH_AT:p.NESP_TAPE_LENGTH_AT + 2] = length.to_bytes(2, "little")
    return bytes(block)


def put(stick, pair, piece=120):
    for at in range(0, len(pair), piece):
        reply = stick.ask(TAPE, p.NESP_TAPE_PUT, at.to_bytes(2, "little") + pair[at:at + piece])
        assert reply.ok


def until_ended(stick, op, payload):
    """Ask, and tick, until the job has ended: its state."""
    for _ in range(4):
        reply = stick.ask(TAPE, op, payload)
        assert reply.ok and reply.payload[1] == payload[0]
        if reply.payload[0] != p.NESP_DECK_BUSY:
            return reply.payload[0]
        stick.tick(0)
    raise AssertionError("still busy")


def save(stick, pair, index=0, job=1):
    put(stick, pair)
    length = len(pair) - HEADER
    return until_ended(stick, p.NESP_TAPE_SAVE, bytes((job, index)) + length.to_bytes(2, "little"))


def find(stick, kind, name=None, index=0, job=2):
    """The state of a FIND, and the pair it found."""
    asked = bytes((job, kind, index)) + (b"" if name is None else name.ljust(p.NESP_TAPE_NAME))
    state = until_ended(stick, p.NESP_TAPE_FIND, asked)
    if state != p.NESP_DECK_DONE:
        return state, None
    pair = b""
    while True:
        reply = stick.ask(TAPE, p.NESP_TAPE_GET, len(pair).to_bytes(2, "little") + bytes((100,)))
        assert reply.ok
        if not reply.payload:
            return state, pair
        pair += reply.payload


def test_a_program_saved_is_a_file_named_for_it_and_found_again(tape):
    program = bytes(range(256)) * 3
    pair = header(PROGRAM, b"HELLO", len(program)) + program
    assert save(tape, pair) == p.NESP_DECK_DONE
    assert tape.file_names == ["HELLO.fbp"]
    assert tape.file("HELLO.fbp") == pair
    assert find(tape, PROGRAM, b"HELLO") == (p.NESP_DECK_DONE, pair)


def test_the_writing_is_done_after_the_reply(tape):
    put(tape, header(PROGRAM, b"A", 4) + b"10 ?")
    reply = tape.ask(TAPE, p.NESP_TAPE_SAVE, bytes((7, 0, 4, 0)))
    assert tuple(reply.payload) == (p.NESP_DECK_BUSY, 7)
    assert tape.file_writes == 0
    tape.tick(0)
    assert tape.file_writes == 1
    reply = tape.ask(TAPE, p.NESP_TAPE_SAVE, bytes((7, 0, 4, 0)))
    assert tuple(reply.payload) == (p.NESP_DECK_DONE, 7)
    tape.tick(0)
    assert tape.file_writes == 1        # the same id is asked after, not done again


def test_a_save_in_place_of_one_of_the_same_name(tape):
    assert save(tape, header(PROGRAM, b"A", 2) + b"xx", job=1) == p.NESP_DECK_DONE
    assert save(tape, header(PROGRAM, b"A", 1) + b"y", job=2) == p.NESP_DECK_DONE
    assert tape.file("A.fbp") == header(PROGRAM, b"A", 1) + b"y"


def test_a_screen_is_its_pairs_one_after_another(tape):
    pairs = [header(SCREEN, b"BG", 256) + bytes((page,)) * 256 for page in range(4)]
    for index, pair in enumerate(pairs):
        assert save(tape, pair, index=index, job=10 + index) == p.NESP_DECK_DONE
    assert tape.file_names == ["BG.fbg"]
    assert tape.file("BG.fbg") == b"".join(pairs)
    for index, pair in enumerate(pairs):
        assert find(tape, SCREEN, b"BG", index=index, job=20 + index) == (p.NESP_DECK_DONE, pair)
    assert find(tape, SCREEN, b"BG", index=4, job=30) == (p.NESP_DECK_NOT_FOUND, None)


def test_a_program_and_a_screen_may_have_one_name(tape):
    assert save(tape, header(PROGRAM, b"X", 1) + b"p", job=1) == p.NESP_DECK_DONE
    assert save(tape, header(SCREEN, b"X", 1) + b"s", job=2) == p.NESP_DECK_DONE
    assert tape.file_names == ["X.fbp", "X.fbg"]
    assert find(tape, SCREEN, b"X", job=3)[1].endswith(b"s")
    assert find(tape, PROGRAM, b"X", job=4)[1].endswith(b"p")


def test_no_such_file(tape):
    assert find(tape, PROGRAM, b"NONE") == (p.NESP_DECK_NOT_FOUND, None)
    assert tape.ask(TAPE, p.NESP_TAPE_GET, bytes((0, 0, 16))).status == p.NESP_ST_NOT_FOUND


def test_with_no_name_the_first_file_of_the_type(tape):
    tape.put_file("SCREEN.fbg", header(SCREEN, b"SCREEN", 1) + b"s")
    tape.put_file("FIRST.fbp", header(PROGRAM, b"FIRST", 1) + b"1")
    tape.put_file("SECOND.fbp", header(PROGRAM, b"SECOND", 1) + b"2")
    assert find(tape, PROGRAM) == (p.NESP_DECK_DONE, header(PROGRAM, b"FIRST", 1) + b"1")


def test_a_file_renamed_is_found_by_its_new_name(tape):
    tape.put_file("NEW.fbp", header(PROGRAM, b"OLD", 1) + b"!")
    state, pair = find(tape, PROGRAM, b"NEW")
    assert state == p.NESP_DECK_DONE
    assert pair == header(PROGRAM, b"NEW", 1) + b"!"


@pytest.mark.parametrize("name, file", [
    (b"HELLO WORLD", "HELLO WORLD.fbp"),
    (b"A\0", "A.fbp"),                       # as the game ends a short one
    (b"A \0X", "A.fbp"),
    (b"A/B:C*.D", "A%2FB%3AC%2A%2ED.fbp"),
    (b" LEAD", "%20LEAD.fbp"),
    (b"", "%20.fbp"),
    (b"100%", "100%25.fbp"),
    (b"\xB2a\x5C", "%B2%61%5C.fbp"),
    (b"0123456789ABCDEF", "0123456789ABCDEF.fbp"),
])
def test_a_name_is_made_one_a_filing_system_takes(tape, name, file):
    assert save(tape, header(PROGRAM, name, 1) + b"z") == p.NESP_DECK_DONE
    assert tape.file_names == [file]
    assert find(tape, PROGRAM, name, job=9)[0] == p.NESP_DECK_DONE


def test_what_is_not_a_pair_is_not_kept(tape):
    put(tape, header(PROGRAM, b"A", 5) + b"abcde")
    length = (4).to_bytes(2, "little")          # not what the header says
    assert until_ended(tape, p.NESP_TAPE_SAVE, bytes((1, 0)) + length) == p.NESP_DECK_FAILED
    too_long = (p.NESP_TAPE_DATA_MAX + 1).to_bytes(2, "little")
    assert tape.ask(TAPE, p.NESP_TAPE_PUT, (p.NESP_TAPE_HEADER + p.NESP_TAPE_DATA_MAX)
                    .to_bytes(2, "little") + b"!").status == p.NESP_ST_BAD_ARG
    put(tape, header(PROGRAM, b"A", p.NESP_TAPE_DATA_MAX + 1))
    assert until_ended(tape, p.NESP_TAPE_SAVE, bytes((2, 0)) + too_long) == p.NESP_DECK_FAILED
    assert tape.file_writes == 0


def test_a_write_that_fails_says_so(tape):
    tape.fail_files()
    assert save(tape, header(PROGRAM, b"A", 1) + b"!") == p.NESP_DECK_FAILED


def test_a_board_with_no_files(tape):
    tape.files_absent()
    assert save(tape, header(PROGRAM, b"A", 1) + b"!") == p.NESP_DECK_FAILED
    assert find(tape, PROGRAM, b"A", job=5) == (p.NESP_DECK_FAILED, None)


def test_one_job_at_a_time(tape):
    put(tape, header(PROGRAM, b"A", 1) + b"!")
    assert tape.ask(TAPE, p.NESP_TAPE_SAVE, bytes((1, 0, 1, 0))).payload[0] == p.NESP_DECK_BUSY
    asked = bytes((2, PROGRAM, 0)) + b"A".ljust(16)
    assert tape.ask(TAPE, p.NESP_TAPE_FIND, asked).status == p.NESP_ST_BUSY
    assert tape.ask(TAPE, p.NESP_TAPE_PUT, b"\x00\x00!").status == p.NESP_ST_BUSY
    tape.tick(0)
    assert tape.ask(TAPE, p.NESP_TAPE_FIND, asked).payload[0] == p.NESP_DECK_BUSY


def test_a_hello_forgets_the_job(tape):
    assert save(tape, header(PROGRAM, b"A", 1) + b"!", job=1) == p.NESP_DECK_DONE
    assert tape.hello(services=[TAPE]).ok
    put(tape, header(PROGRAM, b"A", 1) + b"?")
    # The same id after a hello is a new job: a reset console counts again.
    assert until_ended(tape, p.NESP_TAPE_SAVE, bytes((1, 0, 1, 0))) == p.NESP_DECK_DONE
    assert tape.file("A.fbp").endswith(b"?")


def test_bad_requests(tape):
    assert tape.ask(TAPE, p.NESP_TAPE_PUT, b"\x00").status == p.NESP_ST_BAD_ARG
    assert tape.ask(TAPE, p.NESP_TAPE_SAVE, b"\x01\x00\x01").status == p.NESP_ST_BAD_ARG
    assert tape.ask(TAPE, p.NESP_TAPE_FIND, b"\x01\x02\x00AB").status == p.NESP_ST_BAD_ARG
    assert tape.ask(TAPE, p.NESP_TAPE_GET, b"\x00\x00").status == p.NESP_ST_BAD_ARG
    assert tape.ask(TAPE, 0x7F).status == p.NESP_ST_NO_OP

"""The link itself: the console's library on a ROM, the firmware's link and
services, and a cycle-exact line between them. How soon and how late the
Stick may answer, a clock that is out, a line that loses and damages bytes,
and both of the library's receivers and both of its CRCs.

The ROM is the setup ROM on its link test: a request every frame, each
checked byte for byte, with replies of up to 55 bytes.
"""

import random

import nesp
import nesp_proto as p
import pytest
from drive import MENU_TEST, STATE_STATUS, STATE_TEST, Setup
from nesp import Stick
from wire import link, ms

FRAMES = 200


def counts(c):
    """The link test's counts: sent, good, no reply, wrong."""
    return tuple(c.byte("test_counts", 2 * index) | c.byte("test_counts", 2 * index + 1) << 8
                 for index in range(4))


def accounted(c):
    """Every request sent is counted good, missing or wrong, but for one
    that a vblank has just cut off and the ROM has yet to count."""
    sent, good, silent, wrong = counts(c)
    return 0 <= sent - (good + silent + wrong) <= 1


def run_test(make, frames=FRAMES, poll_every=None, **port_options):
    """The link test for some frames. Returns (console, stick, port)."""
    c = make()
    stick, port = link(c, Stick, **port_options)
    if poll_every is not None:
        c.host_every = poll_every
    s = Setup(c, stick, port)
    c.run_until(lambda: c.byte("linked"), 300)
    s.menu(MENU_TEST)
    s.wait_for(STATE_TEST)
    c.run(frames)
    return c, stick, port


@pytest.fixture(params=["nmi", "timeout"])
def rom(request, console, timeout_console):
    """Both builds of the ROM: the receiver the NMI ends with the CRC worked
    out in code, and the receiver that counts with the CRC from a table."""
    return console if request.param == "nmi" else timeout_console


def test_a_clean_line_loses_nothing(rom):
    c, stick, _ = run_test(rom)
    sent, good, silent, wrong = counts(c)
    assert sent >= FRAMES - 8 and good == sent and (silent, wrong) == (0, 0)
    assert stick.repeats == 0 and stick.dropped == 0


@pytest.mark.parametrize("error", [-0.015, 0.015])
def test_a_stick_whose_clock_is_out(rom, error):
    c, _, _ = run_test(rom, clock_error=error)
    sent, good, silent, wrong = counts(c)
    assert good == sent and (silent, wrong) == (0, 0)


@pytest.mark.parametrize("delay", [0, 7, 14, 21, 29])
def test_every_phase_of_the_nmi_against_the_frame(console, delay):
    def make():
        return console(nmi_delay=delay)
    c, _, _ = run_test(make, frames=60)
    sent, good, silent, wrong = counts(c)
    assert good == sent and (silent, wrong) == (0, 0)


def test_how_soon_the_stick_may_answer(rom):
    """The firmware waits MIN_TURNAROUND after a request before it answers.
    This is what that has to cover: the console is still on its way from
    sending to listening."""
    def works(microseconds):
        c, _, _ = run_test(rom, frames=40, poll_every=5,
                           turnaround=ms(microseconds / 1000))
        sent, good, _, _ = counts(c)
        return good == sent
    assert works(40)                    # documented: no sooner than 40 us
    assert works(100) and works(1000)


def test_how_late_the_stick_may_answer(console):
    """The longest exchange here is 10 bytes out and 55 back. With the NMI
    it leaves the Stick a little over 5 ms; a reply that runs into the next
    vblank is cut off, counted as missing, and asked for afresh."""
    def missing(milliseconds):
        c, _, port = run_test(console, frames=10)
        port.turnaround = ms(milliseconds)      # once the hello is over
        c.run(120)
        sent, good, silent, wrong = counts(c)
        assert wrong == 0 and accounted(c)
        return silent
    assert missing(3.0) == 0
    assert missing(4.5) == 0
    assert missing(9.0) > 30            # the longer replies no longer fit
    assert missing(16.0) > 100          # nor does anything


def test_a_stick_that_answers_late_is_not_taken_for_the_next_reply(console):
    # Replies that arrive a frame late land while the console waits for the
    # answer to its next request. Their sequence number is the old one.
    c, stick, port = run_test(console, frames=20)
    _, good, _, _ = counts(c)
    port.turnaround = ms(17.5)
    c.run(150)
    sent, still_good, silent, wrong = counts(c)
    assert wrong == 0 and accounted(c)
    assert still_good - good <= 1 and silent >= 140


def test_a_line_that_damages_replies_never_passes_one_off_as_good(rom):
    generator = random.Random(5)
    spoiled = [0]

    def damage(data):
        if generator.random() < 0.3:
            spoiled[0] += 1
            data = bytearray(data)
            for _ in range(generator.choice((1, 1, 2, 3, 8))):
                data[generator.randrange(len(data))] ^= 1 << generator.randrange(8)
        return bytes(data)

    c, _, _ = run_test(rom, frames=400, to_console=damage)
    sent, good, silent, wrong = counts(c)
    assert wrong == 0 and accounted(c)
    assert abs(silent - spoiled[0]) <= 8        # but for the requests for counters


def test_a_line_that_damages_requests(rom):
    c = rom()
    stick, port = link(c, Stick)
    generator = random.Random(6)
    heard = port.read

    def damaged():
        # The UART's bytes come one or two at a time: about one request in
        # four has a byte with a bit wrong.
        data = heard()
        if data and generator.random() < 0.03:
            data = bytearray(data)
            data[generator.randrange(len(data))] ^= 1 << generator.randrange(8)
            return bytes(data)
        return data

    port.read = damaged
    s = Setup(c, stick, port)
    c.run_until(lambda: c.byte("linked"), 400)
    s.menu(MENU_TEST)
    s.wait_for(STATE_TEST, 400)
    c.run(300)
    sent, good, silent, wrong = counts(c)
    # A request that arrives wrong is not answered. Not one is acted on as
    # something else: the Stick would have said the pattern was wrong.
    assert wrong == 0 and accounted(c) and silent > 40


def test_a_stick_that_is_unplugged_in_the_test_is_counted_missing_not_wrong(console):
    c, stick, port = run_test(console, frames=50)
    port.deaf = True
    c.run(100)
    sent, good, silent, wrong = counts(c)
    assert wrong == 0 and silent >= 95
    port.deaf = False
    c.run(50)
    assert counts(c)[1] >= good + 45        # and it carries on


def test_a_stick_switched_off_and_on_in_the_test_is_greeted_again(console):
    c, stick, port = run_test(console, frames=50)
    fresh = Stick(port)
    c.host = fresh.poll
    c.run_until(lambda: c.byte("state") == STATE_STATUS, 60)
    c.run_until(lambda: fresh.hellos == 1, 200)
    assert fresh.active(p.NESP_SVC_DIAG)


def test_the_console_and_the_firmware_make_the_same_pattern(console):
    c = console()
    for seed in (1, 0xACE1, 0xFFFF, 0x8000):
        c.memory[c.labels["nesp_rng"]] = seed & 0xFF
        c.memory[c.labels["nesp_rng"] + 1] = seed >> 8
        made = bytes(c.call("nesp_pattern").a for _ in range(64))
        assert made == nesp.pattern(seed, 64)


def test_the_console_and_the_firmware_make_the_same_crc(rom):
    generator = random.Random(9)
    for length in (0, 1, 9, 24):
        c = rom()
        payload = bytes(generator.randrange(256) for _ in range(length))
        expected = nesp.frame(0x12, 0x34, 0x56, payload)
        start = c.labels["nesp_tx"]
        for offset, byte in enumerate(expected[:-2]):
            c.memory[start + offset] = byte
        c.memory[c.labels["nesp_ptr"]] = start & 0xFF
        c.memory[c.labels["nesp_ptr"] + 1] = start >> 8
        mpu = c.call("nesp_sum")
        assert bytes((c.byte("nesp_crc_hi"), c.byte("nesp_crc_lo"))) == expected[-2:]
        assert mpu.y == len(expected) - 2       # where the frame's own two go

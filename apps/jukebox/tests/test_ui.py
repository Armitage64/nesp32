"""The screen and the controller, on both ROMs.

The harness's PPU is its address register and memory, which is enough to
read back what the ROM drew and to time its writes against vblank. What the
picture looks like is tools/gen_ui.py's business; here the nametable is
compared with what that tool laid out.
"""

import glob
import itertools
import os
import random

import nesp_proto as p
import pytest

import gen_ui
import jbs
import vgm
import vgm2jbs
from link_harness import LinkConsole, ms
from linked import (LINK_STOPPED, files, flip_random_bit, frames_of, greet, press, short_track,
                    start, track_stream, wait_for)
from nes_harness import (PAD_A, PAD_B, PAD_LEFT, PAD_RIGHT, PAD_START, VBLANK_CYCLES,
                         Console, expected_frames)

ROOT = os.path.join(os.path.dirname(__file__), "..")
RIPS = sorted(glob.glob(os.path.join(ROOT, "music", "*.vg[mz]")))

# Every PPU write must land inside vblank, with room for the NMI being late
# by an instruction and for the scroll writes that follow.
PPU_WRITE_BUDGET = VBLANK_CYCLES - 300


@pytest.fixture(scope="session")
def demo(build):
    return jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())


def title_line(machine):
    return machine.screen_text(gen_ui.TITLE_COLUMN, gen_ui.TITLE_ROW, gen_ui.TITLE_MAX)


def game_line(machine):
    return machine.screen_text(gen_ui.GAME_COLUMN, gen_ui.GAME_ROW, gen_ui.TITLE_MAX)


def time_line(machine):
    return machine.screen_text(gen_ui.TIME_COLUMN, gen_ui.TIME_ROW,
                               len(gen_ui.TIME_TEMPLATE)).strip()


def status_line(machine):
    return machine.screen_text(gen_ui.STATUS_COLUMN, gen_ui.STATUS_ROW,
                               gen_ui.STATUS_WIDTH).strip()


def bar_tiles(machine, bar):
    """The tiles of one bar on the screen, top first."""
    names = machine.nametable()
    return [names[32 * (gen_ui.BAR_ROW + row) + gen_ui.BAR_COLUMN + bar]
            for row in range(gen_ui.BAR_ROWS)]


def bar_height(machine, bar):
    """A bar's height on the screen, in pixels."""
    return sum(tile - gen_ui.TILE_BAR for tile in bar_tiles(machine, bar))


def lit_bars(machine):
    return {bar for bar in range(gen_ui.BAR_COUNT) if bar_height(machine, bar)}


def song_of(frames, title=None, loop_frame=None):
    """(stream, loop offset) for load_song, with its names and length in
    front as a host sends them."""
    encoded = jbs.encode(frames, loop_frame)
    intro = jbs.intro(title, len(frames)) if title is not None else b""
    loop_offset = len(intro) + encoded.loop_offset if loop_frame is not None else None
    return intro + encoded.data, loop_offset


def play(rom, frames, nmis, **kwargs):
    machine = Console(*rom)
    machine.load_song(*song_of(frames, **kwargs))
    machine.run(nmis)
    return machine


# -- the screen ----------------------------------------------------------------

def test_the_screen_is_the_one_the_generator_laid_out(rom, link_rom):
    link, standalone = gen_ui.build_screens()
    for paths, screen, help_text in ((rom, standalone, gen_ui.HELP_STANDALONE),
                                     (link_rom, link, gen_ui.HELP_LINK)):
        machine = Console(*paths) if paths is rom else LinkConsole(*paths)
        machine.run(1)
        # Nothing has been drawn over it yet but the status line.
        expected = bytearray(screen.nametable())
        start = 32 * gen_ui.STATUS_ROW + gen_ui.STATUS_COLUMN
        got = bytearray(machine.nametable())
        got[start:start + gen_ui.STATUS_WIDTH] = expected[start:start + gen_ui.STATUS_WIDTH]
        assert got == expected
        assert help_text in machine.screen_text(0, gen_ui.HELP_ROW, 32)
        credit = machine.nametable()[32 * gen_ui.CREDIT_ROW:32 * gen_ui.CREDIT_ROW + 32]
        assert sum(tile >= gen_ui.TILE_LOGO for tile in credit) >= 8   # the small print
        palette = bytes(machine.vram[0x3F00:0x3F10])
        assert palette[0] == gen_ui.BACKDROP
        assert [tuple(palette[4 * n + 1:4 * n + 4]) for n in range(4)] == list(gen_ui.PALETTES)
        assert machine.memory[0x2001] == 0x0A       # background on, sprites off


def test_every_character_of_a_title_has_a_tile():
    screen, _ = gen_ui.build_screens()
    data = screen.chr()
    blank = bytes(16)
    for code in range(0x21, 0x7F):
        assert data[code * 16:code * 16 + 16] != blank, chr(code)
    # Lowercase is drawn with the capitals.
    assert data[ord("a") * 16:ord("a") * 16 + 16] == data[ord("A") * 16:ord("A") * 16 + 16]


def test_the_embedded_song_shows_its_title_and_status(rom):
    machine = Console(*rom)
    machine.run_until_played(30)
    assert game_line(machine).strip() == "NESP32 Jukebox"
    assert title_line(machine).strip() == "Demo Arpeggio"
    assert time_line(machine) == "0:00 / -:--"       # it loops: no length to show
    assert status_line(machine) == ""


def test_a_title_is_centered_and_replaced_by_the_next(rom):
    frames = [[(0x15, 0x0F)], [], []]
    first, _ = song_of(frames, title="Game - One")
    second, _ = song_of(frames, title="A much longer second title")
    machine = Console(*rom)
    machine.load_song(first + second)
    machine.run(5)
    assert game_line(machine) == "Game".center(gen_ui.TITLE_MAX)
    assert title_line(machine) == "One".center(gen_ui.TITLE_MAX)
    machine.run(8)
    assert game_line(machine) == " " * gen_ui.TITLE_MAX     # no game: the line clears
    assert title_line(machine) == "A much longer second title".center(gen_ui.TITLE_MAX)
    assert machine.byte("stream_error") == 0


def test_a_song_without_a_loop_ends_with_the_end(rom):
    machine = play(rom, [[(0x15, 0x0F)], [(0x00, 0xBF), (0x03, 0x08)], []], 12, title="Short")
    assert machine.byte("ended") == 1
    assert status_line(machine) == "THE END"


def test_a_title_too_long_for_the_line_is_a_stream_error(rom):
    machine = Console(*rom)
    machine.load_song(bytes([0x80, 0x03, 29]) + b"x" * 29 + jbs.encode([[(0x15, 0x0F)]]).data)
    machine.run(5)
    assert machine.byte("stream_error") == 1


@pytest.mark.parametrize("seed", range(4))
def test_a_title_split_across_top_ups_is_drawn_whole(rom, seed):
    # NMIs this close together starve the ring, so a title record is often
    # only partly there when the NMI reaches it. It must then wait, as a
    # frame's writes do, and never be drawn from half of its text. The loop
    # here is title after title, so most of them arrive in pieces.
    rng = random.Random(seed)
    titles = ["A" * gen_ui.TITLE_MAX, "B" * gen_ui.TITLE_MAX]
    stream = bytes([jbs.OP_CONTROL, jbs.CTRL_INIT])
    for index in range(40):
        stream += jbs.intro(titles[index % 2], 60 * (index + 1))
        stream += jbs.encode_record([(0x00, 0x30 | index % 16)])
    loop_offset = 2
    machine = Console(*rom)
    machine.load_song(stream, loop_offset)
    shown = set()
    while len(machine.played_frames()) < 300 and len(machine.frames) < 20000:
        machine.run(7, period=lambda: rng.randint(20, 400))
        shown.add(title_line(machine))
    assert machine.word("underruns") > 0
    blank = chr(gen_ui.TILE_BLANK) * gen_ui.TITLE_MAX      # before the first title
    assert shown - {blank} == set(titles)
    played = machine.played_frames()
    assert played == list(itertools.islice(expected_frames(stream, loop_offset), len(played)))
    assert machine.byte("stream_error") == 0


def test_ppu_writes_stay_inside_vblank(rom):
    machine = Console(*rom)
    machine.run_until_played(900)
    assert 0 < max(machine.ppu_write_offsets) < PPU_WRITE_BUDGET


@pytest.mark.skipif(not RIPS, reason="no rips in music/")
@pytest.mark.parametrize("path", RIPS, ids=os.path.basename)
def test_rips_draw_inside_vblank_and_move_the_bars(rom, path):
    song, _ = vgm2jbs.convert(vgm.load(path))
    intro = jbs.intro(song.title, song.total_frames)
    machine = Console(*rom)
    machine.load_song(intro + song.stream,
                      len(intro) + song.loop_offset if song.loop_frame is not None else None)
    seen = set()
    for _ in range(40):
        machine.run(30)
        seen |= lit_bars(machine)
    assert max(machine.ppu_write_offsets) < PPU_WRITE_BUDGET
    assert (game_line(machine).strip(), title_line(machine).strip()) == jbs.split_title(song.title)
    assert len(seen) >= 6       # real music moves around the display
    assert machine.byte("stream_error") == 0 and machine.word("underruns") == 0


# -- the clock -----------------------------------------------------------------

def test_the_clock_counts_the_frames_played_against_the_length(rom):
    frames = [[(0x15, 0x0F)]] + [[]] * (60 * 75)
    machine = play(rom, frames, 6, title="Game - Long")    # a vblank per line
    assert time_line(machine) == "0:00 / 1:15"
    machine.run(60 * 9)
    assert time_line(machine) == "0:09 / 1:15"
    machine.run(60 * 62)
    assert time_line(machine) == "1:11 / 1:15"
    machine.run(60 * 10)            # the song ends, and the clock with it
    assert machine.byte("ended") == 1 and time_line(machine) == "1:15 / 1:15"
    assert max(machine.ppu_write_offsets) < PPU_WRITE_BUDGET


def test_the_clock_starts_over_with_each_track_and_stops_when_paused(rom):
    frames = [[(0x15, 0x0F)]] + [[]] * 150
    first, _ = song_of(frames, title="One")
    second, _ = song_of(frames, title="Two")
    machine = Console(*rom)
    machine.load_song(first + second)
    machine.run(140)                # the standalone ROM plays from its first NMI
    assert time_line(machine) == "0:02 / 0:02"
    machine.run(85)                 # 151 frames of One, then 74 of Two
    assert title_line(machine).strip() == "Two" and time_line(machine) == "0:01 / 0:02"
    machine.pad = PAD_START
    machine.run(3)
    machine.pad = 0
    machine.run(200)
    assert time_line(machine) == "0:01 / 0:02"


def test_no_clock_shows_without_a_length(rom):
    machine = play(rom, [[(0x15, 0x0F)]] + [[]] * 200, 150)
    assert time_line(machine).strip("\x00") == ""


# -- the bars ------------------------------------------------------------------

A440 = 0x0FD    # a pulse period: 111860.8 / (253 + 1) = 440 Hz


def test_a_pulse_note_lights_the_bar_for_its_pitch_to_its_volume(rom):
    bar = gen_ui.pulse_column(A440)
    note = [(0x15, 0x0F), (0x00, 0xBF), (0x02, A440 & 0xFF), (0x03, A440 >> 8)]
    machine = play(rom, [note] + [[]] * 40, 20)
    assert lit_bars(machine) == {bar}
    assert bar_tiles(machine, bar) == [gen_ui.TILE_BAR + 8] * gen_ui.BAR_ROWS

    quiet = play(rom, [note, [(0x00, 0xB4)]] + [[]] * 40, 40)   # volume 4 of 15
    assert bar_height(quiet, bar) == 4 * 4 + 4


def test_a_bar_falls_when_its_note_is_silenced(rom):
    bar = gen_ui.pulse_column(A440)
    note = [(0x15, 0x0F), (0x00, 0xBF), (0x02, A440 & 0xFF), (0x03, A440 >> 8)]
    machine = play(rom, [note] + [[]] * 10 + [[(0x00, 0xB0)]] + [[]] * 80, 22)
    heights = []
    for _ in range(12):
        machine.run(4)
        heights.append(bar_height(machine, bar))
    assert heights == sorted(heights, reverse=True) and heights[0] > heights[4] > 0
    assert heights[-1] == 0 and lit_bars(machine) == set()


def test_a_note_cut_off_by_its_length_counter_stops_on_the_screen_too(rom):
    bar = gen_ui.pulse_column(A440)
    # Length index 3 is one frame. With the halt flag clear the console
    # stops the note there, though its volume register still says 15.
    cut = [(0x15, 0x0F), (0x00, 0x9F), (0x02, A440 & 0xFF), (0x03, 0x18 | A440 >> 8)]
    held = [(0x15, 0x0F), (0x00, 0xBF), (0x02, A440 & 0xFF), (0x03, 0x18 | A440 >> 8)]
    assert bar_height(play(rom, [cut] + [[]] * 80, 60), bar) == 0
    assert bar_height(play(rom, [held] + [[]] * 80, 60), bar) == gen_ui.BAR_MAX


def test_a_channel_turned_off_in_4015_stops_on_the_screen_too(rom):
    bar = gen_ui.pulse_column(A440)
    note = [(0x15, 0x0F), (0x00, 0xBF), (0x02, A440 & 0xFF), (0x03, A440 >> 8)]
    machine = play(rom, [note] + [[]] * 5 + [[(0x15, 0x0E)]] + [[]] * 80, 70)
    assert bar_height(machine, bar) == 0


def test_an_envelope_falls_by_itself(rom):
    bar = gen_ui.pulse_column(A440)
    # Envelope period 3: the console's volume falls from 15 by one a frame.
    note = [(0x15, 0x0F), (0x00, 0x83), (0x02, A440 & 0xFF), (0x03, A440 >> 8)]
    machine = play(rom, [note] + [[]] * 80, 6)
    early = bar_height(machine, bar)
    machine.run(40)
    assert early > 30 and bar_height(machine, bar) == 0


def test_the_triangle_sits_an_octave_below_and_the_noise_by_its_period(rom):
    triangle = [(0x15, 0x0F), (0x08, 0xFF), (0x0A, A440 & 0xFF), (0x0B, A440 >> 8)]
    machine = play(rom, [triangle] + [[]] * 40, 20)
    bar = gen_ui.pulse_column(A440) - gen_ui.TRIANGLE_SHIFT
    assert lit_bars(machine) == {bar} and bar_height(machine, bar) == 11 * 4 + 4

    noise = [(0x15, 0x0F), (0x0C, 0x3F), (0x0E, 0x05), (0x0F, 0x00)]
    machine = play(rom, [noise] + [[]] * 40, 20)
    assert lit_bars(machine) == {gen_ui.noise_columns()[5]}


def test_a_triangle_note_ends_with_its_linear_counter(rom):
    bar = gen_ui.pulse_column(A440) - gen_ui.TRIANGLE_SHIFT
    # Control flag clear, reload 8: the linear counter runs out in 2 frames.
    short = [(0x15, 0x0F), (0x08, 0x08), (0x0A, A440 & 0xFF), (0x0B, A440 >> 8)]
    assert bar_height(play(rom, [short] + [[]] * 80, 50), bar) == 0


def test_pitches_spread_across_the_display():
    low, high = gen_ui.period_tables()
    columns = [low[p] if p < 256 else high[p >> 3] for p in range(8, 0x800)]
    assert columns == sorted(columns, reverse=True)     # longer period, lower bar
    assert columns[-1] <= 3 and columns[0] == gen_ui.BAR_COUNT - 1
    for period in range(8, 0x800):                      # the coarse table is close
        assert abs(columns[period - 8] - gen_ui.pulse_column(period)) <= 1


# -- the controller, standalone ROM ---------------------------------------------

def test_start_pauses_and_resumes_the_standalone_rom(rom):
    machine = Console(*rom)
    machine.run_until_played(100)
    machine.pad = PAD_START
    machine.run(10)                 # held: it must count as one press
    machine.pad = 0
    paused_at = len(machine.frames)
    machine.run(60)
    assert status_line(machine) == "PAUSED"
    writes = [writes for writes, _, _ in machine.frames[paused_at:]]
    assert all(not frame for frame in writes)
    assert [(0x15, 0x00)] in [writes for writes, _, _ in machine.frames[paused_at - 10:paused_at]]

    machine.pad = PAD_START
    machine.run(2)
    machine.pad = 0
    machine.run(40)
    assert status_line(machine) == ""
    assert machine.byte("paused") == 0
    assert any(frame for frame, _, _ in machine.frames[-30:])
    assert machine.byte("stream_error") == 0


# -- the controller and the status line, link ROM -------------------------------

LOOPS = 50
BUTTON = (p.NESP_SVC_JUKE, p.NESP_JUKE_BUTTON)
NEXT, PREVIOUS, PLAY = p.NESP_PRESS_NEXT, p.NESP_PRESS_PREVIOUS, p.NESP_PRESS_PLAY


def link_machine(link_rom, demo, begin=True, **options):
    """A console on the link ROM, and a nesp32 with two tracks. Playing,
    unless begin is False."""
    tracks = [("First track", demo), ("Second track", short_track())]
    machine = LinkConsole(*link_rom, tracks=files(tracks), loops=LOOPS, **options)
    machine.streams = [track_stream(title, track, LOOPS) for title, track in tracks]
    if begin:
        start(machine)
    return machine


def button_requests(machine):
    """What the controller asked for, as the nesp32 heard it: a press that
    had to be sent again is there again."""
    return [payload[0] for service, op, payload in machine.requests()
            if (service, op) == BUTTON]


def test_the_status_line_follows_the_link(link_rom, demo):
    machine = LinkConsole(*link_rom, attached=False)
    machine.run(12)
    assert status_line(machine) == "WAITING FOR LINK"

    machine = link_machine(link_rom, demo, begin=False)
    machine.run(12)
    assert status_line(machine) == "PRESS START"
    press(machine, PAD_START)
    machine.run(8)
    assert status_line(machine) == "LOADING"
    machine.run_until_played(10)
    machine.run(2)
    assert status_line(machine) == ""
    assert title_line(machine).strip() == "First track"


def test_the_status_line_says_what_is_wrong_with_the_nesp32(link_rom):
    import nesp

    machine = LinkConsole(*link_rom)                # a nesp32 with no files
    machine.run(12)
    assert status_line(machine) == "NO MUSIC FOUND"

    def old(reply):                                 # one with no JUKE service
        answer = nesp.parse(reply)
        if answer.svc == p.NESP_SVC_SYS:
            return nesp.reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, answer.seq,
                                    answer.payload[:6] + bytes((1, p.NESP_SVC_JUKE)))
        return reply
    machine = LinkConsole(*link_rom, to_console=old)
    machine.run(12)
    assert status_line(machine) == "UPDATE NESP32"


def test_the_controller_read_is_one_byte_of_noise_a_frame(link_rom, demo):
    """OUT0 is the line to the nesp32 too, and the read holds it low for
    two bits: its UART hears a byte, and its decoder passes over it."""
    machine = link_machine(link_rom, demo)
    machine.run_until_played(300)
    frames = len(machine.frames)
    assert frames - 3 <= machine.stick.noise <= frames + 1
    assert machine.word("link_failed") == 0 and machine.stick.juke_resent == 0
    assert button_requests(machine) == []           # no buttons held, none reported


@pytest.mark.parametrize("clock_error", [-0.03, 0.03])
def test_the_controller_read_survives_a_clock_that_is_out(link_rom, demo, clock_error):
    machine = link_machine(link_rom, demo, clock_error=clock_error)
    machine.run_until_played(200)
    assert machine.word("link_failed") == 0
    assert machine.stick.noise <= len(machine.frames) + 1


def test_the_controller_read_is_over_well_before_the_request(link_rom, demo):
    # OUT0 is low for the 8 reads. The nesp32's UART takes that for a start
    # bit and needs ten bit times from its edge to finish the byte, so the
    # request's own start bit must come later than that.
    machine = link_machine(link_rom, demo)
    machine.write_log = []
    before = len(machine.frames)
    machine.run_until_played(200)
    falls = [cycle for (cycle, level), (_, before) in zip(machine.write_log[1:], machine.write_log)
             if level == 0 and before == 1]
    lows = {}
    for (cycle, level), (rise, after) in zip(machine.write_log, machine.write_log[1:]):
        if level == 0 and after == 1:
            lows[cycle] = rise - cycle
    reads = [cycle for cycle in falls if 90 <= lows.get(cycle, 0) <= 98]
    assert len(reads) >= len(machine.frames) - before - 2
    assert {lows[cycle] for cycle in reads} == {94}
    gaps = [min(fall - read for fall in falls if fall > read) for read in reads[:-1]]
    assert min(gaps) > 12 * p.NESP_PERIOD


def test_right_and_left_change_the_track_at_once(link_rom, demo):
    machine = link_machine(link_rom, demo)
    machine.run_until_played(100)
    assert title_line(machine).strip() == "First track"

    pressed = len(machine.frames)
    press(machine, PAD_RIGHT)
    assert button_requests(machine) == [NEXT]
    played = len(machine.played_frames())
    machine.run_until_played(played + 60)
    assert machine.stick.juke_index == 1 and title_line(machine).strip() == "Second track"
    assert machine.played_frames()[played:played + 60] == frames_of(machine.streams[1], 60)
    # The NES held seconds of the first track. The press is heard after one
    # prefill: a title, then the new track, well inside a second.
    wait = next(index for index, (_, underran, playing) in enumerate(machine.frames[pressed:])
                if playing and not underran)
    assert wait < 30

    press(machine, PAD_LEFT)
    machine.run_until_played(len(machine.played_frames()) + 30)
    assert button_requests(machine) == [NEXT, PREVIOUS]
    assert machine.stick.juke_index == 0 and title_line(machine).strip() == "First track"
    assert machine.word("underruns") == 0 and machine.byte("stream_error") == 0


def test_start_pauses_and_goes_on_from_where_it_was(link_rom, demo):
    machine = link_machine(link_rom, demo)
    wait_for(machine, lambda: len(machine.played_frames()) >= 150)
    press(machine, PAD_START, frames=12)            # held: one press
    machine.run(30)
    assert button_requests(machine) == [PLAY]
    assert machine.byte("paused") == 1
    assert machine.memory[0x4015] == 0              # silenced
    assert lit_bars(machine) == set()               # the bars fall with the music
    played = len(machine.played_frames())
    # No words for it: the clock flashes, about once a second, at the
    # position it was paused on.
    shown = []
    for _ in range(128):
        machine.run(1)
        assert status_line(machine) == ""
        shown.append(time_line(machine).strip("\x00"))
    assert set(shown) == {"", "0:02 / 3:33"}
    assert 3 <= sum(a != b for a, b in zip(shown, shown[1:])) <= 4
    assert len(machine.played_frames()) == played
    # The NES keeps asking, so the link stays up and the nesp32 can end it.
    assert machine.word("link_failed") == 0

    press(machine, PAD_A)                           # A does the same as Start
    machine.run_until_played(played + 300)
    assert button_requests(machine) == [PLAY, PLAY]
    assert machine.byte("paused") == 0
    # Nothing was dropped and nothing started over: one unbroken song.
    frames = machine.played_frames()
    assert frames == frames_of(machine.streams[0], len(frames))
    assert machine.memory[0x4015] != 0
    assert machine.word("underruns") == 0 and machine.byte("stream_error") == 0
    machine.run(40)
    assert time_line(machine) > "0:07"              # the clock went on as well


def test_a_nesp32_that_stops_shows_the_clock_flashing_and_start_plays_again(link_rom, demo):
    """Stopped with a track on the screen: no words, since the foot of the
    screen says what Start does. A console that is reset is one way for
    the music to stop; here the nesp32 was switched off and on."""
    machine = link_machine(link_rom, demo)
    wait_for(machine, lambda: len(machine.played_frames()) >= 150)
    machine.power_cycle()
    machine.stick.set_juke(loops=LOOPS)
    wait_for(machine, lambda: machine.byte("playing") == 0, limit=20)
    machine.run(40)
    played = len(machine.played_frames())
    shown = set()
    for _ in range(80):
        machine.run(1)
        shown.add(time_line(machine).strip("\x00"))
    assert shown == {"", "0:02 / 3:33"} and status_line(machine) == ""
    press(machine, PAD_START)
    machine.run_until_played(played + 100)
    assert machine.played_frames()[played:played + 100] == frames_of(machine.streams[0], 100)


@pytest.mark.parametrize("seed", range(3))
def test_pauses_survive_a_slow_noisy_link(link_rom, demo, seed):
    rng = random.Random(seed)
    machine = link_machine(link_rom, demo, to_console=flip_random_bit(rng, 0.15),
                           turnaround=lambda: ms(rng.uniform(0.1, 9)))
    machine.run(rng.randrange(5, 30))               # the first lands in the prefill
    for _ in range(6):
        machine.press_button(p.NESP_EVENT_BUTTON_A)
        wait_for(machine, lambda: machine.byte("paused") == 1, limit=60)
        played = len(machine.played_frames())
        machine.run(rng.randrange(20, 90))
        assert len(machine.played_frames()) == played
        machine.press_button(p.NESP_EVENT_BUTTON_A)
        machine.run_until_played(played + rng.randrange(40, 200))
    frames = machine.played_frames()
    assert frames == frames_of(machine.streams[0], len(frames))
    assert machine.byte("stream_error") == 0


def test_start_plays_from_stopped_and_right_plays_the_next_track(link_rom, demo):
    machine = link_machine(link_rom, demo, begin=False)
    greet(machine)
    machine.run(20)
    press(machine, PAD_RIGHT)
    machine.run_until_played(40)
    assert machine.byte("link_state") != LINK_STOPPED and machine.stick.juke_index == 1
    assert title_line(machine).strip() == "Second track"


def test_other_buttons_do_nothing(link_rom, demo):
    machine = link_machine(link_rom, demo)
    machine.run_until_played(50)
    press(machine, PAD_B | 0x20 | 0x08 | 0x04)      # B, Select, Up, Down
    machine.run(20)
    assert button_requests(machine) == []


def test_a_press_whose_reply_is_lost_is_sent_again_and_done_once(link_rom, demo):
    """The console cannot tell a lost request from a lost reply. It sends
    the same request again, unchanged, and the nesp32, which did hear the
    first, answers as it did then and changes nothing more."""
    machine = link_machine(link_rom, demo)
    machine.run_until_played(60)
    lost = []

    def lose_two(reply):
        if machine.answering[:2] == BUTTON and len(lost) < 2:
            lost.append(reply)
            return None
        return reply
    machine.port.to_console = lose_two
    press(machine, PAD_RIGHT)
    machine.run(10)
    assert len(lost) == 2 and machine.stick.repeats == 2
    assert machine.stick.juke_index == 1            # one track on, not three
    assert button_requests(machine) == [NEXT] * 3 and machine.byte("button_sending") == 0
    machine.run_until_played(len(machine.played_frames()) + 30)
    assert title_line(machine).strip() == "Second track"


def test_every_press_is_done_once_on_a_slow_noisy_link(link_rom, demo):
    """Whatever is lost, the track is never changed twice by one press,
    and never not at all."""
    rng = random.Random(11)
    machine = link_machine(link_rom, demo, to_console=flip_random_bit(rng, 0.15),
                           turnaround=lambda: ms(rng.uniform(0.1, 9)))
    machine.run_until_played(100)
    for presses in range(1, 7):
        press(machine, PAD_RIGHT)
        machine.run(rng.randrange(20, 70))
        assert machine.stick.juke_index == presses % 2
    machine.run_until_played(len(machine.played_frames()) + 60)
    assert machine.byte("stream_error") == 0
    assert title_line(machine).strip() == "First track"

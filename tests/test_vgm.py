"""The firmware's converter of rips (vgm.c): a .vgm as the .jbs file the
jukebox plays.

It is nes-jukebox's converter in C, and that Python is still here
(apps/jukebox/tools), so the two are held to the same bytes: over the rips
that come with the jukebox, over rips made up to reach each thing the
converter does, and over a few hundred made at random.
"""

import gzip
import os
import random
import struct
import sys

import nesp
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
JUKEBOX = os.path.join(HERE, "..", "apps", "jukebox")
sys.path.insert(0, os.path.join(JUKEBOX, "tools"))

import jbs  # noqa: E402
import vgm  # noqa: E402
import vgm2jbs  # noqa: E402

MUSIC = os.path.join(JUKEBOX, "music")
RIPS = sorted(name for name in os.listdir(MUSIC) if name.endswith((".vgz", ".vgm")))
NTSC, PAL = vgm.NTSC_CLOCK, vgm.PAL_CLOCK
HEADER = 0x100


def python(data, name=""):
    """What nes-jukebox's tools make of a rip (pack_tracks.load_track), or
    None where they make nothing."""
    try:
        song, _ = vgm2jbs.convert(vgm.parse(data))
    except (ValueError, AssertionError, struct.error, IndexError):
        return None
    song.title = song.title or name
    return song.to_bytes()


def write(register, value):
    return bytes([0xB4, register, value])


def wait(samples):
    return bytes([0x61]) + struct.pack("<H", samples)


FRAME = bytes([0x62])           # a wait of 735 samples
PAL_FRAME = bytes([0x63])       # and of 882
END = bytes([0x66])


def rip(commands, clock=NTSC, loop=None, samples=None, tag=None, version=0x171):
    """A .vgm of some commands. loop is how many bytes of them come before
    the loop, and tag the strings of a GD3 tag."""
    body = b"".join(commands) if isinstance(commands, (list, tuple)) else commands
    if samples is None:
        samples = sum(735 for byte in body if byte == 0x62)
    header = bytearray(HEADER)
    header[0:4] = b"Vgm "
    struct.pack_into("<I", header, 0x08, version)
    struct.pack_into("<I", header, 0x18, samples)
    struct.pack_into("<I", header, 0x34, HEADER - 0x34)
    struct.pack_into("<I", header, 0x84, clock)
    if loop is not None:
        struct.pack_into("<I", header, 0x1C, HEADER + loop - 0x1C)
    data = bytes(header) + body
    if tag is not None:
        text = "\x00".join(tag).encode("utf-16-le") + b"\x00\x00"
        struct.pack_into("<I", header, 0x14, len(data) - 0x14)
        data = bytes(header) + body + b"Gd3 " + struct.pack("<II", 0x100, len(text)) + text
    data = bytearray(data)
    struct.pack_into("<I", data, 0x04, len(data) - 4)
    return bytes(data)


def same(data, name=""):
    """Both converters' file of a rip, which must be the one file."""
    made = nesp.vgm_to_jbs(data, name)
    assert made == python(data, name)
    return made


# --- the rips that come with the jukebox ------------------------------------------

@pytest.mark.parametrize("name", RIPS)
def test_a_real_rip_comes_out_as_the_python_makes_it(name):
    with open(os.path.join(MUSIC, name), "rb") as handle:
        data = handle.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    made = same(data, os.path.splitext(name)[0])
    song = jbs.JbsFile.from_bytes(made)
    assert song.total_frames > 600 and song.title
    jbs.decode(song.stream)


# --- what it does, a thing at a time ----------------------------------------------

def test_a_rip_with_nothing_in_it_is_a_frame_of_enabled_channels():
    made = same(rip([END]), "Silence")
    song = jbs.JbsFile.from_bytes(made)
    assert song.title == "Silence" and song.total_frames == 1 and song.loop_frame is None
    assert jbs.decode(song.stream)[0] == [[jbs.Control(jbs.CTRL_INIT), (0x15, 0x0F)]]


def test_writes_go_to_their_frames_and_the_frames_between_are_waited():
    made = same(rip([write(0x00, 0x3F), FRAME, write(0x02, 0x10), write(0x03, 0x08),
                     FRAME * 300, write(0x00, 0x30), FRAME, END]))
    frames, _ = jbs.decode(jbs.JbsFile.from_bytes(made).stream)
    assert len(frames) == 302
    assert frames[1] == [(0x02, 0x10), (0x03, 0x08)] and frames[301] == [(0x00, 0x30)]
    assert not any(frames[2:301])


def test_a_write_that_changes_nothing_is_left_out_and_a_note_start_never_is():
    made = same(rip([write(0x00, 0x3F), write(0x03, 0x08), FRAME,
                     write(0x00, 0x3F), write(0x03, 0x08), FRAME, END]))
    frames, _ = jbs.decode(jbs.JbsFile.from_bytes(made).stream)
    assert frames[1] == [(0x03, 0x08)]


def test_what_the_stream_cannot_carry_is_dropped():
    made = same(rip([write(0x10, 0x0F), write(0x12, 0x40), write(0x13, 0xFF), write(0x09, 1),
                     write(0x0D, 1), write(0x14, 2), write(0x16, 1), write(0x1F, 1),
                     write(0x80, 0x3F), write(0x23, 0x10),       # a second chip, and the FDS
                     write(0x15, 0x1F), write(0x17, 0x80), FRAME, END]))
    frames, _ = jbs.decode(jbs.JbsFile.from_bytes(made).stream)
    assert frames[0] == [jbs.Control(jbs.CTRL_INIT), (0x15, 0x0F), (0x17, 0xC0)]


def test_a_few_dmc_levels_in_a_frame_are_kept_and_sampled_sound_is_not():
    few = [write(0x11, 0x80 | level) for level in (1, 2, 3, 4)]
    many = [write(0x11, level) + wait(50) for level in range(5)]
    made = same(rip(few + [FRAME] + many + [wait(485), write(0x11, 0x55), FRAME, END],
                    samples=3 * 735))
    frames, _ = jbs.decode(jbs.JbsFile.from_bytes(made).stream)
    assert frames[0][-1] == (0x11, 0x04) and frames[1] == [] and frames[2] == [(0x11, 0x55)]


def test_writes_whose_order_matters_stay_in_it_as_chained_records():
    # A length load before its channel is enabled does nothing, and one
    # after it sounds: the console's order would enable first.
    made = same(rip([write(0x15, 0x00), FRAME,
                     write(0x03, 0x08), write(0x15, 0x01), write(0x03, 0x18), FRAME, END]))
    stream = jbs.JbsFile.from_bytes(made).stream
    assert jbs.OP_CHAIN in stream
    frames, _ = jbs.decode(stream)
    assert frames[1] == [(0x03, 0x08), (0x15, 0x01), (0x03, 0x18)]


def test_a_frame_of_more_writes_than_the_console_stages_is_no_track():
    starts = [write(register, value) for value in range(20) for register in (0x03, 0x07, 0x0B, 0x0F)]
    assert same(rip(starts + [FRAME, END])) is None
    assert same(rip(starts[:60] + [FRAME, END])) is not None


def test_a_loop_is_found_and_the_console_is_told_everything_again_there():
    intro = [write(0x00, 0x3F), write(0x02, 0x55), FRAME]
    body = [write(0x00, 0x3F), write(0x03, 0x08), FRAME, FRAME, END]
    made = same(rip(intro + body, loop=len(b"".join(intro))))
    song = jbs.JbsFile.from_bytes(made)
    assert song.loop_frame == 1
    frames, _ = jbs.decode(song.stream, song.loop_offset)
    assert frames[0] == [(0x00, 0x3F), (0x03, 0x08)]        # $4000 again: it is not known held


@pytest.mark.parametrize("before", [0, 1, 3, 130, 400])
def test_a_loop_may_be_in_a_frame_with_nothing_in_it(before):
    for after in (0, 1, 200):
        commands = [write(0x00, 0x3F)] + [FRAME] * before
        loop = len(b"".join(commands))
        made = same(rip(commands + [FRAME] * after + [write(0x02, 1), FRAME, END], loop=loop))
        assert jbs.JbsFile.from_bytes(made).loop_frame == before


def test_a_loop_at_the_very_end_or_past_it_is_no_loop():
    commands = [write(0x00, 0x3F), FRAME, FRAME]
    for extra in ([], [FRAME] * 5):
        data = rip(commands + extra + [END], loop=len(b"".join(commands + extra)),
                   samples=2 * 735)
        assert jbs.JbsFile.from_bytes(same(data)).loop_frame is None
    assert same(rip(commands + [END], loop=1)) is None      # inside a command


def test_the_headers_length_counts_when_it_is_the_longer():
    made = same(rip([write(0x00, 1), FRAME, END], samples=600 * 735))
    assert jbs.JbsFile.from_bytes(made).total_frames == 600
    made = same(rip([write(0x00, 1), FRAME * 9, write(0x09, 1), END], samples=735))
    assert jbs.JbsFile.from_bytes(made).total_frames == 10   # a dropped write is still its last


def test_a_pal_rip_is_rewritten_for_an_ntsc_consoles_pitch():
    commands = []
    for period in list(range(0, 0x800, 7)) + [0x7FF]:
        for low, high in ((0x02, 0x03), (0x06, 0x07), (0x0A, 0x0B)):
            commands += [write(low, period & 0xFF), write(high, 0xF8 | period >> 8)]
        commands += [write(0x0E, 0x80 | period & 0x0F), PAL_FRAME,
                     write(0x02, (period * 3) & 0xFF), write(0x0A, (period * 5) & 0xFF),
                     PAL_FRAME]
    made = same(rip(commands + [END], clock=PAL, samples=len(commands) * 882))
    song = jbs.JbsFile.from_bytes(made)
    assert song.pal_source
    assert same(rip(commands + [END], clock=NTSC)) != made


def test_the_title_is_the_tags_game_and_track_or_the_files_name():
    commands = [write(0x00, 1), FRAME, END]

    def title(tag, name="A File"):
        return jbs.JbsFile.from_bytes(same(rip(commands, tag=tag), name)).title

    assert title(["Vampire Killer", "", "Castlevania", "", "NES"]) == "Castlevania - Vampire Killer"
    assert title(["Only A Track", "", ""]) == "Only A Track"
    assert title(["", "", "Only A Game"]) == "Only A Game"
    assert title(["", "", ""]) == "A File" and title(None) == "A File"
    assert title(["Café \U0001F3B5!", "タイトル", "Pokémon"]) == "Pok?mon - Caf? ?!"
    assert title(["", "", ""], name="Café") == "Caf?"
    assert len(title(["T" * 300, "", "G" * 100])) == 255
    assert title(["Track"]) == "Track"                      # a tag cut short


def test_what_is_not_a_rip_of_a_nes_is_no_track():
    good = rip([write(0x00, 1), FRAME, END])
    assert same(good) is not None
    assert same(b"") is None and same(b"Vgm") is None and same(b"JUNK" + good[4:]) is None
    assert same(rip([END], clock=0)) is None                # another machine's
    assert same(rip([END], version=0x150)) is None          # before the format had a NES
    assert same(rip([bytes([0x2F]), END])) is None          # no such command
    assert same(rip([bytes([0xB4, 0x00])])) is None         # cut short in a write
    assert same(rip([bytes([0x67, 0x00, 0x00, 0, 0, 0, 0]), END])) is None


def test_other_chips_commands_are_walked_past():
    other = [bytes([0x4F, 1]), bytes([0x50, 1]), bytes([0x51, 1, 2]), bytes([0xA0, 1, 2]),
             bytes([0xC0, 1, 2, 3]), bytes([0xE0, 1, 2, 3, 4]), bytes([0x90, 1, 2, 3, 4]),
             bytes([0x93] + [0] * 10), bytes([0x68] + [0] * 11), bytes([0x30, 1]),
             bytes([0x67, 0x66, 0x07, 3, 0, 0, 0, 9, 9, 9]), bytes([0x7F]), bytes([0x85])]
    commands = [write(0x00, 0x3F)]
    for command in other:
        commands += [command, wait(400), write(0x02, len(commands))]
    same(rip(commands + [END], samples=len(other) * 420))


def test_a_file_that_does_not_fit_is_no_track():
    data = rip([write(0x00, value) + FRAME for value in range(200)] + [END])
    whole = same(data)
    assert nesp.vgm_to_jbs(data, room=len(whole)) == whole
    assert nesp.vgm_to_jbs(data, room=len(whole) - 1) is None
    assert nesp.vgm_to_jbs(data, room=10) is None


# --- and whatever else ------------------------------------------------------------

REGISTERS = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0A, 0x0B, 0x0C, 0x0E, 0x0F,
             0x11, 0x15, 0x17, 0x10, 0x09]


@pytest.mark.parametrize("seed", range(300))
def test_a_rip_made_at_random_comes_out_as_the_python_makes_it(seed):
    rng = random.Random(seed)
    busy = rng.choice([1, 2, 4, 12])
    commands = []
    marks = []
    for _ in range(rng.randrange(1, 120)):
        marks.append(len(b"".join(commands)))
        for _ in range(rng.randrange(0, busy)):
            commands.append(write(rng.choice(REGISTERS), rng.choice([0, 1, 0x0F, 0x80, 0x88,
                                                                      rng.randrange(256)])))
            if rng.random() < 0.2:
                commands.append(wait(rng.randrange(1, 300)))
        commands.append(rng.choice([FRAME, FRAME, PAL_FRAME, wait(rng.randrange(1, 3000)),
                                    FRAME * rng.randrange(1, 200)]))
    body = b"".join(commands)
    samples = rng.choice([0, 735 * rng.randrange(1, 400), 10_000_000])
    data = rip(body + END, clock=rng.choice([NTSC, PAL]), samples=samples,
               loop=rng.choice([None, None] + marks + [len(body)]))
    made = same(data, "Random %d" % seed)
    if made is not None:
        song = jbs.JbsFile.from_bytes(made)
        frames, tail = jbs.decode(song.stream)
        assert len(frames) == song.total_frames and not tail

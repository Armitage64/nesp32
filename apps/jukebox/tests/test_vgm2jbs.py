import json
from collections import Counter

import jbs
import vgm
import vgm2jbs
from test_jbs import assert_stream_matches
from vgmbuild import PAL, VgmBuilder


def test_writes_land_on_the_nearest_frame():
    song = vgm.parse(
        VgmBuilder()
        .write(0x00, 1)
        .wait(367).write(0x00, 2)    # rounds down to frame 0
        .wait(1).write(0x00, 3)      # 368 rounds up to frame 1
        .wait(735 * 2).write(0x00, 4)
        .build()
    )
    frames, loop_frame, _ = vgm2jbs.normalize(song)
    assert frames == [[(0x00, 1), (0x00, 2)], [(0x00, 3)], [], [(0x00, 4)]]
    assert loop_frame is None


def test_dmc_and_io_registers_are_dropped_and_counted():
    song = vgm.parse(
        VgmBuilder()
        .write(0x10, 0x0F).write(0x11, 0x40).write(0x14, 0x02).write(0x16, 0x01)
        .write(0x09, 0x00).write(0x15, 0x1F).write(0x17, 0x80)
        .build()
    )
    frames, _, stats = vgm2jbs.normalize(song)
    assert frames == [[(0x11, 0x40), (0x15, 0x0F), (0x17, 0xC0)]]
    assert stats["dropped_dmc_4010"] == 1
    assert stats["dropped_4014"] == 1
    assert stats["dropped_4016"] == 1
    assert stats["dropped_4009"] == 1
    assert stats["dmc_enable_cleared"] == 1


def test_frame_irq_is_always_inhibited():
    song = vgm.parse(VgmBuilder().write(0x17, 0x00).frame().write(0x17, 0x80).build())
    frames, _, _ = vgm2jbs.normalize(song)
    assert frames[0] == [(0x17, 0x40)]
    assert frames[1] == [(0x17, 0xC0)]


def test_pal_rips_keep_their_tempo_and_rescale_pitch():
    builder = VgmBuilder(clock=PAL)
    builder.write(0x02, 0xFD).write(0x03, 0x08)   # pulse period 253
    for _ in range(5):
        builder.raw(b"\x63", samples=882)         # five PAL frames = 1/10 s
    builder.write(0x0E, 0x85)                     # noise mode 1, PAL index 5
    frames, _, _ = vgm2jbs.normalize(vgm.parse(builder.build()))
    # 253 -> round(254 * 1.07649) - 1 = 272 = $110. The lone low write is
    # rescaled against an unknown high byte of 0, which gives the same $10.
    assert frames[0] == [(0x02, 0x10), (0x02, 0x10), (0x03, 0x09)]
    assert len(frames) == 7
    assert frames[6] == [(0x0E, 0x85)]            # PAL 88 is closest to NTSC 96


def test_pal_rescale_can_be_turned_off():
    song = vgm.parse(VgmBuilder(clock=PAL).write(0x02, 0xFD).write(0x03, 0x08).build())
    frames, _, _ = vgm2jbs.normalize(song, pal_rescale=False)
    assert frames[0] == [(0x02, 0xFD), (0x03, 0x08)]


def test_muted_pulse_periods_stay_muted():
    rescaler = vgm2jbs.PalRescaler(stats={})
    assert rescaler.write(0x03, 0x00) == [(0x02, 0x00), (0x03, 0x00)]
    assert rescaler.write(0x02, 0x07) == [(0x02, 0x07)]


def test_low_byte_slide_across_a_high_boundary_is_counted():
    rescaler = vgm2jbs.PalRescaler(stats=Counter())
    rescaler.write(0x02, 0xE0)
    rescaler.write(0x03, 0x00)           # 224 -> 241, high bits 0
    rescaler.write(0x02, 0xF0)           # 240 -> 259 needs high bits 1
    assert rescaler.stats["pal_period_high_mismatch"] == 1


def test_convert_end_to_end_with_loop():
    builder = VgmBuilder()
    builder.write(0x15, 0x0F).write(0x00, 0xBF).write(0x02, 0xFD).write(0x03, 0x08).frame()
    builder.loop_here()
    for note in range(8):
        builder.write(0x02, 0x80 + note).write(0x03, 0x08).frame(4)
    song = vgm.parse(builder.build(title="Theme", game="Test"))
    jbs_file, report = vgm2jbs.convert(song)
    assert jbs_file.title == "Test - Theme"
    assert jbs_file.total_frames == 33
    assert jbs_file.loop_frame == 1
    assert report["frames"] == 33
    assert report["bytes_per_frame_max"] >= report["bytes_per_frame_p99"] > 0
    frames, loop_frame, _ = vgm2jbs.normalize(song)
    encoded = jbs.Encoded(jbs_file.stream, jbs_file.loop_offset, [])
    assert_stream_matches(frames, encoded, loop_frame)


def test_cli_writes_stream_and_report(tmp_path, capsys):
    source = tmp_path / "song.vgz"
    source.write_bytes(VgmBuilder().write(0x00, 0x30).frame(10).build(compress=True))
    report_path = tmp_path / "song.json"
    assert vgm2jbs.main([str(source), "--report", str(report_path)]) == 0
    loaded = jbs.JbsFile.from_bytes((tmp_path / "song.jbs").read_bytes())
    assert loaded.total_frames == 10
    assert json.loads(report_path.read_text())["frames"] == 10
    assert "song.jbs" in capsys.readouterr().out


def test_cli_reports_unreadable_inputs(tmp_path, capsys):
    bad = tmp_path / "bad.vgm"
    bad.write_bytes(b"nope")
    assert vgm2jbs.main([str(bad), "--out-dir", str(tmp_path / "out")]) == 1
    assert "not a VGM" in capsys.readouterr().err


def test_occasional_dmc_level_writes_are_kept_and_pcm_is_dropped():
    builder = VgmBuilder().write(0x11, 0xB0).frame()      # bit 7 is unused
    for level in range(20):                               # PCM: 20 in one frame
        builder.write(0x11, level).wait(36)
    song = vgm.parse(builder.build())
    frames, _, stats = vgm2jbs.normalize(song)
    assert frames[0] == [(0x11, 0x30)]
    assert all(register != 0x11 for frame in frames[1:] for register, _ in frame)
    assert stats["dropped_dmc_pcm_4011"] == 20


def test_a_constant_dmc_level_costs_one_write():
    builder = VgmBuilder()
    for _ in range(10):
        builder.write(0x11, 0x30).frame()
    encoded = jbs.encode(vgm2jbs.normalize(vgm.parse(builder.build()))[0])
    decoded, _ = jbs.decode(encoded.data)
    writes = [item for frame in decoded for item in frame if item != jbs.Control(jbs.CTRL_INIT)]
    assert writes == [(0x11, 0x30)]


def test_a_rip_that_never_enables_its_channels_still_sounds():
    """Castlevania's Vampire Killer rip has no $4015 write at all. On the
    console, which starts a track with every channel disabled, it was silent."""
    song = vgm.parse(VgmBuilder().write(0x00, 0xBF).write(0x02, 0xFD).write(0x03, 0x08)
                     .frame().write(0x00, 0xB0).frame().build())
    jbs_file, _ = vgm2jbs.convert(song)
    frames, _ = jbs.decode(jbs_file.stream)
    assert frames[0] == [jbs.Control(jbs.CTRL_INIT), (0x15, 0x0F),
                         (0x00, 0xBF), (0x02, 0xFD), (0x03, 0x08)]
    assert frames[1] == [(0x00, 0xB0)]

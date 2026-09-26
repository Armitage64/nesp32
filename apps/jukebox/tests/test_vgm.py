import struct

import pytest

import vgm
from vgmbuild import PAL, VgmBuilder


def test_writes_carry_sample_timestamps_across_every_wait_kind():
    song = vgm.parse(
        VgmBuilder()
        .write(0x15, 0x0F)
        .frame()                              # 0x62: 735
        .raw(b"\x63", samples=882)            # PAL frame
        .raw(b"\x61\x10\x00", samples=16)     # explicit wait
        .raw(b"\x73", samples=4)              # 0x7n waits n+1
        .raw(b"\x85", samples=5)              # YM2612 DAC write, then wait n
        .write(0x00, 0xBF)
        .build()
    )
    assert song.writes == [
        vgm.ApuWrite(0, 0x15, 0x0F),
        vgm.ApuWrite(735 + 882 + 16 + 4 + 5, 0x00, 0xBF),
    ]
    assert song.total_samples == 735 + 882 + 16 + 4 + 5
    assert song.skipped["other_chip"] == 1


def test_gzipped_input_is_accepted():
    song = vgm.parse(VgmBuilder().write(0x00, 0x30).build(compress=True))
    assert song.writes == [vgm.ApuWrite(0, 0x00, 0x30)]


def test_other_chips_and_data_blocks_are_skipped_and_counted():
    song = vgm.parse(
        VgmBuilder()
        .raw(b"\x50\x9F")                     # SN76489
        .raw(b"\x52\x28\x00")                 # YM2612
        .raw(b"\xC0\x00\x10\x55")             # Sega PCM
        .raw(b"\xE0\x00\x00\x00\x00")         # PCM seek
        .raw(b"\x67\x66\xC2\x04\x00\x00\x00" + b"\x00\xC0\xAA\x55")
        .write(0x08, 0x81)
        .build()
    )
    assert song.writes == [vgm.ApuWrite(0, 0x08, 0x81)]
    assert song.skipped["other_chip"] == 4
    assert song.skipped["data_block_C2"] == 1


def test_fds_and_second_apu_writes_are_counted_not_kept():
    song = vgm.parse(
        VgmBuilder(fds=True).write(0x23, 0x80).write(0x80, 0x10).write(0x01, 0x08).build()
    )
    assert song.fds
    assert song.writes == [vgm.ApuWrite(0, 0x01, 0x08)]
    assert song.skipped["fds"] == 1
    assert song.skipped["second_apu"] == 1


def test_loop_start_is_the_sample_at_the_loop_offset():
    song = vgm.parse(VgmBuilder().write(0x00, 1).frame(3).loop_here().write(0x00, 2).frame(2).build())
    assert song.loop_start_sample == 3 * 735
    assert song.total_samples == 5 * 735


def test_loop_offset_inside_a_command_is_rejected():
    data = bytearray(VgmBuilder().write(0x00, 1).frame().loop_here().frame().build())
    struct.pack_into("<I", data, 0x1C, 0x100 + 1 - 0x1C)  # middle of the B4 write
    with pytest.raises(vgm.VgmError, match="loop offset"):
        vgm.parse(bytes(data))


def test_gd3_title_and_game():
    song = vgm.parse(VgmBuilder().build(title="Stage 1", game="Some Game"))
    assert (song.title, song.game) == ("Stage 1", "Some Game")


def test_pal_clock_is_detected():
    assert vgm.parse(VgmBuilder(clock=PAL).build()).is_pal
    assert not vgm.parse(VgmBuilder().build()).is_pal


def test_non_nes_and_non_vgm_files_are_rejected():
    with pytest.raises(vgm.VgmError, match="not a VGM"):
        vgm.parse(b"RIFF....")
    with pytest.raises(vgm.VgmError, match="no NES APU"):
        vgm.parse(VgmBuilder(clock=0).build())
    # Before 1.61 the NES clock field does not exist, so it reads as zero.
    with pytest.raises(vgm.VgmError, match="no NES APU"):
        vgm.parse(VgmBuilder(version=0x160).build())


def test_header_fields_past_the_data_offset_read_as_zero():
    data = bytearray(VgmBuilder().write(0x00, 1).build())
    struct.pack_into("<I", data, 0x34, 0x40 - 0x34)  # data "starts" at 0x40
    with pytest.raises(vgm.VgmError, match="no NES APU"):
        vgm.parse(bytes(data))


def test_unknown_command_is_an_error():
    with pytest.raises(vgm.VgmError, match="unknown VGM command 0x20"):
        vgm.parse(VgmBuilder().raw(b"\x20").build())

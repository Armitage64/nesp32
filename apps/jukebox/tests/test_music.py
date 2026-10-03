"""Run the converter's equivalence check on the real rips in music/.

The rips are copyrighted and git-ignored, so this skips when there are none.
"""

import glob
import os

import pytest

import jbs
import vgm
import vgm2jbs
from test_jbs import assert_stream_matches

MUSIC = os.path.join(os.path.dirname(__file__), "..", "music")
RIPS = sorted(glob.glob(os.path.join(MUSIC, "*.vg[mz]")))

# Planned at 38400 baud: about 30 payload bytes per frame after turnaround.
BURST_BUDGET = 30


@pytest.mark.skipif(not RIPS, reason="no rips in music/")
@pytest.mark.parametrize("path", RIPS, ids=os.path.basename)
def test_rip_round_trips_and_fits_the_link(path):
    song = vgm.load(path)
    jbs_file, report = vgm2jbs.convert(song)
    frames, loop_frame, _ = vgm2jbs.normalize(song)
    vgm2jbs.enable_channels(frames)
    encoded = jbs.Encoded(jbs_file.stream, jbs_file.loop_offset, [])
    assert_stream_matches(frames, encoded, loop_frame)
    loaded = jbs.JbsFile.from_bytes(jbs_file.to_bytes())
    assert loaded == jbs_file
    assert report["bytes_per_frame_p99"] < BURST_BUDGET

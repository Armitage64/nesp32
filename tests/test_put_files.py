"""tools/put_files.py: the image of the nesp32's files that goes over USB.

The image is made by ESP-IDF's tool, and here it is read back by ESP-IDF's
other one: both need ESP-IDF (IDF_PATH) and the `construct` module.
"""

import os
import subprocess
import sys

import pytest

import put_files


def read_back(image, directory):
    """The files of an image's tracks directory, as {name: contents}."""
    path = os.path.join(str(directory), "storage.bin")
    with open(path, "wb") as handle:
        handle.write(image)
    subprocess.run([sys.executable, os.path.join(put_files.FATFS, "fatfsparse.py"),
                    "--wl-layer", "enabled", path], cwd=str(directory), check=True,
                   capture_output=True)
    found = {}
    for top, _, names in os.walk(os.path.join(str(directory), "Espressif")):
        for name in names:
            assert os.path.basename(top).lower() == put_files.DIRECTORY
            with open(os.path.join(top, name), "rb") as handle:
                found[name] = handle.read()
    return found


@pytest.fixture
def idf():
    pytest.importorskip("construct")
    if not os.path.exists(os.path.join(put_files.FATFS, "wl_fatfsgen.py")):
        pytest.skip("no ESP-IDF at %s" % put_files.IDF)


def track(directory, name, data):
    path = os.path.join(str(directory), name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def test_the_partition_is_the_firmwares():
    offset, size = put_files.partition()
    assert (offset, size) == (0x420000, 0x3E0000)
    assert offset + size == 8 * 1024 * 1024         # the rest of an 8 MB flash
    with pytest.raises(ValueError):
        put_files.partition("nothing")


def test_a_directorys_tracks_are_taken_in_the_order_of_their_names(tmp_path):
    track(tmp_path, "02.pcm", b"NPCM....")
    track(tmp_path, "00.jbs", b"JBS\x1a....")
    track(tmp_path, "01 A Rip.VGZ", b"\x1f\x8b....")
    track(tmp_path, "03.vgm", b"Vgm ....")
    track(tmp_path, "._03.vgm", b"Vgm ....")     # what a Mac leaves beside a file
    track(tmp_path, "notes.txt", b"not a track")
    names = [name for name, _ in put_files.tracks_in([str(tmp_path)])]
    assert names == ["00.jbs", "01 A Rip.VGZ", "02.pcm", "03.vgm"]


@pytest.mark.parametrize("name, data", [
    ("song.jbs", b"NPCM...."),                  # not what its name says
    ("song.pcm", b""),
    ("song.vgz", b"Vgm ...."),                  # not packed
    ("song.mp3", b"ID3....."),                  # not converted
])
def test_a_file_the_stick_would_pass_over_is_refused(tmp_path, name, data):
    with pytest.raises(ValueError):
        put_files.tracks_in([track(tmp_path, name, data)])


def test_two_files_of_one_name_are_refused(tmp_path):
    os.mkdir(str(tmp_path / "a"))
    os.mkdir(str(tmp_path / "b"))
    paths = [track(tmp_path / "a", "00.jbs", b"JBS\x1a1"), track(tmp_path / "b", "00.JBS", b"JBS\x1a2")]
    with pytest.raises(ValueError):
        put_files.tracks_in(paths)


def test_the_image_holds_the_tracks_and_fills_the_partition(tmp_path, idf):
    source = tmp_path / "music"
    os.mkdir(str(source))
    files = {"00.jbs": b"JBS\x1a" + bytes(range(256)) * 40,
             "01.pcm": b"NPCM" + bytes(200000),
             "02 Jungle Battle (Stage 1, 7).vgz": b"\x1f\x8b" + bytes(range(256)) * 12}
    for name, data in files.items():
        track(source, name, data)
    _, size = put_files.partition()
    image = put_files.image(put_files.tracks_in([str(source)]), size)
    assert len(image) == size
    found = read_back(image, tmp_path)
    # A name of eight characters and three is kept in capitals, and a longer
    # one in small letters: the firmware minds neither.
    assert {name.lower(): data for name, data in found.items()} \
        == {name.lower(): data for name, data in files.items()}


def test_tracks_that_do_not_fit_say_so(tmp_path, idf):
    big = track(tmp_path, "00.pcm", b"NPCM" + bytes(300000))
    with pytest.raises(ValueError, match="do not fit"):
        put_files.image(put_files.tracks_in([big]), 64 * 4096)

"""tools/put_files.py: the image of the nesp32's files that goes over USB.

That the firmware's own LittleFS mounts such an image and reads its files
was checked by hand, with the component's lfs.c built for this computer;
here the image is read back with the library that made it.
"""

import os

import pytest

import put_files


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
    track(tmp_path, "01.jbs", b"JBS\x1a....")
    track(tmp_path, "notes.txt", b"not a track")
    names = [name for name, _ in put_files.tracks_in([str(tmp_path)])]
    assert names == ["00.jbs", "01.jbs", "02.pcm"]


@pytest.mark.parametrize("name, data", [
    ("song.jbs", b"NPCM...."),                  # not what its name says
    ("song.pcm", b""),
    ("song.vgz", b"JBS\x1a...."),               # not converted
    ("x" * 60 + ".jbs", b"JBS\x1a...."),        # the nesp32's names are shorter
])
def test_a_file_the_stick_would_pass_over_is_refused(tmp_path, name, data):
    with pytest.raises(ValueError):
        put_files.tracks_in([track(tmp_path, name, data)])


def test_two_files_of_one_name_are_refused(tmp_path):
    os.mkdir(str(tmp_path / "a"))
    os.mkdir(str(tmp_path / "b"))
    paths = [track(tmp_path / "a", "00.jbs", b"JBS\x1a1"), track(tmp_path / "b", "00.jbs", b"JBS\x1a2")]
    with pytest.raises(ValueError):
        put_files.tracks_in(paths)


def test_the_image_holds_the_tracks_and_fills_the_partition(tmp_path):
    littlefs = pytest.importorskip("littlefs")
    first = track(tmp_path, "00.jbs", b"JBS\x1a" + bytes(range(256)) * 40)
    second = track(tmp_path, "01.pcm", b"NPCM" + bytes(200000))
    _, size = put_files.partition()
    image = put_files.image(put_files.tracks_in([str(tmp_path)]), size)
    assert len(image) == size
    files = littlefs.LittleFS(block_size=put_files.BLOCK, block_count=size // put_files.BLOCK,
                              name_max=put_files.NAME_MAX, mount=False)
    files.context.buffer = bytearray(image)
    files.mount()
    assert sorted(files.listdir("/tracks")) == ["00.jbs", "01.pcm"]
    for name, path in (("00.jbs", first), ("01.pcm", second)):
        with files.open("/tracks/" + name, "rb") as handle, open(path, "rb") as source:
            assert handle.read() == source.read()


def test_tracks_that_do_not_fit_say_so(tmp_path):
    pytest.importorskip("littlefs")
    big = track(tmp_path, "00.pcm", b"NPCM" + bytes(300000))
    with pytest.raises(ValueError, match="do not fit"):
        put_files.image(put_files.tracks_in([big]), 64 * put_files.BLOCK)

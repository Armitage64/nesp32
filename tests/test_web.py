"""The web site's ROM patches page, as tools/gen_web.py writes it: every
patch beside it and linked from it, and nothing left unfilled."""

import os
import re

import gen_web
import pytest


def test_patches_page(tmp_path):
    gen_web.write_patches_page(str(tmp_path), "9.9.9", "release", {"style.css": "abcd1234"})
    directory = tmp_path / "patches"
    text = (directory / "index.html").read_text()
    for path, _ in gen_web.PATCHES:
        name = os.path.basename(path)
        with open(os.path.join(gen_web.ROOT, path), "rb") as f:
            assert (directory / name).read_bytes() == f.read()
        mark = gen_web.fingerprint(str(directory / name))
        assert 'href="%s?v=%s" download' % (name, mark) in text
    assert 'href="../style.css?v=abcd1234"' in text
    assert not re.search(r"\{[a-z]+(:[^}\s]+)?\}", text)


def test_patch_needing_unreleased_firmware_stops_a_release(tmp_path, capsys):
    with pytest.raises(SystemExit, match="Release the firmware first"):
        gen_web.write_patches_page(str(tmp_path), "0.2.0", "release", {})
    gen_web.write_patches_page(str(tmp_path), "0.2.0", None, {})
    assert "Warning" in capsys.readouterr().out


def test_page_and_patches_agree(tmp_path, monkeypatch):
    patches = list(gen_web.PATCHES)
    monkeypatch.setattr(gen_web, "PATCHES", patches[1:])
    with pytest.raises(SystemExit, match="PATCHES in tools/gen_web.py has not"):
        gen_web.write_patches_page(str(tmp_path), "9.9.9", None, {})
    monkeypatch.setattr(gen_web, "PATCHES", patches + [("apps/drmario/Makefile", "0.2.0")])
    with pytest.raises(SystemExit, match="has no link to Makefile"):
        gen_web.write_patches_page(str(tmp_path), "9.9.9", None, {})


def test_log_page(tmp_path):
    """The log page has no placeholder the build would stop at, and asks for
    the style sheet by its fingerprint."""
    target = tmp_path / "index.html"
    gen_web.page(os.path.join(gen_web.WEB, "log", "index.html"), str(target),
                 {"style.css": "abcd1234"}, {})
    text = target.read_text()
    assert 'href="../style.css?v=abcd1234"' in text
    assert "navigator.serial" in text

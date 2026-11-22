import atexit
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

# The ROM's host is a nesp32, whose firmware is at the top of this
# repository. Its link and services are built for this computer, into a
# directory of their own, and the tests run the ROM against them. The
# console and the serial line are its tests' too (tests/console.py,
# tests/wire.py there).
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
NESP_BUILD = tempfile.mkdtemp(prefix="nes-gallery-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
HAVE_NESP32 = os.path.isdir(NESP32)
if HAVE_NESP32:
    subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32,
                   check=True)
    os.environ["NESP_BUILD"] = NESP_BUILD
    sys.path.insert(0, NESP_BUILD)
    sys.path.insert(0, os.path.join(NESP32, "host"))
    sys.path.insert(0, os.path.join(NESP32, "tests"))


@pytest.fixture(scope="session")
def rom(tmp_path_factory):
    """(ROM path, labels path, build directory), built from this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not HAVE_NESP32:
        pytest.skip("no nesp32 checkout at %s" % NESP32)
    build = tmp_path_factory.mktemp("gallery_build")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "verify"], cwd=ROOT, check=True)
    return str(build / "gallery.nes"), str(build / "gallery.labels"), str(build)


def fixture(name):
    """One of nesp32's test fixtures (its tests/fixtures)."""
    with open(os.path.join(NESP32, "tests", "fixtures", name), "rb") as handle:
        return handle.read()


@pytest.fixture
def gallery(rom):
    """Make a console on the ROM with a nesp32, and the test as Wikimedia
    Commons: gallery(**options) is a Viewer."""
    from viewer import Viewer

    def make(**options):
        options.setdefault("picture", fixture("commons_tower.jpg"))
        return Viewer(rom[0], rom[1], **options)
    return make

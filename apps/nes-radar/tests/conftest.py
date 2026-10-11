import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

import atexit  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import pytest  # noqa: E402

# The nesp32's end of the link is nesp32's firmware, at the top of this
# repository. Its link and services are built for this computer, into a
# directory of their own, and the link ROM's tests run against them. The
# console and the line are its tests' too.
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
NESP_BUILD = tempfile.mkdtemp(prefix="nes-radar-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32, check=True)
os.environ["NESP_BUILD"] = NESP_BUILD
for path in (HERE, os.path.join(NESP32, "tools"), os.path.join(NESP32, "tests"),
             os.path.join(NESP32, "host"), NESP_BUILD):
    sys.path.insert(0, path)


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the ROMs and everything made on the way, built from
    this tree, the original checked against nes-radar's own."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not os.path.isfile(os.path.join(NESP32, "third_party", "nes-radar", "README.md")):
        pytest.skip("no nes-radar in third_party: git submodule update --init")
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "PYTHON=%s" % sys.executable, "verify"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return out


@pytest.fixture
def scope(build):
    """Make a Scope: the link ROM on a console and a nesp32, joined by the
    line. scope(**port_options), or scope(stick=False) for a console with
    nothing on port 2."""
    from scope import Scope

    def make(**options):
        return Scope(str(build / "nes_radar_link.nes"), str(build / "nes_radar_link.labels"),
                     **options)
    return make

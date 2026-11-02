"""The HTTPS sample's tests: the ROM, built from this tree, on a simulated
console, with a nesp32's own firmware built for this computer.

What comes from nesp32's checkout (two directories up): the firmware's link
and services (`make host`, loaded by host/nesp.py), and the simulated
console and serial line (tests/console.py and tests/wire.py).
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
NESP_BUILD = tempfile.mkdtemp(prefix="nesp32-https-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32, check=True)
os.environ["NESP_BUILD"] = NESP_BUILD
for path in (HERE, NESP_BUILD, os.path.join(NESP32, "host"), os.path.join(NESP32, "tests")):
    sys.path.insert(0, path)


@pytest.fixture(scope="session")
def rom(tmp_path_factory):
    """(the ROM, its labels), built into a directory of their own."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD], cwd=ROOT, check=True)
    return str(out / "https.nes"), str(out / "https.labels")

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)

FIXTURES = os.path.join(HERE, "fixtures")


import atexit  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import pytest  # noqa: E402

# The Stick's end of the link is nesp32's firmware, a checkout of which sits
# beside this one. Its link and services are built for this computer, into
# a directory of their own, and the link ROM's tests run against them.
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "nesp32")))
NESP_BUILD = tempfile.mkdtemp(prefix="nes-wiki-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
HAVE_NESP32 = os.path.isdir(NESP32)
if HAVE_NESP32:
    subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32,
                   check=True)
    os.environ["NESP_BUILD"] = NESP_BUILD
    sys.path.insert(0, NESP_BUILD)
    sys.path.insert(0, os.path.join(NESP32, "host"))


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the ROMs and everything made on the way, built from
    this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not HAVE_NESP32:
        pytest.skip("no nesp32 checkout at %s" % NESP32)
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "verify"], cwd=ROOT, check=True)
    return out


@pytest.fixture
def console(build):
    """Make a Console on the standalone ROM: console(skip_waits=True)."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "nespedia.nes"), str(build / "nespedia.labels"), **kwargs)
    return make


@pytest.fixture
def link_console(build):
    """Make a Console on the link ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "nespedia_link.nes"), str(build / "nespedia_link.labels"),
                       **kwargs)
    return make


@pytest.fixture(scope="session")
def article(build):
    """The built-in article's lines, 28 tile numbers each."""
    data = (build / "article.bin").read_bytes()
    return [data[start:start + 28] for start in range(0, len(data), 28)]

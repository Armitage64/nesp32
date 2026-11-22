"""The nesp32's own code, for the tools and the tests.

The nesp32 runs the firmware at the top of this repository (or wherever
NESP32 says). Its link and services, and the numbers its link shares with
this ROM, are built for this computer by `make` (into build/nesp, or
wherever NESP_BUILD says) and loaded here:

    from stick import nesp, proto

    nesp.Stick().picture(jpeg)          a picture as COMMONS makes it
    proto.NESP_COMMONS_SIZE, ...        the numbers
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
BUILD = os.path.abspath(os.environ.setdefault("NESP_BUILD", os.path.join(ROOT, "build", "nesp")))

if not os.path.exists(os.path.join(BUILD, "nesp_proto.py")):
    sys.exit("nothing of nesp32's in %s: run `make` first (it wants a checkout of nesp32 at %s)"
             % (BUILD, NESP32))
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(NESP32, "host"))

import nesp  # noqa: E402
import nesp_proto as proto  # noqa: E402

COLUMNS = proto.NESP_COMMONS_COLUMNS    # characters in a line of a picture's words
QUERY_MAX = proto.NESP_COMMONS_QUERY_MAX

__all__ = ["nesp", "proto", "COLUMNS", "QUERY_MAX"]

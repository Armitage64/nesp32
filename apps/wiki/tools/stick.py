"""The Stick's own code, for the tools and the tests.

The Stick runs nesp32's firmware, a checkout of which sits beside this one
(or wherever NESP32 says). Its text code, which lays an article out, and
the numbers its link shares with this ROM are built for this computer by
`make` (into build/nesp, or wherever NESP_BUILD says) and loaded here:

    from stick import nesp, proto

    nesp.Wrap, nesp.Extract, nesp.to_ascii, nesp.wiki_url    the text code
    proto.NESP_WIKI_COLUMNS, ...                             the numbers
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "nesp32")))
BUILD = os.path.abspath(os.environ.setdefault("NESP_BUILD", os.path.join(ROOT, "build", "nesp")))

if not os.path.exists(os.path.join(BUILD, "nesp_proto.py")):
    sys.exit("nothing of nesp32's in %s: run `make` first (it wants a checkout of nesp32 at %s)"
             % (BUILD, NESP32))
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(NESP32, "host"))

import nesp  # noqa: E402
import nesp_proto as proto  # noqa: E402

COLUMNS = proto.NESP_WIKI_COLUMNS       # characters in a line of an article
QUERY_MAX = proto.NESP_WIKI_QUERY_MAX   # characters in a search
# Laid out after every article, as the Stick does.
SOURCE = (b"", b"From Wikipedia, the free", b"encyclopedia. CC BY-SA 4.0.")

__all__ = ["nesp", "proto", "COLUMNS", "QUERY_MAX", "SOURCE"]

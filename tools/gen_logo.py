#!/usr/bin/env python3
"""Write the logo for the Stick's screen from nes/lib/logo.py.

    tools/gen_logo.py build

    nesp_logo.h       for the firmware (C): the picture, two pixels to a
                      byte, the left one in the high half, and the colour
                      of each number in it as 0xRRGGBB; 0 is the backdrop,
                      left as it is

The colours are the dark web page's (gen_web.py's LOGO_RGB), the logo as
the NES shows it. The file is rewritten only if its contents changed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nes", "lib"))
import logo  # noqa: E402
from gen_web import LOGO_RGB  # noqa: E402

# Each of the picture's characters, as a number in the header: '.' the
# backdrop, then the colours.
NUMBERS = {".": 0, "1": 1, "2": 2, "3": 3, "r": 4}


def c_header():
    width = logo.WIDTH + logo.WIDTH % 2
    lines = ["/* Written by tools/gen_logo.py from nes/lib/logo.py. Do not edit. */",
             "#pragma once", "", "#include <stdint.h>", "",
             "#define NESP_LOGO_WIDE %d" % logo.WIDTH,
             "#define NESP_LOGO_HIGH %d" % logo.HEIGHT,
             "#define NESP_LOGO_ROW_BYTES %d" % (width // 2), "",
             "static const uint32_t NESP_LOGO_RGB[%d] = {" % len(NUMBERS)]
    for char, number in sorted(NUMBERS.items(), key=lambda item: item[1]):
        rgb = LOGO_RGB.get(char, (0, 0, 0))
        lines.append("    0x%02X%02X%02Xu,   /* %s */" % (rgb + (char,)))
    lines += ["};", "",
              "static const uint8_t NESP_LOGO[NESP_LOGO_HIGH][NESP_LOGO_ROW_BYTES] = {"]
    for row in logo.PICTURE:
        numbers = [NUMBERS[char] for char in row.ljust(width, ".")]
        packed = [numbers[i] << 4 | numbers[i + 1] for i in range(0, width, 2)]
        lines.append("    {" + ",".join("0x%02X" % byte for byte in packed) + "},")
    lines += ["};", ""]
    return "\n".join(lines)


def write_if_changed(path, text):
    data = text.encode("ascii")
    try:
        with open(path, "rb") as handle:
            if handle.read() == data:
                return
    except FileNotFoundError:
        pass
    with open(path, "wb") as handle:
        handle.write(data)


def main(argv):
    out = argv[1]
    os.makedirs(out, exist_ok=True)
    write_if_changed(os.path.join(out, "nesp_logo.h"), c_header())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

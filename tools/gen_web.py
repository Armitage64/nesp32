#!/usr/bin/env python3
"""Put together the nesp32's web site: the product page, and the page that
flashes a nesp32 from a browser.

    tools/gen_web.py build/web build/nesp32.nes

    index.html            web/product/index.html, as it is
    style.css             web/style.css, which both pages use
    nesp32.nes            the cartridge, which the product page links to
    img/                  pictures of the programs, from their docs, and
                          img/logo.png and img/logo-dark.png, the header's logo
                          (nes/lib/logo.py) for a light page and a dark one
    flash/index.html      web/flash/index.html, as it is
    flash/manifest.json   what ESP Web Tools is to write, and where
    flash/s3-*.bin        the StickS3's firmware, from firmware/build-esp32s3
    flash/plus2-*.bin     the StickC Plus2's, from firmware/build-esp32

The firmware's pieces go as they are, each to its own offset, and are not
merged into one image: an image from 0 to the end of the firmware would
cover the `nvs` partition between them, and writing it would take the
nesp32's saved networks with every update.

The firmware has to have been built first (firmware/deploy.sh build), and
the cartridge (make cart; make web does that itself).
"""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WEB = os.path.join(ROOT, "web")

sys.path.insert(0, os.path.join(ROOT, "nes", "lib"))
import logo  # noqa: E402

# The logo's colours, as the screenshots show them: its palette's navy, cyan
# and white, and the NES's red for its 32.
LOGO_RGB = {"1": (0, 30, 116), "2": (56, 180, 204), "3": (236, 238, 236),
            "r": (152, 34, 32)}
# The dark page has it as the NES does. On the light page its 32 is the
# buttons' red (--accent in style.css), its white, the outline and the port,
# is black, and the word's blues change places: cyan letters with a navy
# band.
LOGO_OUTLINE_LIGHT = (0, 0, 0)
WORD_TOP = 14                   # the logo's first row of the word, under the Wi-Fi mark

# The product page's pictures: (its name for one, where it is)
PICTURES = [("cart-menu.png", "docs/cart-menu.png"),
            ("search.png", "apps/wiki/docs/search.png"),
            ("drmario.png", "apps/drmario/docs/network-game.png"),
            ("jukebox.png", "apps/jukebox/docs/screen.png"),
            ("status.png", "apps/setup/docs/status.png"),
            ("weather.png", "apps/weather/docs/screen.png"),
            ("npr-news.png", "apps/npr/docs/screen-news.png"),
            ("radar.png", "apps/nes-radar/docs/scope.png"),
            ("bluesky.png", "apps/bluesky/docs/screen-splash.png")]

# (ESP Web Tools' name for the chip, the build's directory, a prefix for its
# files). ESP Web Tools asks the chip what it is and writes the build for it:
# the StickS3's ESP32-S3, or the StickC Plus2's ESP32.
BOARDS = [("ESP32-S3", os.path.join(ROOT, "firmware", "build-esp32s3"), "s3"),
          ("ESP32", os.path.join(ROOT, "firmware", "build-esp32"), "plus2")]


def version():
    """The commit the firmware was built from, as git names it."""
    try:
        return subprocess.check_output(
            ["git", "-C", ROOT, "describe", "--always", "--dirty", "--tags"],
            text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def date():
    """The day of the commit the firmware was built from, as YYYY-MM-DD:
    the same for every build of it, wherever and whenever that is."""
    try:
        return subprocess.check_output(
            ["git", "-C", ROOT, "log", "-1", "--format=%cs"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build(family, directory, prefix, out):
    """Copy one board's files to `out` and return its entry in the manifest."""
    with open(os.path.join(directory, "flasher_args.json")) as f:
        files = json.load(f)["flash_files"]
    parts = []
    for offset, path in sorted(files.items(), key=lambda item: int(item[0], 0)):
        name = "%s-%s" % (prefix, os.path.basename(path))
        shutil.copyfile(os.path.join(directory, path), os.path.join(out, name))
        parts.append({"path": name, "offset": int(offset, 0)})
    return {"chipFamily": family, "parts": parts}


def fingerprint(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:8]


def page(source, target, versions):
    """A page, with each of its files in `versions` (name: fingerprint)
    asked for by a name that changes when the file does: a browser that
    kept the old one does not go on using it."""
    with open(source) as f:
        text = f.read()
    for name, version in versions.items():
        text = text.replace('%s"' % name, '%s?v=%s"' % (name, version))
    with open(target, "w") as f:
        f.write(text)


def accent():
    """style.css's --accent for the light page, as RGB: the first one."""
    with open(os.path.join(WEB, "style.css")) as f:
        found = re.search(r"--accent:\s*#([0-9a-fA-F]{6})", f.read())
    if not found:
        sys.exit("style.css: no --accent")
    return tuple(bytes.fromhex(found.group(1)))


def write_logo(path, red=LOGO_RGB["r"], outline=LOGO_RGB["3"], swap_blues=False):
    """The logo as a PNG, a pixel for each of the NES's, the backdrop clear,
    the 32 in `red` and the white in `outline`; with `swap_blues`, the
    word's navy and cyan change places."""
    colors = dict(LOGO_RGB, r=red)
    colors["3"] = outline
    picture = [line.translate(str.maketrans("12", "21")) if swap_blues and row >= WORD_TOP
               else line for row, line in enumerate(logo.PICTURE)]
    rows = b"".join(b"\0" + b"".join(bytes(colors[c] + (255,)) if c in colors else bytes(4)
                                      for c in line)
                    for line in picture)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    header = struct.pack(">IIBBBBB", len(logo.PICTURE[0]), len(logo.PICTURE), 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main(out, cart):
    if not os.path.exists(cart):
        sys.exit("No cartridge at %s: run make cart first." % os.path.relpath(cart))
    flash = os.path.join(out, "flash")
    os.makedirs(flash, exist_ok=True)
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    builds = []
    for family, directory, prefix in BOARDS:
        if not os.path.exists(os.path.join(directory, "flasher_args.json")):
            sys.exit("No firmware in %s: run firmware/deploy.sh build first."
                     % os.path.relpath(directory))
        builds.append(build(family, directory, prefix, flash))
    manifest = {
        "name": "nesp32",
        "version": version(),
        # Not ESP Web Tools': the flash page shows it beside the version.
        "date": date(),
        # The browser asks whether to erase first. Not erasing keeps the
        # saved networks and the music.
        "new_install_prompt_erase": True,
        "builds": builds,
    }
    with open(os.path.join(flash, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    shutil.copyfile(os.path.join(WEB, "style.css"), os.path.join(out, "style.css"))
    shutil.copyfile(cart, os.path.join(out, "nesp32.nes"))
    for name, path in PICTURES:
        shutil.copyfile(os.path.join(ROOT, path), os.path.join(out, "img", name))
    write_logo(os.path.join(out, "img", "logo.png"), accent(), LOGO_OUTLINE_LIGHT, swap_blues=True)
    write_logo(os.path.join(out, "img", "logo-dark.png"))
    # The pages last, since they name the files by what is in them.
    files = ["style.css", "nesp32.nes"] + ["img/" + name for name in os.listdir(
        os.path.join(out, "img"))]
    versions = {name: fingerprint(os.path.join(out, name)) for name in files}
    page(os.path.join(WEB, "flash", "index.html"), os.path.join(flash, "index.html"), versions)
    page(os.path.join(WEB, "product", "index.html"), os.path.join(out, "index.html"), versions)
    print("%s: nesp32 %s, %s" % (os.path.relpath(out), manifest["version"], manifest["date"]))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])

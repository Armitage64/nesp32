#!/usr/bin/env python3
"""Put together the nesp32's web site: the product page, and the page that
flashes a nesp32 from a browser.

    tools/gen_web.py build/web build/nesp32.nes

    index.html            web/product/index.html, as it is
    style.css             web/style.css, which both pages use
    nesp32.nes            the cartridge, which the product page links to
    img/                  pictures of the programs, from their docs
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
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WEB = os.path.join(ROOT, "web")

# The product page's pictures: (its name for one, where it is)
PICTURES = [("cart-menu.png", "docs/cart-menu.png"),
            ("search.png", "apps/wiki/docs/search.png"),
            ("jukebox.png", "apps/jukebox/docs/screen.png"),
            ("status.png", "apps/setup/docs/status.png"),
            ("weather.png", "apps/weather/docs/screen.png"),
            ("npr-news.png", "apps/npr/docs/screen-news.png"),
            ("radar.png", "apps/nes-radar/docs/scope.png")]

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


def page(source, target, style):
    """A page, with the stylesheet asked for by a name that changes when
    it does: a browser that kept the old one does not go on using it."""
    with open(source) as f:
        text = f.read()
    with open(target, "w") as f:
        f.write(text.replace('style.css"', 'style.css?v=%s"' % style))


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
    with open(os.path.join(WEB, "style.css"), "rb") as f:
        style = hashlib.sha256(f.read()).hexdigest()[:8]
    page(os.path.join(WEB, "flash", "index.html"), os.path.join(flash, "index.html"), style)
    page(os.path.join(WEB, "product", "index.html"), os.path.join(out, "index.html"), style)
    shutil.copyfile(os.path.join(WEB, "style.css"), os.path.join(out, "style.css"))
    shutil.copyfile(cart, os.path.join(out, "nesp32.nes"))
    for name, path in PICTURES:
        shutil.copyfile(os.path.join(ROOT, path), os.path.join(out, "img", name))
    print("%s: nesp32 %s, %s" % (os.path.relpath(out), manifest["version"], manifest["date"]))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])

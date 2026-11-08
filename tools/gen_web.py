#!/usr/bin/env python3
"""Put together the nesp32's web site: the product page, and the page that
flashes a nesp32 from a browser.

    tools/gen_web.py build/web build/nesp32.nes     this tree's own builds
    tools/gen_web.py build/web --release DIR        a release's, as the web
                                                    site has them

The site's firmware and cartridge are the latest release's, from its GitHub
release: DIR holds what release.yml attached to it (nesp32-X.Y.Z.nes,
nesp32-s3-X.Y.Z.zip, nesp32-plus2-X.Y.Z.zip, nesp32-s3-generic-X.Y.Z.zip)
and release.json, which web.yml writes (gh release view --json tagName,publishedAt,url). The pages
and the ROM patches are this tree's, so they go up without a release.

    index.html            web/product/index.html, as it is
    style.css             web/style.css, which both pages use
    nesp32.nes            the cartridge, which the product page links to
    nesp32-rom-patches.zip  each game's BPS patch, from apps/*/dist/ as
                          committed, and web/patches/README.txt for players
    img/                  pictures of the programs, from their docs, and
                          img/logo.png and img/logo-dark.png, the header's logo
                          (nes/lib/logo.py) for a light page and a dark one
    flash/index.html      web/flash/index.html, as it is
    flash/manifest.json   what ESP Web Tools is to write for the nesp32 hat,
                          and where
    flash/manifest-generic.json  and for an ESP32-S3 wired with resistors
    flash/s3-*.bin        the StickS3's firmware, from firmware/build-esp32s3
    flash/plus2-*.bin     the StickC Plus2's, from firmware/build-esp32
    flash/s3-generic-*.bin  the generic ESP32-S3's, from
                          firmware/build-esp32s3-generic

The firmware's pieces go as they are, each to its own offset, and are not
merged into one image: an image from 0 to the end of the firmware would
cover the `nvs` partition between them, and writing it would take the
nesp32's saved networks with every update.

Without --release, the firmware has to have been built first
(firmware/deploy.sh build), and the cartridge (make cart; make web does
that itself), and the site says it is this tree's version (0.2.0-dev).
"""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

import version

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

# (the manifest it is in, ESP Web Tools' name for the chip, the build's
# directory, a prefix for its files). The flash page asks how the nesp32 is
# wired and gives ESP Web Tools that manifest, which asks the chip what it
# is and writes the build for it. The nesp32 hat's, manifest.json, has the
# StickS3's ESP32-S3 and the StickC Plus2's ESP32; the resistors',
# manifest-generic.json, has only the ESP32-S3.
HAT = "manifest.json"
GENERIC = "manifest-generic.json"
BOARDS = [(HAT, "ESP32-S3", os.path.join(ROOT, "firmware", "build-esp32s3"), "s3"),
          (HAT, "ESP32", os.path.join(ROOT, "firmware", "build-esp32"), "plus2"),
          (GENERIC, "ESP32-S3", os.path.join(ROOT, "firmware", "build-esp32s3-generic"),
           "s3-generic")]


def date(*paths):
    """The day of the last commit (to `paths`, if given), as YYYY-MM-DD:
    the same for every build of it, wherever and whenever that is."""
    try:
        return subprocess.check_output(
            ["git", "-C", ROOT, "log", "-1", "--format=%cs", "--"] + list(paths),
            text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def numbers(text):
    """A version's numbers, to compare: (0, 2, 0) for 0.2.0 or 0.2.0-dev."""
    return tuple(int(part) for part in re.match(r"v?(\d+)\.(\d+)\.(\d+)", text).groups())


# The patches that make the games that are not on the cartridge, each
# from the player's own copy: as committed, since the game is needed to
# make one (`make bps` in the app's directory). Each with the first release
# of the firmware it works with: a patch that needs a firmware not yet
# released is not put on the site.
PATCHES = [("apps/drmario/dist/drmario_net.bps", "0.2.0"),
           ("apps/tetris/dist/tetris_net.bps", "0.2.0"),
           ("apps/contra/dist/contra_net.bps", "0.2.0"),
           ("apps/tmnt2/dist/tmnt2_net.bps", "0.2.0"),
           ("apps/bubblebobble/dist/bubblebobble_net.bps", "0.2.0"),
           ("apps/jackal/dist/jackal_net.bps", "0.2.0"),
           ("apps/family-basic/dist/fbasic.bps", "0.2.0")]


def write_patches(path, firmware, release):
    """The patches and their README in one zip, the same for every build
    until one of them changes: each entry dated the day of the last commit
    to them. `firmware` is the site's; with `release`, a patch that needs
    a later one stops the build."""
    missing = [name for name, _ in PATCHES if not os.path.exists(os.path.join(ROOT, name))]
    if missing:
        sys.exit("No %s: run make bps in its app." % ", ".join(missing))
    needs = max((needed for _, needed in PATCHES), key=numbers)
    later = [os.path.basename(name) for name, needed in PATCHES
             if numbers(needed) > numbers(firmware)]
    if later:
        complaint = "%s need firmware %s, and the site's is %s." % (", ".join(later), needs, firmware)
        if release:
            sys.exit(complaint + " Release the firmware first.")
        print("Warning: " + complaint)
    day = date(*[name for name, _ in PATCHES] + ["web/patches"])
    stamp = tuple(int(part) for part in (day or "1980-01-01").split("-")) + (0, 0, 0)
    with open(os.path.join(WEB, "patches", "README.txt")) as f:
        readme = f.read().replace("{date}", day).replace("{firmware}", needs)
    entries = [("README.txt", readme.encode())]
    for name, _ in PATCHES:
        with open(os.path.join(ROOT, name), "rb") as f:
            entries.append((os.path.basename(name), f.read()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


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


def page(source, target, versions, release):
    """A page, with each of its files in `versions` (name: fingerprint)
    asked for by a name that changes when the file does: a browser that
    kept the old one does not go on using it. {version} and {notes} are the
    release's number and the page of what is new in it."""
    with open(source) as f:
        text = f.read()
    text = text.replace("{version}", release["version"]).replace("{notes}", release["notes"])
    for name, mark in versions.items():
        text = text.replace('%s"' % name, '%s?v=%s"' % (name, mark))
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


def released(directory, unpacked):
    """A release's cartridge, each board's firmware's directory (unpacked
    from its zip), and its number, day and notes."""
    with open(os.path.join(directory, "release.json")) as f:
        about = json.load(f)
    number = about["tagName"].lstrip("v")
    cart = os.path.join(directory, "nesp32-%s.nes" % number)
    builds = []
    for manifest, family, _, prefix in BOARDS:
        place = os.path.join(unpacked, prefix)
        packed = os.path.join(directory, "nesp32-%s-%s.zip" % (prefix, number))
        # Releases before the generic firmware have none: the flash page
        # then offers only the hat.
        if manifest == GENERIC and not os.path.exists(packed):
            print("%s has no generic ESP32-S3 firmware: no %s" % (about["tagName"], GENERIC))
            continue
        with zipfile.ZipFile(packed) as z:
            z.extractall(place)
        builds.append((manifest, family, place, prefix))
    return cart, builds, {"version": number, "date": about["publishedAt"][:10],
                          "notes": about["url"]}


def main(out, cart=None, release=None):
    unpacked = tempfile.TemporaryDirectory()
    if release:
        cart, boards, about = released(release, unpacked.name)
    else:
        boards = BOARDS
        about = {"version": version.text(), "date": date(),
                 "notes": "https://github.com/Armitage64/nesp32/blob/main/CHANGELOG.md"}
    if not os.path.exists(cart):
        sys.exit("No cartridge at %s: run make cart first." % os.path.relpath(cart))
    flash = os.path.join(out, "flash")
    os.makedirs(flash, exist_ok=True)
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    builds = {}
    for name, family, directory, prefix in boards:
        if not os.path.exists(os.path.join(directory, "flasher_args.json")):
            sys.exit("No firmware in %s: run firmware/deploy.sh build first."
                     % os.path.relpath(directory))
        builds.setdefault(name, []).append(build(family, directory, prefix, flash))
    for name, its in builds.items():
        manifest = {
            "name": "nesp32",
            "version": about["version"],
            # Not ESP Web Tools': the flash page shows them beside the version.
            "date": about["date"],
            "notes": about["notes"],
            # The browser asks whether to erase first. Not erasing keeps the
            # saved networks and the music.
            "new_install_prompt_erase": True,
            "builds": its,
        }
        with open(os.path.join(flash, name), "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
    shutil.copyfile(os.path.join(WEB, "style.css"), os.path.join(out, "style.css"))
    shutil.copyfile(cart, os.path.join(out, "nesp32.nes"))
    write_patches(os.path.join(out, "nesp32-rom-patches.zip"), about["version"], release)
    for name, path in PICTURES:
        shutil.copyfile(os.path.join(ROOT, path), os.path.join(out, "img", name))
    write_logo(os.path.join(out, "img", "logo.png"), accent(), LOGO_OUTLINE_LIGHT, swap_blues=True)
    write_logo(os.path.join(out, "img", "logo-dark.png"))
    # The pages last, since they name the files by what is in them.
    files = ["style.css", "nesp32.nes", "nesp32-rom-patches.zip"] + ["img/" + name for name in os.listdir(
        os.path.join(out, "img"))]
    versions = {name: fingerprint(os.path.join(out, name)) for name in files}
    page(os.path.join(WEB, "flash", "index.html"), os.path.join(flash, "index.html"), versions, about)
    page(os.path.join(WEB, "product", "index.html"), os.path.join(out, "index.html"), versions, about)
    unpacked.cleanup()
    print("%s: nesp32 %s, %s" % (os.path.relpath(out), manifest["version"], manifest["date"]))


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], cart=sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[2] == "--release":
        main(sys.argv[1], release=sys.argv[3])
    else:
        sys.exit(__doc__)

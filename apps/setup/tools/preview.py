#!/usr/bin/env python3
"""Pictures of the setup ROM's screens, for the README.

    tools/preview.py docs [CART_DOCS]

Runs nesp32's build/setup.nes on its tests' simulated console against the
firmware's own link and services (build/libnesp_host), works it with the
controller, and writes what the nametable and the sprites hold at each stop
as a PNG. Needs `make` at the top of the repository first. With a second
directory, and after `make cart` there, the cartridge's menu goes to it as
cart-menu.png.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..")
BUILD = os.environ.setdefault("NESP_BUILD", os.path.join(ROOT, "build"))
for path in (BUILD, "host", "tests"):
    sys.path.insert(0, os.path.join(ROOT, path))
sys.path.insert(0, HERE)

import gen_screen as layout  # noqa: E402
import nesp_proto as p  # noqa: E402
from console import Console  # noqa: E402
from drive import (MENU_TEST, MENU_USB, PAD_B, PAD_DOWN, PAD_START, STATE_FAILED, STATE_JOINING, STATE_KEYS,  # noqa: E402
                   STATE_STATUS, STATE_TEST, STATE_USB, Setup)
from nesp import Stick  # noqa: E402
from wire import link  # noqa: E402

NETWORKS = [(b"Home Network", -48, p.NESP_AUTH_PASSWORD), (b"Upstairs", -58, p.NESP_AUTH_PASSWORD),
            (b"Cafe Guest", -66, p.NESP_AUTH_OPEN), (b"printer-7f3a", -71, p.NESP_AUTH_PASSWORD),
            (b"Neighbours", -84, p.NESP_AUTH_PASSWORD)]


def picture(console):
    names = console.vram[0x2000:0x2000 + 960]
    sprites = [sprite for sprite in (console.sprite(index) for index in range(64)) if sprite]
    return layout.render(console.chr, names, sprites=sprites)


def main(argv):
    out = argv[1]
    os.makedirs(out, exist_ok=True)

    def save(name, console):
        layout.write_png(os.path.join(out, name + ".png"), picture(console))

    console = Console(os.path.join(BUILD, "setup.nes"), os.path.join(BUILD, "setup.labels"))
    console.run(60)
    save("no-stick", console)

    stick, port = link(console, Stick)
    setup = Setup(console, stick, port)
    stick.set_battery(83)
    console.run_until(lambda: console.byte("linked"), 300)
    setup.settle(80)
    save("status-new", console)

    setup.scan(NETWORKS)
    setup.press(PAD_DOWN)
    save("list", console)

    setup.choose(0)
    setup.wait_for(STATE_KEYS)
    setup.type("Tr0ub4dor&3")
    setup.settle(6)
    save("password", console)

    setup.press(PAD_START)
    setup.wait_for(STATE_JOINING)
    stick.set_wifi(p.NESP_WIFI_FAILED, why=p.NESP_WHY_PASSWORD)
    setup.wait_for(STATE_FAILED)
    setup.settle(10)
    save("failed", console)

    setup.press(PAD_START)
    setup.wait_for(STATE_KEYS)
    setup.press(PAD_START)
    setup.wait_for(STATE_JOINING)
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-48, address=(192, 168, 1, 77))
    setup.wait_for(STATE_STATUS)
    setup.settle(80)
    save("status", console)

    stick.note_turnaround(212)
    stick.note_turnaround(148)
    setup.menu(MENU_TEST)
    setup.wait_for(STATE_TEST)
    console.run(700)
    save("test", console)

    setup.press(PAD_B)
    setup.wait_for(STATE_STATUS)
    setup.menu(MENU_USB)
    setup.wait_for(STATE_USB)
    stick.set_drive(p.NESP_DRIVE_MOUNTED)
    setup.wait_for_message("THE USB DRIVE IS MOUNTED")
    setup.settle(10)
    save("usb", console)

    cart = os.path.join(BUILD, "nesp32.nes")
    if len(argv) > 2 and os.path.exists(cart):
        out = argv[2]
        os.makedirs(out, exist_ok=True)
        console = Console(cart, os.path.join(BUILD, "cart", "menu.labels"))
        console.run(10)
        save("cart-menu", console)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""What the netplay counts on of the game, held to the original ROM: the zero
page it lends the link is the game's to lend, and it never picks a bank the
netplay ROM has put its own in."""

import random
from itertools import islice

import console as console_module
from drive import PAD_A, PAD_B, PAD_DOWN, PAD_START, PAD_UP, moves, press, two_players

# The link's zero page (net/net_ram.inc).
LINK_ZERO_PAGE = (0x15, 0x16, 0x17, 0xF3, 0xF9, 0xFA)
BANKS = 7                       # the game's switchable banks, 0 to 6
PLAY_FRAMES = 6000


def play_with_pauses(nes, seed):
    """A game for two at random, with the pause's screens now and then."""
    for pads in two_players():
        nes.run(1, pads=pads)
    rng = random.Random(seed)
    play = moves(seed)
    while len(nes.frames) < PLAY_FRAMES:
        for pads in islice(play, 900):
            nes.run(1, pads=pads)
        player = rng.randrange(2)
        script = press(PAD_START, player, rest=60)
        for _ in range(rng.randrange(4)):
            script += press(rng.choice((PAD_UP, PAD_DOWN)), player, rest=20)
        script += press(PAD_A, player, rest=120) + press(PAD_B, player, rest=40)
        script += press(PAD_B, player, rest=40) + press(PAD_START, player, rest=60)
        for pads in script:
            nes.run(1, pads=pads)


def test_the_game_leaves_the_links_zero_page_alone(console, monkeypatch):
    touched = set()
    read, write = console_module.Bus.__getitem__, console_module.Bus.__setitem__

    def get(bus, address):
        if address in LINK_ZERO_PAGE:
            touched.add(address)
        return read(bus, address)

    def put(bus, address, value):
        if address in LINK_ZERO_PAGE:
            touched.add(address)
        write(bus, address, value)
    monkeypatch.setattr(console_module.Bus, "__getitem__", get)
    monkeypatch.setattr(console_module.Bus, "__setitem__", put)
    nes = console()
    play_with_pauses(nes, 1)
    assert touched == set()


def test_the_game_picks_none_of_the_netplays_banks(console):
    """Every switch the game makes is BANK_PAIR's, the pair in A."""
    nes = console()
    picked = set()
    nes.watch("BANK_PAIR", lambda nes: picked.add(nes.mpu.a))
    play_with_pauses(nes, 2)
    assert picked and max(picked) < BANKS

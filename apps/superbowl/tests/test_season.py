"""The season in a session: TEAM CONTROL, a season game for two played to
its end, a week of the CPU's games skipped through (SCHEDULE's autoskip),
and the season's last game into the standings and the playoffs. The season
is in the save RAM, so the two consoles' saves are compared at the end of
each, and tick by tick with the rest of the game.

A whole season would take hours in the simulation, so a test that needs the
season further on puts it there itself, the same on both consoles at a
tick, with the save's checksum made right as the game makes it."""

from drive import PAD_A, PAD_B, PAD_DOWN
from netplay import Table
from test_game import END_OF_GAME_STATS, GAME_BANKS, game_banks, in_session, scenes
from test_game import short_quarters, tap
from test_lockstep import moves
from test_menu import save_of
from wire import ms

SKP = 3                         # TEAM_TYPE_SEASON: MAN 0, COA 1, COM 2, SKP 3
MAN = 0
TEAMS = 28
LAST_WEEK, PLAYOFFS = 0x10, 0x11
MAX_GAMES_PER_WEEK = 14
# The save's checksum (CALCULATE_CHECKSUM): the sum of these, plus $3412.
CHECKSUM_RANGES = ((0x66C0, 0x083E), (0x7002, 0x0F70))
CHECKSUM_CONSTANT = 0x3412
GAME_FRAMES = 9000
SKIP_FRAMES = 30000             # a week of the CPU's games, with no presses
PLAYOFF_PRESSES = 80


def sram(console, name, offset=0):
    return console.bus.prg_ram[console.labels[name] + offset - 0x6000]


def set_sram(console, name, value, offset=0):
    console.bus.prg_ram[console.labels[name] + offset - 0x6000] = value


def fix_checksum(console):
    ram = console.bus.prg_ram
    total = CHECKSUM_CONSTANT + sum(sum(ram[start - 0x6000:start - 0x6000 + length])
                                    for start, length in CHECKSUM_RANGES)
    set_sram(console, "SRAM_CHECKSUM", total & 0xFF)
    set_sram(console, "SRAM_CHECKSUM", (total >> 8) & 0xFF, 1)


def change_season(table, change):
    """The season changed on both consoles alike at a tick soon, at the main
    menu, and the save's checksum made right."""
    def changed(console):
        change(console)
        fix_checksum(console)
    table.at_tick(max(table.ticks(0), table.ticks(1)) + 5, changed)
    table.run(20)


def to_season_menu(table):
    """From a session's start at the main menu: SEASON GAME."""
    table.run(90)
    tap(table, 0, PAD_DOWN, 30)
    tap(table, 0, PAD_A, 150)


def season_choice(table, downs):
    """One of the season menu's lines, from its first, TEAM CONTROL."""
    for _ in range(downs):
        tap(table, 0, PAD_DOWN, 20)
    tap(table, 0, PAD_A, 150)


TEAM_CONTROL, SCHEDULE, GAME_START = 0, 1, 2
SEASON_MENU_ARROWS = (0x50, 0x60, 0x70)  # the arrow's Y beside those three


def controls(console):
    return [sram(console, "TEAM_TYPE_SEASON", team) for team in range(TEAMS)]


def ended(table, drawn, play=None):
    """Run (with buttons from `play`, or none) until both consoles have
    drawn the statistics after a game."""
    start = table.frames()
    while not all(END_OF_GAME_STATS in side for side in drawn):
        assert table.frames() - start < GAME_FRAMES
        if play:
            table.play(50, play)
        else:
            table.run(50)


def test_a_season_game_for_two(net_console):
    """TEAM CONTROL's A on its first team makes it MAN; the week's first
    game's two teams are made MAN, and GAME START is that game for two,
    played to its end, its result and statistics in the season."""
    table = Table(net_console, delay=ms(10))
    table.start()
    picked = game_banks(table)
    to_season_menu(table)
    host = table.consoles[0]
    before = controls(host)
    assert set(before) == {SKP}
    season_choice(table, TEAM_CONTROL)
    tap(table, 0, PAD_A, 60)
    tap(table, 0, PAD_B, 150)
    for console in table.consoles:
        after = controls(console)
        assert sorted(after) == [MAN] + [SKP] * (TEAMS - 1)

    def for_two(console):
        for side in range(2):
            team = sram(console, "WEEKLY_MATCHUPS_START", side)
            set_sram(console, "TEAM_TYPE_SEASON", MAN, team)
    change_season(table, for_two)
    season_choice(table, GAME_START)
    # The two teams, the coin toss (whose winner chooses), and the kickoff.
    for press in range(12):
        if host.byte("CLOCK_MINUTES") == 5:
            break
        tap(table, press % 2, PAD_A, 120)
    assert host.byte("CLOCK_MINUTES") == 5
    assert host.byte("TEAM_CONTROL_TYPES") == 0      # MAN VS MAN
    table.every_tick(short_quarters)
    drawn = scenes(table)
    ended(table, drawn, moves(11))
    table.every_tick(None)
    table.run(300)
    tap(table, 0, PAD_A, 300)
    for console in table.consoles:
        assert sram(console, "CURRENT_WEEK_IN_SEASON") == 0
        assert sram(console, "CURRENT_GAME_IN_WEEK") == 1
    in_session(table)
    assert table.same_game() > 4000
    assert save_of(table.consoles[0]) == save_of(table.consoles[1])
    assert picked and max(picked) < GAME_BANKS


def test_a_week_skipped(net_console):
    """SCHEDULE's autoskip to the next week, and GAME START: the week's
    games played out by the CPU with no buttons pressed."""
    table = Table(net_console, delay=ms(10))
    table.start()
    picked = game_banks(table)
    to_season_menu(table)
    season_choice(table, SCHEDULE)
    tap(table, 0, PAD_A, 60)            # the schedule's menu
    tap(table, 0, PAD_A, 60)            # AUTO SKIP: TO WEEK, the week after this one
    tap(table, 0, PAD_A, 120)
    for console in table.consoles:
        assert sram(console, "WEEK_TO_SKIP_TO") == 1
    host = table.consoles[0]
    for _ in range(3):
        if host.byte("MENU_ARROW_SPR_Y") in SEASON_MENU_ARROWS:
            break
        tap(table, 0, PAD_B, 150)
    arrow = host.byte("MENU_ARROW_SPR_Y")
    assert arrow in SEASON_MENU_ARROWS
    season_choice(table, GAME_START - SEASON_MENU_ARROWS.index(arrow))
    start = table.frames()
    while sram(host, "CURRENT_WEEK_IN_SEASON") == 0:
        assert table.frames() - start < SKIP_FRAMES
        table.run(200)
    table.run(300)
    in_session(table)
    assert table.same_game() > 1000
    assert save_of(table.consoles[0]) == save_of(table.consoles[1])
    assert picked and max(picked) < GAME_BANKS


def test_the_season_into_the_playoffs(net_console):
    """The last game of the last week, which ends the season: the standings,
    the playoffs' teams, and GAME START again, the first playoff game."""
    table = Table(net_console, delay=ms(10))
    table.start()
    picked = game_banks(table)

    def last_game(console):
        set_sram(console, "CURRENT_WEEK_IN_SEASON", LAST_WEEK)
        set_sram(console, "CURRENT_GAME_IN_WEEK", MAX_GAMES_PER_WEEK - 1)
    table.run(90)
    change_season(table, last_game)
    tap(table, 0, PAD_DOWN, 30)
    tap(table, 0, PAD_A, 150)
    season_choice(table, GAME_START)
    host = table.consoles[0]
    played = False
    for _ in range(PLAYOFF_PRESSES):
        if sram(host, "CURRENT_WEEK_IN_SEASON") == PLAYOFFS and sram(host, "CURRENT_GAME_IN_WEEK"):
            played = True
            break
        if host.byte("MENU_ARROW_SPR_Y") == 0x50 and sram(host, "CURRENT_WEEK_IN_SEASON") == PLAYOFFS:
            season_choice(table, GAME_START)    # back at the season menu: the playoffs' first game
        else:
            tap(table, 0, PAD_A, 150)
    assert played
    in_session(table)
    assert table.same_game() > 2000
    assert save_of(table.consoles[0]) == save_of(table.consoles[1])
    assert picked and max(picked) < GAME_BANKS

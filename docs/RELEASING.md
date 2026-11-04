# Releases

The nesp32's firmware and its cartridge are released together, under one
number, from main. The web site offers players the latest release, not
whatever is on main. The site's own pages and the games' ROM patches are
not part of a release: they go up whenever they change on main.

## Version numbers

`VERSION`, at the top of the tree, holds the number: `0.2.0`.

- **Minor** (0.2.0 → 0.3.0): a change to the protocol, or something new
  a player or a ROM can use.
- **Patch** (0.2.0 → 0.2.1): fixes only.
- **Major** stays 0 for now.
- A **pre-release**, such as `0.3.0-rc.1`, is built and attached to a
  GitHub pre-release for testing, and the web site keeps the last release.

`tools/version.py` gives the version, and everything else takes it from
there. That covers the firmware (through `nesp_version.h`, which the build
writes), the host library and its tests, `tools/lcd.py` and the site. A build of the
commit tagged `v0.2.0`, with nothing changed, is the release and says
`0.2.0`. Any other build says `0.2.0-dev`, on the Stick's screen, in
Setup's FIRMWARE, and on a site built with `make web`. Its numbers in the
hello reply stay 0.2.0. A ROM that asks for a firmware version means a
release, so a ROM's minimum is raised in the release that brings what
it needs.

The firmware's boot log also gives the commit, as `git describe` names
it (ESP-IDF's `PROJECT_VER`), e.g. `nesp32 0.2.0-dev (v0.2.0-3-g1a2b3c4)`.

## The changelog

`CHANGELOG.md` says what changed in each release, for players and ROM
authors. It is short on purpose:

- A pull request that changes something a player or a ROM sees adds one
  line under **Unreleased**, under Firmware, Cartridge or Protocol, with
  its number. One that changes nothing they see adds nothing.
- Say what changed for them, not how: "Setup: type the Wi-Fi password on
  a Bluetooth keyboard (#55)".
- A change to the protocol says what a ROM can now use, and that it needs
  this release's firmware.

## Cutting a release

1. Look over **Unreleased** in `CHANGELOG.md` on main, and fix it there
   first if it needs it.
2. `tools/release.py 0.3.0`. From an up-to-date `origin/main` and a clean
   tree, it makes the branch `release-0.3.0`. There it writes `VERSION`,
   turns **Unreleased** into `## 0.3.0 — <today>` under a new empty
   Unreleased, and commits the two.
3. Push the branch and open a pull request. Edit the notes in it if you
   like.
4. Merge it. That's the release. `.github/workflows/release.yml` sees
   VERSION change on main and:
   - tags the merged commit `v0.3.0`;
   - builds both Sticks' firmware (and checks that they say 0.3.0), runs
     the tests, and builds the cartridge;
   - makes the GitHub release *nesp32 0.3.0*, with CHANGELOG.md's section
     as its notes. It attaches `nesp32-0.3.0.nes`, `nesp32-s3-0.3.0.zip`
     and `nesp32-plus2-0.3.0.zip` (`tools/release.py pack`);
   - runs `web.yml`, which puts them on the site.

If a run fails, fix the cause on main and run *Release* again from the
Actions tab. A tag that is already the commit's is kept, and the files on
an existing GitHub release are replaced. If the fix has to change the
released commit, release the next patch version instead of moving a tag
players may already have.

## The web site

`.github/workflows/web.yml` builds nothing. It downloads the latest
release's files from GitHub (`gh release download`) and makes the site
with `tools/gen_web.py --release`. It runs:

- when a release is made;
- when the pages, the pictures or the ROM patches change on main
  (`web/`, `apps/*/dist/`, ...);
- by hand, from the Actions tab.

So a change to the product page, or a new patch, goes up as soon as it
is merged, and firmware on main waits for its release.

`make web` builds the same site locally from this tree's own builds, and
says it is `-dev`. `make web-serve` serves it.

## The ROM patches

`nesp32-rom-patches.zip` is made from `apps/*/dist/*.bps` as committed,
and is dated by the last commit to them. Each patch in `PATCHES` in
`tools/gen_web.py` gives the first release of the firmware it works with,
and the zip's README tells players the highest one. If a patch needs a
firmware that has not been released yet, web.yml fails and the site stays
as it was: release the firmware first. `make web` only warns.

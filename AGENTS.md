# Notes for AI assistants (and people)

## NES Radar and the nes-radar submodule

NES Radar lives in two repositories. Read this before changing anything
in `apps/nes-radar`, `third_party/nes-radar` or the RADAR service.

- **[k6lcm/nes-radar](https://github.com/k6lcm/nes-radar)** is the source
  of truth for the ROM, including the cartridge build (`.ifdef CART`). It
  is the submodule at `third_party/nes-radar`. Nothing here patches it.
- **Here** are what builds it for the cartridge and the tests
  (`apps/nes-radar`), the firmware's RADAR service
  (`firmware/components/nesp_services/radar.c`), and the link protocol
  (`proto/nesp.toml`, `nes/lib/`).
- nes-radar's `legacy/ftdi-0.4.x` branch is the old FTDI cable version.
  Nothing here uses it.

### Where a change goes

| Change | Where | Then |
|---|---|---|
| The ROM: screens, buttons, LINK, bugs | nes-radar | release it there; then a PR here that moves the submodule to the new commit |
| Cartridge-only ROM behaviour (`CART`) | nes-radar | `tests/test_cart.py` here covers it |
| The link protocol (`proto/nesp.toml`, `nes/lib/`) | here | in nes-radar: `nes_radar/tools/update_nesp32.sh /path/to/this/repo`, commit, push, then move the submodule here |
| Firmware, RADAR service, other apps | here only | nothing in nes-radar, unless the protocol changed |
| Needs both (e.g. a new RADAR request) | both | nes-radar first, then the PR here also moves the submodule |

### Rules

- Work on nes-radar in `third_party/nes-radar`: it is a full clone. Make
  a branch there, and run the tests here against it before pushing
  either repository:
  `make -C apps/nes-radar verify test` and
  `pytest tests/test_cart.py tests/test_radar.py`.
- **Push nes-radar first**, and get the commit onto its `main` (merge
  commit, not squash). Never push a commit here whose submodule points at
  a nes-radar commit GitHub doesn't have.
- `make -C apps/nes-radar verify` fails when nes-radar's copy of the link
  library (`nes_radar/vendor/nesp32/`) differs from this repository's.
  Fix it in nes-radar with `update_nesp32.sh`, never by editing the copy.
- The submodule need not follow every nes-radar commit: move it when the
  ROM, or something built here from it, changes.
- `tests/fixtures/nes-radar-server/` is a frozen copy of nes-radar's
  0.4.4 server, which `tests/test_radar.py` holds the RADAR service's
  scenes to. Don't update it from nes-radar: nes-radar has no server from
  0.5.0.
- To try a change on hardware, `make cart` builds `build/nesp32.nes`, the
  whole cartridge with NES Radar from `third_party/nes-radar` as it is
  checked out.

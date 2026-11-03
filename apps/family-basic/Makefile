# Family BASIC V3 with nesp32's Bluetooth keyboard.
#
#   make            build/fbasic.nes
#   make verify     check its size and header
#   make test       the ROM against nesp32's firmware, on a simulated console
#   make bps        dist/fbasic.bps again: the ROM as a patch to the game,
#                   which players apply to their own copy
#
# The game is not in this repository: put a copy of Family BASIC V3 in
# baserom.nes, or say where it is with BASEROM=. tools/fbasic.py checks it.
#
# The ROM's host is a nesp32, whose firmware is at the top of this
# repository (two directories up). From it come the link's library for
# the console and the numbers the two ends share.

BUILD ?= build
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
BASEROM ?= baserom.nes
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/fbasic.nes
ROM_SIZE := 73744   # 16-byte header + 64 KB PRG + 8 KB CHR
# The ROM as a patch to Family BASIC V3, for players who build nothing:
# kept in the repository, as it holds none of the game (tools/gen_patch.py
# refuses one that would). The game's 8 KB of CHR is after its 32 KB of
# PRG in its file, and after the 64 KB in ours: the patch copies it from
# the player's own ROM.
DIST := dist
GEN_PATCH := $(NESP32)/tools/gen_patch.py

.PHONY: all verify test bps clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto
	@test -f $@ || touch $@

# Every exchange is made in the NMI: the receiver that gives up by counting.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout

$(BUILD)/keys.inc: tools/gen_keys.py tools/fbasic.py $(BASEROM) $(NESP) | $(BUILD)
	$(PYTHON) tools/gen_keys.py $(BASEROM) $(NESP_BUILD) $@

$(BUILD)/fbkbd.o: nes/fbkbd.s $(NESP_LIB) $(BUILD)/link.inc $(BUILD)/keys.inc $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib -o $@ $<

$(BUILD)/fbkbd.bin: $(BUILD)/fbkbd.o nes/mmc1.cfg
	ld65 -C nes/mmc1.cfg -o $@ -Ln $(BUILD)/fbkbd.labels \
		--dbgfile $(BUILD)/fbkbd.dbg -m $(BUILD)/fbkbd.map $<

$(ROM): $(BUILD)/fbkbd.bin tools/build_rom.py tools/fbasic.py $(BASEROM)
	$(PYTHON) tools/build_rom.py $(BASEROM) $< $(BUILD)/fbkbd.labels $@

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))"
	printf 'NES\032\004\001\023\000\001' | cmp -n 9 - $(ROM)

test:
	$(PYTHON) -m pytest

# From the game itself: tools/fbasic.py has checked its SHA-1 as the ROM
# was built, and the patch is for that one release.
bps: verify
	mkdir -p $(DIST)
	$(PYTHON) $(GEN_PATCH) $(BASEROM) $(ROM) $(DIST)/fbasic.bps

clean:
	rm -rf $(BUILD)

FORCE:

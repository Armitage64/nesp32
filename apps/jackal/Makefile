# Jackal build.
#
#   make            build/jackal.nes, the original, and build/jackal_net.nes,
#                   for two consoles and two nesp32s; and
#                   build/jackal_net_slow.nes, the same with the game's own
#                   routines where the netplay has faster ways, for the tests
#                   to hold the two alike
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the sources in build/src
#   make bps        dist/jackal_net.bps again, the netplay ROM as a patch to
#                   the game, which players apply to their own
#   make bench      how long the frames of the game take, each ROM, each
#                   level, for two players (tools/bench.py)
#   make clean
#
# The game is not here. Its source is RayofJay's disassembly, a submodule at
# third_party/NES-Jackal_Disassembly_Fully_Commented, which is for ASM6 and
# leaves out the graphics. tools/convert.py makes ca65 source of it in
# build/gen, with what it leaves out taken from baserom.nes, which whoever
# builds has to put here. The source is copied to build/src, and patches/
# puts the netplay's few lines into the copy. Everything they add is under
# .ifdef NETPLAY, so jackal.nes stays the original, byte for byte, and
# `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The netplay ROM's link is nesp32's, at the top of this repository (two
# directories up). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The original ROM needs
# none of it.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/jackal.nes
NET_ROM := $(BUILD)/jackal_net.nes
SLOW_ROM := $(BUILD)/jackal_net_slow.nes
# The netplay ROM as a patch to the US release, for players who build
# nothing: kept in the repository, as it holds none of the game
# (tools/gen_patch.py refuses one that would).
DIST := dist
GEN_PATCH := $(NESP32)/tools/gen_patch.py
# Jackal (USA), with its iNES header.
SHA512_ORIGINAL := 9306817c5edf72c08608fc5f0e3854ac9410f8933ab871a929fa6699596597766b6f644ca2d83a8ee794072630e8edb970e5ded8cd1bb73374762e1344439385
BASEROM ?= baserom.nes
# The disassembly's directory has a space in its name: make is given the
# one file it has to watch with the space escaped, and the converter the
# directory in quotes.
DISASM := $(NESP32)/third_party/NES-Jackal_Disassembly_Fully_Commented/ASM Source
DISASM_MAIN := $(NESP32)/third_party/NES-Jackal_Disassembly_Fully_Commented/ASM\ Source/MAIN.asm
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
# The converted files, all of them assembled as one unit (jackal.asm), and
# those that patches/ changes.
FILES := jackal symbols header bank0 bank1 bank2 bank3 bank4 bank5 bank6 bank7
PATCHED := header bank1 bank7
SOURCES := $(SRC)/jackal.asm $(SRC)/symbols.inc $(patsubst %,$(SRC)/%.asm,header bank0 bank1 bank2 bank3 bank4 bank5 bank6 bank7)
NET_SOURCES := $(wildcard net/*.inc net/*.asm) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib

.PHONY: all verify test patches bps bench clean FORCE

all: $(ROM) $(NET_ROM) $(SLOW_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net $(BUILD)/slow:
	mkdir -p $@

$(CONVERTED): tools/convert.py $(BASEROM) $(DISASM_MAIN) | $(BUILD)
	@test -f "$(DISASM)/MAIN.asm" || { echo "no disassembly: git submodule update --init third_party/NES-Jackal_Disassembly_Fully_Commented"; exit 1; }
	rm -rf $(GEN)
	$(PYTHON) tools/convert.py "$(DISASM)" $(BASEROM) $(GEN)
	touch $@

# The converted sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(CONVERTED) $(PATCHED:%=patches/%.patch)
	rm -rf $(SRC)
	cp -R $(GEN) $(SRC)
	for name in $(PATCHED); do test ! -s patches/$$name.patch || patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the ROM"; exit 1

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# A session's line, in CPU cycles a bit, once the nesp32 has agreed to it
# (PEER's RATE): its exchanges at that rate, and everything else at the
# link's own, 21.
NET_RATE ?= 14

# The library's serial routines: the receiver that gives up by counting,
# since every exchange is made in an NMI, and both routines on the one page
# net/jackal_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP) Makefile
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack \
		--short-period=$(NET_RATE) $(LINK_OPTIONS)

# Each ROM is assembled from the same sources: the original as it is, and
# the netplay one with NETPLAY defined, which brings in net/. The graphics
# are .incbin'd from the ROM the build was given.
BIN_DIR := $(dir $(abspath $(BASEROM)))

$(BUILD)/orig/jackal.o: $(SOURCES) | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BIN_DIR) -I $(SRC) -o $@ $(SRC)/jackal.asm

$(BUILD)/net/jackal.o: $(SOURCES) $(NET_SOURCES) | $(BUILD)/net
	ca65 -D NETPLAY -D NET_FAST --debug-info --bin-include-dir $(BIN_DIR) -I $(SRC) $(NET_INCLUDES) -o $@ $(SRC)/jackal.asm

$(BUILD)/slow/jackal.o: $(SOURCES) $(NET_SOURCES) | $(BUILD)/slow
	ca65 -D NETPLAY -D NET_SLOW --debug-info --bin-include-dir $(BIN_DIR) -I $(SRC) $(NET_INCLUDES) -o $@ $(SRC)/jackal.asm

$(ROM): $(BUILD)/orig/jackal.o jackal.cfg
	ld65 -C jackal.cfg --dbgfile $(BUILD)/jackal.dbg -o $@ $<

$(NET_ROM): $(BUILD)/net/jackal.o net/jackal_net.cfg
	ld65 -C net/jackal_net.cfg --dbgfile $(BUILD)/jackal_net.dbg \
		-m $(BUILD)/jackal_net.map -o $@ $<

$(SLOW_ROM): $(BUILD)/slow/jackal.o net/jackal_net.cfg
	ld65 -C net/jackal_net.cfg --dbgfile $(BUILD)/jackal_net_slow.dbg -o $@ $<

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

bench: $(ROM) $(NET_ROM)
	$(PYTHON) tools/bench.py $(ROM) $(BUILD)/jackal.dbg
	$(PYTHON) tools/bench.py $(NET_ROM) $(BUILD)/jackal_net.dbg

# From the original as built, once it is known to be the game: the patch
# is for the US release and no other.
bps: verify $(NET_ROM)
	mkdir -p $(DIST)
	$(PYTHON) $(GEN_PATCH) $(ROM) $(NET_ROM) $(DIST)/jackal_net.bps

# What a source in build/src has that the converted one has not.
PATCH_OF = diff -U0 --label a/src/$(1).asm --label b/src/$(1).asm \
	$(GEN)/$(1).asm $(SRC)/$(1).asm

patches: $(UPSTREAM)
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(GEN) ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch || { \
				echo "$(SRC)/$$name.asm has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

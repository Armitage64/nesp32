# Tecmo Super Bowl build.
#
#   make            build/tsb.nes, the original, and build/tsb_net.nes, for
#                   two consoles and two nesp32s; and build/tsb_net_slow.nes,
#                   the same with the game's own routines where the netplay
#                   ROM has quicker ones, which it is held to and measured
#                   against; and build/tsb_net_debug.nes, the netplay ROM
#                   with NET_DEBUG: what a session's console last did, kept
#                   in the save RAM and shown on NETWORK GAME, for one that
#                   stops (README, "The menu")
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make bench      how the frames go, the original against a session, in a
#                   game for two (tools/bench.py)
#   make import     tools/game.map again, from the disassembly (needs asm6f)
#   make patches    write patches/ again from the sources in build/src
#   make clean
#
# The game is not here. Its disassembly, third_party/Tecmo_Super_Bowl_NES_
# Disassembly, is asm6f source, which ca65 cannot take as it is: so
# tools/import.py read it once, through asm6f's listing, into tools/game.map
# (addresses, names and comments, none of the game's bytes), and
# tools/convert.py makes ca65 source of baserom.nes with it, in build/gen.
# baserom.nes is the ROM, which whoever builds has to put here. The source
# is copied to build/src, and patches/ puts the netplay's lines into the
# copy, all under .ifdef NETPLAY, so tsb.nes stays the original, byte for
# byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# Tecmo Super Bowl (USA), with its iNES header.
SHA512_ORIGINAL := c3fb1a2ca0d3bfbc04fe33f75cd330e1e3d4b316b48ea63dcf37a009304c800128bd24bd3b8d26170ea01130f253e9241314b12009c6cae21021f5fcb8cc6cd8
BASEROM ?= baserom.nes
DISASSEMBLY ?= ../../third_party/Tecmo_Super_Bowl_NES_Disassembly
ASM6F ?= asm6f
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
ROM := $(BUILD)/tsb.nes
NET_ROM := $(BUILD)/tsb_net.nes
SLOW_ROM := $(BUILD)/tsb_net_slow.nes
DEBUG_ROM := $(BUILD)/tsb_net_debug.nes
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := header tsb
NAMES := header tsb chr
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)
NET_OBJECTS := $(NAMES:%=$(BUILD)/net/%.o)
SLOW_OBJECTS := $(NAMES:%=$(BUILD)/slow/%.o)
DEBUG_OBJECTS := $(NAMES:%=$(BUILD)/debug/%.o)
NET_SOURCES := $(wildcard net/*.inc net/*.asm) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib

.PHONY: all verify test bench import patches clean FORCE

all: $(ROM) $(NET_ROM) $(SLOW_ROM) $(DEBUG_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net $(BUILD)/slow $(BUILD)/debug:
	mkdir -p $@

$(CONVERTED): tools/convert.py tools/game.map $(BASEROM) | $(BUILD)
	rm -rf $(GEN) $(BUILD)/convert
	$(PYTHON) tools/convert.py $(BASEROM) $(BUILD)/convert
	mv $(BUILD)/convert/src $(GEN)
	mv $(BUILD)/convert/chr.bin $(BUILD)/chr.bin
	rmdir $(BUILD)/convert
	printf '.segment "CHR"\n    .incbin "chr.bin"\n' > $(GEN)/chr.asm
	touch $@

# The converted sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(CONVERTED) $(wildcard $(PATCHED:%=patches/%.patch))
	rm -rf $(SRC)
	cp -R $(GEN) $(SRC)
	for name in $(PATCHED); do test -s patches/$$name.patch || continue; patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
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
# link's own, 21. The game plays samples, whose fetches are what made 10
# too fast for Jackal (nesp32's docs/MULTIPLAYER.md): 14, as Jackal's.
NET_RATE ?= 14

# The library's serial routines: the receiver that gives up by counting,
# since no interrupt breaks into an exchange (net/net.inc), and both
# routines on the one page net/superbowl_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP) Makefile
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack \
		--short-period=$(NET_RATE) $(LINK_OPTIONS)

# Each ROM is assembled from the same sources: the original as it is, and
# the netplay one with NETPLAY defined, which brings in net/.
$(BUILD)/orig/%.o: $(SRC)/%.asm | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -I $(SRC) -o $@ $<

$(BUILD)/net/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/net
	ca65 -D NETPLAY --debug-info --bin-include-dir $(BUILD) -I $(SRC) $(NET_INCLUDES) -o $@ $<

$(BUILD)/slow/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/slow
	ca65 -D NETPLAY -D NET_SLOW --debug-info --bin-include-dir $(BUILD) -I $(SRC) $(NET_INCLUDES) -o $@ $<

$(BUILD)/debug/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/debug
	ca65 -D NETPLAY -D NET_DEBUG --debug-info --bin-include-dir $(BUILD) -I $(SRC) $(NET_INCLUDES) -o $@ $<

$(ROM): $(OBJECTS) superbowl.cfg
	ld65 -C superbowl.cfg --dbgfile $(BUILD)/tsb.dbg -o $@ $(OBJECTS)

$(NET_ROM): $(NET_OBJECTS) net/superbowl_net.cfg
	ld65 -C net/superbowl_net.cfg --dbgfile $(BUILD)/tsb_net.dbg \
		-m $(BUILD)/tsb_net.map -o $@ $(NET_OBJECTS)

$(SLOW_ROM): $(SLOW_OBJECTS) net/superbowl_net.cfg
	ld65 -C net/superbowl_net.cfg --dbgfile $(BUILD)/tsb_net_slow.dbg -o $@ $(SLOW_OBJECTS)

$(DEBUG_ROM): $(DEBUG_OBJECTS) net/superbowl_net.cfg
	ld65 -C net/superbowl_net.cfg --dbgfile $(BUILD)/tsb_net_debug.dbg -o $@ $(DEBUG_OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

# On every core if this Python has pytest-xdist (conftest.py at the top of
# nesp32 starts the longest first).
XDIST = $(shell $(PYTHON) -c 'import xdist' 2>/dev/null \
	&& printf '%s' '-n auto --dist load --maxschedchunk 1')

test:
	$(PYTHON) -m pytest $(XDIST) -q tests

# Each seed's original and session side by side, on every core.
bench: $(ROM) $(NET_ROM) $(NESP)
	$(PYTHON) tools/bench.py $(ROM) $(BUILD)/tsb.dbg $(NET_ROM) $(BUILD)/tsb_net.dbg $(BENCH_OPTIONS)

# The map again, from the disassembly: only when it changes, or the import.
import: $(BASEROM)
	$(PYTHON) tools/import.py $(ASM6F) $(DISASSEMBLY) $(BASEROM) tools/game.map

# What a source in build/src has that the converted one has not.
PATCH_OF = diff -U0 --label a/src/$(1).asm --label b/src/$(1).asm \
	$(GEN)/$(1).asm $(SRC)/$(1).asm

patches: $(UPSTREAM)
	mkdir -p patches
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(GEN) ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch 2>/dev/null || \
			{ test ! -f patches/$$name.patch && $(call PATCH_OF,$$name) >/dev/null; } || { \
				echo "$(SRC)/$$name.asm has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

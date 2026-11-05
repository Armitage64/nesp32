# Bubble Bobble build.
#
#   make            build/bubblebobble.nes, the original, and
#                   build/bubblebobble_net.nes, for two consoles and two
#                   nesp32s; and build/bubblebobble_net_slow.nes, the same
#                   with the game's own routines where the netplay has
#                   faster ways, for the tests to hold the two alike
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make trace      tools/entries.txt again, from the game run on the
#                   simulated console (tools/trace.py)
#   make patches    write patches/ again from the sources in build/src
#   make bps        dist/bubblebobble_net.bps again, the netplay ROM as a
#                   patch to the game, which players apply to their own
#   make clean
#
# The game is not here. There is no disassembly of it to start from, so
# tools/convert.py makes one: ca65 source in build/gen, every byte of it
# from baserom.nes, which whoever builds has to put here, with the names
# and comments of tools/game.map. The CHR ROM is cut out of baserom.nes
# too. The source is copied to build/src, and patches/ puts the netplay's
# few lines into the copy. Everything they add is under .ifdef NETPLAY, so
# bubblebobble.nes stays the original, byte for byte, and `make verify`
# says so.

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
ROM := $(BUILD)/bubblebobble.nes
NET_ROM := $(BUILD)/bubblebobble_net.nes
SLOW_ROM := $(BUILD)/bubblebobble_net_slow.nes
# The netplay ROM as a patch to the US release, for players who build
# nothing: kept in the repository, as it holds none of the game
# (tools/gen_patch.py refuses one that would).
DIST := dist
GEN_PATCH := $(NESP32)/tools/gen_patch.py
# Bubble Bobble (USA), with its iNES header.
SHA512_ORIGINAL := 4c72314ac5234e0b6090d7c095871b335fbe5a16bb92011ccc4f68f6041fdbb6fc839cb1e887d75c840e9e00c184e5956f5b71e366b06d7a47272d716d951027
BASEROM ?= baserom.nes
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := header bubblebobble
NAMES := header bubblebobble chr
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)
NET_OBJECTS := $(NAMES:%=$(BUILD)/net/%.o)
SLOW_OBJECTS := $(NAMES:%=$(BUILD)/slow/%.o)
NET_SOURCES := $(wildcard net/*.inc net/*.asm) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib

.PHONY: all verify test trace patches bps clean FORCE

all: $(ROM) $(NET_ROM) $(SLOW_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net $(BUILD)/slow:
	mkdir -p $@

$(CONVERTED): tools/convert.py tools/game.map tools/entries.txt $(BASEROM) | $(BUILD)
	rm -rf $(GEN)
	$(PYTHON) tools/convert.py $(BASEROM) $(BUILD)/convert
	mv $(BUILD)/convert/src $(GEN)
	mv $(BUILD)/convert/chr.bin $(BUILD)/chr.bin
	rmdir $(BUILD)/convert
	printf '.segment "CHR"\n    .incbin "chr.bin"\n' > $(GEN)/chr.asm
	touch $@

# The converted sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(CONVERTED) $(PATCHED:%=patches/%.patch)
	rm -rf $(SRC)
	cp -R $(GEN) $(SRC)
	for name in $(PATCHED); do patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the ROM"; exit 1

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines: the receiver that gives up by counting,
# since every exchange is made in an NMI, and both routines on the one page
# net/bubblebobble_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack $(LINK_OPTIONS)

# Each ROM is assembled from the same sources: the original as it is, and
# the netplay one with NETPLAY defined, which brings in net/.
$(BUILD)/orig/%.o: $(SRC)/%.asm | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -o $@ $<

$(BUILD)/net/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/net
	ca65 -D NETPLAY --debug-info --bin-include-dir $(BUILD) $(NET_INCLUDES) -o $@ $<

$(BUILD)/slow/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/slow
	ca65 -D NETPLAY -D NET_SLOW --debug-info --bin-include-dir $(BUILD) $(NET_INCLUDES) -o $@ $<

$(ROM): $(OBJECTS) bubblebobble.cfg
	ld65 -C bubblebobble.cfg --dbgfile $(BUILD)/bubblebobble.dbg -o $@ $(OBJECTS)

$(NET_ROM): $(NET_OBJECTS) net/bubblebobble_net.cfg
	ld65 -C net/bubblebobble_net.cfg --dbgfile $(BUILD)/bubblebobble_net.dbg \
		-m $(BUILD)/bubblebobble_net.map -o $@ $(NET_OBJECTS)

$(SLOW_ROM): $(SLOW_OBJECTS) net/bubblebobble_net.cfg
	ld65 -C net/bubblebobble_net.cfg --dbgfile $(BUILD)/bubblebobble_net_slow.dbg -o $@ $(SLOW_OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

# From the original as built, once it is known to be the game: the patch
# is for the US release and no other.
bps: verify $(NET_ROM)
	mkdir -p $(DIST)
	$(PYTHON) $(GEN_PATCH) $(ROM) $(NET_ROM) $(DIST)/bubblebobble_net.bps

trace: $(BASEROM)
	$(PYTHON) tools/trace.py $(BASEROM) tools/entries.txt

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

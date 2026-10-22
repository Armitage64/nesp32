# TMNT II build.
#
#   make            build/tmnt2.nes, the original, and
#                   build/tmnt2_net.nes, for two consoles and two nesp32s;
#                   and build/tmnt2_net_slow.nes, the same with the game's
#                   own sprite pass, for the tests to hold the faster to
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the sources in build/src
#   make clean
#
# The game is not here. Its disassembly is Aaron Bottegal's
# TMNT2-NES-Reverse-Engineered, a submodule at the top of this repository,
# which is a listing to read rather than a source to build.
# tools/convert.py makes ca65 source of it in build/gen, taking every byte
# from baserom.nes, which whoever builds has to put here, and the listing's
# names and comments where the ROM agrees with them. The CHR ROM is cut out
# of baserom.nes too. The source is copied to build/src, and patches/ puts
# netplay's few lines into the copy. Everything they add is under .ifdef
# NETPLAY, so tmnt2.nes stays the original, byte for byte, and `make
# verify` says so.

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
ROM := $(BUILD)/tmnt2.nes
NET_ROM := $(BUILD)/tmnt2_net.nes
SLOW_ROM := $(BUILD)/tmnt2_net_slow.nes
# Teenage Mutant Ninja Turtles II - The Arcade Game (USA), with its iNES
# header.
SHA512_ORIGINAL := f01d2492409536845999a95a763d9a3a9c03342b5b4c23162aa87ec85eecd5679cabe335367c4c044e79b8f0dac658887e0dd09ff524b967441419518c06010e
# The disassembly, and the commit of it that the conversion, and so
# patches/, was made for: a patch has line numbers and none of the
# source's lines to go by.
TMNT2_SRC ?= $(NESP32)/third_party/TMNT2-NES-Reverse-Engineered
TMNT2_COMMIT ?= 35b7a15017eedd602e7485c12f11bb228b00923f
BASEROM ?= baserom.nes
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := tmnt2 header
NAMES := header tmnt2 chr
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)
NET_OBJECTS := $(NAMES:%=$(BUILD)/net/%.o)
SLOW_OBJECTS := $(NAMES:%=$(BUILD)/slow/%.o)
NET_SOURCES := $(wildcard net/*.inc net/*.asm) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib

.PHONY: all verify test patches clean FORCE

all: $(ROM) $(NET_ROM) $(SLOW_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net $(BUILD)/slow:
	mkdir -p $@

$(CONVERTED): tools/convert.py $(BASEROM) | $(BUILD)
	@test -f $(TMNT2_SRC)/TMNT2.bank31.asm || { \
		echo "no disassembly at $(TMNT2_SRC): git submodule update --init"; exit 1; }
	@test -z "$(TMNT2_COMMIT)" \
		|| test "$$(git -C $(TMNT2_SRC) rev-parse HEAD)" = "$(TMNT2_COMMIT)" || { \
		echo "$(TMNT2_SRC) is not at $(TMNT2_COMMIT), which the conversion is for"; exit 1; }
	rm -rf $(GEN)
	$(PYTHON) tools/convert.py $(TMNT2_SRC) $(BASEROM) $(BUILD)/convert
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
# net/tmnt2_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack $(LINK_OPTIONS)

# Each ROM is assembled from the same sources: the original as it is, and
# the netplay one with NETPLAY defined, which brings in net/.
$(BUILD)/orig/%.o: $(SRC)/%.asm | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -o $@ $<

$(BUILD)/net/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/net
	ca65 -D NETPLAY --debug-info --bin-include-dir $(BUILD) $(NET_INCLUDES) -o $@ $<

$(BUILD)/slow/%.o: $(SRC)/%.asm $(NET_SOURCES) | $(BUILD)/slow
	ca65 -D NETPLAY -D NET_SLOW_SPRITES --debug-info --bin-include-dir $(BUILD) \
		$(NET_INCLUDES) -o $@ $<

$(ROM): $(OBJECTS) tmnt2.cfg
	ld65 -C tmnt2.cfg --dbgfile $(BUILD)/tmnt2.dbg -o $@ $(OBJECTS)

$(NET_ROM): $(NET_OBJECTS) net/tmnt2_net.cfg
	ld65 -C net/tmnt2_net.cfg --dbgfile $(BUILD)/tmnt2_net.dbg -m $(BUILD)/tmnt2_net.map \
		-o $@ $(NET_OBJECTS)

$(SLOW_ROM): $(SLOW_OBJECTS) net/tmnt2_net.cfg
	ld65 -C net/tmnt2_net.cfg --dbgfile $(BUILD)/tmnt2_net_slow.dbg -o $@ $(SLOW_OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

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

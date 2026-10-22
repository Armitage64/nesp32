# Contra build.
#
#   make            build/contra.nes, the original, and
#                   build/contra_net.nes, for two consoles and two nesp32s
#   make ines       build/contra_net_ines.nes: the netplay ROM with the
#                   original's iNES header in place of its NES 2.0 one, for
#                   a cartridge or an emulator that will not take that
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the sources in build/src
#   make clean
#
# The game is not here. Its disassembly is vermiceli's nes-contra-us, a
# submodule at the top of this repository, and its graphics and sound are
# cut out of baserom.nes, which whoever builds has to put here. The
# disassembly is copied to build/src, and patches/ puts netplay's few lines
# into the copy. Everything they add is under .ifdef NETPLAY, so contra.nes
# stays the original, byte for byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The netplay ROM's link is nesp32's, at the top of this repository
# (two directories up). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The original ROM needs
# none of it.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/contra.nes
NET_ROM := $(BUILD)/contra_net.nes
SHA512_ORIGINAL := 1c747c78c678f14a68d4e5fcae065298a103f833638775860f0e5c5ffaa061f62d45fd8942148b1507c1fd57fde950a5d83f9f84a9782ec048a56067740c48e9
# The disassembly, and the commit of it that patches/ was made against: a
# patch has line numbers and none of the disassembly's lines to go by.
CONTRA_SRC ?= $(NESP32)/third_party/nes-contra-us
CONTRA_COMMIT ?= 687d651c021fd7020f10d05b970ccb62663c94bd
BASEROM ?= baserom.nes
SRC := $(BUILD)/src
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := bank1 bank5 bank6 bank7 ines_header
NAMES := ram constants ines_header bank0 bank1 bank2 bank3 bank4 bank5 bank6 bank7
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)
NET_OBJECTS := $(NAMES:%=$(BUILD)/net/%.o)
NET_SOURCES := $(wildcard net/*.inc) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib
ASSETS := $(BUILD)/assets.stamp

.PHONY: all ines verify test patches clean FORCE

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net:
	mkdir -p $@

# The disassembly's sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(PATCHED:%=patches/%.patch) | $(BUILD)
	@test -f $(CONTRA_SRC)/src/bank7.asm || { \
		echo "no disassembly at $(CONTRA_SRC): git submodule update --init"; exit 1; }
	@test -z "$(CONTRA_COMMIT)" \
		|| test "$$(git -C $(CONTRA_SRC) rev-parse HEAD)" = "$(CONTRA_COMMIT)" || { \
		echo "$(CONTRA_SRC) is not at $(CONTRA_COMMIT), which patches/ is for"; exit 1; }
	mkdir -p $(SRC)
	cp $(CONTRA_SRC)/src/*.asm $(SRC)
	for name in $(PATCHED); do patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

$(ASSETS): $(BASEROM) $(UPSTREAM) tools/extract_assets.py
	$(PYTHON) tools/extract_assets.py $(BASEROM) $(CONTRA_SRC)/assets.txt $(BUILD)
	touch $@

$(BASEROM):
	@echo "no $(BASEROM): the game's graphics and sound are cut out of the ROM"; exit 1

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines: the receiver that gives up by counting,
# since every exchange is made in an NMI, and both routines on the one page
# net/contra_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack $(LINK_OPTIONS)

# Each ROM is assembled from the same sources: the original as it is, and
# the netplay one with NETPLAY defined.
$(BUILD)/orig/%.o: $(SRC)/%.asm $(ASSETS) | $(BUILD)/orig
	ca65 -D Contra --debug-info -o $@ $<

$(BUILD)/net/%.o: $(SRC)/%.asm $(ASSETS) $(NET_SOURCES) | $(BUILD)/net
	ca65 -D Contra -D NETPLAY --debug-info $(NET_INCLUDES) -o $@ $<

$(ROM): $(OBJECTS)
	ld65 -C $(CONTRA_SRC)/contra.cfg --dbgfile $(BUILD)/contra.dbg -o $@ $(OBJECTS)

$(NET_ROM): $(NET_OBJECTS) net/contra_net.cfg
	ld65 -C net/contra_net.cfg --dbgfile $(BUILD)/contra_net.dbg -m $(BUILD)/contra_net.map \
		-o $@ $(NET_OBJECTS)

ines: $(BUILD)/contra_net_ines.nes

$(BUILD)/contra_net_ines.nes: $(NET_ROM) $(ROM)
	{ head -c 16 $(ROM); tail -c +17 $(NET_ROM); } > $@

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

# What a source in build/src has that the disassembly's has not.
PATCH_OF = diff -U0 --label a/src/$(1).asm --label b/src/$(1).asm \
	$(CONTRA_SRC)/src/$(1).asm $(SRC)/$(1).asm

patches: $(UPSTREAM)
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(CONTRA_SRC)/src ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch || { \
				echo "$(SRC)/$$name.asm has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

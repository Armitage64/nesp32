# Contra build.
#
#   make            build/contra.nes, the original, and
#                   build/contra_net.nes, for two consoles and two nesp32s
#   make ines       build/contra_net_ines.nes: the netplay ROM with the
#                   original's iNES header in place of its NES 2.0 one, for
#                   a cartridge or an emulator that will not take that
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make clean
#
# build.sh still builds the original as it always has. Everything netplay
# changes is under .ifdef NETPLAY, so contra.nes stays the original, byte
# for byte, and `make verify` says so. baserom.nes has to be here: the
# graphics and the sound are cut out of it.

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
NAMES := ram constants ines_header bank0 bank1 bank2 bank3 bank4 bank5 bank6 bank7
SOURCES := $(NAMES:%=src/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)
NET_OBJECTS := $(NAMES:%=$(BUILD)/net/%.o)
NET_SOURCES := $(wildcard net/*.inc) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib
ASSETS := $(BUILD)/assets.stamp

.PHONY: all ines verify test clean FORCE

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/net:
	mkdir -p $@

$(ASSETS): baserom.nes assets.txt tools/extract_assets.py | $(BUILD)
	$(PYTHON) tools/extract_assets.py baserom.nes assets.txt
	touch $@

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
$(BUILD)/orig/%.o: src/%.asm $(ASSETS) | $(BUILD)/orig
	ca65 -D Contra --debug-info -o $@ $<

$(BUILD)/net/%.o: src/%.asm $(ASSETS) $(NET_SOURCES) | $(BUILD)/net
	ca65 -D Contra -D NETPLAY --debug-info $(NET_INCLUDES) -o $@ $<

$(ROM): $(OBJECTS) contra.cfg
	ld65 -C contra.cfg --dbgfile $(BUILD)/contra.dbg -o $@ $(OBJECTS)

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

clean:
	rm -rf $(BUILD)

FORCE:

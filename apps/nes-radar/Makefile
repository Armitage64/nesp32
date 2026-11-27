# NES Radar build.
#
#   make            build/nes_radar_link.nes, for a nesp32
#   make cart CART_CHR=n    build/nes_radar_cart.nes, the ROM as a part of
#                   nesp32's cartridge, with its tiles at the mapper's n.
#                   nesp32's own `make cart` asks for it
#   make verify     the ROM's size and header, and the ROMs built with
#                   nes-radar's copy of nesp32's link library the same as
#                   those built with nesp32's own
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make clean
#
# The program is not here. It is k6lcm's nes-radar, a submodule at the top
# of this repository, which from 0.5.0 is for a nesp32 and nothing else. It
# is assembled from there as it is, into build/.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# nesp32, at the top of this repository (two directories up). Its link and
# services are built for this computer, for the tests to run the ROM
# against, and its link library is what nes-radar's copy is checked against.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
LINK_ROM := $(BUILD)/nes_radar_link.nes
CART_ROM := $(BUILD)/nes_radar_cart.nes
ROM_SIZE := 65552   # 16-byte header + 32 KB PRG + 32 KB CHR
RADAR ?= $(NESP32)/third_party/nes-radar
RADAR_SRC := $(abspath $(RADAR))/nes_radar
VENDOR := $(RADAR_SRC)/vendor/nesp32
NAME := nes_radar_scope_v3
SOURCE := $(RADAR_SRC)/nes/$(NAME).s
SOURCES := $(SOURCE) $(RADAR_SRC)/nes/radar_link.inc $(wildcard $(VENDOR)/*.inc)
# nes-radar's own tool draws the targets' sprites. The source has their
# tiles as build/radar_sprites_16.chr, its own build/, so they are drawn
# into a build/ of our own, which ca65 is told to look for binaries in.
SPRITES := $(BUILD)/radar
METASPRITES := $(SPRITES)/build/metasprites.stamp
INCLUDES := -I $(abspath $(SPRITES))/build -I assets/ldv -I nes -I $(VENDOR) \
	-I $(abspath $(BUILD)) --bin-include-dir $(abspath $(SPRITES))

.PHONY: all cart verify test clean FORCE

all: $(LINK_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

$(METASPRITES): | $(BUILD)
	@test -f $(SOURCE) || { \
		echo "no nes-radar at $(RADAR): git submodule update --init"; exit 1; }
	mkdir -p $(dir $@)
	$(PYTHON) -B $(RADAR_SRC)/tools/generate_metasprites.py --output-dir $(dir $@)
	touch $@

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The source names its assets from its own directory, so it is assembled
# from there.
$(BUILD)/nes_radar_link.o: $(SOURCES) $(METASPRITES)
	cd $(RADAR_SRC) && ca65 -g $(INCLUDES) -o $(abspath $@) nes/$(NAME).s

$(LINK_ROM): $(BUILD)/nes_radar_link.o $(RADAR_SRC)/nes/cnrom256.cfg
	ld65 -C $(RADAR_SRC)/nes/cnrom256.cfg -o $@ -Ln $(BUILD)/nes_radar_link.labels \
		-m $(BUILD)/nes_radar_link.map --dbgfile $(BUILD)/nes_radar_link.dbg $<

# The cartridge's part: the ROM with CART defined, which asks the
# cartridge's MMC1 for its tiles where a CN-ROM's latch would be written,
# and has each page of them once. Where they are on the cartridge is
# nesp32's to say, and is written down so that another answer builds it
# again.
$(BUILD)/cart.inc: FORCE | $(BUILD)
	@test -n "$(CART_CHR)" || { echo "CART_CHR=: where on the cartridge the tiles are"; exit 1; }
	@echo "CART_CHR = $(CART_CHR)" | cmp -s - $@ || echo "CART_CHR = $(CART_CHR)" > $@

$(BUILD)/nes_radar_cart.o: $(SOURCES) $(METASPRITES) $(BUILD)/cart.inc
	cd $(RADAR_SRC) && ca65 -g -D CART $(INCLUDES) -o $(abspath $@) nes/$(NAME).s

$(CART_ROM): $(BUILD)/nes_radar_cart.o nes/mmc1_cart.cfg
	ld65 -C nes/mmc1_cart.cfg -o $@ -Ln $(BUILD)/nes_radar_cart.labels \
		-m $(BUILD)/nes_radar_cart.map --dbgfile $(BUILD)/nes_radar_cart.dbg $<

cart: $(CART_ROM)

# nes-radar builds with a copy of nesp32's link library: the same as
# nesp32's, or tools/update_nesp32.sh in nes-radar has to be run again.
# nes-radar's copy of the link library need not be nesp32's byte for byte:
# nesp32 adds constants and code behind an .ifdef that nes-radar never
# uses. What matters is the ROM. So both ROMs, the standalone one and the
# cartridge's, are built again with nesp32's library as it now is, in
# place of the copy, and must come out the same. Each is built in a
# directory of its own, so that build/'s cartridge ROM is left as nesp32
# asked for it. Where the tiles are on the cartridge does not matter here:
# both builds are told the same.
LIB := $(BUILD)/nesp32-lib
THEIRS := $(BUILD)/with-copy
OURS := $(BUILD)/with-nesp32
VERIFY_CHR := 0

verify: $(LINK_ROM) $(NESP)
	@test "$$(wc -c < $(LINK_ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" \
		&& printf 'NES\032\002\004\060\000' | cmp -n 8 - $(LINK_ROM)
	@mkdir -p $(LIB)
	@cp $(NESP32)/nes/lib/nesp.inc $(NESP_BUILD)/nesp_proto.inc $(LIB)/
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $(LIB)/link.inc --timeout
	@$(MAKE) -s BUILD=$(THEIRS) CART_CHR=$(VERIFY_CHR) \
		$(THEIRS)/nes_radar_link.nes $(THEIRS)/nes_radar_cart.nes
	@$(MAKE) -s BUILD=$(OURS) VENDOR=$(abspath $(LIB)) CART_CHR=$(VERIFY_CHR) \
		$(OURS)/nes_radar_link.nes $(OURS)/nes_radar_cart.nes
	@for rom in nes_radar_link.nes nes_radar_cart.nes; do \
		cmp -s $(THEIRS)/$$rom $(OURS)/$$rom || { \
			echo "$$rom is not the same with nesp32's link library as with" \
				"nes-radar's copy: run nes-radar's tools/update_nesp32.sh" \
				"$(abspath $(NESP32))"; exit 1; }; \
	done
	@for file in nesp.inc nesp_proto.inc link.inc; do \
		cmp -s $(LIB)/$$file $(VENDOR)/$$file || changed="$$changed $$file"; \
	done; \
	if [ -n "$$changed" ]; then \
		echo "nes-radar's ROMs are the same with nesp32's link library," \
			"though its copy differs in:$$changed"; \
	else echo "nes-radar's copy of the link library is nesp32's"; fi

# On every core if this Python has pytest-xdist (conftest.py at the top of
# nesp32 starts the longest first).
XDIST = $(shell $(PYTHON) -c 'import xdist' 2>/dev/null \
	&& printf '%s' '-n auto --dist load --maxschedchunk 1')

test:
	$(PYTHON) -m pytest $(XDIST) -q tests

clean:
	rm -rf $(BUILD)

FORCE:

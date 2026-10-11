# NES Radar build.
#
#   make            build/nes_radar.nes, the original, and
#                   build/nes_radar_link.nes, for a nesp32
#   make verify     check the original against its SHA-256 and with
#                   nes-radar's own verifiers, and the link ROM's size
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the source in build/src
#   make clean
#
# The program is not here. It is k6lcm's nes-radar, a submodule at the top
# of this repository. Its ROM's source, assets and tools are copied to
# build/src, and patches/ puts the nesp32's link into the copy. Everything
# the patch adds is under .ifdef NESP32, so nes_radar.nes stays the
# original, byte for byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The link ROM's link is nesp32's, at the top of this repository (two
# directories up). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The original ROM needs
# none of it.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/nes_radar.nes
LINK_ROM := $(BUILD)/nes_radar_link.nes
ROM_SIZE := 65552   # 16-byte header + 32 KB PRG + 32 KB CHR
SHA256_ORIGINAL := 0c08c2bd7ad6f50474b8e56f1814d12570b9b2e7d2789050dcc0d2c8179ba47a
# nes-radar, and the commit of it that patches/ was made against: a patch
# has line numbers and none of nes-radar's lines to go by.
RADAR ?= $(NESP32)/third_party/nes-radar
RADAR_COMMIT ?= ba14bd5ce1db1b0b298caa54584db8edd140f7f7
RADAR_SRC := $(RADAR)/nes_radar
# The copy is laid out as nes-radar's own directory is, and assembled from
# inside it: the source names its assets from there.
SRC := $(BUILD)/src
HERE := $(CURDIR)
UPSTREAM := $(BUILD)/upstream.stamp
NAME := nes_radar_scope_v3
PATCHED := $(NAME)
SOURCE := $(SRC)/nes/$(NAME).s
METASPRITES := $(SRC)/build/metasprites.stamp
LINK_SOURCES := nes/radar_link.inc $(BUILD)/link.inc $(NESP_LIB) $(NESP)
LINK_INCLUDES := -I $(HERE)/nes -I $(abspath $(BUILD)) -I $(NESP_BUILD) \
	-I $(abspath $(NESP32))/nes/lib

.PHONY: all verify test patches clean FORCE

all: $(ROM) $(LINK_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

# nes-radar's ROM directory, copied and patched. A patch that has changed
# makes it again.
$(UPSTREAM): $(PATCHED:%=patches/%.patch) | $(BUILD)
	@test -f $(RADAR_SRC)/nes/$(NAME).s || { \
		echo "no nes-radar at $(RADAR): git submodule update --init"; exit 1; }
	@test -z "$(RADAR_COMMIT)" \
		|| test "$$(git -C $(RADAR) rev-parse HEAD)" = "$(RADAR_COMMIT)" || { \
		echo "$(RADAR) is not at $(RADAR_COMMIT), which patches/ is for"; exit 1; }
	rm -rf $(SRC)
	mkdir -p $(SRC)/build
	cp -R $(RADAR_SRC)/nes $(RADAR_SRC)/assets $(RADAR_SRC)/tools $(SRC)
	for name in $(PATCHED); do patch -s -p1 -d $(SRC) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCE): $(UPSTREAM) ;

# The targets' sprites, drawn by nes-radar's own tool.
$(METASPRITES): $(UPSTREAM)
	$(PYTHON) -B $(SRC)/tools/generate_metasprites.py --output-dir $(SRC)/build
	touch $@

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines, with the receiver that gives up by
# counting: the ROM keeps its NMI off but for a vblank's writes, so there is
# no handler to end a wait.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout

# Each ROM is assembled from the same source: the original as it is, and
# the link ROM with NESP32 defined.
$(BUILD)/nes_radar.o: $(SOURCE) $(METASPRITES)
	cd $(SRC) && ca65 -g -I build -I assets/ldv -o $(abspath $@) nes/$(NAME).s

$(BUILD)/nes_radar_link.o: $(SOURCE) $(METASPRITES) $(LINK_SOURCES)
	cd $(SRC) && ca65 -g -D NESP32 -I build -I assets/ldv $(LINK_INCLUDES) \
		-o $(abspath $@) nes/$(NAME).s

$(ROM): $(BUILD)/nes_radar.o
	ld65 -C $(SRC)/nes/cnrom256.cfg -o $@ -m $(BUILD)/nes_radar.map \
		--dbgfile $(BUILD)/nes_radar.dbg $<

$(LINK_ROM): $(BUILD)/nes_radar_link.o nes/cnrom256_link.cfg
	ld65 -C nes/cnrom256_link.cfg -o $@ -Ln $(BUILD)/nes_radar_link.labels \
		-m $(BUILD)/nes_radar_link.map --dbgfile $(BUILD)/nes_radar_link.dbg $<

# The original is checked as nes-radar checks its own: its two verifiers
# time the sender it has and the link ROM has not, and read its requests
# against the server's code for them.
verify: $(ROM) $(LINK_ROM)
	@test "$$(shasum -a 256 $(ROM) | cut -d' ' -f1)" = "$(SHA256_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }
	$(PYTHON) -B $(RADAR_SRC)/tools/verify_tx_timing.py $(ROM) $(BUILD)/nes_radar.dbg
	$(PYTHON) -B $(RADAR_SRC)/tools/verify_frame_bytes.py $(ROM) $(BUILD)/nes_radar.dbg
	for rom in $(ROM) $(LINK_ROM); do \
		test "$$(wc -c < $$rom | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\004\060\000' | cmp -n 8 - $$rom || exit 1; \
	done

test:
	$(PYTHON) -m pytest -q tests

# What the source in build/src has that nes-radar's has not.
PATCH_OF = diff -U0 --label a/nes/$(1).s --label b/nes/$(1).s \
	$(RADAR_SRC)/nes/$(1).s $(SRC)/nes/$(1).s

patches: $(UPSTREAM)
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(RADAR_SRC)/nes ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch || { \
				echo "$(SRC)/nes/$$name.s has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

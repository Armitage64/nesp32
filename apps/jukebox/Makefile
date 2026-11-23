# NES Jukebox build.
#
#   make                                  demo song
#   make SONG="music/01 Running About.vgz"
#   make test
#
# SONG may contain spaces, so it is only ever used quoted inside recipes and
# the embed step always runs; it rewrites its outputs only when they change.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The link ROM's host is a nesp32, whose firmware is at the top of this
# repository (two directories up). From it come the link's library for the console and the numbers
# the two ends share; its link and services are built for this computer,
# for the tests to run the ROM against.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
DEMO := $(BUILD)/demo.jbs
SONG ?= $(DEMO)
ROM := $(BUILD)/jukebox.nes
LINK_ROM := $(BUILD)/jukebox_link.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR
LINK_ROM_SIZE := 24592   # 16-byte header + 16 KB PRG + 8 KB CHR

.PHONY: all verify famicom-link-rom test clean FORCE

all: $(ROM) $(LINK_ROM)

$(BUILD):
	mkdir -p $@

$(DEMO): tools/demo_song.py tools/jbs.py tools/apu_model.py | $(BUILD)
	$(PYTHON) tools/demo_song.py -o $@

$(BUILD)/song.bin: FORCE $(if $(filter $(DEMO),$(SONG)),$(DEMO)) | $(BUILD)
	$(PYTHON) tools/embed_song.py "$(SONG)" $(BUILD)

$(BUILD)/song.inc: $(BUILD)/song.bin

# The screen: tiles, nametables and tables for nes/ui.inc.
# gen_ui.py rewrites only the files whose contents changed, so the ROMs
# depend on each of them, not on one that stands for all.
UI := $(BUILD)/ui_data.inc $(BUILD)/chr.bin $(BUILD)/screen.bin $(BUILD)/screen_standalone.bin

$(BUILD)/ui.stamp: tools/gen_ui.py $(NESP32)/nes/lib/logo.py | $(BUILD)
	$(PYTHON) tools/gen_ui.py $(BUILD)
	touch $@

$(UI): $(BUILD)/ui.stamp ;

$(BUILD)/jukebox.o: nes/jukebox.s nes/ui.inc nes/fake_link.inc $(UI) $(BUILD)/song.bin $(BUILD)/song.inc
	ca65 -g -I $(BUILD) -I nes --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/jukebox.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/jukebox.labels \
		--dbgfile $(BUILD)/jukebox.dbg -m $(BUILD)/jukebox.map $<

# The serial link build: the same player, its music from a nesp32 on
# controller port 2, over nesp32's link. nesp32's own Makefile knows what of
# it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
# LINK_OPTIONS: nesp32's Famicom cartridge passes --joy2-bit=1 (docs/WIRING.md,
# the Famicom); empty for the ordinary build.
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ $(LINK_OPTIONS)

# The routines that play sampled sound, one per rate.
$(BUILD)/pcm_rates.inc: tools/gen_pcm.py tools/pcm.py | $(BUILD)
# LINK_OPTIONS: nesp32's Famicom cartridge passes --joy2-bit=1; empty for
# the ordinary build.
	$(PYTHON) tools/gen_pcm.py $@ $(LINK_OPTIONS)

# The same link ROM for a Famicom: the Stick's wire is on its expansion
# port's joypad 2 /D1, so its link and its sound read bit 1 of $4017
# (--joy2-bit=1), and its rates from PCM_LIMIT on have no routines, where
# the fold's 6-cycle sample bought them on a NES. Nothing ships it: the
# tests play sound with it. The wiring: docs/WIRING.md, the Famicom.
FAMICOM_LINK_ROM := $(BUILD)/jukebox_famicom_link.nes
FAMICOM_LINK_OPTIONS := --joy2-bit=1

$(BUILD)/famicom:
	mkdir -p $@

$(BUILD)/famicom/link.inc: $(NESP_LIB) $(NESP) | $(BUILD)/famicom
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ $(FAMICOM_LINK_OPTIONS)

$(BUILD)/famicom/pcm_rates.inc: tools/gen_pcm.py tools/pcm.py $(NESP) | $(BUILD)/famicom
	$(PYTHON) tools/gen_pcm.py $@ $(FAMICOM_LINK_OPTIONS)

$(BUILD)/jukebox_famicom_link.o: nes/jukebox.s nes/ui.inc nes/serial_link.inc $(UI) $(NESP_LIB) \
		$(BUILD)/famicom/link.inc $(BUILD)/famicom/pcm_rates.inc $(BUILD)/pcm_rates.inc $(NESP)
	ca65 -g -D LINK -I $(BUILD)/famicom -I $(BUILD) -I $(NESP_BUILD) -I nes -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -o $@ $<

$(FAMICOM_LINK_ROM): $(BUILD)/jukebox_famicom_link.o nes/nrom128_link.cfg
	ld65 -C nes/nrom128_link.cfg -o $@ -Ln $(BUILD)/jukebox_famicom_link.labels \
		--dbgfile $(BUILD)/jukebox_famicom_link.dbg -m $(BUILD)/jukebox_famicom_link.map $<

famicom-link-rom: $(FAMICOM_LINK_ROM)

$(BUILD)/jukebox_link.o: nes/jukebox.s nes/ui.inc nes/serial_link.inc $(UI) $(NESP_LIB) \
		$(BUILD)/link.inc $(BUILD)/pcm_rates.inc $(NESP)
	ca65 -g -D LINK -I $(BUILD) -I $(NESP_BUILD) -I nes -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -o $@ $<

$(LINK_ROM): $(BUILD)/jukebox_link.o nes/nrom128_link.cfg
	ld65 -C nes/nrom128_link.cfg -o $@ -Ln $(BUILD)/jukebox_link.labels \
		--dbgfile $(BUILD)/jukebox_link.dbg -m $(BUILD)/jukebox_link.map $<

verify: $(ROM) $(LINK_ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\001\000\000' | cmp -n 8 - $(ROM)
	test "$$(wc -c < $(LINK_ROM) | tr -d ' ')" = "$(strip $(LINK_ROM_SIZE))" && \
		printf 'NES\032\001\001\000\000' | cmp -n 8 - $(LINK_ROM)

# On every core if this Python has pytest-xdist (conftest.py at the top of
# nesp32 starts the longest first).
XDIST = $(shell $(PYTHON) -c 'import xdist' 2>/dev/null \
	&& printf '%s' '-n auto --dist load --maxschedchunk 1')

test:
	$(PYTHON) -m pytest $(XDIST)

clean:
	rm -rf $(BUILD)

FORCE:

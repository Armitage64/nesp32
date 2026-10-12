# NPR build.
#
#   make          build/npr.nes
#   make test     the ROM against nesp32's firmware, on a simulated console
#
# The ROM's host is a nesp32, whose firmware is at the top of this
# repository (two directories up; the jukebox's Makefile has the same
# arrangement). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The font, the header and
# the palette, and the routines that play sampled sound, come from the
# jukebox's tools in ../jukebox/tools.

BUILD ?= build
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
# Its Python, when it has one: the tools and the tests are run from there.
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
JUKEBOX ?= ../jukebox
NESP := $(NESP_BUILD)/nesp.stamp
ROM := $(BUILD)/npr.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all verify test clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

# The routines that play sampled sound, one per rate; this ROM uses the
# fastest.
$(BUILD)/pcm_rates.inc: $(JUKEBOX)/tools/gen_pcm.py $(JUKEBOX)/tools/pcm.py | $(BUILD)
	$(PYTHON) $(JUKEBOX)/tools/gen_pcm.py $@

# gen_screen.py rewrites only the files whose contents changed.
SCREEN := $(BUILD)/chr.bin $(BUILD)/screen.bin $(BUILD)/palette.bin $(BUILD)/screen.inc

$(BUILD)/screen.stamp: tools/gen_screen.py $(JUKEBOX)/tools/gen_ui.py | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/npr.o: nes/npr.s $(NESP_LIB) $(BUILD)/link.inc $(BUILD)/pcm_rates.inc $(SCREEN) $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib --bin-include-dir $(BUILD) \
		-o $@ $<

$(ROM): $(BUILD)/npr.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/npr.labels \
		--dbgfile $(BUILD)/npr.dbg -m $(BUILD)/npr.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\001\000\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

FORCE:

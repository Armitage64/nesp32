# Weather build.
#
#   make            build/weather.nes
#   make verify     check its size and header
#   make test       the ROM against nesp32's firmware, on a simulated console
#   make preview    docs/screen.png and docs/screen-form.png
#
# The ROM's host is a nesp32, whose firmware is at the top of this
# repository (two directories up; NPR's Makefile has the same arrangement).
# From it come the link's library for the console and the numbers the two
# ends share. The font, the header and the picture's writer come from the
# jukebox's tools in ../jukebox/tools.

BUILD ?= build
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
# Its Python, when it has one: the tools and the tests are run from there.
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
JUKEBOX ?= ../jukebox
NESP := $(NESP_BUILD)/nesp.stamp
ROM := $(BUILD)/weather.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all verify test preview clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto
	@test -f $@ || touch $@

NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

# gen_screen.py rewrites only the files whose contents changed.
SCREEN := $(BUILD)/chr.bin $(BUILD)/screen.bin $(BUILD)/palette.bin $(BUILD)/screen.inc

$(BUILD)/screen.stamp: tools/gen_screen.py $(JUKEBOX)/tools/gen_ui.py | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/weather.o: nes/weather.s $(NESP_LIB) $(BUILD)/link.inc $(SCREEN) $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib --bin-include-dir $(BUILD) \
		-o $@ $<

$(ROM): $(BUILD)/weather.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/weather.labels \
		--dbgfile $(BUILD)/weather.dbg -m $(BUILD)/weather.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\001\000\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest

preview: | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD) --preview docs/screen.png

clean:
	rm -rf $(BUILD)

FORCE:

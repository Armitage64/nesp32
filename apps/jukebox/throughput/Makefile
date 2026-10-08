# Throughput test build.
#
#   make          build/linktest.nes
#   make -B TX_FIRST=8    the same, with the climb from the console begun at
#                 that rate of its ladder (nes/linktest.s)
#   make test     the ROM against nesp32's firmware, on a simulated console
#
# The ROM's host is a nesp32, whose firmware is at the top of this
# repository (../Makefile has the same arrangement). From it come the link's
# library for the console and the numbers the two ends share; its link and
# services are built for this computer, for the tests to run the ROM
# against. The font, the header and the palette come from the jukebox's
# tools in ../tools.

PYTHON ?= $(if $(wildcard ../.venv/bin/python),../.venv/bin/python,python3)
BUILD ?= build
NESP32 ?= ../../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
ROM := $(BUILD)/linktest.nes
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

$(BUILD)/rates.inc: tools/gen_rates.py tools/rates.py $(NESP)
	$(PYTHON) tools/gen_rates.py $(NESP_BUILD) $@

# gen_screen.py rewrites only the files whose contents changed.
SCREEN := $(BUILD)/chr.bin $(BUILD)/screen.bin $(BUILD)/palette.bin $(BUILD)/screen.inc

$(BUILD)/screen.stamp: tools/gen_screen.py ../tools/gen_ui.py | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/linktest.o: nes/linktest.s $(NESP_LIB) $(BUILD)/link.inc $(BUILD)/rates.inc $(SCREEN) $(NESP)
	ca65 -g $(if $(TX_FIRST),-D TX_FIRST=$(TX_FIRST)) -I $(BUILD) -I $(NESP_BUILD) \
		-I $(NESP32)/nes/lib --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/linktest.o nes/linktest.cfg
	ld65 -C nes/linktest.cfg -o $@ -Ln $(BUILD)/linktest.labels \
		--dbgfile $(BUILD)/linktest.dbg -m $(BUILD)/linktest.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))"
	printf 'NES\032\002\001\000\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest tests

clean:
	rm -rf $(BUILD)

FORCE:

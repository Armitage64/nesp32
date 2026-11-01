# The HTTPS sample's build.
#
#   make            build/https.nes
#   make test       the ROM against a nesp32's firmware, on a simulated
#                   console, with the test as the web site (needs pytest
#                   and py65)
#   make clean
#
# Its host is a nesp32, whose firmware is at the top of this repository
# (two directories up). From there come the link's library for the console
# (nes/lib/nesp.inc), the serial routines written for the link's rate
# (nes/lib/gen_link.py), and the numbers both ends share (proto/nesp.toml,
# made into nesp_proto.inc). The font comes from the jukebox's tools.
#
# Needs cc65 (ca65 and ld65) and Python 3.

BUILD ?= build
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/https.nes

.PHONY: all test clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# nesp_proto.inc, from nesp32's own Makefile, which knows when it is out
# of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto
	@test -f $@ || touch $@

# The serial routines, with the receiver that the NMI ends: every exchange
# is made from the main loop.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

$(BUILD)/chr.bin: tools/gen_chr.py $(NESP32)/apps/jukebox/tools/gen_ui.py | $(BUILD)
	$(PYTHON) tools/gen_chr.py $(BUILD)

$(BUILD)/https.o: nes/https.s $(NESP_LIB) $(BUILD)/link.inc $(BUILD)/chr.bin $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -l $(BUILD)/https.lst -o $@ nes/https.s

$(ROM): $(BUILD)/https.o nes/nrom.cfg
	ld65 -C nes/nrom.cfg -o $@ -Ln $(BUILD)/https.labels \
		--dbgfile $(BUILD)/https.dbg -m $(BUILD)/https.map $<

test:
	$(PYTHON) -m pytest -q tests

clean:
	rm -rf $(BUILD)

FORCE:

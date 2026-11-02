# The lobby sample's build.
#
#   make            build/lobby.nes
#   make test       two consoles on the ROM, each with a nesp32's firmware,
#                   on a simulated network (needs pytest and py65)
#   make preview    docs/screen.png, the session screen
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
ROM := $(BUILD)/lobby.nes
SOURCES := nes/lobby.s nes/menu.inc nes/session.inc nes/pads.inc

.PHONY: all test preview clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# nesp_proto.inc, from nesp32's own Makefile, which knows when it is out
# of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto
	@test -f $@ || touch $@

# The serial routines, with the receiver that gives up by counting: every
# exchange is made inside the NMI.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout

# The tiles, the session screen and where the sprites go. gen_chr.py
# rewrites only the files whose contents changed.
CHR := $(BUILD)/chr.bin $(BUILD)/session.bin $(BUILD)/layout.inc

$(BUILD)/chr.stamp: tools/gen_chr.py $(NESP32)/apps/jukebox/tools/gen_ui.py | $(BUILD)
	$(PYTHON) tools/gen_chr.py $(BUILD)
	touch $@

$(CHR): $(BUILD)/chr.stamp ;

$(BUILD)/lobby.o: $(SOURCES) $(NESP_LIB) $(BUILD)/link.inc $(CHR) $(NESP)
	ca65 -g -I nes -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -l $(BUILD)/lobby.lst -o $@ nes/lobby.s

$(ROM): $(BUILD)/lobby.o nes/nrom.cfg
	ld65 -C nes/nrom.cfg -o $@ -Ln $(BUILD)/lobby.labels \
		--dbgfile $(BUILD)/lobby.dbg -m $(BUILD)/lobby.map $<

test:
	$(PYTHON) -m pytest -q tests

preview: | $(BUILD)
	mkdir -p docs
	$(PYTHON) tools/gen_chr.py $(BUILD) --preview docs/screen.png

clean:
	rm -rf $(BUILD)

FORCE:

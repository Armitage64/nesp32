# Bluesky build.
#
#   make            build/bluesky.nes (NROM-128: 16 KB of PRG, 8 KB of CHR)
#   make verify     check its size and header
#   make test       the ROM against nesp32's firmware, on a simulated console
#   make preview    docs/screen.png, and -list, -form and -splash beside it
#
# The ROM's host is a nesp32, whose firmware is at the top of this
# repository (two directories up). From it come the link's library for the
# console and the numbers the two ends share. Every screen is ConnectedNES's,
# from connectednes/; the sprite's two tiles are NESpedia's font's, from its
# tools in ../wiki/tools, which load nesp32's code built for this computer,
# as NESpedia's own build does.

BUILD ?= build
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
# Its Python, when it has one: the tools and the tests are run from there.
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
WIKI ?= ../wiki
NESP := $(NESP_BUILD)/nesp.stamp
ROM := $(BUILD)/bluesky.nes
ROM_SIZE := 24592   # 16-byte header + 16 KB PRG + 8 KB CHR

.PHONY: all verify test preview clean FORCE

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

# gen_screen.py rewrites only the files whose contents changed.
SCREEN := $(BUILD)/chr.bin $(BUILD)/splash.bin $(BUILD)/her.bin $(BUILD)/palette.bin \
	$(BUILD)/screen.inc
CONNECTEDNES := $(wildcard connectednes/*.nam connectednes/*.chr connectednes/*.pal \
	connectednes/*.atr)

$(BUILD)/screen.stamp: tools/gen_screen.py $(WIKI)/tools/gen_screen.py $(CONNECTEDNES) \
		$(NESP) | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/bluesky.o: nes/bluesky.s $(NESP_LIB) $(BUILD)/link.inc $(SCREEN) $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib --bin-include-dir $(BUILD) \
		-o $@ $<

$(ROM): $(BUILD)/bluesky.o nes/nrom128.cfg
	ld65 -C nes/nrom128.cfg -o $@ -Ln $(BUILD)/bluesky.labels \
		--dbgfile $(BUILD)/bluesky.dbg -m $(BUILD)/bluesky.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\001\001\001\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest

preview: $(NESP) | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD) --preview docs/screen.png

clean:
	rm -rf $(BUILD)

FORCE:

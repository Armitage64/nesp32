# The setup ROM's build.
#
#   make            build/setup.nes
#   make verify     check its size and header
#   make test       its tests, which are among nesp32's own
#   make preview    docs/*.png: its screens, from the ROM itself, and the
#                   cartridge's menu if nesp32 has built the cartridge
#   make clean
#
# The top of this repository builds it too (`make rom` there), into its own
# build directory, for its tests and for the cartridge.

BUILD ?= build
# The link is nesp32's, at the top of this repository (two directories up).
# From it come the link's library for the console and the numbers the two
# ends share.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
# Its Python, when it has one: the tests and the pictures are run from there.
PYTHON ?= $(firstword $(wildcard $(abspath .venv/bin/python $(NESP32)/.venv/bin/python)) python3)
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/setup.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR
SOURCES := $(wildcard nes/*.s nes/*.inc) $(NESP32)/nes/lib/nesp.inc
INCLUDES := -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib -I nes

.PHONY: all timeout-rom verify test preview clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto
	@test -f $@ || touch $@

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

# The screen: tiles, the header and the layout's numbers. gen_screen.py
# rewrites only the files whose contents changed, so the ROM depends on
# each of them, and on a stamp for the three.
SCREEN := $(BUILD)/chr.bin $(BUILD)/header.bin $(BUILD)/screen.inc

$(BUILD)/screen.stamp: tools/gen_screen.py $(NESP32)/nes/lib/logo.py $(NESP) | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/setup.o: $(SOURCES) $(SCREEN) $(BUILD)/link.inc
	ca65 -g $(INCLUDES) --bin-include-dir $(BUILD) -o $@ nes/setup.s

$(ROM): $(BUILD)/setup.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/setup.labels \
		--dbgfile $(BUILD)/setup.dbg -m $(BUILD)/setup.map $<

# The same ROM on the library's other receiver, the one for exchanges made
# inside an NMI, which gives up by counting, and with its CRC from a table.
# Nothing ships it: the tests time that receiver in it, and run the ROM on
# it.
TIMEOUT_ROM := $(BUILD)/setup_timeout.nes

$(BUILD)/timeout/link.inc: $(NESP_LIB) $(NESP)
	mkdir -p $(BUILD)/timeout
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout

$(BUILD)/setup_timeout.o: $(SOURCES) $(SCREEN) $(BUILD)/timeout/link.inc
	ca65 -g -D TIMEOUT_BUILD -I $(BUILD)/timeout $(INCLUDES) \
		--bin-include-dir $(BUILD) -o $@ nes/setup.s

$(TIMEOUT_ROM): $(BUILD)/setup_timeout.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/setup_timeout.labels $<

timeout-rom: $(TIMEOUT_ROM)

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))"
	printf 'NES\032\002\001\001\000' | cmp -n 8 - $(ROM)

# The tests work the ROM on nesp32's simulated console, with the tests of
# the link it is the first user of.
test:
	cd $(NESP32) && $(PYTHON) -m pytest -q tests/test_setup.py

# The pictures are taken from what the top of the repository builds.
preview:
	$(MAKE) -s -C $(NESP32)
	NESP_BUILD=$(abspath $(NESP32)/build) $(PYTHON) tools/preview.py docs $(NESP32)/docs

clean:
	rm -rf $(BUILD)

FORCE:

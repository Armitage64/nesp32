# Dr. Mario build.
#
#   make            build/drmario.nes, the original, and
#                   build/drmario_net.nes, for two consoles and two nesp32s
#   make verify     check it against the original ROM's SHA-1
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make clean
#
# Everything netplay changes is under .ifdef NETPLAY, so drmario.nes stays
# the original, byte for byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The netplay ROM's link is nesp32's, a checkout of whose firmware sits
# beside this one. From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The original ROM needs
# none of it.
NESP32 ?= ../nesp32
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/drmario.nes
NET_ROM := $(BUILD)/drmario_net.nes
NET_SOURCES := net/common.inc net/ram.inc net/net.inc net/session.inc $(BUILD)/link.inc \
	$(NESP_LIB) $(NESP)
NET_INCLUDES := -I $(BUILD) -I $(NESP_BUILD) -I . -I $(NESP32)/nes/lib
SHA1_ORIGINAL := 01de1e04c396298358e86468ba96148066688194
SOURCES := bank_FF.asm bank_ram.inc bank_val.inc
COPIES := $(addprefix $(BUILD)/copy_,$(SOURCES))

.PHONY: all verify test clean FORCE

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

$(BUILD)/prepare.stamp: $(SOURCES) tools/prepare.py | $(BUILD)
	$(PYTHON) tools/prepare.py $(BUILD) $(SOURCES)
	touch $@

$(COPIES): $(BUILD)/prepare.stamp ;

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines: the receiver that gives up by counting,
# since every exchange is made in an NMI, and both routines on one page,
# which is what the game's bank has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack

# Each ROM is assembled from the same copies: the original as it is, and
# the netplay one with NETPLAY defined.
$(BUILD)/drmario.o: $(COPIES) DPCM.bin
	ca65 -U -g -I $(BUILD) --bin-include-dir . -l $(BUILD)/drmario.lst \
		-o $@ $(BUILD)/copy_bank_FF.asm

$(BUILD)/drmario_net.o: $(COPIES) DPCM.bin $(NET_SOURCES)
	ca65 -U -g -D NETPLAY $(NET_INCLUDES) --bin-include-dir . \
		-l $(BUILD)/drmario_net.lst -o $@ $(BUILD)/copy_bank_FF.asm

$(BUILD)/drmario_net.prg: $(BUILD)/drmario_net.o net/game.cfg
	ld65 -C net/game.cfg -o $@ --dbgfile $(BUILD)/drmario_net.dbg \
		-m $(BUILD)/drmario_net.map $<

# The menu's bank, and a header that says the PRG is twice the size. It is
# an NES 2.0 header, which the MiSTer's core asks for: the same mapper, no
# submapper, and no memory on the cartridge.
$(BUILD)/menu.o: net/menu.s net/common.inc net/ram.inc $(BUILD)/link.inc $(NESP_LIB) $(NESP)
	ca65 -g $(NET_INCLUDES) -l $(BUILD)/menu.lst -o $@ net/menu.s

$(BUILD)/menu.prg: $(BUILD)/menu.o net/menu.cfg
	ld65 -C net/menu.cfg -o $@ --dbgfile $(BUILD)/menu.dbg -m $(BUILD)/menu.map $<

$(BUILD)/header_net.bin: header.bin | $(BUILD)
	{ head -c 4 $<; printf '\004'; tail -c 11 $< | head -c 2; printf '\010'; \
		tail -c 8 $<; } > $@

$(NET_ROM): $(BUILD)/header_net.bin $(BUILD)/drmario_net.prg $(BUILD)/menu.prg CHR_ROM.chr
	cat $^ > $@

$(BUILD)/%.prg: $(BUILD)/%.o ld65.cfg
	ld65 -C ld65.cfg -o $@ --dbgfile $(BUILD)/$*.dbg $<

$(BUILD)/%.nes: header.bin $(BUILD)/%.prg CHR_ROM.chr
	cat $^ > $@

verify: $(ROM)
	@test "$$(shasum -a 1 $(ROM) | cut -d' ' -f1)" = "$(SHA1_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

clean:
	rm -rf $(BUILD)

FORCE:

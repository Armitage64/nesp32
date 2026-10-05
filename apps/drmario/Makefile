# Dr. Mario build.
#
#   make            build/drmario.nes, the original, and
#                   build/drmario_net.nes, for two consoles and two Sticks
#   make verify     check it against the original ROM's SHA-1
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make clean
#
# Everything netplay changes is under .ifdef NETPLAY, so drmario.nes stays
# the original, byte for byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
ROM := $(BUILD)/drmario.nes
NET_ROM := $(BUILD)/drmario_net.nes
NET_SOURCES := net/ram.inc net/net.inc net/exchange.inc net/session.inc $(BUILD)/link.inc
SHA1_ORIGINAL := 01de1e04c396298358e86468ba96148066688194
SOURCES := bank_FF.asm bank_ram.inc bank_val.inc
COPIES := $(addprefix $(BUILD)/copy_,$(SOURCES))

.PHONY: all verify test clean

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

$(BUILD)/prepare.stamp: $(SOURCES) tools/prepare.py | $(BUILD)
	$(PYTHON) tools/prepare.py $(BUILD) $(SOURCES)
	touch $@

$(COPIES): $(BUILD)/prepare.stamp ;

$(BUILD)/link.inc: tools/gen_link.py firmware/stick/drnet/linkrate.py | $(BUILD)
	$(PYTHON) tools/gen_link.py $@

# Each ROM is assembled from the same copies: the original as it is, and
# the netplay one with NETPLAY defined.
$(BUILD)/drmario.o: $(COPIES) DPCM.bin
	ca65 -U -g -I $(BUILD) --bin-include-dir . -l $(BUILD)/drmario.lst \
		-o $@ $(BUILD)/copy_bank_FF.asm

$(BUILD)/drmario_net.o: $(COPIES) DPCM.bin $(NET_SOURCES)
	ca65 -U -g -D NETPLAY -I $(BUILD) -I . --bin-include-dir . \
		-l $(BUILD)/drmario_net.lst -o $@ $(BUILD)/copy_bank_FF.asm

# The menu's bank, and a header that says the PRG is twice the size.
$(BUILD)/menu.o: net/menu.s net/ram.inc net/exchange.inc $(BUILD)/link.inc
	ca65 -g -I $(BUILD) -I . -l $(BUILD)/menu.lst -o $@ net/menu.s

$(BUILD)/menu.prg: $(BUILD)/menu.o net/menu.cfg
	ld65 -C net/menu.cfg -o $@ --dbgfile $(BUILD)/menu.dbg $<

$(BUILD)/header_net.bin: header.bin | $(BUILD)
	{ head -c 4 $<; printf '\004'; tail -c 11 $<; } > $@

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

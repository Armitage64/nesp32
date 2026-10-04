# Throughput test build.
#
#   make          build/linktest.nes
#   make test     the ROM and the Stick's code, on a simulated console
#
# The font and the CRC table come from the jukebox's tools in ../tools.

PYTHON ?= $(if $(wildcard ../.venv/bin/python),../.venv/bin/python,python3)
BUILD ?= build
ROM := $(BUILD)/linktest.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all verify test clean

all: $(ROM)

$(BUILD):
	mkdir -p $@

$(BUILD)/rates.inc: tools/gen_rates.py stick/linktest/rates.py | $(BUILD)
	$(PYTHON) tools/gen_rates.py $@

$(BUILD)/crc16_table.inc: ../tools/gen_crc_table.py | $(BUILD)
	$(PYTHON) ../tools/gen_crc_table.py $@

# gen_screen.py rewrites only the files whose contents changed.
SCREEN := $(BUILD)/chr.bin $(BUILD)/screen.bin

$(BUILD)/screen.stamp: tools/gen_screen.py ../tools/gen_ui.py stick/linktest/tester.py | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

$(BUILD)/linktest.o: nes/linktest.s $(BUILD)/rates.inc $(BUILD)/crc16_table.inc $(SCREEN)
	ca65 -g -I $(BUILD) --bin-include-dir $(BUILD) -o $@ $<

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

# NES Jukebox build.
#
#   make                                  demo song
#   make SONG="music/01 Running About.vgz"
#   make test
#
# SONG may contain spaces, so it is only ever used quoted inside recipes and
# the embed step always runs; it rewrites its outputs only when they change.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
DEMO := $(BUILD)/demo.jbs
SONG ?= $(DEMO)
ROM := $(BUILD)/jukebox.nes
LINK_ROM := $(BUILD)/jukebox_link.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all verify test clean FORCE

all: $(ROM) $(LINK_ROM)

$(BUILD):
	mkdir -p $@

$(DEMO): tools/demo_song.py tools/jbs.py tools/apu_model.py | $(BUILD)
	$(PYTHON) tools/demo_song.py -o $@

$(BUILD)/song.bin: FORCE $(if $(filter $(DEMO),$(SONG)),$(DEMO)) | $(BUILD)
	$(PYTHON) tools/embed_song.py "$(SONG)" $(BUILD)

$(BUILD)/song.inc: $(BUILD)/song.bin

$(BUILD)/jukebox.o: nes/jukebox.s nes/fake_link.inc $(BUILD)/song.bin $(BUILD)/song.inc
	ca65 -g -I $(BUILD) -I nes --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/jukebox.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/jukebox.labels \
		--dbgfile $(BUILD)/jukebox.dbg -m $(BUILD)/jukebox.map $<

# The serial link build: same player, bursts over controller port 2.
$(BUILD)/crc16_table.inc: tools/gen_crc_table.py | $(BUILD)
	$(PYTHON) tools/gen_crc_table.py $@

$(BUILD)/jukebox_link.o: nes/jukebox.s nes/serial_link.inc $(BUILD)/crc16_table.inc
	ca65 -g -D LINK -I $(BUILD) -I nes -o $@ $<

$(LINK_ROM): $(BUILD)/jukebox_link.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/jukebox_link.labels \
		--dbgfile $(BUILD)/jukebox_link.dbg -m $(BUILD)/jukebox_link.map $<

verify: $(ROM) $(LINK_ROM)
	for rom in $(ROM) $(LINK_ROM); do \
		test "$$(wc -c < $$rom | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\001\000\000' | cmp -n 8 - $$rom || exit 1; \
	done

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

FORCE:

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
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all verify test clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

$(DEMO): tools/demo_song.py tools/jbs.py tools/apu_model.py | $(BUILD)
	$(PYTHON) tools/demo_song.py -o $@

$(BUILD)/song.bin: FORCE $(if $(filter $(DEMO),$(SONG)),$(DEMO)) | $(BUILD)
	$(PYTHON) tools/embed_song.py "$(SONG)" $(BUILD)

$(BUILD)/song.inc: $(BUILD)/song.bin

$(BUILD)/jukebox.o: nes/jukebox.s $(BUILD)/song.bin $(BUILD)/song.inc
	ca65 -g -I $(BUILD) --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/jukebox.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/jukebox.labels \
		--dbgfile $(BUILD)/jukebox.dbg -m $(BUILD)/jukebox.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))"
	printf 'NES\032\002\001\000\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

FORCE:

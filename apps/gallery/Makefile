# Gallery build.
#
#   make                         build/gallery.nes
#   make test
#   make preview                 build/search.png and build/info.png
#   make picture FILES="a.jpg"   each file as the Gallery shows it, next to it

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The nesp32's firmware is at the top of this repository (two directories
# up). From it come the link's library for the console, the numbers the two
# ends share, and the code that makes a picture, built for this computer so
# that the tools make pictures as a nesp32 does.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
ROM := $(BUILD)/gallery.nes
ROM_SIZE := 32784   # 16-byte header + 32 KB PRG, and CHR RAM
NESP := $(NESP_BUILD)/nesp.stamp
SOURCES := nes/gallery.s nes/keyboard.inc nes/serial_link.inc nes/viewer.inc

.PHONY: all verify test preview picture clean FORCE

all: $(ROM)

$(BUILD):
	mkdir -p $@

# The screen: tiles, the search screen and the layout's numbers. gen_screen.py
# rewrites only the files whose contents changed, so the ROM depends on each
# of them, not on one that stands for all.
SCREEN := $(BUILD)/chr.bin $(BUILD)/screen.bin $(BUILD)/screen.inc

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

FORCE:

$(BUILD)/screen.stamp: tools/gen_screen.py tools/stick.py $(NESP) $(NESP32)/nes/lib/logo.py | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

$(BUILD)/gallery.o: $(SOURCES) $(SCREEN) $(NESP_LIB) $(BUILD)/link.inc $(NESP)
	ca65 -g -I $(BUILD) -I $(NESP_BUILD) -I nes -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/gallery.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/gallery.labels \
		--dbgfile $(BUILD)/gallery.dbg -m $(BUILD)/gallery.map $<

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\000\001\000' | cmp -n 8 - $(ROM)

preview: $(NESP) | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD) --preview $(BUILD)/search.png --info $(BUILD)/info.png

picture: $(NESP)
	$(PYTHON) tools/picture.py $(FILES)

# On every core if this Python has pytest-xdist (conftest.py at the top of
# nesp32 starts the longest first).
XDIST = $(shell $(PYTHON) -c 'import xdist' 2>/dev/null \
	&& printf '%s' '-n auto --dist load --maxschedchunk 1')

test:
	$(PYTHON) -m pytest $(XDIST)

clean:
	rm -rf $(BUILD)

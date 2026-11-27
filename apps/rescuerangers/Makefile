# Chip 'n Dale Rescue Rangers build.
#
#   make            build/rescuerangers.nes, the original, made from the
#                   converted source
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make trace      tools/entries.txt again, from the game run on the
#                   simulated console (tools/trace.py)
#   make patches    write patches/ again from the sources in build/src
#   make clean
#
# The netplay ROM is not built yet: see README.md, "Not done".
#
# The game is not here. There is no disassembly of it to start from, so
# tools/convert.py makes one: ca65 source in build/gen, every byte of it
# from baserom.nes, which whoever builds has to put here, with the names
# and comments of tools/game.map. The CHR ROM is cut out of baserom.nes
# too. The source is copied to build/src, and patches/ (none yet) puts the
# netplay's lines into the copy. Everything they add will be under .ifdef
# NETPLAY, so rescuerangers.nes stays the original, byte for byte, and
# `make verify` says so.

PYTHON ?= $(if $(wildcard ../../.venv/bin/python),../../.venv/bin/python,python3)
BUILD ?= build
ROM := $(BUILD)/rescuerangers.nes
# Chip 'n Dale Rescue Rangers (USA), with its iNES header.
SHA512_ORIGINAL := 0ed9cddeeb1dc3231fc707465eccbce40776d554bf783acecd25faf370a3355fefe943eb1685b044774c51272f039286cbc1c4c6cedc26cf9b7b14b50d5e68ad
BASEROM ?= baserom.nes
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := $(patsubst patches/%.patch,%,$(wildcard patches/*.patch))
NAMES := header rescuerangers chr
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)

.PHONY: all verify test trace patches clean

all: $(ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig:
	mkdir -p $@

$(CONVERTED): tools/convert.py tools/game.map tools/entries.txt $(BASEROM) | $(BUILD)
	rm -rf $(GEN) $(BUILD)/convert
	$(PYTHON) tools/convert.py $(BASEROM) $(BUILD)/convert
	mv $(BUILD)/convert/src $(GEN)
	mv $(BUILD)/convert/chr.bin $(BUILD)/chr.bin
	rmdir $(BUILD)/convert
	printf '.segment "CHR"\n    .incbin "chr.bin"\n' > $(GEN)/chr.asm
	touch $@

# The converted sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(CONVERTED) $(PATCHED:%=patches/%.patch)
	rm -rf $(SRC)
	cp -R $(GEN) $(SRC)
	for name in $(PATCHED); do patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the ROM"; exit 1

$(BUILD)/orig/%.o: $(SRC)/%.asm | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(OBJECTS) rescuerangers.cfg
	ld65 -C rescuerangers.cfg --dbgfile $(BUILD)/rescuerangers.dbg -o $@ $(OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

# On every core if this Python has pytest-xdist (conftest.py at the top of
# nesp32 starts the longest first).
XDIST = $(shell $(PYTHON) -c 'import xdist' 2>/dev/null \
	&& printf '%s' '-n auto --dist load --maxschedchunk 1')

test:
	$(PYTHON) -m pytest $(XDIST) -q tests

trace: $(BASEROM)
	$(PYTHON) tools/trace.py $(BASEROM) tools/entries.txt

# What a source in build/src has that the converted one has not.
PATCH_OF = diff -U0 --label a/src/$(1).asm --label b/src/$(1).asm \
	$(GEN)/$(1).asm $(SRC)/$(1).asm

patches: $(UPSTREAM)
	mkdir -p patches
	$(foreach name,header rescuerangers,$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(GEN) ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch || { \
				echo "$(SRC)/$$name.asm has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

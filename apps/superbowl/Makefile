# Tecmo Super Bowl build.
#
#   make            build/tsb.nes, the original
#   make verify     check the original against the ROM's SHA-512
#   make import     tools/game.map again, from the disassembly (needs asm6f)
#   make patches    write patches/ again from the sources in build/src
#   make clean
#
# The game is not here. Its disassembly, third_party/Tecmo_Super_Bowl_NES_
# Disassembly, is asm6f source, which ca65 cannot take as it is: so
# tools/import.py read it once, through asm6f's listing, into tools/game.map
# (addresses, names and comments, none of the game's bytes), and
# tools/convert.py makes ca65 source of baserom.nes with it, in build/gen.
# baserom.nes is the ROM, which whoever builds has to put here. The source
# is copied to build/src, and patches/ puts the netplay's lines into the
# copy, all under .ifdef NETPLAY, so tsb.nes stays the original, byte for
# byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# Tecmo Super Bowl (USA), with its iNES header.
SHA512_ORIGINAL := c3fb1a2ca0d3bfbc04fe33f75cd330e1e3d4b316b48ea63dcf37a009304c800128bd24bd3b8d26170ea01130f253e9241314b12009c6cae21021f5fcb8cc6cd8
BASEROM ?= baserom.nes
DISASSEMBLY ?= ../../third_party/Tecmo_Super_Bowl_NES_Disassembly
ASM6F ?= asm6f
ROM := $(BUILD)/tsb.nes
GEN := $(BUILD)/gen
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := tsb
NAMES := header tsb chr
SOURCES := $(NAMES:%=$(SRC)/%.asm)
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)

.PHONY: all verify import patches clean

all: $(ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig:
	mkdir -p $@

$(CONVERTED): tools/convert.py tools/game.map $(BASEROM) | $(BUILD)
	rm -rf $(GEN) $(BUILD)/convert
	$(PYTHON) tools/convert.py $(BASEROM) $(BUILD)/convert
	mv $(BUILD)/convert/src $(GEN)
	mv $(BUILD)/convert/chr.bin $(BUILD)/chr.bin
	rmdir $(BUILD)/convert
	printf '.segment "CHR"\n    .incbin "chr.bin"\n' > $(GEN)/chr.asm
	touch $@

# The converted sources, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(CONVERTED) $(wildcard $(PATCHED:%=patches/%.patch))
	rm -rf $(SRC)
	cp -R $(GEN) $(SRC)
	for name in $(PATCHED); do test -s patches/$$name.patch || continue; patch -s -p1 -d $(BUILD) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the ROM"; exit 1

$(BUILD)/orig/%.o: $(SRC)/%.asm | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -I $(SRC) -o $@ $<

$(ROM): $(OBJECTS) superbowl.cfg
	ld65 -C superbowl.cfg --dbgfile $(BUILD)/tsb.dbg -o $@ $(OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

# The map again, from the disassembly: only when it changes, or the import.
import: $(BASEROM)
	$(PYTHON) tools/import.py $(ASM6F) $(DISASSEMBLY) $(BASEROM) tools/game.map

# What a source in build/src has that the converted one has not.
PATCH_OF = diff -U0 --label a/src/$(1).asm --label b/src/$(1).asm \
	$(GEN)/$(1).asm $(SRC)/$(1).asm

patches: $(UPSTREAM)
	mkdir -p patches
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(name).patch; test $$? -le 1;)

# Not while build/src has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(GEN) ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$$name.patch 2>/dev/null || \
			{ test ! -f patches/$$name.patch && $(call PATCH_OF,$$name) >/dev/null; } || { \
				echo "$(SRC)/$$name.asm has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

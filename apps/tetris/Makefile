# Tetris build.
#
#   make            build/tetris.nes, the original, and
#                   build/tetris_net.nes, for two consoles and two nesp32s
#   make verify     check it against the original ROM's SHA-1
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the sources in build/upstream
#   make clean
#
# The game is not here. Its disassembly, with its graphics, is
# CelestialAmber's TetrisNESDisasm, a submodule at the top of this
# repository. What the build needs of it is copied to build/upstream, and
# patches/ puts the two-player game and netplay's lines into the copy.
# Everything they add is under .ifdef NETPLAY, so tetris.nes stays the
# original, byte for byte, and `make verify` says so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The netplay ROM's link is nesp32's, at the top of this repository
# (two directories up). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against. The original ROM needs
# none of it.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
ROM := $(BUILD)/tetris.nes
NET_ROM := $(BUILD)/tetris_net.nes
NET_SOURCES := net/common.inc net/ram.inc net/net.inc net/twoplayer.inc net/twoplayer_game.nam
MENU_SOURCES := net/menu.s net/session.inc net/common.inc net/ram.inc $(BUILD)/link.inc \
	$(NESP_LIB) $(NESP)
NET_INCLUDES := -I $(BUILD) -I $(NESP_BUILD) -I . -I $(NESP32)/nes/lib
SHA1_ORIGINAL := 77747840541bfc62a28a5957692a98c550bd6b2b
# The disassembly, and the commit of it that patches/ was made against: a
# patch has line numbers and none of the disassembly's lines to go by.
TETRIS_SRC ?= $(NESP32)/third_party/TetrisNESDisasm
TETRIS_COMMIT ?= 94581c0306fa0009fe11fde48222875549d15b8b
UP := $(BUILD)/upstream
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := main.asm
SOURCE_NAMES := tetris.asm main.asm tetris-ram.asm constants.asm charmap.asm tetris.nes.cfg
SOURCES := $(addprefix $(UP)/,$(SOURCE_NAMES))
TILESETS := title_menu_tileset typeB_ending_tileset typeA_ending_tileset game_tileset
CHRS := $(TILESETS:%=$(UP)/gfx/%.chr)
# The four tilesets, in the order tetris.asm has them.
CHR := $(BUILD)/tetris.chr

.PHONY: all verify test patches clean FORCE

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

# The disassembly's files, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(PATCHED:%.asm=patches/%.patch) | $(BUILD)
	@test -f $(TETRIS_SRC)/main.asm || { \
		echo "no disassembly at $(TETRIS_SRC): git submodule update --init"; exit 1; }
	@test -z "$(TETRIS_COMMIT)" \
		|| test "$$(git -C $(TETRIS_SRC) rev-parse HEAD)" = "$(TETRIS_COMMIT)" || { \
		echo "$(TETRIS_SRC) is not at $(TETRIS_COMMIT), which patches/ is for"; exit 1; }
	mkdir -p $(UP)
	cp $(addprefix $(TETRIS_SRC)/,$(SOURCE_NAMES)) $(UP)
	cp -R $(TETRIS_SRC)/data $(TETRIS_SRC)/gfx $(TETRIS_SRC)/audio $(UP)
	for name in $(basename $(PATCHED)); do patch -s -p1 -d $(UP) < patches/$$name.patch || exit 1; done
	touch $@

$(SOURCES): $(UPSTREAM) ;

# The disassembly's own encoder needs Pillow; this one does not.
$(UP)/gfx/%.chr: $(UPSTREAM) tools/png2chr.py
	$(PYTHON) tools/png2chr.py $(UP)/gfx/$*.png $@

$(CHR): $(CHRS)
	cat $^ > $@

# The original, as the disassembly's own Makefile makes it.
$(BUILD)/tetris.o: $(SOURCES) $(CHRS)
	ca65 -g -I $(UP) --bin-include-dir $(UP) -o $@ $(UP)/tetris.asm

$(BUILD)/tetris-ram.o: $(UP)/tetris-ram.asm
	ca65 -g -o $@ $<

$(ROM): $(BUILD)/tetris.o $(BUILD)/tetris-ram.o $(UP)/tetris.nes.cfg
	ld65 -C $(UP)/tetris.nes.cfg --dbgfile $(BUILD)/tetris.dbg -m $(BUILD)/tetris.map \
		-o $@ $(BUILD)/tetris.o $(BUILD)/tetris-ram.o

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines, with the receiver that gives up by
# counting, since every exchange is made in an NMI.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack

# The game's bank of the netplay ROM: the same sources with NETPLAY
# defined. Its header and CHR are left out by net/game.cfg.
$(BUILD)/tetris_net.o: $(SOURCES) $(CHRS) $(NET_SOURCES)
	ca65 -g -D NETPLAY $(NET_INCLUDES) -I $(UP) --bin-include-dir $(UP) --bin-include-dir . \
		-l $(BUILD)/tetris_net.lst -o $@ $(UP)/tetris.asm

$(BUILD)/tetris_net.prg: $(BUILD)/tetris_net.o $(BUILD)/tetris-ram.o net/game.cfg
	ld65 -C net/game.cfg --dbgfile $(BUILD)/tetris_net.dbg -m $(BUILD)/tetris_net.map \
		-o $@ $(BUILD)/tetris_net.o $(BUILD)/tetris-ram.o

# The menu's bank, which has a session's frames and the link's library too.
$(BUILD)/menu.o: $(MENU_SOURCES)
	ca65 -g $(NET_INCLUDES) -l $(BUILD)/menu.lst -o $@ net/menu.s

$(BUILD)/menu.prg: $(BUILD)/menu.o net/menu.cfg
	ld65 -C net/menu.cfg -o $@ --dbgfile $(BUILD)/menu.dbg -m $(BUILD)/menu.map $<

# The two-player game's tiles, which the original's game tileset has not.
$(BUILD)/tetris_net.chr: $(CHR) tools/chr_tiles.py net/twoplayer.chr
	$(PYTHON) tools/chr_tiles.py $(CHR) net/twoplayer.chr $@

# An NES 2.0 header, which the MiSTer's core asks for: MMC1 as the
# original, with 64 KB of PRG where it has 32, and no memory on the cartridge.
$(BUILD)/header_net.bin: | $(BUILD)
	printf 'NES\032\004\002\020\010\000\000\000\000\000\000\000\000' > $@

$(NET_ROM): $(BUILD)/header_net.bin $(BUILD)/tetris_net.prg $(BUILD)/menu.prg $(BUILD)/tetris_net.chr
	cat $^ > $@

verify: $(ROM)
	@test "$$(shasum -a 1 $(ROM) | cut -d' ' -f1)" = "$(SHA1_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

# What a source in build/upstream has that the disassembly's has not.
PATCH_OF = diff -U0 --label a/$(1) --label b/$(1) $(TETRIS_SRC)/$(1) $(UP)/$(1)

patches: $(UPSTREAM)
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(basename $(name)).patch; test $$? -le 1;)

# Not while build/upstream has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d $(TETRIS_SRC) ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$${name%.*}.patch || { \
				echo "$(UP)/$$name has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

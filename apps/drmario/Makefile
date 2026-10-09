# Dr. Mario build.
#
#   make            build/drmario.nes, the original, and
#                   build/drmario_net.nes, for two consoles and two nesp32s
#   make verify     check it against the original ROM's SHA-1
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make patches    write patches/ again from the sources in build/upstream
#   make clean
#
# The game is not here. Its disassembly, with its graphics, is in
# cyneprepou4uk's NES-Games-Disassembly, a submodule at the top of this
# repository. What the build needs of it is copied to build/upstream, and
# patches/ puts netplay's few lines into the copy. Everything they add is
# under .ifdef NETPLAY, so drmario.nes stays the original, byte for byte,
# and `make verify` says so.

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
ROM := $(BUILD)/drmario.nes
NET_ROM := $(BUILD)/drmario_net.nes
NET_SOURCES := net/common.inc net/ram.inc net/net.inc
MENU_SOURCES := net/menu.s net/session.inc net/common.inc net/ram.inc $(BUILD)/link.inc \
	$(NESP_LIB) $(NESP)
NET_INCLUDES := -I $(BUILD) -I $(NESP_BUILD) -I . -I $(NESP32)/nes/lib
SHA1_ORIGINAL := 01de1e04c396298358e86468ba96148066688194
# The disassembly, and the commit of it that patches/ was made against: a
# patch has line numbers and none of the disassembly's lines to go by. Its
# directory has a space in its name, so make is told of the copies only.
DRMARIO_SRC ?= $(NESP32)/third_party/NES-Games-Disassembly/Dr. Mario
DRMARIO_COMMIT ?= df2c8e55e7f13e5792482527db9e7c9e4a84c6e1
UP := $(BUILD)/upstream
UPSTREAM := $(BUILD)/upstream.stamp
PATCHED := bank_FF.asm bank_val.inc
SOURCE_NAMES := bank_FF.asm bank_ram.inc bank_val.inc
SOURCES := $(addprefix $(UP)/,$(SOURCE_NAMES))
COPIES := $(addprefix $(BUILD)/copy_,$(SOURCE_NAMES))
FROM_UPSTREAM := $(SOURCES) $(UP)/DPCM.bin $(UP)/CHR_ROM.chr $(UP)/header.bin $(UP)/ld65.cfg

.PHONY: all verify test patches clean FORCE

all: $(ROM) $(NET_ROM)

.SECONDARY:

$(BUILD):
	mkdir -p $@

# The disassembly's files, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(patsubst %,patches/%.patch,$(basename $(PATCHED))) | $(BUILD)
	@test -f "$(DRMARIO_SRC)/bank_FF.asm" || { \
		echo "no disassembly at $(DRMARIO_SRC): git submodule update --init"; exit 1; }
	@test -z "$(DRMARIO_COMMIT)" \
		|| test "$$(git -C "$(DRMARIO_SRC)" rev-parse HEAD)" = "$(DRMARIO_COMMIT)" || { \
		echo "$(DRMARIO_SRC) is not at $(DRMARIO_COMMIT), which patches/ is for"; exit 1; }
	mkdir -p $(UP)
	for name in $(notdir $(FROM_UPSTREAM)); do cp "$(DRMARIO_SRC)/$$name" $(UP) || exit 1; done
	for name in $(basename $(PATCHED)); do patch -s -p1 -d $(UP) < patches/$$name.patch || exit 1; done
	touch $@

$(FROM_UPSTREAM): $(UPSTREAM) ;

$(BUILD)/prepare.stamp: $(SOURCES) tools/prepare.py | $(BUILD)
	$(PYTHON) tools/prepare.py $(BUILD) $(SOURCES)
	touch $@

$(COPIES): $(BUILD)/prepare.stamp ;

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines, with the receiver that gives up by
# counting, since every exchange is made in an NMI.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack

# Each ROM is assembled from the same copies: the original as it is, and
# the netplay one with NETPLAY defined.
$(BUILD)/drmario.o: $(COPIES) $(UP)/DPCM.bin
	ca65 -U -g -I $(BUILD) --bin-include-dir $(UP) -l $(BUILD)/drmario.lst \
		-o $@ $(BUILD)/copy_bank_FF.asm

$(BUILD)/drmario_net.o: $(COPIES) $(UP)/DPCM.bin $(NET_SOURCES)
	ca65 -U -g -D NETPLAY $(NET_INCLUDES) --bin-include-dir $(UP) \
		-l $(BUILD)/drmario_net.lst -o $@ $(BUILD)/copy_bank_FF.asm

$(BUILD)/drmario_net.prg: $(BUILD)/drmario_net.o net/game.cfg
	ld65 -C net/game.cfg -o $@ --dbgfile $(BUILD)/drmario_net.dbg \
		-m $(BUILD)/drmario_net.map $<

# The menu's bank, which has a session's frames and the link's library
# too, and a header that says the PRG is twice the size. It is
# an NES 2.0 header, which the MiSTer's core asks for: the same mapper, no
# submapper, and no memory on the cartridge.
$(BUILD)/menu.o: $(MENU_SOURCES)
	ca65 -g $(NET_INCLUDES) -l $(BUILD)/menu.lst -o $@ net/menu.s

$(BUILD)/menu.prg: $(BUILD)/menu.o net/menu.cfg
	ld65 -C net/menu.cfg -o $@ --dbgfile $(BUILD)/menu.dbg -m $(BUILD)/menu.map $<

$(BUILD)/header_net.bin: $(UP)/header.bin | $(BUILD)
	{ head -c 4 $<; printf '\004'; tail -c 11 $< | head -c 2; printf '\010'; \
		tail -c 8 $<; } > $@

$(NET_ROM): $(BUILD)/header_net.bin $(BUILD)/drmario_net.prg $(BUILD)/menu.prg $(UP)/CHR_ROM.chr
	cat $^ > $@

$(BUILD)/%.prg: $(BUILD)/%.o $(UP)/ld65.cfg
	ld65 -C $(UP)/ld65.cfg -o $@ --dbgfile $(BUILD)/$*.dbg $<

$(BUILD)/%.nes: $(UP)/header.bin $(BUILD)/%.prg $(UP)/CHR_ROM.chr
	cat $^ > $@

verify: $(ROM)
	@test "$$(shasum -a 1 $(ROM) | cut -d' ' -f1)" = "$(SHA1_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

# What a source in build/upstream has that the disassembly's has not.
PATCH_OF = diff -U0 --label a/$(1) --label b/$(1) "$(DRMARIO_SRC)/$(1)" $(UP)/$(1)

patches: $(UPSTREAM)
	$(foreach name,$(PATCHED),$(call PATCH_OF,$(name)) > patches/$(basename $(name)).patch; test $$? -le 1;)

# Not while build/upstream has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ] && [ -d "$(DRMARIO_SRC)" ]; then \
		for name in $(PATCHED); do \
			$(call PATCH_OF,$$name) | cmp -s - patches/$${name%.*}.patch || { \
				echo "$(UP)/$$name has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; }; \
		done; fi
	rm -rf $(BUILD)

FORCE:

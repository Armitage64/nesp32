# Contra Force build.
#
#   make            build/contraforce.nes, the original, and
#                   build/contraforce_fast.nes, the same game for one
#                   console with the faster passes (fast/), on an MMC3 with
#                   PRG RAM and twice the PRG ROM
#   make verify     check the original against the ROM's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make profile    where a tick's cycles go, in both ROMs
#   make bench      how long ticks of play take in both, every stage
#   make patches    write patches/ again from the sources in build/upstream
#   make clean
#
# The game is not here. Its disassembly, with its graphics and samples, is
# the Contra Force directory of cyneprepou4uk's NES-Games-Disassembly, a
# submodule at the top of this repository. What the build needs of it is
# copied to build/upstream, and patches/ puts the faster ROM's few lines
# into the copy. Everything they add is under .ifdef FAST, so
# contraforce.nes stays the original, byte for byte, and `make verify` says
# so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
NESP32 ?= ../..
ROM := $(BUILD)/contraforce.nes
FAST_ROM := $(BUILD)/contraforce_fast.nes
# Contra Force (USA), with its iNES header.
SHA512_ORIGINAL := b5ce746e595b50d8e58a595ac9d72385b1ea12c7dd42cd0b417384524971e9fdc62e2e034609ae82b1576d6fc6a8f75c931e9d4e06fceb289319fa80c316a0fa
# The disassembly, and the commit of it that patches/ was made against: a
# patch has line numbers and none of the disassembly's lines to go by. Its
# directory has a space in its name, so make is told of the copies only.
CF_SRC ?= $(NESP32)/third_party/NES-Games-Disassembly/Contra Force
CF_COMMIT ?= df2c8e55e7f13e5792482527db9e7c9e4a84c6e1
UP := $(BUILD)/upstream
UPSTREAM := $(BUILD)/upstream.stamp
BANKS := 00 02 03 04 05 06 07 08 0A 0C FF
PATCHED := $(wildcard patches/*.patch)
SOURCE_NAMES := $(BANKS:%=bank_%.asm) bank_ram.inc bank_val.inc
SOURCES := $(addprefix $(UP)/,$(SOURCE_NAMES))
COPIES := $(addprefix $(BUILD)/copy_,$(SOURCE_NAMES))
FROM_UPSTREAM := $(SOURCES) $(UP)/DPCM.bin $(UP)/CHR_ROM.chr $(UP)/header.bin $(UP)/ld65.cfg
OBJECTS := $(BANKS:%=$(BUILD)/orig/bank_%.o)
FAST_OBJECTS := $(BANKS:%=$(BUILD)/fast/bank_%.o) $(BUILD)/fast/fast.o
FAST_SOURCES := $(wildcard fast/*.inc fast/*.s)

.PHONY: all verify test profile bench patches clean

all: $(ROM) $(FAST_ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig $(BUILD)/fast:
	mkdir -p $@

# The disassembly's files, copied and patched. A patch that has changed
# makes them again.
$(UPSTREAM): $(PATCHED) | $(BUILD)
	@test -f "$(CF_SRC)/bank_FF.asm" || { \
		echo "no disassembly at $(CF_SRC): git submodule update --init"; exit 1; }
	@test -z "$(CF_COMMIT)" \
		|| test "$$(git -C "$(CF_SRC)" rev-parse HEAD)" = "$(CF_COMMIT)" || { \
		echo "$(CF_SRC) is not at $(CF_COMMIT), which patches/ is for"; exit 1; }
	rm -rf $(UP)
	mkdir -p $(UP)
	for name in $(notdir $(FROM_UPSTREAM)); do cp "$(CF_SRC)/$$name" $(UP) || exit 1; done
	for patch in $(PATCHED); do patch -s -p1 -d $(UP) < $$patch || exit 1; done
	touch $@

$(FROM_UPSTREAM): $(UPSTREAM) ;

$(BUILD)/prepare.stamp: $(SOURCES) tools/prepare.py | $(BUILD)
	$(PYTHON) tools/prepare.py $(BUILD) $(SOURCES)
	touch $@

$(COPIES): $(BUILD)/prepare.stamp ;

# Each bank is assembled twice from the same copies: the original as it
# is, and the faster ROM's with FAST defined.
$(BUILD)/orig/bank_%.o: $(BUILD)/copy_bank_%.asm $(COPIES) | $(BUILD)/orig
	ca65 -U -g -I $(BUILD) --bin-include-dir $(UP) -o $@ $<

$(BUILD)/fast/bank_%.o: $(BUILD)/copy_bank_%.asm $(COPIES) $(FAST_SOURCES) | $(BUILD)/fast
	ca65 -U -g -D FAST -I $(BUILD) -I fast --bin-include-dir $(UP) -o $@ $<

# The game's background test, for fast/probe.inc, made from the disassembly.
$(BUILD)/probe_game.inc: $(UP)/bank_FF.asm tools/probe.py
	$(PYTHON) tools/probe.py $< $@

$(BUILD)/fast/fast.o: $(FAST_SOURCES) $(COPIES) $(BUILD)/probe_game.inc | $(BUILD)/fast
	ca65 -U -g -D FAST -I $(BUILD) -I fast -l $(BUILD)/fast/fast.lst -o $@ fast/fast.s

$(BUILD)/contraforce.prg: $(OBJECTS) $(UP)/ld65.cfg
	ld65 -C $(UP)/ld65.cfg -o $@ --dbgfile $(BUILD)/contraforce.dbg $(OBJECTS)

$(ROM): $(UP)/header.bin $(BUILD)/contraforce.prg $(UP)/CHR_ROM.chr
	cat $^ > $@

# The faster ROM's header is in fast/fast.s, its first segment.
$(FAST_ROM): $(FAST_OBJECTS) fast/fast.cfg $(UP)/CHR_ROM.chr
	ld65 -C fast/fast.cfg -o $(BUILD)/contraforce_fast.prg --dbgfile $(BUILD)/contraforce_fast.dbg \
		-m $(BUILD)/contraforce_fast.map $(FAST_OBJECTS)
	cat $(BUILD)/contraforce_fast.prg $(UP)/CHR_ROM.chr > $@

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

test:
	$(PYTHON) -m pytest -q tests

profile: all
	$(PYTHON) tools/profile.py $(BUILD)

bench: all
	$(PYTHON) tools/bench.py $(BUILD)

# What a source in build/upstream has that the disassembly's has not.
PATCH_OF = diff -U0 --label a/$(1) --label b/$(1) "$(CF_SRC)/$(1)" $(UP)/$(1)

patches: $(UPSTREAM)
	@for name in $(SOURCE_NAMES); do \
		$(call PATCH_OF,$$name) > $(BUILD)/patch.tmp; status=$$?; \
		test $$status -le 1 || exit 1; \
		if [ $$status = 1 ]; then mv $(BUILD)/patch.tmp patches/$${name%.*}.patch; \
		else rm -f $(BUILD)/patch.tmp patches/$${name%.*}.patch; fi; \
	done
	touch $(UPSTREAM)

# Not while build/upstream has changes that patches/ has not.
clean:
	@if [ -f $(UPSTREAM) ]; then \
		for name in $(SOURCE_NAMES); do \
			$(call PATCH_OF,$$name) > /dev/null; status=$$?; \
			if [ $$status = 1 ] && ! [ -f patches/$${name%.*}.patch ] \
				|| [ -f patches/$${name%.*}.patch ] && ! $(call PATCH_OF,$$name) \
					| cmp -s - patches/$${name%.*}.patch; then \
				echo "$(UP)/$$name has changes that patches/ has not:" \
					"make patches, or delete $(BUILD) yourself"; exit 1; \
			fi; \
		done; fi
	rm -rf $(BUILD)

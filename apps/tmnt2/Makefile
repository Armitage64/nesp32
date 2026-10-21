# TMNT II build.
#
#   make            build/tmnt2.nes, the original
#   make verify     check it against the ROM's SHA-512
#   make clean
#
# The game is not here. Its disassembly is Aaron Bottegal's
# TMNT2-NES-Reverse-Engineered, a submodule at the top of this repository,
# which is a listing to read rather than a source to build.
# tools/convert.py makes ca65 source of it in build/src, taking every byte
# from baserom.nes, which whoever builds has to put here, and the listing's
# names and comments where the ROM agrees with them. The CHR ROM is cut out
# of baserom.nes too.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
NESP32 ?= ../..
ROM := $(BUILD)/tmnt2.nes
# Teenage Mutant Ninja Turtles II - The Arcade Game (USA), with its iNES
# header.
SHA512_ORIGINAL := f01d2492409536845999a95a763d9a3a9c03342b5b4c23162aa87ec85eecd5679cabe335367c4c044e79b8f0dac658887e0dd09ff524b967441419518c06010e
# The disassembly, and the commit of it that the conversion was made for.
TMNT2_SRC ?= $(NESP32)/third_party/TMNT2-NES-Reverse-Engineered
TMNT2_COMMIT ?= 35b7a15017eedd602e7485c12f11bb228b00923f
BASEROM ?= baserom.nes
SRC := $(BUILD)/src
CONVERTED := $(BUILD)/converted.stamp
NAMES := header tmnt2 chr
OBJECTS := $(NAMES:%=$(BUILD)/orig/%.o)

.PHONY: all verify clean

all: $(ROM)

.SECONDARY:

$(BUILD) $(BUILD)/orig:
	mkdir -p $@

$(CONVERTED): tools/convert.py $(BASEROM) | $(BUILD)
	@test -f $(TMNT2_SRC)/TMNT2.bank31.asm || { \
		echo "no disassembly at $(TMNT2_SRC): git submodule update --init"; exit 1; }
	@test -z "$(TMNT2_COMMIT)" \
		|| test "$$(git -C $(TMNT2_SRC) rev-parse HEAD)" = "$(TMNT2_COMMIT)" || { \
		echo "$(TMNT2_SRC) is not at $(TMNT2_COMMIT), which the conversion is for"; exit 1; }
	$(PYTHON) tools/convert.py $(TMNT2_SRC) $(BASEROM) $(BUILD)
	printf '.segment "CHR"\n    .incbin "chr.bin"\n' > $(SRC)/chr.asm
	touch $@

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the ROM"; exit 1

$(BUILD)/orig/%.o: $(CONVERTED) | $(BUILD)/orig
	ca65 --debug-info --bin-include-dir $(BUILD) -o $@ $(SRC)/$*.asm

$(ROM): $(OBJECTS) tmnt2.cfg
	ld65 -C tmnt2.cfg --dbgfile $(BUILD)/tmnt2.dbg -o $@ $(OBJECTS)

verify: $(ROM)
	@test "$$(shasum -a 512 $(ROM) | cut -d' ' -f1)" = "$(SHA512_ORIGINAL)" \
		&& echo "$(ROM) matches the original" \
		|| { echo "$(ROM) differs from the original"; exit 1; }

clean:
	rm -rf $(BUILD)

# NESpedia build.
#
#   make                         build/nespedia.nes, with the demo article,
#                                and build/nespedia_link.nes, for a Stick
#   make ARTICLE=some.txt        with another text built in
#   make test
#   make preview                 build/search.png and build/reader.png

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The Stick runs nesp32's firmware, a checkout of which sits beside this
# one. From it come the link's library for the console, the numbers the two
# ends share, and the text code that lays an article out, which is built
# for this computer so that the tools lay text out as a Stick does.
NESP32 ?= ../nesp32
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
ARTICLE ?= nes/demo_article.txt
ROM := $(BUILD)/nespedia.nes
LINK_ROM := $(BUILD)/nespedia_link.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR
NESP := $(NESP_BUILD)/nesp.stamp
SOURCES := nes/nespedia.s nes/split.inc nes/keyboard.inc nes/reader.inc

.PHONY: all verify test preview clean FORCE

all: $(ROM) $(LINK_ROM)

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

$(BUILD)/screen.stamp: tools/gen_screen.py tools/stick.py $(NESP) | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

# The standalone ROM's built-in article.
BUILT_IN := $(BUILD)/article.bin $(BUILD)/article.inc

$(BUILD)/article.stamp: $(ARTICLE) tools/embed_article.py tools/stick.py $(NESP) \
		$(NESP32)/firmware/components/nesp_services/text.c | $(BUILD)
	$(PYTHON) tools/embed_article.py $(ARTICLE) $(BUILD)
	touch $@

$(BUILT_IN): $(BUILD)/article.stamp ;

$(BUILD)/nespedia.o: $(SOURCES) nes/fake_link.inc $(SCREEN) $(BUILT_IN)
	ca65 -g -I $(BUILD) -I nes --bin-include-dir $(BUILD) -o $@ $<

$(ROM): $(BUILD)/nespedia.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/nespedia.labels \
		--dbgfile $(BUILD)/nespedia.dbg -m $(BUILD)/nespedia.map $<

# The serial link build: the same reader, its article from a Stick on
# controller port 2, over nesp32's link.
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py

$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@

$(BUILD)/nespedia_link.o: $(SOURCES) nes/serial_link.inc $(SCREEN) $(NESP_LIB) \
		$(BUILD)/link.inc $(NESP)
	ca65 -g -D LINK -I $(BUILD) -I $(NESP_BUILD) -I nes -I $(NESP32)/nes/lib \
		--bin-include-dir $(BUILD) -o $@ $<

$(LINK_ROM): $(BUILD)/nespedia_link.o nes/nrom256.cfg
	ld65 -C nes/nrom256.cfg -o $@ -Ln $(BUILD)/nespedia_link.labels \
		--dbgfile $(BUILD)/nespedia_link.dbg -m $(BUILD)/nespedia_link.map $<

verify: $(ROM) $(LINK_ROM)
	for rom in $(ROM) $(LINK_ROM); do \
		test "$$(wc -c < $$rom | tr -d ' ')" = "$(strip $(ROM_SIZE))" && \
		printf 'NES\032\002\001\001\000' | cmp -n 8 - $$rom || exit 1; \
	done

preview: | $(BUILD)
	$(PYTHON) tools/gen_screen.py $(BUILD) --preview $(BUILD)/search.png --reader $(BUILD)/reader.png

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

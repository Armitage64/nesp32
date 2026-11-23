# The line-palette test ROM (README.md).
#
#   make PHOTOS="a.jpg b.jpg c.jpg"    build/linetest.nes: the test pattern,
#                                      then each photo two ways (up to three)
#
# The converter is the Gallery's, patched as the experiment had it
# (bands.py, then lines_patch.py) and driven by lines3.c.

PYTHON ?= python3
BUILD ?= build
NESP32 ?= ../../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
PHOTOS ?= $(NESP32)/tests/fixtures/commons_tower.jpg
OFF_DOT ?= 245
FW := $(NESP32)/firmware/components
CFLAGS := -std=c11 -O2 -I $(BUILD) -I $(NESP_BUILD) -I $(FW)/nesp_core/include \
	-I $(FW)/nesp_services/include -I $(FW)/nesp_services -I $(NESP32)/third_party/stb
NESP := $(NESP_BUILD)/nesp.stamp

.PHONY: all clean FORCE

all: $(BUILD)/linetest.nes

$(BUILD):
	mkdir -p $@

$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

FORCE:

$(BUILD)/picture.c: $(FW)/nesp_services/picture.c bands.py lines_patch.py | $(BUILD)
	cp $< $@
	$(PYTHON) bands.py $@
	$(PYTHON) lines_patch.py $@

$(BUILD)/convert_lines: lines3.c $(BUILD)/picture.c $(NESP)
	$(CC) $(CFLAGS) -DBAND_ROWS=1 -o $@ lines3.c $(FW)/nesp_services/image.c -lm

$(BUILD)/convert_today: lines3.c $(BUILD)/picture.c $(NESP)
	$(CC) $(CFLAGS) -DBAND_ROWS=15 -o $@ lines3.c $(FW)/nesp_services/image.c -lm

# Each photo as pictures/N_lines and pictures/N_today (.bin, .pal, .sched).
$(BUILD)/pictures.stamp: $(BUILD)/convert_lines $(BUILD)/convert_today $(PHOTOS) Makefile
	rm -rf $(BUILD)/pictures
	mkdir -p $(BUILD)/pictures
	n=0; for photo in $(PHOTOS); do \
		cp "$$photo" $(BUILD)/pictures/$${n}_lines.jpg; \
		cp "$$photo" $(BUILD)/pictures/$${n}_today.jpg; \
		$(BUILD)/convert_lines $(BUILD)/pictures/$${n}_lines.jpg || exit 1; \
		$(BUILD)/convert_today $(BUILD)/pictures/$${n}_today.jpg || exit 1; \
		n=$$((n + 1)); \
	done
	touch $@

$(BUILD)/timed.stamp: gen_linetest.py $(BUILD)/pictures.stamp
	$(PYTHON) gen_linetest.py --off-dot $(OFF_DOT) $(BUILD) \
		$$(n=0; for photo in $(PHOTOS); do \
			printf '%s ' $(BUILD)/pictures/$${n}_lines.jpg $(BUILD)/pictures/$${n}_today.jpg; \
			n=$$((n + 1)); done)
	touch $@

$(BUILD)/linetest.o: linetest.s $(BUILD)/timed.stamp
	ca65 -g -I $(BUILD) --bin-include-dir $(BUILD) -o $@ $<

$(BUILD)/linetest.nes: $(BUILD)/linetest.o unrom.cfg
	ld65 -C unrom.cfg -o $@ -Ln $(BUILD)/linetest.labels -m $(BUILD)/linetest.map $<

clean:
	rm -rf $(BUILD)

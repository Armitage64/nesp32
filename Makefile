# nesp32 build.
#
#   make            everything below
#   make proto      build/nesp_proto.h, .inc and .py from proto/nesp.toml
#   make host       build/libnesp_host: the firmware's link and services for
#                   this computer, which the tests load
#   make rom        build/setup.nes: the setup ROM
#   make test
#
# The Stick's firmware itself is built with ESP-IDF, from firmware/.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
CC ?= cc
CFLAGS ?= -std=c11 -O2 -g -Wall -Wextra -Werror -Wconversion -Wshadow -fPIC

UNAME := $(shell uname -s)
HOST_LIB := $(BUILD)/libnesp_host.$(if $(filter Darwin,$(UNAME)),dylib,so)
PROTO := $(BUILD)/nesp_proto.h $(BUILD)/nesp_proto.inc $(BUILD)/nesp_proto.py
CORE := firmware/components/nesp_core
SERVICES := firmware/components/nesp_services
HOST_SOURCES := $(CORE)/nesp_core.c $(wildcard $(SERVICES)/*.c) host/nesp_host.c
HOST_HEADERS := $(CORE)/include/nesp_core.h $(SERVICES)/include/nesp_services.h

ROM := $(BUILD)/setup.nes
ROM_SIZE := 40976   # 16-byte header + 32 KB PRG + 8 KB CHR

.PHONY: all proto host rom timeout-rom verify test clean

all: proto host rom

$(BUILD):
	mkdir -p $@

# gen_proto.py rewrites only the files whose contents changed, so what is
# built from them depends on each, and on a stamp for the three.
$(BUILD)/proto.stamp: proto/nesp.toml tools/gen_proto.py | $(BUILD)
	$(PYTHON) tools/gen_proto.py $(BUILD)
	touch $@

$(PROTO): $(BUILD)/proto.stamp ;

proto: $(PROTO)

$(HOST_LIB): $(HOST_SOURCES) $(HOST_HEADERS) $(BUILD)/nesp_proto.h
	$(CC) $(CFLAGS) -shared -I $(BUILD) -I $(CORE)/include -I $(SERVICES)/include \
		-o $@ $(HOST_SOURCES)

host: $(HOST_LIB)

# --- the setup ROM --------------------------------------------------------------

$(BUILD)/link.inc: nes/lib/gen_link.py $(BUILD)/nesp_proto.py | $(BUILD)
	$(PYTHON) nes/lib/gen_link.py $(BUILD) $@

SCREEN := $(BUILD)/chr.bin $(BUILD)/header.bin $(BUILD)/screen.inc

$(BUILD)/screen.stamp: nes/setup/gen_screen.py $(BUILD)/nesp_proto.py | $(BUILD)
	$(PYTHON) nes/setup/gen_screen.py $(BUILD)
	touch $@

$(SCREEN): $(BUILD)/screen.stamp ;

SETUP_SOURCES := $(wildcard nes/setup/*.s nes/setup/*.inc) nes/lib/nesp.inc

$(BUILD)/setup.o: $(SETUP_SOURCES) $(SCREEN) $(BUILD)/link.inc $(BUILD)/nesp_proto.inc
	ca65 -g -I $(BUILD) -I nes/lib -I nes/setup --bin-include-dir $(BUILD) \
		-o $@ nes/setup/setup.s

$(ROM): $(BUILD)/setup.o nes/setup/nrom256.cfg
	ld65 -C nes/setup/nrom256.cfg -o $@ -Ln $(BUILD)/setup.labels \
		--dbgfile $(BUILD)/setup.dbg -m $(BUILD)/setup.map $<

rom: $(ROM)

# The same ROM on the library's other receiver, the one for exchanges made
# inside an NMI, which gives up by counting, and with its CRC from a table.
# Nothing ships it: the tests time that receiver in it, and run the ROM on
# it.
TIMEOUT_ROM := $(BUILD)/setup_timeout.nes

$(BUILD)/timeout/link.inc: nes/lib/gen_link.py $(BUILD)/nesp_proto.py | $(BUILD)
	mkdir -p $(BUILD)/timeout
	$(PYTHON) nes/lib/gen_link.py $(BUILD) $@ --timeout

$(BUILD)/setup_timeout.o: $(SETUP_SOURCES) $(SCREEN) $(BUILD)/timeout/link.inc $(BUILD)/nesp_proto.inc
	ca65 -g -D TIMEOUT_BUILD -I $(BUILD)/timeout -I $(BUILD) -I nes/lib -I nes/setup \
		--bin-include-dir $(BUILD) -o $@ nes/setup/setup.s

$(TIMEOUT_ROM): $(BUILD)/setup_timeout.o nes/setup/nrom256.cfg
	ld65 -C nes/setup/nrom256.cfg -o $@ -Ln $(BUILD)/setup_timeout.labels $<

timeout-rom: $(TIMEOUT_ROM)

verify: $(ROM)
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "$(strip $(ROM_SIZE))"
	printf 'NES\032\002\001\001\000' | cmp -n 8 - $(ROM)

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

# nesp32 build.
#
#   make            everything below
#   make proto      build/nesp_proto.h, .inc and .py from proto/nesp.toml
#   make host       build/libnesp_host: the firmware's link and services for
#                   this computer, which the tests load
#   make rom        build/setup.nes: the setup ROM
#   make cart       build/nesp32.nes: the setup ROM and the four other
#                   programs on one cartridge, with a menu. It builds them
#                   from their checkouts beside this one.
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

.PHONY: all proto host rom timeout-rom verify cart verify-cart test clean FORCE

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

# --- the cartridge --------------------------------------------------------------

# The other four programs, each built by its own Makefile from a checkout
# beside this one, into this build directory and against this tree. BUILD
# is given to each by name: one given to this make would otherwise be
# theirs too.
JUKEBOX ?= ../nes-jukebox
WIKI ?= ../nes-wiki
DRMARIO ?= ../nes-drmario
THROUGHPUT ?= $(JUKEBOX)/throughput

CART := $(BUILD)/nesp32.nes
CART_SIZE := 393232   # 16-byte header + 256 KB PRG + 128 KB CHR
CART_BUILD := $(BUILD)/cart
PARTS := $(abspath $(CART_BUILD))
JUKEBOX_ROM := $(PARTS)/jukebox/jukebox_link.nes
WIKI_ROM := $(PARTS)/wiki/nespedia_link.nes
DRMARIO_ROM := $(PARTS)/drmario/drmario_net.nes
THROUGHPUT_ROM := $(PARTS)/throughput/linktest.nes
CART_ROMS := $(JUKEBOX_ROM) $(WIKI_ROM) $(DRMARIO_ROM) $(THROUGHPUT_ROM)
CART_ARGS := --jukebox $(JUKEBOX_ROM) --wiki $(WIKI_ROM) --drmario $(DRMARIO_ROM) \
	--throughput $(THROUGHPUT_ROM) --setup $(ROM)
PART = $(MAKE) -s -C $(1) BUILD=$(@D) NESP32=$(CURDIR) NESP_BUILD=$(abspath $(BUILD)) $@

# Each of their Makefiles knows what of its ROM is out of date.
$(JUKEBOX_ROM): FORCE $(PROTO) $(HOST_LIB)
	$(call PART,$(JUKEBOX))

$(WIKI_ROM): FORCE $(PROTO) $(HOST_LIB)
	$(call PART,$(WIKI))

$(DRMARIO_ROM): FORCE $(PROTO) $(HOST_LIB)
	$(call PART,$(DRMARIO))

$(THROUGHPUT_ROM): FORCE $(PROTO) $(HOST_LIB)
	$(call PART,$(THROUGHPUT))

# gen_cart.py rewrites only the files whose contents changed.
CART_TABLES := $(CART_BUILD)/chr.bin $(CART_BUILD)/screen.bin $(CART_BUILD)/menu.inc

$(CART_BUILD)/tables.stamp: nes/cart/gen_cart.py nes/setup/gen_screen.py $(CART_ROMS) $(ROM)
	$(PYTHON) nes/cart/gen_cart.py tables $(CART_BUILD) $(CART_ARGS)
	touch $@

$(CART_TABLES): $(CART_BUILD)/tables.stamp ;

$(CART_BUILD)/menu.o: nes/cart/menu.s $(CART_TABLES)
	ca65 -g -I $(CART_BUILD) --bin-include-dir $(CART_BUILD) -o $@ $<

$(CART_BUILD)/menu.prg: $(CART_BUILD)/menu.o nes/cart/menu.cfg
	ld65 -C nes/cart/menu.cfg -o $@ -Ln $(CART_BUILD)/menu.labels \
		--dbgfile $(CART_BUILD)/menu.dbg -m $(CART_BUILD)/menu.map $<

$(CART): $(CART_BUILD)/menu.prg $(CART_BUILD)/chr.bin nes/cart/gen_cart.py $(CART_ROMS) $(ROM)
	$(PYTHON) nes/cart/gen_cart.py rom $@ --menu $(CART_BUILD)/menu.prg \
		--chr $(CART_BUILD)/chr.bin $(CART_ARGS)

cart: $(CART)

verify-cart: $(CART)
	test "$$(wc -c < $(CART) | tr -d ' ')" = "$(strip $(CART_SIZE))"
	printf 'NES\032\020\020\020\010' | cmp -n 8 - $(CART)

FORCE:

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

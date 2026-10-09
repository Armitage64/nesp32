# nesp32 build.
#
#   make            everything below
#   make proto      build/nesp_proto.h, .inc and .py from proto/nesp.toml
#   make host       build/libnesp_host: the firmware's link and services for
#                   this computer, which the tests load
#   make rom        build/setup.nes: the setup ROM, from apps/setup
#   make cart       build/nesp32.nes: the setup ROM and the four other
#                   programs on one cartridge, with a menu. It builds them
#                   from apps/.
#   make web        build/web: the product page, and under flash/ the page
#                   that flashes a nesp32 from a browser, with the firmware
#                   as firmware/deploy.sh build left it.
#                   make web-serve serves it at http://localhost:8032
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

.PHONY: all proto host rom timeout-rom verify cart verify-cart web web-serve test clean FORCE

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

# Built by its own Makefile in apps/setup, into this build directory and
# against this tree: the tests of the link are run on it, and it is one of
# the cartridge's programs. That Makefile knows what of it is out of date.
SETUP ?= apps/setup
TIMEOUT_ROM := $(BUILD)/setup_timeout.nes
SETUP_MAKE = $(MAKE) -s -C $(SETUP) BUILD=$(abspath $(BUILD)) NESP32=$(CURDIR) \
	NESP_BUILD=$(abspath $(BUILD))

$(ROM): FORCE $(PROTO)
	$(SETUP_MAKE) $(abspath $@)

rom: $(ROM)

$(TIMEOUT_ROM): FORCE $(PROTO)
	$(SETUP_MAKE) $(abspath $@)

timeout-rom: $(TIMEOUT_ROM)

verify: $(ROM)
	$(SETUP_MAKE) verify

# --- the cartridge --------------------------------------------------------------

# The other four programs, each built by its own Makefile in apps/ as the
# setup ROM is, into this build directory and against this tree. BUILD
# is given to each by name: one given to this make would otherwise be
# theirs too.
# Dr. Mario's takes the game from its disassembly, a submodule in
# third_party/, and says so if that is not there.
JUKEBOX ?= apps/jukebox
WIKI ?= apps/wiki
DRMARIO ?= apps/drmario
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

$(CART_BUILD)/tables.stamp: nes/cart/gen_cart.py $(SETUP)/tools/gen_screen.py $(CART_ROMS) $(ROM)
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

web:
	$(PYTHON) tools/gen_web.py $(BUILD)/web

web-serve: web
	$(PYTHON) -m http.server -d $(BUILD)/web -b localhost 8032

FORCE:

test:
	$(PYTHON) -m pytest

clean:
	rm -rf $(BUILD)

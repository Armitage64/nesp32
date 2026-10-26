# The netplay build of the SMB two-player hack, SMBX.
#
#   make            build/smbx_net.nes, for two consoles and two nesp32s
#   make verify     check baserom.nes against the hack's SHA-512
#   make test       the simulation's tests (needs requirements-dev.txt)
#   make bps        dist/smbx_net.bps and .ips again, the netplay ROM as a
#                   patch to the hack, which players apply to their own
#   make clean
#
# The game is not here. Whoever builds puts the hack in this directory as
# baserom.nes (or says where it is with BASEROM=), and the build takes the
# game from it: net/rom.asm copies it by the place of each byte in the
# file, around the few the netplay changes. Nothing of the game is in this
# directory, and the build checks the file before it trusts those places.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
BUILD ?= build
# The netplay ROM's link is nesp32's, at the top of this repository (two
# directories up). From it come the link's library for the console and the
# numbers the two ends share; its link and services are built for this
# computer, for the tests to run the ROM against.
NESP32 ?= ../..
NESP_BUILD ?= $(abspath $(BUILD))/nesp
export NESP32 NESP_BUILD
NESP := $(NESP_BUILD)/nesp.stamp
NESP_LIB := $(NESP32)/nes/lib/nesp.inc $(NESP32)/nes/lib/gen_link.py
NET_ROM := $(BUILD)/smbx_net.nes
# The netplay ROM as a patch to the hack, for players who build nothing:
# kept in the repository, as it holds none of the game
# (tools/gen_patch.py refuses one that would).
DIST := dist
GEN_PATCH := $(NESP32)/tools/gen_patch.py
BASEROM ?= baserom.nes
# Super Mario Bros. - Two Players Hack (Corpse Grinder, 2018), as patched
# onto the US release: a VRC6 cartridge, 64 KB of PRG and 8 KB of CHR.
SHA512_BASEROM := cf536c1e82da8ce57a8a0bebda9050a137f07f3a214aacf837ec7c1e54b921e9998e23eb25124f4759669cdc5274a8b814c0e27349a15062d32a5a2ee31b74e5
CHECKED := $(BUILD)/baserom.nes
NET_SOURCES := $(wildcard net/*.inc net/*.asm) $(BUILD)/link.inc $(NESP_LIB) $(NESP)
NET_INCLUDES := -I net -I $(BUILD) -I $(NESP_BUILD) -I $(NESP32)/nes/lib

.PHONY: all verify test bps clean FORCE

all: $(NET_ROM)

$(BUILD):
	mkdir -p $@

# baserom.nes, once it is known to be the hack: net/rom.asm takes it from
# here.
$(CHECKED): $(BASEROM) | $(BUILD)
	@test "$$($(PYTHON) -c 'import hashlib,sys; print(hashlib.sha512(open(sys.argv[1],"rb").read()).hexdigest())' $(BASEROM))" = "$(SHA512_BASEROM)" \
		|| { echo "$(BASEROM) is not the hack this build is for (README.md)"; exit 1; }
	cp $(BASEROM) $@

verify: $(CHECKED)
	@echo "$(BASEROM) is the hack"

$(BASEROM):
	@echo "no $(BASEROM): the game is built from the hack's ROM (README.md)"; exit 1

# nesp32's own Makefile knows what of it is out of date.
$(NESP): FORCE | $(BUILD)
	$(MAKE) -s -C $(NESP32) BUILD=$(NESP_BUILD) proto host
	@test -f $@ || touch $@

# The library's serial routines: the receiver that gives up by counting,
# since every exchange is made in an NMI, and both routines on the one page
# net/smbx_net.cfg has for them.
$(BUILD)/link.inc: $(NESP_LIB) $(NESP)
	$(PYTHON) $(NESP32)/nes/lib/gen_link.py $(NESP_BUILD) $@ --timeout --pack $(LINK_OPTIONS)

$(BUILD)/smbx_net.o: $(NET_SOURCES) $(CHECKED)
	ca65 --cpu 6502 --debug-info --bin-include-dir $(BUILD) $(NET_INCLUDES) -o $@ net/rom.asm

$(NET_ROM): $(BUILD)/smbx_net.o net/smbx_net.cfg
	ld65 -C net/smbx_net.cfg --dbgfile $(BUILD)/smbx_net.dbg -m $(BUILD)/smbx_net.map \
		-o $@ $(BUILD)/smbx_net.o

test:
	$(PYTHON) -m pytest -q tests

# From baserom.nes, once it is known to be the hack: the patch is for it
# and no other.
bps: $(CHECKED) $(NET_ROM)
	mkdir -p $(DIST)
	$(PYTHON) $(GEN_PATCH) $(CHECKED) $(NET_ROM) $(DIST)/smbx_net.bps --ips $(DIST)/smbx_net.ips

clean:
	rm -rf $(BUILD)

FORCE:

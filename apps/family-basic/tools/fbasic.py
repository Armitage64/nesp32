"""What is known of Family BASIC V3's ROM, for the build and the tests.

The game is not in this repository: whoever builds puts a copy in
baserom.nes. Everything here is checked against it as it is read.
"""

import hashlib

INES_HEADER = 16
PRG_SIZE = 0x8000
CHR_SIZE = 0x2000
PRG_START = 0x8000
SHA1 = "21620b454c8b1253afc720feb25be9c8132dbfbc"   # the iNES file, header and all

# The keyboard's matrix as the game decodes it: 9 rows of 8 keys, a key's
# place being row * 8 + bit. Each table has the game's code for every key,
# plain and with SHIFT.
KEYS_PLAIN = 0xBAA9
KEYS_SHIFT = 0xBAF1
MATRIX_KEYS = 9 * 8
SHIFTED = 0x80              # a place's bit for "with SHIFT", in keys.inc

# The game's codes for its keys that are not characters.
CODE_STOP = 0x03
CODE_DEL = 0x08
CODE_CLR_HOME = 0x0B
CODE_RETURN = 0x0D
CODE_INS = 0x12
CODE_CLS = 0x0C                 # SHIFT and CLR HOME
CODE_RIGHT, CODE_LEFT, CODE_UP, CODE_DOWN = 0x1C, 0x1D, 0x1E, 0x1F
CODE_F1 = 0xF0                  # to F8, $F7
CODE_KANA = 0xFF
# Its codes that are not ASCII's for the same character: its font has the
# square brackets at $B2 and $B3, and other signs at ASCII's $5B and $5D.
# (It has the yen at ASCII's backslash, and the key that types it.)
CODES_NOT_ASCII = {"[": 0xB2, "]": 0xB3}

# The bytes the build changes, as they are in the game: where, and what is
# there.
PATCH_SITES = {
    "nmi": (0x80CC, bytes((0xA9, 0x71, 0x85, 0xEE, 0xA9, 0x89, 0x85, 0xEF))),
    "stop": (0x883A, bytes((0xA9, 0x05, 0x8D))),
    "pad": (0xAD15, bytes((0x85, 0x19, 0xA9))),
    "scan": (0xB958, bytes((0xA9, 0x05, 0x8D, 0x16, 0x40, 0xEA))),
    # The rest of the scan, which the game no longer runs: reset_stub.
    "stub": (0xB95E, bytes((0xEA, 0xEA, 0xEA, 0xEA, 0xEA, 0xA2, 0x00, 0xA9, 0x04, 0x8D,
                            0x16, 0x40))),
    "reset_vector": (0xFFFC, bytes((0xBA, 0x80))),
    # The data recorder: the starts of its routines, each of which turned
    # the NMI off first (jsr $BE0E), and two of their calls.
    "save_header": (0xBF1F, bytes((0x20, 0x0E, 0xBE))),
    "save_data": (0xBF30, bytes((0x20, 0x0E, 0xBE))),
    "find_program": (0xBE53, bytes((0x20, 0x0E, 0xBE))),
    "load_data": (0xBE24, bytes((0x20, 0x0E, 0xBE))),
    "check_data": (0xBE1C, bytes((0x20, 0x0E, 0xBE))),
    "save_program": (0x9D9C, bytes((0x4C, 0x30, 0xBF))),     # SAVE's jmp to save_data
    "find_screen": (0xC56D, bytes((0x20, 0x53, 0xBE))),      # BG GRAPHIC's jsr to find_program
}
# Where each of those goes now, in fbkbd.s: a routine's start jumps to
# its, and a call or a jump is to its instead.
JMP, JSR = 0x4C, 0x20
TAPE_SITES = {"save_header": (JMP, "fb_save_header"), "save_data": (JMP, "fb_save_data"),
              "find_program": (JMP, "fb_find_program"), "load_data": (JMP, "fb_load_data"),
              "check_data": (JMP, "fb_check_data"), "save_program": (JMP, "fb_save_program"),
              "find_screen": (JSR, "fb_find_screen")}
SCAN_DECODE = 0xB9A1        # where the game reads the matrix it scanned


class Rom:
    def __init__(self, path):
        with open(path, "rb") as handle:
            data = handle.read()
        digest = hashlib.sha1(data).hexdigest()
        if digest != SHA1:
            raise ValueError("%s is not Family BASIC V3 (SHA-1 %s)" % (path, digest))
        self.header = data[:INES_HEADER]
        self.prg = bytearray(data[INES_HEADER:INES_HEADER + PRG_SIZE])
        self.chr = data[INES_HEADER + PRG_SIZE:]
        assert len(self.chr) == CHR_SIZE

    def read(self, address, length):
        return bytes(self.prg[address - PRG_START:address - PRG_START + length])

    def write(self, address, data):
        self.prg[address - PRG_START:address - PRG_START + len(data)] = data

    def key_codes(self):
        """(plain, shifted): the game's code for each place in the matrix."""
        return self.read(KEYS_PLAIN, MATRIX_KEYS), self.read(KEYS_SHIFT, MATRIX_KEYS)

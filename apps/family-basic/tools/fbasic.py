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
CODE_RIGHT, CODE_LEFT, CODE_UP, CODE_DOWN = 0x1C, 0x1D, 0x1E, 0x1F
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
}
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

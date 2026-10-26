"""py65's 6502 with the NMOS chip's unofficial opcodes, which the hack uses.

py65 has only the documented instructions, and steps over any other as if
it were a byte long. The hack's code has the stable unofficial ones: the
combined read-modify-write instructions (SLO, RLA, SRE, RRA, DCP, ISC),
LAX and SAX, the immediate ones (ANC, ALR, ARR, AXS, and SBC's twin at
$EB), and the NOPs that read an operand. Each takes the cycles a real 2A03
takes. Any other unofficial opcode raises, so that a test cannot run past
one quietly.
"""

from py65.devices.mpu6502 import MPU as MPU6502


class UnknownOpcode(Exception):
    pass


# The addressing modes of the read-modify-write group: (mode, its low bits
# of the opcode, the address function's name, operand bytes, cycles).
RMW_MODES = (
    ("zpg", 0x07, "ZeroPageAddr", 1, 5),
    ("zpx", 0x17, "ZeroPageXAddr", 1, 6),
    ("inx", 0x03, "IndirectXAddr", 1, 8),
    ("iny", 0x13, "IndirectYAddr", 1, 8),
    ("abs", 0x0F, "AbsoluteAddr", 2, 6),
    ("abx", 0x1F, "AbsoluteXAddr", 2, 7),
    ("aby", 0x1B, "AbsoluteYAddr", 2, 7),
)
# Each is a shift or a step of the byte, and then an operation of A with it.
RMW_OPS = {
    0x00: ("SLO", "opASL", "opORA"),
    0x20: ("RLA", "opROL", "opAND"),
    0x40: ("SRE", "opLSR", "opEOR"),
    0x60: ("RRA", "opROR", "opADC"),
    0xC0: ("DCP", "opDECR", None),      # then CMP
    0xE0: ("ISC", "opINCR", "opSBC"),
}


class MPU(MPU6502):
    instruct = list(MPU6502.instruct)
    cycletime = list(MPU6502.cycletime)
    extracycles = list(MPU6502.extracycles)
    disassemble = list(MPU6502.disassemble)

    def __init__(self, *args, **kwargs):
        MPU6502.__init__(self, *args, **kwargs)
        self.name = "2A03"

    def inst_unknown(self):
        raise UnknownOpcode("opcode $%02X at $%04X" % (self.memory[(self.pc - 1) & 0xFFFF],
                                                       (self.pc - 1) & 0xFFFF))


def _define(opcode, name, mode, cycles, extra, run):
    MPU.instruct[opcode] = run
    MPU.cycletime[opcode] = cycles
    MPU.extracycles[opcode] = extra
    MPU.disassemble[opcode] = (name, mode)


def _rmw(shift, then, size, mode_fn):
    def run(self):
        # Fixed cycles: the address is worked out with no extra for a page.
        address = getattr(self, mode_fn)()
        getattr(self, shift)(lambda: address)
        if then is None:
            self.opCMPR(lambda: address, self.a)
        else:
            getattr(self, then)(lambda: address)
        self.pc += size
    return run


def _read(fn, size, mode_fn):
    def run(self):
        fn(self, getattr(self, mode_fn)())
        self.pc += size
    return run


def _lax(self, address):
    self.a = self.x = self.ByteAt(address)
    self.FlagsNZ(self.a)


def _nop_read(self, address):
    self.ByteAt(address)


def _sax(fn_name, size):
    def run(self):
        self.memory[getattr(self, fn_name)()] = self.a & self.x
        self.pc += size
    return run


def _immediate(run_value):
    def run(self):
        run_value(self, self.ByteAt(self.pc))
        self.pc += 1
    return run


def _anc(self, value):
    self.a &= value
    self.FlagsNZ(self.a)
    self.p = (self.p & ~self.CARRY) | (self.CARRY if self.a & 0x80 else 0)


def _alr(self, value):
    self.a &= value
    self.p = (self.p & ~self.CARRY) | (self.a & 1)
    self.a >>= 1
    self.FlagsNZ(self.a)


def _arr(self, value):
    self.a &= value
    self.a = (self.a >> 1) | (0x80 if self.p & self.CARRY else 0)
    self.FlagsNZ(self.a)
    bit6, bit5 = self.a >> 6 & 1, self.a >> 5 & 1
    self.p &= ~(self.CARRY | self.OVERFLOW)
    if bit6:
        self.p |= self.CARRY
    if bit6 ^ bit5:
        self.p |= self.OVERFLOW


def _axs(self, value):
    both = self.a & self.x
    result = both - value
    self.p = (self.p & ~self.CARRY) | (self.CARRY if result >= 0 else 0)
    self.x = result & 0xFF
    self.FlagsNZ(self.x)


def _sbc(self, value):
    self.opSBC(lambda: self.pc)


for _opcode in range(256):
    if MPU.instruct[_opcode] is MPU6502.inst_not_implemented:
        MPU.instruct[_opcode] = MPU.inst_unknown

for _high, (_name, _shift, _then) in RMW_OPS.items():
    for _mode, _low, _fn, _size, _cycles in RMW_MODES:
        _define(_high | _low, _name, _mode, _cycles, 0, _rmw(_shift, _then, _size, _fn))

# LAX: A and X loaded alike. SAX: A AND X stored.
for _opcode, _mode, _fn, _size, _cycles, _extra in (
        (0xA7, "zpg", "ZeroPageAddr", 1, 3, 0), (0xB7, "zpy", "ZeroPageYAddr", 1, 4, 0),
        (0xA3, "inx", "IndirectXAddr", 1, 6, 0), (0xB3, "iny", "IndirectYAddr", 1, 5, 1),
        (0xAF, "abs", "AbsoluteAddr", 2, 4, 0), (0xBF, "aby", "AbsoluteYAddr", 2, 4, 1)):
    _define(_opcode, "LAX", _mode, _cycles, _extra, _read(_lax, _size, _fn))
for _opcode, _mode, _fn, _size, _cycles in (
        (0x87, "zpg", "ZeroPageAddr", 1, 3), (0x97, "zpy", "ZeroPageYAddr", 1, 4),
        (0x83, "inx", "IndirectXAddr", 1, 6), (0x8F, "abs", "AbsoluteAddr", 2, 4)):
    _define(_opcode, "SAX", _mode, _cycles, 0, _sax(_fn, _size))

for _opcode, _name, _fn in ((0x0B, "ANC", _anc), (0x2B, "ANC", _anc), (0x4B, "ALR", _alr),
                            (0x6B, "ARR", _arr), (0xCB, "AXS", _axs), (0xEB, "SBC", _sbc)):
    _define(_opcode, _name, "imm", 2, 0, _immediate(_fn))

# The NOPs: of one byte, and those that read an operand and drop it.
for _opcode in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA):
    _define(_opcode, "NOP", "imp", 2, 0, lambda self: None)
for _opcode in (0x80, 0x82, 0x89, 0xC2, 0xE2):
    _define(_opcode, "NOP", "imm", 2, 0, _immediate(lambda self, value: None))
for _opcode in (0x04, 0x44, 0x64):
    _define(_opcode, "NOP", "zpg", 3, 0, _read(_nop_read, 1, "ZeroPageAddr"))
for _opcode in (0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4):
    _define(_opcode, "NOP", "zpx", 4, 0, _read(_nop_read, 1, "ZeroPageXAddr"))
_define(0x0C, "NOP", "abs", 4, 0, _read(_nop_read, 2, "AbsoluteAddr"))
for _opcode in (0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC):
    _define(_opcode, "NOP", "abx", 4, 1, _read(_nop_read, 2, "AbsoluteXAddr"))

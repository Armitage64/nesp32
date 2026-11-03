"""Family BASIC on py65, joined by the serial line model to a nesp32, with
the test as the Bluetooth keyboard.

The console is nesp32's (its tests/console.py), with what more of the PPU
the game uses: it reads the nametable back through PPUDATA, as its screen
editor does. It is not held to what nesp32's own ROMs are (`strict`): the
game reads its controllers through a pointer, and writes the PPU when it
likes.
"""

import nesp
import nesp_proto as p
from console import PPUDATA, Console
from wire import link

import fbasic

PALETTE = 0x3F00
FRAME_MS = 1000 * 29780.5 / p.NESP_CPU_HZ
REPEAT_DELAY_MS = 500           # the firmware's (firmware/main/keyboard.c)
REPEAT_EVERY_MS = 40
FONT = {code: char for char, code in fbasic.CODES_NOT_ASCII.items()}
SCREEN_ROWS = 30


RAM = range(0x6000, 0x8000)
RAM_OFF = 0x10              # bit 4 of the PRG register (MMC1B), or of CHR0 (SNROM)


class Famicom(Console):
    """registers, if given, are the MMC1's at power-on (control, CHR0, CHR1,
    PRG), in place of the last 16 KB at $C000 and the rest 0. With
    ram_switch, bit 4 of the PRG register or of CHR0 turns the cartridge's
    memory off, as an MMC1B's and an SNROM board's do: writes do nothing,
    and reads give the bus's last byte, the address's high one."""

    def __init__(self, rom_path, labels_path, registers=None, ram_switch=False):
        super().__init__(rom_path, labels_path)
        if registers is not None:
            self.mapper = list(registers)
            self._map()
            self.mpu.pc = self.memory[0xFFFC] | self.memory[0xFFFD] << 8
        if ram_switch:
            self.memory.subscribe_to_write(RAM, self._write_ram)
            self.memory.subscribe_to_read(RAM, self._read_ram)
        self.strict = False
        self._read_buffer = 0
        self.memory.subscribe_to_read([PPUDATA], self._read_data)
        # The console's NMI is the game's handler, to its rti; fbkbd.s's
        # link comes after that, and ends with its own. Each frame's
        # link_cycles is how long that took, from the fetches of the two.
        self.link_started = None
        self.memory.subscribe_to_read([self.labels["fb_after_basic"]], self._link_start)
        self.memory.subscribe_to_read([self.labels["fb_nmi_done"]], self._link_end)

    def _link_start(self, address):
        if self.link_started is None:
            self.link_started = self.now
        return None

    def _link_end(self, address):
        if self.link_started is not None:
            self.frame.link_cycles = self.now - self.link_started
            self.link_started = None
        return None

    def _ram_off(self):
        return (self.mapper[1] | self.mapper[3]) & RAM_OFF

    def _write_ram(self, address, value):
        if self._ram_off():
            return self.memory._subject[address]
        return None

    def _read_ram(self, address):
        return address >> 8 if self._ram_off() else None

    def _read_data(self, address):
        # Below the palette a read gives what the last one fetched.
        where = self._mirror(self.v)
        value = self._read_buffer
        self._read_buffer = self.vram[where]
        if where >= PALETTE:
            value = self.vram[where]
        self.v = (self.v + (32 if self.ctrl & 0x04 else 1)) & 0x7FFF
        return value

    def text(self, row, column=0, length=32):
        """A row's tiles as text: the game's font has ASCII's capitals,
        digits and most signs at their own codes (fbasic.CODES_NOT_ASCII
        has the others), and the yen at the backslash's."""
        return "".join(FONT.get(tile, chr(tile) if 0x20 <= tile < 0x7F else " ")
                       for tile in self.tiles(row, column, length))


class Basic:
    """A console on the ROM, and a nesp32 with a keyboard connected unless
    attached says otherwise."""

    def __init__(self, rom_path, labels_path, attached=True, registers=None, ram_switch=False,
                 **port_options):
        self.c = Famicom(rom_path, labels_path, registers=registers, ram_switch=ram_switch)
        self.stick = self.port = None
        if attached:
            self.stick, self.port = link(self.c, nesp.Stick, **port_options)
            self.stick.kbd_paired(b"MX KEYS S")
            self.stick.kbd_state = p.NESP_KEYBOARD_CONNECTED

    def run(self, frames=1):
        self.c.run(frames)

    def run_until(self, condition, frames=600):
        return self.c.run_until(condition, frames)

    def type(self, text):
        """Type on the Bluetooth keyboard: bytes as KBD KEYS sends them."""
        if isinstance(text, str):
            text = text.encode()
        self.stick.kbd_type(text)
        self.waiting = getattr(self, "waiting", 0) + len(text)

    def typed_out(self, frames_each=8):
        """Run until the nesp32 has sent everything typed and the console
        has put it all through the matrix. Returns the frames it took."""
        frames = self.run_until(lambda: self.stick.kbd_unread == 0
                                and self.c.byte("fb_count") == 0
                                and self.c.byte("fb_phase") == 0,
                                frames=60 + frames_each * self.waiting)
        self.waiting = 0
        return frames

    def hold(self, key, ms, paced=True):
        """Hold a key down for this long, as the nesp32's firmware repeats
        it (firmware/main/keyboard.c): once at once, then after
        REPEAT_DELAY_MS and every REPEAT_EVERY_MS, each repeat kept only if
        everything typed before it has been taken (unless not paced, as
        the firmware was before)."""
        if isinstance(key, str):
            key = key.encode()
        self.stick.kbd_type(key)
        held = 0.0
        due = REPEAT_DELAY_MS
        while held < ms:
            self.run(1)
            held += FRAME_MS
            while due <= held:
                if not paced or self.stick.kbd_unread == 0:
                    self.stick.kbd_type(key)
                due += REPEAT_EVERY_MS

    def enter(self, line, frames=10):
        """Type a line and Enter, and let the game act on it."""
        self.type(line + "\n")
        self.typed_out()
        self.run(frames)

    def requests(self):
        """Every request the nesp32's UART heard, as (service, op, payload)."""
        heard = b"".join(self.port.received)
        out = []
        at = 0
        while at + p.NESP_OVERHEAD <= len(heard):
            total = p.NESP_OVERHEAD + heard[at + 4]
            frame = heard[at:at + total]
            if (heard[at] == p.NESP_REQUEST_MARKER and len(frame) == total
                    and nesp.checks(frame[1:-2]) == frame[-2:]):
                out.append((frame[1], frame[2], frame[5:-2]))
                at += total
            else:
                at += 1
        return out

    def screen(self):
        return self.c.screen()

    def rows(self):
        return [self.c.text(row).rstrip() for row in range(SCREEN_ROWS)]

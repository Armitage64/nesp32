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
FONT = {code: char for char, code in fbasic.CODES_NOT_ASCII.items()}
SCREEN_ROWS = 30


class Famicom(Console):
    def __init__(self, rom_path, labels_path):
        super().__init__(rom_path, labels_path)
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

    def __init__(self, rom_path, labels_path, attached=True, **port_options):
        self.c = Famicom(rom_path, labels_path)
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

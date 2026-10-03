"""Status screen on UIFlow's M5.Lcd.

Both Sticks have a 135x240 panel; rotation 1 makes it 240x135 landscape.
A refresh paints at most one row, so it takes a bounded time and fits in the
quiet gap after a burst. Rows repaint only when their text changed.
"""

import M5

BLACK = 0x000000
GREEN = 0x00FF40
AMBER = 0xFFB000
RED = 0xFF3030
GREY = 0x8C8C8C
WHITE = 0xFFFFFF

BRIGHTNESS = 96
WIDTH = 240
ROW_TOP = 22
ROW_HEIGHT = 16
VALUE_X = 52
MAX_VALUE_CHARS = 27
MAX_ERROR_CHARS = 34

HEADER = "header"
ROWS = ("track", "title", "time", "state", "link", "reply", "error")
LABELS = {"track": "TRACK", "title": "", "time": "TIME", "state": "STATE", "link": "LINK",
          "reply": "REPLY", "error": ""}


class StatusScreen:
    def __init__(self, version):
        self.lcd = M5.Lcd
        self.version = version
        self.fields = {name: "" for name in ROWS}
        self.board = ""
        self.battery = ""
        self.backlight = True
        self._dirty = [HEADER] + list(ROWS)
        self.lcd.setRotation(1)
        self.lcd.setBrightness(BRIGHTNESS)
        self.lcd.fillScreen(BLACK)

    def set(self, **fields):
        for key, value in fields.items():
            value = str(value)
            if key in ("board", "battery"):
                if getattr(self, key) != value:
                    setattr(self, key, value)
                    self._mark(HEADER)
            elif self.fields[key] != value:
                self.fields[key] = value
                self._mark(key)

    def _mark(self, name):
        if name not in self._dirty:
            self._dirty.append(name)

    def off(self):
        self.lcd.setBrightness(0)

    def refresh(self, everything=False):
        """Paint one changed row, or all of them. Returns True if more wait."""
        while self._dirty:
            name = self._dirty.pop(0)
            self.lcd.startWrite()
            try:
                if name == HEADER:
                    self._draw_header()
                else:
                    self._draw_row(name)
            finally:
                self.lcd.endWrite()
            if not everything:
                break
        return bool(self._dirty)

    def _draw_header(self):
        lcd = self.lcd
        lcd.fillRect(0, 0, WIDTH, ROW_TOP - 2, BLACK)
        lcd.setFont(lcd.FONTS.Montserrat14)
        lcd.setTextColor(GREEN, BLACK)
        lcd.drawString("NES JUKEBOX", 4, 2)
        lcd.setFont(lcd.FONTS.Montserrat12)
        lcd.setTextColor(GREY, BLACK)
        lcd.drawString(self.board, 112, 4)
        if self.battery:
            lcd.drawString(self.battery, WIDTH - lcd.textWidth(self.battery) - 4, 4)
        lcd.drawLine(0, ROW_TOP - 3, WIDTH - 1, ROW_TOP - 3, GREEN)

    def _draw_row(self, name):
        lcd = self.lcd
        y = ROW_TOP + ROWS.index(name) * ROW_HEIGHT
        lcd.fillRect(0, y, WIDTH, ROW_HEIGHT, BLACK)
        lcd.setFont(lcd.FONTS.Montserrat12)
        value = self.fields[name]
        label = LABELS[name]
        if not label:
            lcd.setTextColor(RED if name == "error" else WHITE, BLACK)
            lcd.drawString(value[:MAX_ERROR_CHARS], 4, y + 1)
            return
        lcd.setTextColor(GREY, BLACK)
        lcd.drawString(label, 4, y + 1)
        if name == "state":
            lcd.setTextColor(GREEN if value == "PLAYING" else AMBER, BLACK)
        else:
            lcd.setTextColor(WHITE, BLACK)
        lcd.drawString(value[:MAX_VALUE_CHARS], VALUE_X, y + 1)


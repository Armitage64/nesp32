"""NES Jukebox host for M5Stack Sticks on UIFlow 2.0 (MicroPython).

protocol.py and tracks.py are ports of host/protocol.py and host/playlist.py
and are tested byte for byte against them. player.py is the reply loop.
board.py, ui.py and device.py are the only modules that touch the hardware.
"""

VERSION = "0.1"

"""NESpedia's host side: fetch a Wikipedia article and serve it to a NES.

Everything but net.py, board.py, ui.py and device.py is plain Python: it runs
under pytest on a desktop and unchanged on the Stick's MicroPython.
"""

VERSION = "0.1"

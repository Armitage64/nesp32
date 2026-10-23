; What the faster ROM's code and the patches to the game's share.

MMC3_SELECT     = $8000         ; the register the next write to $8001 sets
MMC3_DATA       = $8001
MMC3_PRG_RAM    = $A001
MMC3_PRG_RAM_ON = $80           ; on, and writable
FAST_BANK       = $0E           ; fast/fast.s's own 8 KB bank
IMAGE_PAGES     = $10           ; of the PRG RAM, from $6000, that the reset fills

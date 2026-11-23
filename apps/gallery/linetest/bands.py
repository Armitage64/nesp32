"""Patch picture.c (in place) so each band of BAND_ROWS rows of squares
chooses its own four palettes. Revert with git checkout afterwards."""
import sys

p = sys.argv[1]
s = open(p).read()


def rep(a, b, count=1):
    global s
    assert s.count(a) >= count, a
    s = s.replace(a, b) if count == 0 else s.replace(a, b, count)


rep("#ifndef PASSES", "#ifndef BAND_ROWS\n#define BAND_ROWS 15\n#endif\n#define BANDS ((BLOCKS_Y + BAND_ROWS - 1) / BAND_ROWS)\n#ifndef PASSES")
rep("    int x0, y0, w, h;               /* where the image went */",
    "    int x0, y0, w, h;               /* where the image went */\n"
    "    size_t first, last;             /* the band's squares */\n"
    "    uint8_t band_palette[BANDS][PALETTES][3];")
# Every loop over the squares is over the band's.
rep("for (size_t square = 0; square < BLOCKS; square++) {",
    "for (size_t square = work->first; square < work->last; square++) {", 0)
rep("for (size_t square = 0; square < BLOCKS && total < now; square++) {",
    "for (size_t square = work->first; square < work->last && total < now; square++) {")
rep("size_t worst = 0;", "size_t worst = work->first;")
rep("            float n = work->count[square][c];", "            float n = work->count[square][c];")
# Palettes: one search per band.
rep("static void palettes(work_t *work)\n{", "static void palettes_band(work_t *work)\n{")
rep("""    /* The colours a palette may have: those nearest enough of the pixels. */""",
    """    }

static void palettes_rest(work_t *work)
{
    bins_t *bins0 = &work->gathered;
    (void)bins0;
    /* The colours a palette may have: those nearest enough of the pixels. */""")
rep("""    polish(work);
    assign(work);
}""", """    polish(work);
    assign(work);
}

static void palettes(work_t *work)
{
    work->first = 0;
    work->last = BLOCKS;
    palettes_band(work);
    for (size_t band = 0; band < BANDS; band++) {
        work->first = band * BAND_ROWS * BLOCKS_X;
        work->last = (band + 1) * BAND_ROWS * BLOCKS_X;
        if (work->last > BLOCKS) {
            work->last = BLOCKS;
        }
        palettes_rest(work);
        memcpy(work->band_palette[band], work->palette, sizeof(work->palette));
    }
    work->first = 0;
    work->last = BLOCKS;
}""")
rep("""            const uint8_t *palette = work->palette[work->square[(y / BLOCK) * BLOCKS_X + x / BLOCK]];
            uint8_t pick = 0;""",
    """            size_t sq = (size_t)(y / BLOCK) * BLOCKS_X + (size_t)(x / BLOCK);
            const uint8_t *palette = work->band_palette[sq / (BAND_ROWS * BLOCKS_X)][work->square[sq]];
            uint8_t pick = 0;""")
open(p, "w").write(s)

"""After bands.py: palettes by line (work->line_palette), used by the
dithering and the tile step (a tile's colours for each pair of its lines)."""
import sys

p = sys.argv[1]
s = open(p).read()


def rep(a, b, count=1):
    global s
    n = s.count(a)
    assert n >= 1 and (count == 0 or n >= count), (n, a)
    s = s.replace(a, b) if count == 0 else s.replace(a, b, count)


rep("    float colours[HALF_CELLS][4][3];    /* its first place's palette, weighed */",
    "    float colours[HALF_CELLS][4][4][3]; /* its first place's palettes, each 2 lines, weighed */")
rep("    uint8_t band_palette[BANDS][PALETTES][3];",
    "    uint8_t band_palette[BANDS][PALETTES][3];\n    uint8_t line_palette[HEIGHT][PALETTES][3];")

# tile_look: colours by the 2 x 2's row.
rep("""static void tile_look(const half_t *half, uint16_t tile, float (*colours)[3], float (*out)[3])
{
    for (size_t square = 0; square < 16; square++) {
        const uint8_t *share = half->share[tile][square];""",
    """static void tile_look(const half_t *half, uint16_t tile, float (*rows)[4][3], float (*out)[3])
{
    for (size_t square = 0; square < 16; square++) {
        const uint8_t *share = half->share[tile][square];
        float (*colours)[3] = rows[square / 4];""")

# find_nearest: far by row.
rep("""    float far[16][MIXES];
    for (size_t each = 0; each < MIXES; each++) {
        float mixed[3];
        for (size_t axis = 0; axis < 3; axis++) {
            mixed[axis] = (mixes[each][0] * half->colours[tile][0][axis]
                           + mixes[each][1] * half->colours[tile][1][axis]
                           + mixes[each][2] * half->colours[tile][2][axis]
                           + mixes[each][3] * half->colours[tile][3][axis]) * 0.25f;
        }
        for (size_t square = 0; square < 16; square++) {
            far[square][each] = sqrtf(squared(half->seen[tile][square], mixed));
        }
    }""", """    float far[16][MIXES];
    for (size_t each = 0; each < MIXES; each++) {
        for (size_t square = 0; square < 16; square++) {
            float (*c)[3] = half->colours[tile][square / 4];
            float mixed[3];
            for (size_t axis = 0; axis < 3; axis++) {
                mixed[axis] = (mixes[each][0] * c[0][axis] + mixes[each][1] * c[1][axis]
                               + mixes[each][2] * c[2][axis] + mixes[each][3] * c[3][axis]) * 0.25f;
            }
            far[square][each] = sqrtf(squared(half->seen[tile][square], mixed));
        }
    }""")

# cell_palette -> cell_colours.
rep("""static const uint8_t *cell_palette(const work_t *work, size_t cell)
{
    size_t top = cell / COLUMNS * 8;
    size_t left = cell % COLUMNS * 8;
    return work->palette[work->square[(top / BLOCK) * BLOCKS_X + left / BLOCK]];
}""", """/* A place's colours for each pair of its lines: the two lines' averaged. */
static void cell_colours(const work_t *work, size_t cell, float (*out)[4][3])
{
    size_t top = cell / COLUMNS * 8;
    size_t left = cell % COLUMNS * 8;
    uint8_t p = work->square[(top / BLOCK) * BLOCKS_X + left / BLOCK];
    for (size_t row = 0; row < 4; row++) {
        float a[4][3], b[4][3];
        palette_colours(work->line_palette[top + 2 * row][p], a);
        palette_colours(work->line_palette[top + 2 * row + 1][p], b);
        for (size_t i = 0; i < 4; i++) {
            for (size_t axis = 0; axis < 3; axis++) {
                out[row][i][axis] = (a[i][axis] + b[i][axis]) * 0.5f;
            }
        }
    }
}""")

rep("""static void set_tile(half_t *half, uint16_t tile, const uint8_t *planes, const uint8_t *palette)
{""", """static void set_tile(const work_t *work, half_t *half, uint16_t tile, size_t cell)
{
    const uint8_t *planes = work->cell_pattern[cell];""")
rep("""    palette_colours(palette, half->colours[tile]);
    tile_look(""", """    cell_colours(work, cell, half->colours[tile]);
    tile_look(""")
rep("set_tile(half, tile, planes, cell_palette(work, cell));", "set_tile(work, half, tile, cell);")
rep("set_tile(half, tile, work->cell_pattern[cell], cell_palette(work, cell));", "set_tile(work, half, tile, cell);")

# refit: by row.
rep("""            float colours[4][3];
            palette_colours(cell_palette(work, cell), colours);
            float far[16][MIXES];
            for (size_t each = 0; each < MIXES; each++) {
                float mixed[3];
                for (size_t axis = 0; axis < 3; axis++) {
                    mixed[axis] = (mixes[each][0] * colours[0][axis]
                                   + mixes[each][1] * colours[1][axis]
                                   + mixes[each][2] * colours[2][axis]
                                   + mixes[each][3] * colours[3][axis]) * 0.25f;
                }
                for (size_t square = 0; square < 16; square++) {
                    far[square][each] = sqrtf(squared(image[square], mixed));
                }
            }""", """            float rows[4][4][3];
            cell_colours(work, cell, rows);
            float far[16][MIXES];
            for (size_t each = 0; each < MIXES; each++) {
                for (size_t square = 0; square < 16; square++) {
                    float (*colours)[3] = rows[square / 4];
                    float mixed[3];
                    for (size_t axis = 0; axis < 3; axis++) {
                        mixed[axis] = (mixes[each][0] * colours[0][axis]
                                       + mixes[each][1] * colours[1][axis]
                                       + mixes[each][2] * colours[2][axis]
                                       + mixes[each][3] * colours[3][axis]) * 0.25f;
                    }
                    far[square][each] = sqrtf(squared(image[square], mixed));
                }
            }""")

# dither by line.
rep("const uint8_t *palette = work->band_palette[sq / (BAND_ROWS * BLOCKS_X)][work->square[sq]];",
    "const uint8_t *palette = work->line_palette[y][work->square[sq]];")

# palettes: each line's from its band.
rep("""        memcpy(work->band_palette[band], work->palette, sizeof(work->palette));
    }""", """        memcpy(work->band_palette[band], work->palette, sizeof(work->palette));
    }
    for (int y = 0; y < HEIGHT; y++) {
        memcpy(work->line_palette[y], work->band_palette[(y / BLOCK) / BAND_ROWS], sizeof(work->palette));
    }""")
open(p, "w").write(s)

/* A picture for the console: an image made into what the NES can show of
 * it, laid out as COMMONS's DATA serves it (docs/PROTOCOL.md).
 *
 * The NES shows a screen of 32 x 30 tiles from a table of 256, and has two
 * tables. The top 15 rows of tiles here are drawn from the first table and
 * the bottom 15 from the second: the ROM changes table between them, in the
 * hblank of the line above the bottom half, where sprite 0's hit says it
 * has got to. So a picture has 511 tiles of its own, the 512th being the
 * sprite's, and the 960 places on the screen share them.
 *
 * Its colours: black behind everything, and in each square of 16 x 16
 * pixels three more, one of four palettes of three. Colours are compared as
 * luma and colour difference (YCbCr), the colour counting twice. The
 * palettes are chosen for the picture: k-means over the squares, each
 * palette's colours by coordinate descent over the NES colours nearest its
 * squares' pixels, counting what dithering can mix of two colours; then
 * each colour of each palette tried as every other against the whole
 * picture. The picture is dithered (seven eighths of Floyd-Steinberg) with
 * each square's four.
 *
 * Where a half has more different tiles than it has room for, the tile
 * that costs least to lose (the fewest places, times how far it is from
 * the nearest other) goes to that other, until they fit. Tiles are
 * compared by the average colour of each 2 x 2 of their pixels, which is
 * what the eye sees of dithering. Then every place takes, of the tiles
 * left, the one nearest its part of the image, and a tile no place takes
 * goes to the place served worst.
 *
 * tools/picture.py in apps/gallery shows what this makes of a photograph.
 * The figures below were chosen on twelve photographs from Commons, by how
 * far the picture, a little blurred, is from the image.
 *
 * Sprite 0 is one pixel, behind the background and the backdrop's colour,
 * so it is never seen. It sits on the last line of the top half, over a
 * pixel of the background that is not black (a hit needs one), as far
 * along the line as leaves the ROM's write in the hblank; the ROM's delay
 * from the hit to the write is worked out here for where it is. A picture
 * with no such pixel there is given one, in a tile of its own.
 *
 * The image is fitted in, whole, below the top 8 lines and above the
 * bottom 8, which a television hides; the NES's pixels are 8/7 as wide as
 * they are high. What is round it is black.
 */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "nesp_services.h"

#define WIDTH 256
#define HEIGHT 240
#define TOP 8                       /* the first line a picture may use */
#define TALL 224                    /* and how many it may */
#define COLUMNS 32
#define ROWS 30
#define CELLS (COLUMNS * ROWS)
#define HALF_CELLS (CELLS / 2)
#define BLOCK 16                    /* pixels on a side of a palette's square */
#define BLOCKS_X (WIDTH / BLOCK)
#define BLOCKS_Y (HEIGHT / BLOCK)
#define BLOCKS (BLOCKS_X * BLOCKS_Y)
#ifndef PALETTES
#define PALETTES 4
#endif
#define CHOICES 54                  /* the NES colours a pixel may be */
#define BLACK 0x0F                  /* the backdrop: choice 0 */
#define SPRITE_TILE 0xFF            /* of the first table: sprite 0's */
#define SPARE_TILE 0xFE             /* and the one given a pixel to hit, when one is needed */
#define SPLIT_LINE (8 * NESP_COMMONS_SPLIT_ROW - 1)     /* the top half's last line */
#define SPRITE_BEHIND 0x20          /* OAM: behind the background */
#ifndef CANDIDATE_PIXELS
#define CANDIDATE_PIXELS 12.0f      /* a colour nearest fewer pixels is in no palette */
#endif
#ifndef PASSES
#define PASSES 6                    /* of k-means over the squares */
#endif
#ifndef CHROMA
#define CHROMA 2.0f                 /* how much a difference of colour counts against one of luma */
#endif
#ifndef POLISH
#define POLISH 2                    /* passes over every palette colour, for the whole picture */
#endif
#ifndef REFITS
#define REFITS 3                    /* rounds of places choosing their tiles again */
#endif
#ifndef DIFFUSE
#define DIFFUSE 56                  /* of the error dithering passes on, in 64ths */
#endif
#ifndef NOISE
#define NOISE 0.1f                  /* what a dithered mixture costs, for how far apart its two are */
#endif

/* Where the ROM's write to PPUCTRL lands, in dots from the start of the
 * hit's line, for sprite 0 at x: the hit two dots after its pixel, then 15
 * cycles to the write with no delay and 13 + 5 a loop with some
 * (nes/viewer.inc in apps/gallery), at 3 dots a cycle, and up to 11 cycles
 * more for the look that sees it. It must be after dot 240, where the last
 * tile of the line has been fetched, and before 321, where the next line's
 * first is; so the earliest is aimed at from 243 and the latest is 33
 * dots after. */
#define HIT_DOT 2
#define LAND_FIRST 243
#define LAND_LAST 275               /* the earliest landing; 33 dots of looks after it */
#define HIT_X_MAX (LAND_LAST - HIT_DOT - 45)    /* 228: no delay at all */
#define HIT_X_SPARE 216             /* the spare tile's pixel, when one is needed */

/* The NES's 64 colours as a 2C02 shows them. */
static const uint8_t nes_rgb[64][3] = {
    {84, 84, 84}, {0, 30, 116}, {8, 16, 144}, {48, 0, 136}, {68, 0, 100}, {92, 0, 48},
    {84, 4, 0}, {60, 24, 0}, {32, 42, 0}, {8, 58, 0}, {0, 64, 0}, {0, 60, 0}, {0, 50, 60},
    {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
    {152, 150, 152}, {8, 76, 196}, {48, 50, 236}, {92, 30, 228}, {136, 20, 176},
    {160, 20, 100}, {152, 34, 32}, {120, 60, 0}, {84, 90, 0}, {40, 114, 0}, {8, 124, 0},
    {0, 118, 40}, {0, 102, 120}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
    {236, 238, 236}, {76, 154, 236}, {120, 124, 236}, {176, 98, 236}, {228, 84, 236},
    {236, 88, 180}, {236, 106, 100}, {212, 136, 32}, {160, 170, 0}, {116, 196, 0},
    {76, 208, 32}, {56, 204, 108}, {56, 180, 204}, {60, 60, 60}, {0, 0, 0}, {0, 0, 0},
    {236, 238, 236}, {168, 204, 236}, {188, 188, 236}, {212, 178, 236}, {236, 174, 236},
    {236, 174, 212}, {236, 180, 176}, {228, 196, 144}, {204, 210, 120}, {180, 222, 120},
    {168, 226, 144}, {152, 226, 180}, {160, 214, 228}, {160, 162, 160}, {0, 0, 0}, {0, 0, 0},
};

/* One half's tiles while they are cut down to the room there is. */
typedef struct {
    uint16_t count;                 /* different tiles */
    uint16_t active;                /* of them not yet merged into another */
    uint8_t pattern[HALF_CELLS][16];
    uint8_t share[HALF_CELLS][16][4];   /* each 2 x 2 of it: how many of each colour */
    uint8_t mix[HALF_CELLS][16];        /* and which of the MIXES that is */
    float colours[HALF_CELLS][4][3];    /* its first place's palette, weighed */
    float seen[HALF_CELLS][16][3];      /* its 2 x 2s' averages, in that palette */
    uint16_t uses[HALF_CELLS];
    uint16_t nearest[HALF_CELLS];
    float distance[HALF_CELLS];
    float error[HALF_CELLS];            /* each place's, from the image, by refit */
    bool gone[HALF_CELLS];
    uint16_t of_cell[HALF_CELLS];   /* each place's tile, as counted here */
    uint8_t number[HALF_CELLS];     /* each tile's in the pattern table */
} half_t;

/* Pixels counted by the NES colour each is nearest: the colours with any,
 * how many, and the average of them. */
typedef struct {
    uint8_t used;
    uint8_t choice[CHOICES];
    float count[CHOICES];
    float point[CHOICES][3];
} bins_t;

typedef struct {
    int16_t rgb[HEIGHT][WIDTH][3];  /* the image, and then the error dithering carries */
    uint8_t source[HEIGHT][WIDTH][3];   /* the image */
    uint8_t color[HEIGHT][WIDTH];   /* 0 to 3, dithered */
    bins_t bins[BLOCKS];            /* each square's */
    bins_t gathered;
    uint8_t candidate[CHOICES];     /* the colours a palette may have */
    size_t candidates;
    float cost[BLOCKS][PALETTES];   /* what each square loses to each palette */
    uint8_t palette[PALETTES][3];   /* choices */
    uint8_t square[BLOCKS];         /* each square's palette */
    uint8_t cell_pattern[CELLS][16];
    union {                         /* the palettes' counts, then the tiles */
        struct {
            float count[BLOCKS][CHOICES];
            float sum[BLOCKS][CHOICES][3];
        };
        half_t halves[2];
    };
    int x0, y0, w, h;               /* where the image went */
} work_t;

static uint8_t choices[CHOICES];    /* NES colours */

/* Colours are compared as luma and two differences of colour (YCbCr), the
 * luma counting twice: a space in which plain distance is near enough to
 * how far apart two colours look, and in which, being a linear one, a
 * mixture of two colours (dithering's) lies between them. */
static void weigh_rgb(float r, float g, float b, float *out)
{
    out[0] = 0.299f * r + 0.587f * g + 0.114f * b;
    out[1] = CHROMA * (-0.168736f * r - 0.331264f * g + 0.5f * b);
    out[2] = CHROMA * (0.5f * r - 0.418688f * g - 0.081312f * b);
}

static float rgb_distance(int r1, int g1, int b1, int r2, int g2, int b2)
{
    float d[3];
    weigh_rgb((float)(r1 - r2), (float)(g1 - g2), (float)(b1 - b2), d);
    return d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
}

static void make_choices(void)
{
    if (choices[0] == BLACK) {
        return;
    }
    size_t count = 0;
    choices[count++] = BLACK;
    for (uint8_t row = 0; row < 4; row++) {
        for (uint8_t hue = 0; hue <= 0x0C; hue++) {
            uint8_t code = (uint8_t)(row << 4 | hue);
            if (code != 0x20) {     /* the same white as $30 */
                choices[count++] = code;
            }
        }
    }
    choices[count++] = 0x2D;
    choices[count++] = 0x3D;
}

static float to_choice(int r, int g, int b, uint8_t choice)
{
    const uint8_t *c = nes_rgb[choices[choice]];
    return rgb_distance(r, g, b, c[0], c[1], c[2]);
}

/* --- the image into its place ------------------------------------------------ */

static void fit(work_t *work, uint32_t width, uint32_t height)
{
    double aspect = (double)width / (double)height;
    double h = TALL;
    double w = h * aspect * 7.0 / 8.0;
    if (w > WIDTH) {
        w = WIDTH;
        h = WIDTH * 8.0 / (7.0 * aspect);
    }
    work->w = (int)(w + 0.5);
    work->h = (int)(h + 0.5);
    if (work->w < 1) {
        work->w = 1;
    }
    if (work->h < 1) {
        work->h = 1;
    }
    if (work->h > TALL) {
        work->h = TALL;
    }
    work->x0 = (WIDTH - work->w) / 2;
    work->y0 = TOP + (TALL - work->h) / 2;
}

static bool inside(const work_t *work, int x, int y)
{
    return x >= work->x0 && x < work->x0 + work->w && y >= work->y0 && y < work->y0 + work->h;
}

/* Each pixel of the picture the average of the image's under it. */
static void resample(work_t *work, const uint8_t *rgb, uint32_t width, uint32_t height)
{
    memset(work->rgb, 0, sizeof(work->rgb));
    double sx = (double)width / work->w;
    double sy = (double)height / work->h;
    for (int y = 0; y < work->h; y++) {
        double top = y * sy;
        double bottom = (y + 1) * sy;
        for (int x = 0; x < work->w; x++) {
            double left = x * sx;
            double right = (x + 1) * sx;
            double sum[3] = {0, 0, 0};
            double weight = 0;
            for (uint32_t v = (uint32_t)top; v < height && v < bottom; v++) {
                double wy = (v + 1 < bottom ? v + 1 : bottom) - (v > top ? v : top);
                for (uint32_t u = (uint32_t)left; u < width && u < right; u++) {
                    double wx = (u + 1 < right ? u + 1 : right) - (u > left ? u : left);
                    const uint8_t *pixel = rgb + 3 * ((size_t)v * width + u);
                    double each = wx * wy;
                    sum[0] += pixel[0] * each;
                    sum[1] += pixel[1] * each;
                    sum[2] += pixel[2] * each;
                    weight += each;
                }
            }
            int16_t *out = work->rgb[work->y0 + y][work->x0 + x];
            for (int channel = 0; channel < 3; channel++) {
                out[channel] = (int16_t)(weight > 0 ? sum[channel] / weight + 0.5 : 0);
            }
        }
    }
}

/* --- the palettes ------------------------------------------------------------ */

/* A square's pixels are counted by the NES colour each is nearest, and
 * each count keeps the average of its pixels (in weigh_rgb's space), so
 * that what a palette loses of them can be worked out from a few dozen
 * numbers. */
static void weigh(const int16_t *rgb, float *out)
{
    weigh_rgb(rgb[0], rgb[1], rgb[2], out);
}

static void weigh_code(uint8_t code, float *out)
{
    const int16_t rgb[3] = {nes_rgb[code][0], nes_rgb[code][1], nes_rgb[code][2]};
    weigh(rgb, out);
}

static float squared(const float *a, const float *b)
{
    float d0 = a[0] - b[0];
    float d1 = a[1] - b[1];
    float d2 = a[2] - b[2];
    return d0 * d0 + d1 * d1 + d2 * d2;
}

/* What a colour loses to a palette: the nearest of its four colours, or of
 * the mixtures of two that dithering makes, a mixture costing more the
 * further apart its two are (it is seen as noise). */
static float colour_loss(const float *point, float (*colours)[3])
{
    float best = squared(point, colours[0]);
    for (size_t a = 1; a < 4; a++) {
        float d = squared(point, colours[a]);
        if (d < best) {
            best = d;
        }
    }
    for (size_t a = 0; a < 4; a++) {
        for (size_t b = a + 1; b < 4; b++) {
            float span[3] = {colours[b][0] - colours[a][0], colours[b][1] - colours[a][1],
                             colours[b][2] - colours[a][2]};
            float length = span[0] * span[0] + span[1] * span[1] + span[2] * span[2];
            if (length <= 0.0f) {
                continue;
            }
            float t = ((point[0] - colours[a][0]) * span[0] + (point[1] - colours[a][1]) * span[1]
                       + (point[2] - colours[a][2]) * span[2]) / length;
            if (t <= 0.0f || t >= 1.0f) {
                continue;
            }
            float mix[3] = {colours[a][0] + t * span[0], colours[a][1] + t * span[1],
                            colours[a][2] + t * span[2]};
            float d = squared(point, mix) + NOISE * t * (1.0f - t) * length;
            if (d < best) {
                best = d;
            }
        }
    }
    return best;
}

static void palette_colours(const uint8_t *palette, float (*colours)[3])
{
    weigh_code(BLACK, colours[0]);
    for (size_t slot = 0; slot < 3; slot++) {
        weigh_code(choices[palette[slot]], colours[slot + 1]);
    }
}

/* What a set of counts loses to a palette. */
static float loss(const bins_t *bins, const uint8_t *palette)
{
    float colours[4][3];
    palette_colours(palette, colours);
    float sum = 0.0f;
    for (size_t index = 0; index < bins->used; index++) {
        sum += bins->count[index] * colour_loss(bins->point[index], colours);
    }
    return sum;
}

/* The palette that loses least of a set of counts, from the one given, a
 * colour at a time. */
static void best_palette(const work_t *work, const bins_t *bins, uint8_t *palette)
{
    float current = loss(bins, palette);
    for (int pass = 0; pass < 4; pass++) {
        bool changed = false;
        for (size_t slot = 0; slot < 3; slot++) {
            uint8_t kept = palette[slot];
            for (size_t each = 0; each < work->candidates; each++) {
                uint8_t c = work->candidate[each];
                if (c == kept || c == palette[(slot + 1) % 3] || c == palette[(slot + 2) % 3]) {
                    continue;
                }
                palette[slot] = c;
                float tried = loss(bins, palette);
                if (tried < current) {
                    current = tried;
                    kept = c;
                    changed = true;
                }
            }
            palette[slot] = kept;
        }
        if (!changed) {
            break;
        }
    }
}

/* A palette to begin from: the commonest colours of the counts but black,
 * or greys where there are fewer than three. */
static void seed_palette(const bins_t *bins, uint8_t *palette)
{
    static const uint8_t greys[3] = {1, 14, 39};    /* $00, $10, $30 as choices */
    for (size_t slot = 0; slot < 3; slot++) {
        float most = 0.0f;
        uint8_t pick = 0;
        for (size_t index = 0; index < bins->used; index++) {
            uint8_t c = bins->choice[index];
            bool taken = c == 0;
            for (size_t other = 0; other < slot; other++) {
                taken = taken || palette[other] == c;
            }
            if (!taken && bins->count[index] > most) {
                most = bins->count[index];
                pick = c;
            }
        }
        for (size_t grey = 0; grey < 3 && pick == 0; grey++) {
            bool taken = false;
            for (size_t other = 0; other < slot; other++) {
                taken = taken || palette[other] == greys[grey];
            }
            if (!taken) {
                pick = greys[grey];
            }
        }
        palette[slot] = pick;
    }
}

/* Counts added together: one square's if `only` is one, else those of the
 * squares with palette p, or all of them if p is PALETTES. */
static void gather_bins(const work_t *work, uint8_t p, size_t only, bins_t *out)
{
    float count[CHOICES] = {0};
    float sum[CHOICES][3] = {{0}};
    for (size_t square = 0; square < BLOCKS; square++) {
        if (only < BLOCKS ? square != only : p < PALETTES && work->square[square] != p) {
            continue;
        }
        const bins_t *bins = &work->bins[square];
        for (size_t index = 0; index < bins->used; index++) {
            uint8_t c = bins->choice[index];
            count[c] += bins->count[index];
            for (size_t axis = 0; axis < 3; axis++) {
                sum[c][axis] += bins->count[index] * bins->point[index][axis];
            }
        }
    }
    out->used = 0;
    for (uint8_t c = 0; c < CHOICES; c++) {
        if (count[c] > 0.0f) {
            out->choice[out->used] = c;
            out->count[out->used] = count[c];
            for (size_t axis = 0; axis < 3; axis++) {
                out->point[out->used][axis] = sum[c][axis] / count[c];
            }
            out->used++;
        }
    }
}

/* Each square the palette that loses it least. */
static void assign(work_t *work)
{
    for (size_t square = 0; square < BLOCKS; square++) {
        float best = -1.0f;
        for (uint8_t p = 0; p < PALETTES; p++) {
            float each = loss(&work->bins[square], work->palette[p]);
            if (best < 0.0f || each < best) {
                best = each;
                work->square[square] = p;
            }
        }
    }
}

/* The square worst served by the first `palettes` palettes. */
static size_t worst_square(const work_t *work, uint8_t palettes)
{
    size_t worst = 0;
    float most = -1.0f;
    for (size_t square = 0; square < BLOCKS; square++) {
        float best = -1.0f;
        for (uint8_t p = 0; p < palettes; p++) {
            float each = loss(&work->bins[square], work->palette[p]);
            if (best < 0.0f || each < best) {
                best = each;
            }
        }
        if (best > most) {
            most = best;
            worst = square;
        }
    }
    return worst;
}

/* K-means stops where no square would rather another palette, which can
 * leave two palettes alike and a part of the picture with none for it.
 * Here each colour of each palette is tried as every other, and kept if
 * the whole picture, every square taking the palette it would, loses
 * less. */
static void polish(work_t *work)
{
    float (*cost)[PALETTES] = work->cost;
    for (size_t square = 0; square < BLOCKS; square++) {
        for (uint8_t p = 0; p < PALETTES; p++) {
            cost[square][p] = loss(&work->bins[square], work->palette[p]);
        }
    }
    for (int pass = 0; pass < POLISH; pass++) {
        bool changed = false;
        for (uint8_t p = 0; p < PALETTES; p++) {
            /* What every square loses to the other palettes. */
            float others[BLOCKS];
            float now = 0.0f;
            for (size_t square = 0; square < BLOCKS; square++) {
                float best = -1.0f;
                for (uint8_t q = 0; q < PALETTES; q++) {
                    if (q != p && (best < 0.0f || cost[square][q] < best)) {
                        best = cost[square][q];
                    }
                }
                others[square] = best;
                now += cost[square][p] < best ? cost[square][p] : best;
            }
            for (size_t slot = 0; slot < 3; slot++) {
                uint8_t *palette = work->palette[p];
                uint8_t kept = palette[slot];
                for (size_t each = 0; each < work->candidates; each++) {
                    uint8_t c = work->candidate[each];
                    if (c == kept || c == palette[(slot + 1) % 3] || c == palette[(slot + 2) % 3]) {
                        continue;
                    }
                    palette[slot] = c;
                    float total = 0.0f;
                    for (size_t square = 0; square < BLOCKS && total < now; square++) {
                        float mine = work->bins[square].used == 1
                                     && work->bins[square].choice[0] == 0
                                     ? 0.0f : loss(&work->bins[square], palette);
                        total += mine < others[square] ? mine : others[square];
                    }
                    if (total < now) {
                        now = total;
                        kept = c;
                        changed = true;
                    }
                }
                palette[slot] = kept;
            }
            for (size_t square = 0; square < BLOCKS; square++) {
                cost[square][p] = loss(&work->bins[square], work->palette[p]);
            }
        }
        if (!changed) {
            break;
        }
    }
}

static void palettes(work_t *work)
{
    /* Each square's pixels counted by their nearest colour. */
    memset(work->count, 0, sizeof(work->count));
    memset(work->sum, 0, sizeof(work->sum));
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            const int16_t *p = work->rgb[y][x];
            uint8_t best = 0;
            float least = to_choice(p[0], p[1], p[2], 0);
            for (uint8_t c = 1; c < CHOICES && least > 0.0f; c++) {
                float d = to_choice(p[0], p[1], p[2], c);
                if (d < least) {
                    least = d;
                    best = c;
                }
            }
            size_t square = (size_t)(y / BLOCK) * BLOCKS_X + (size_t)(x / BLOCK);
            float point[3];
            weigh(p, point);
            work->count[square][best] += 1.0f;
            for (size_t axis = 0; axis < 3; axis++) {
                work->sum[square][best][axis] += point[axis];
            }
        }
    }
    for (size_t square = 0; square < BLOCKS; square++) {
        bins_t *bins = &work->bins[square];
        bins->used = 0;
        for (uint8_t c = 0; c < CHOICES; c++) {
            float n = work->count[square][c];
            if (n > 0.0f) {
                bins->choice[bins->used] = c;
                bins->count[bins->used] = n;
                for (size_t axis = 0; axis < 3; axis++) {
                    bins->point[bins->used][axis] = work->sum[square][c][axis] / n;
                }
                bins->used++;
            }
        }
    }

    /* The colours a palette may have: those nearest enough of the pixels. */
    work->candidates = 0;
    for (uint8_t c = 1; c < CHOICES; c++) {
        float total = 0.0f;
        for (size_t square = 0; square < BLOCKS; square++) {
            total += work->count[square][c];
        }
        if (total >= CANDIDATE_PIXELS) {
            work->candidate[work->candidates++] = c;
        }
    }

    /* The first palette for the whole picture; each next one for the square
     * the palettes so far serve worst. */
    bins_t *bins = &work->gathered;
    gather_bins(work, PALETTES, BLOCKS, bins);
    seed_palette(bins, work->palette[0]);
    best_palette(work, bins, work->palette[0]);
    for (uint8_t p = 1; p < PALETTES; p++) {
        gather_bins(work, PALETTES, worst_square(work, p), bins);
        seed_palette(bins, work->palette[p]);
        best_palette(work, bins, work->palette[p]);
    }
    for (int pass = 0; pass < PASSES; pass++) {
        assign(work);
        for (uint8_t p = 0; p < PALETTES; p++) {
            gather_bins(work, p, BLOCKS, bins);
            if (bins->used == 0) {  /* none chose it: start it again where it is needed most */
                gather_bins(work, PALETTES, worst_square(work, PALETTES), bins);
                seed_palette(bins, work->palette[p]);
            }
            best_palette(work, bins, work->palette[p]);
        }
    }
    polish(work);
    assign(work);
}

/* --- the pixels -------------------------------------------------------------- */

static void spread(work_t *work, int x, int y, const int *error, int share)
{
    if (x < 0 || x >= WIDTH || y >= HEIGHT || !inside(work, x, y)) {
        return;
    }
    int16_t *p = work->rgb[y][x];
    for (int channel = 0; channel < 3; channel++) {
        int value = p[channel] + error[channel] * share / 64;
        p[channel] = (int16_t)(value < -96 ? -96 : value > 352 ? 352 : value);
    }
}

/* Each pixel one of its square's four colours, the error passed on (by
 * seven eighths of Floyd-Steinberg's, serpentine). */
static void dither(work_t *work)
{
    memset(work->color, 0, sizeof(work->color));
    for (int y = work->y0; y < work->y0 + work->h; y++) {
        bool back = (y & 1) != 0;
        int step = back ? -1 : 1;
        for (int i = 0; i < work->w; i++) {
            int x = back ? work->x0 + work->w - 1 - i : work->x0 + i;
            int16_t *p = work->rgb[y][x];
            int r = p[0] < 0 ? 0 : p[0] > 255 ? 255 : p[0];
            int g = p[1] < 0 ? 0 : p[1] > 255 ? 255 : p[1];
            int b = p[2] < 0 ? 0 : p[2] > 255 ? 255 : p[2];
            const uint8_t *palette = work->palette[work->square[(y / BLOCK) * BLOCKS_X + x / BLOCK]];
            uint8_t pick = 0;
            float least = to_choice(r, g, b, 0);
            for (uint8_t slot = 0; slot < 3; slot++) {
                float d = to_choice(r, g, b, palette[slot]);
                if (d < least) {
                    least = d;
                    pick = (uint8_t)(slot + 1);
                }
            }
            work->color[y][x] = pick;
            const uint8_t *chosen = nes_rgb[choices[pick == 0 ? 0 : palette[pick - 1]]];
            int error[3] = {p[0] - chosen[0], p[1] - chosen[1], p[2] - chosen[2]};
            /* 7, 3, 5 and 1 sixteenths, of DIFFUSE 64ths. */
            spread(work, x + step, y, error, 7 * DIFFUSE / 16);
            spread(work, x - step, y + 1, error, 3 * DIFFUSE / 16);
            spread(work, x, y + 1, error, 5 * DIFFUSE / 16);
            spread(work, x + step, y + 1, error, DIFFUSE / 16);
        }
    }
}

static void patterns(work_t *work)
{
    for (size_t cell = 0; cell < CELLS; cell++) {
        int top = (int)(cell / COLUMNS) * 8;
        int left = (int)(cell % COLUMNS) * 8;
        uint8_t *planes = work->cell_pattern[cell];
        memset(planes, 0, 16);
        for (int y = 0; y < 8; y++) {
            for (int x = 0; x < 8; x++) {
                uint8_t color = work->color[top + y][left + x];
                planes[y] = (uint8_t)(planes[y] | (color & 1) << (7 - x));
                planes[8 + y] = (uint8_t)(planes[8 + y] | (color >> 1) << (7 - x));
            }
        }
    }
}

static uint8_t pattern_pixel(const uint8_t *planes, int x, int y)
{
    return (uint8_t)(((planes[y] >> (7 - x)) & 1) | ((planes[8 + y] >> (7 - x)) & 1) << 1);
}

/* --- the tiles --------------------------------------------------------------- */

/* Tiles are compared as the eye sees them from a little way off: by the
 * average colour of each 2 x 2 of their pixels, in weigh_rgb's space. So a
 * tile dithered between two colours is near a tile of the colour between,
 * and near another dithered the other way, where pixel by pixel they would
 * be far apart. */

/* The ways four pixels can share four colours: 35 of them. mixes has how
 * many of each colour each has, and mix_of which it is, by the first three
 * counts as a number in base 5. */
#define MIXES 35
static uint8_t mixes[MIXES][4];
static uint8_t mix_of[125];

static void make_mixes(void)
{
    uint8_t count = 0;
    for (uint8_t a = 0; a <= 4; a++) {
        for (uint8_t b = 0; a + b <= 4; b++) {
            for (uint8_t c = 0; a + b + c <= 4; c++) {
                mixes[count][0] = a;
                mixes[count][1] = b;
                mixes[count][2] = c;
                mixes[count][3] = (uint8_t)(4 - a - b - c);
                mix_of[(a * 5 + b) * 5 + c] = count++;
            }
        }
    }
}

/* A tile's 2 x 2 squares' averages, with its colours (0 to 3) as these. */
static void tile_look(const half_t *half, uint16_t tile, float (*colours)[3], float (*out)[3])
{
    for (size_t square = 0; square < 16; square++) {
        const uint8_t *share = half->share[tile][square];
        for (size_t axis = 0; axis < 3; axis++) {
            out[square][axis] = (share[0] * colours[0][axis] + share[1] * colours[1][axis]
                                 + share[2] * colours[2][axis] + share[3] * colours[3][axis])
                                * 0.25f;
        }
    }
}

static void find_nearest(half_t *half, uint16_t tile)
{
    /* How far each of the tile's 2 x 2s is from each mix of its colours:
     * then another tile's distance, in the tile's palette, is 16 of these. */
    float far[16][MIXES];
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
    }
    half->distance[tile] = 3.4e38f;
    half->nearest[tile] = tile;
    for (uint16_t other = 0; other < half->count; other++) {
        if (other == tile || half->gone[other]) {
            continue;
        }
        const uint8_t *mix = half->mix[other];
        float d = 0.0f;
        for (size_t square = 0; square < 16 && d < half->distance[tile]; square++) {
            d += far[square][mix[square]];
        }
        if (d < half->distance[tile]) {
            half->distance[tile] = d;
            half->nearest[tile] = other;
        }
    }
}

static const uint8_t *cell_palette(const work_t *work, size_t cell)
{
    size_t top = cell / COLUMNS * 8;
    size_t left = cell % COLUMNS * 8;
    return work->palette[work->square[(top / BLOCK) * BLOCKS_X + left / BLOCK]];
}

/* Tile `tile` of a half to be this pattern, as it looks with this palette. */
static void set_tile(half_t *half, uint16_t tile, const uint8_t *planes, const uint8_t *palette)
{
    memcpy(half->pattern[tile], planes, 16);
    memset(half->share[tile], 0, sizeof(half->share[tile]));
    for (int y = 0; y < 8; y++) {
        for (int x = 0; x < 8; x++) {
            half->share[tile][(y / 2) * 4 + x / 2][pattern_pixel(planes, x, y)]++;
        }
    }
    for (size_t square = 0; square < 16; square++) {
        const uint8_t *share = half->share[tile][square];
        half->mix[tile][square] = mix_of[(share[0] * 5 + share[1]) * 5 + share[2]];
    }
    palette_colours(palette, half->colours[tile]);
    tile_look(half, tile, half->colours[tile], half->seen[tile]);
    half->uses[tile] = 0;
    half->gone[tile] = false;
}

/* The half's places, rows from `row` on, as different tiles. */
static void gather(work_t *work, half_t *half, size_t row)
{
    half->count = 0;
    for (size_t index = 0; index < HALF_CELLS; index++) {
        size_t cell = row * COLUMNS + index;
        const uint8_t *planes = work->cell_pattern[cell];
        uint16_t tile = 0;
        while (tile < half->count && memcmp(half->pattern[tile], planes, 16) != 0) {
            tile++;
        }
        if (tile == half->count) {
            set_tile(half, tile, planes, cell_palette(work, cell));
            half->count++;
        }
        half->uses[tile]++;
        half->of_cell[index] = tile;
    }
    half->active = half->count;
    if (half->count > 256 - 2) {    /* it may have to lose some: each one's nearest */
        for (uint16_t tile = 0; tile < half->count; tile++) {
            find_nearest(half, tile);
        }
    }
}

/* Merge tiles until no more than `room` are left. */
static void cut(half_t *half, uint16_t room)
{
    while (half->active > room) {
        uint16_t loser = UINT16_MAX;
        float least = 3.4e38f;
        for (uint16_t tile = 0; tile < half->count; tile++) {
            if (half->gone[tile]) {
                continue;
            }
            float cost = (float)half->uses[tile] * half->distance[tile];
            if (loser == UINT16_MAX || cost < least) {
                least = cost;
                loser = tile;
            }
        }
        uint16_t into = half->nearest[loser];
        half->gone[loser] = true;
        half->uses[into] = (uint16_t)(half->uses[into] + half->uses[loser]);
        half->active--;
        for (size_t index = 0; index < HALF_CELLS; index++) {
            if (half->of_cell[index] == loser) {
                half->of_cell[index] = into;
            }
        }
        for (uint16_t tile = 0; tile < half->count; tile++) {
            if (!half->gone[tile] && half->nearest[tile] == loser) {
                find_nearest(half, tile);
            }
        }
    }
}

/* Merging chose each place's tile by how near it is to the one it had; but
 * what a place should look like is its part of the image. Here each place
 * takes, of the tiles left, the one nearest the image there in its own
 * palette. A tile no place then takes is given up for the place served
 * worst, with its own tile, and the places choose again. */
static void refit(work_t *work, half_t *half, size_t row)
{
    for (int round = 0; round < REFITS; round++) {
        for (uint16_t tile = 0; tile < half->count; tile++) {
            half->uses[tile] = 0;
        }
        for (size_t index = 0; index < HALF_CELLS; index++) {
            size_t cell = row * COLUMNS + index;
            size_t top = cell / COLUMNS * 8;
            size_t left = cell % COLUMNS * 8;
            float image[16][3];
            for (size_t square = 0; square < 16; square++) {
                float sum[3] = {0.0f, 0.0f, 0.0f};
                for (size_t dy = 0; dy < 2; dy++) {
                    for (size_t dx = 0; dx < 2; dx++) {
                        float point[3];
                        const uint8_t *pixel =
                            work->source[top + square / 4 * 2 + dy][left + square % 4 * 2 + dx];
                        weigh_rgb(pixel[0], pixel[1], pixel[2], point);
                        sum[0] += point[0];
                        sum[1] += point[1];
                        sum[2] += point[2];
                    }
                }
                for (size_t axis = 0; axis < 3; axis++) {
                    image[square][axis] = sum[axis] * 0.25f;
                }
            }
            /* How far each 2 x 2 of the image is from each mix of the
             * place's colours: then a tile's distance is 16 of these. */
            float colours[4][3];
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
            }
            uint16_t best = half->of_cell[index];
            float least = 3.4e38f;
            for (uint16_t tile = 0; tile < half->count; tile++) {
                if (half->gone[tile]) {
                    continue;
                }
                const uint8_t *mix = half->mix[tile];
                float d = 0.0f;
                for (size_t square = 0; square < 16 && d < least; square++) {
                    d += far[square][mix[square]];
                }
                if (d < least) {
                    least = d;
                    best = tile;
                }
            }
            half->of_cell[index] = best;
            half->uses[best]++;
            half->error[index] = least;
        }
        /* Tiles left with no place, for the places served worst. */
        bool freed = false;
        for (uint16_t tile = 0; tile < half->count; tile++) {
            if (half->gone[tile] || half->uses[tile] != 0) {
                continue;
            }
            size_t worst = HALF_CELLS;
            for (size_t index = 0; index < HALF_CELLS; index++) {
                if (worst == HALF_CELLS || half->error[index] > half->error[worst]) {
                    worst = index;
                }
            }
            size_t cell = row * COLUMNS + worst;
            set_tile(half, tile, work->cell_pattern[cell], cell_palette(work, cell));
            half->uses[tile] = 1;
            half->of_cell[worst] = tile;
            half->error[worst] = 0.0f;
            freed = true;
        }
        if (!freed) {
            break;
        }
    }
}

/* Each tile left its number in the pattern table, in the order found. */
static void number(half_t *half)
{
    uint8_t next = 0;
    for (uint16_t tile = 0; tile < half->count; tile++) {
        if (!half->gone[tile]) {
            half->number[tile] = next++;
        }
    }
}

static uint8_t top_pixel(const work_t *work, int x)
{
    const half_t *top = &work->halves[0];
    size_t index = (size_t)(NESP_COMMONS_SPLIT_ROW - 1) * COLUMNS + (size_t)x / 8;
    return pattern_pixel(top->pattern[top->of_cell[index]], x % 8, SPLIT_LINE % 8);
}

/* Loops of the ROM's delay for a hit at x on the split's line. */
static uint8_t split_delay(int x)
{
    if (x + HIT_DOT + 45 >= LAND_FIRST) {
        return 0;
    }
    int loops = (LAND_FIRST - HIT_DOT - 39 - x + 14) / 15;     /* 13 + 5 a loop, at 3 dots */
    return (uint8_t)loops;
}

static void lay_out(work_t *work, uint8_t *out)
{
    make_mixes();
    memset(out, 0, NESP_COMMONS_SIZE);
    half_t *top = &work->halves[0];
    half_t *bottom = &work->halves[1];
    gather(work, bottom, NESP_COMMONS_SPLIT_ROW);
    cut(bottom, 256);
    refit(work, bottom, NESP_COMMONS_SPLIT_ROW);
    number(bottom);
    gather(work, top, 0);
    cut(top, 255);                  /* the last is sprite 0's */
    refit(work, top, 0);

    /* Sprite 0's place: the last pixel along the split's line that is not
     * black and lets the write land in time; or one made. */
    int hit = -1;
    for (int x = HIT_X_MAX; x >= 0 && hit < 0; x--) {
        if (top_pixel(work, x) != 0) {
            hit = x;
        }
    }
    bool spare = hit < 0;
    if (spare) {
        for (uint16_t tile = 0; tile < top->count; tile++) {
            if (!top->gone[tile]) {     /* refit moved places: each one's nearest again */
                find_nearest(top, tile);
            }
        }
        cut(top, 254);
        refit(work, top, 0);
        hit = HIT_X_SPARE;
    }
    number(top);

    uint8_t *chr = out + NESP_COMMONS_CHR;
    for (size_t side = 0; side < 2; side++) {
        const half_t *half = &work->halves[side];
        for (uint16_t tile = 0; tile < half->count; tile++) {
            if (!half->gone[tile]) {
                memcpy(chr + side * 0x1000 + (size_t)half->number[tile] * 16,
                       half->pattern[tile], 16);
            }
        }
    }
    chr[SPRITE_TILE * 16] = 0x80;   /* its one pixel, top left, colour 1 */

    uint8_t *names = out + NESP_COMMONS_NAMES;
    for (size_t index = 0; index < HALF_CELLS; index++) {
        names[index] = top->number[top->of_cell[index]];
        names[HALF_CELLS + index] = bottom->number[bottom->of_cell[index]];
    }
    if (spare) {
        size_t index = (size_t)(NESP_COMMONS_SPLIT_ROW - 1) * COLUMNS + HIT_X_SPARE / 8;
        uint8_t *planes = chr + SPARE_TILE * 16;
        memcpy(planes, top->pattern[top->of_cell[index]], 16);
        planes[SPLIT_LINE % 8] |= 0x80;
        names[index] = SPARE_TILE;
    }
    uint8_t *attributes = names + CELLS;
    for (size_t square = 0; square < BLOCKS; square++) {
        size_t bx = square % BLOCKS_X;
        size_t by = square / BLOCKS_X;
        size_t byte = (by / 2) * 8 + bx / 2;
        unsigned shift = (unsigned)((by % 2) * 4 + (bx % 2) * 2);
        attributes[byte] = (uint8_t)(attributes[byte] | work->square[square] << shift);
    }

    uint8_t *palette = out + NESP_COMMONS_PALETTE;
    memset(palette, BLACK, 32);     /* the sprites' too: sprite 0 is not to be seen */
    for (size_t p = 0; p < PALETTES; p++) {
        for (size_t slot = 0; slot < 3; slot++) {
            palette[4 * p + 1 + slot] = choices[work->palette[p][slot]];
        }
    }

    uint8_t *sprite = out + NESP_COMMONS_SPRITE;
    sprite[0] = SPLIT_LINE - 1;     /* a sprite is drawn a line below its Y */
    sprite[1] = SPRITE_TILE;
    sprite[2] = SPRITE_BEHIND;
    sprite[3] = (uint8_t)hit;
    out[NESP_COMMONS_DELAY] = split_delay(hit);
}

bool nesp_picture_make(const nesp_hal_t *hal, const uint8_t *rgb, uint32_t width,
                       uint32_t height, uint8_t *out)
{
    if (width == 0 || height == 0) {
        return false;
    }
    work_t *work = hal->alloc(hal->ctx, sizeof(work_t));
    if (work == NULL) {
        return false;
    }
    make_choices();
    fit(work, width, height);
    resample(work, rgb, width, height);
    palettes(work);
    for (size_t y = 0; y < HEIGHT; y++) {   /* resample leaves 0 to 255 */
        for (size_t x = 0; x < WIDTH; x++) {
            for (size_t axis = 0; axis < 3; axis++) {
                work->source[y][x][axis] = (uint8_t)work->rgb[y][x][axis];
            }
        }
    }
    dither(work);
    patterns(work);
    lay_out(work, out);
    hal->release(hal->ctx, work);
    return true;
}

uint8_t nesp_picture_split_delay(uint8_t x)
{
    return split_delay(x);
}

bool nesp_picture_target(const nesp_hal_t *hal, const uint8_t *rgb, uint32_t width,
                         uint32_t height, uint8_t *out)
{
    if (width == 0 || height == 0) {
        return false;
    }
    work_t *work = hal->alloc(hal->ctx, sizeof(work_t));
    if (work == NULL) {
        return false;
    }
    make_choices();
    fit(work, width, height);
    resample(work, rgb, width, height);
    for (size_t y = 0; y < HEIGHT; y++) {
        for (size_t x = 0; x < WIDTH; x++) {
            for (size_t channel = 0; channel < 3; channel++) {
                int value = work->rgb[y][x][channel];
                out[(y * WIDTH + x) * 3 + channel] = (uint8_t)(value < 0 ? 0 : value > 255 ? 255 : value);
            }
        }
    }
    hal->release(hal->ctx, work);
    return true;
}

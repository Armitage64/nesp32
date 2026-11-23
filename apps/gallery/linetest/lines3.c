/* Palettes for each row of squares (picture.c patched by bands.py, with
 * BAND_ROWS 1), changed PER_LINE colours a line at most: each change put on
 * the line, within WINDOW of the rows' boundary, where it costs least. The
 * picture is dithered with the palettes each line has, and written to
 * file.dithered (file.bin and file.target as convert.c). */
#include <stdio.h>
#include "picture.c"

#ifndef PER_LINE
#define PER_LINE 1
#endif
#ifndef WINDOW
#define WINDOW 8
#endif
#define ROWS_SQ BLOCKS_Y

static void *al(void *ctx, size_t n) { (void)ctx; return malloc(n); }
static void rel(void *ctx, void *p) { (void)ctx; free(p); }

typedef uint8_t set_t[PALETTES][3];
static set_t target[ROWS_SQ];
static set_t line_set[HEIGHT];
static uint8_t attr[BLOCKS];
static float points[HEIGHT][WIDTH][3];

static bool has(const uint8_t *pal, uint8_t c)
{
    return pal[0] == c || pal[1] == c || pal[2] == c;
}

static int common(const uint8_t *a, const uint8_t *b)
{
    return has(b, a[0]) + has(b, a[1]) + has(b, a[2]);
}

static bool used(size_t row, uint8_t p)
{
    for (size_t bx = 0; bx < BLOCKS_X; bx++) {
        if (attr[row * BLOCKS_X + bx] == p) {
            return true;
        }
    }
    return false;
}

/* Row r's palettes renumbered, and their colours put in the slots, to keep
 * as many of row r-1's as can be; one no square uses keeps row r-1's. */
static void align(size_t r)
{
    static const uint8_t perms[24][4] = {
        {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},
        {1,0,2,3},{1,0,3,2},{1,2,0,3},{1,2,3,0},{1,3,0,2},{1,3,2,0},
        {2,0,1,3},{2,0,3,1},{2,1,0,3},{2,1,3,0},{2,3,0,1},{2,3,1,0},
        {3,0,1,2},{3,0,2,1},{3,1,0,2},{3,1,2,0},{3,2,0,1},{3,2,1,0}};
    int best = -1;
    size_t pick = 0;
    for (size_t k = 0; k < 24; k++) {
        int score = 0;
        for (uint8_t q = 0; q < PALETTES; q++) {
            /* new palette perms[k][q] goes to place q */
            score += used(r, perms[k][q]) ? common(target[r - 1][q], target[r][perms[k][q]]) : 3;
        }
        if (score > best) {
            best = score;
            pick = k;
        }
    }
    set_t was;
    memcpy(was, target[r], sizeof(was));
    uint8_t place[PALETTES];
    bool use[PALETTES];
    for (uint8_t q = 0; q < PALETTES; q++) {
        place[perms[pick][q]] = q;
        use[q] = used(r, perms[pick][q]);
    }
    for (size_t bx = 0; bx < BLOCKS_X; bx++) {
        attr[r * BLOCKS_X + bx] = place[attr[r * BLOCKS_X + bx]];
    }
    for (uint8_t q = 0; q < PALETTES; q++) {
        const uint8_t *n = was[perms[pick][q]];
        const uint8_t *o = target[r - 1][q];
        uint8_t *out = target[r][q];
        if (!use[q]) {
            memcpy(out, o, 3);
            continue;
        }
        bool taken[3] = {false, false, false};
        bool filled[3] = {false, false, false};
        for (int s = 0; s < 3; s++) {
            for (int t = 0; t < 3; t++) {
                if (!taken[t] && n[t] == o[s]) {
                    out[s] = n[t];
                    taken[t] = filled[s] = true;
                    break;
                }
            }
        }
        for (int s = 0; s < 3; s++) {
            for (int t = 0; t < 3 && !filled[s]; t++) {
                if (!taken[t]) {
                    out[s] = n[t];
                    taken[t] = filled[s] = true;
                }
            }
        }
    }
}

/* What line y's pixels in squares of palette p lose to that palette. */
static float line_loss(int y, uint8_t p, const uint8_t *palette)
{
    float colours[4][3];
    palette_colours(palette, colours);
    size_t row = (size_t)y / BLOCK;
    float sum = 0.0f;
    for (size_t bx = 0; bx < BLOCKS_X; bx++) {
        if (attr[row * BLOCKS_X + bx] != p) {
            continue;
        }
        for (int x = (int)bx * BLOCK; x < (int)(bx + 1) * BLOCK; x++) {
            sum += colour_loss(points[y][x], colours);
        }
    }
    return sum;
}


#ifndef ALLOWED
#define ALLOWED(y) ((y) % 8 < 4 && (y) != 120)   /* fine Y 0-3, not the split */
#endif
static int change_line[ROWS_SQ][PALETTES][3];
static int dropped;
static work_t *cur_work;

/* Boundary r's changes, each on the allowed line of its window that costs
 * least; those that do not fit are dropped (row r keeps the colour). */
static void schedule_row(size_t r)
{
    int start = (int)r * BLOCK;
    int lo = start - WINDOW, hi = start + WINDOW - 1;
    int load[2 * WINDOW + 1] = {0};
    float cost[PALETTES][3][2 * WINDOW + 1];
    bool pending[PALETTES][3];
    int left = 0;
    for (uint8_t p = 0; p < PALETTES; p++) {
        for (int s = 0; s < 3; s++) {
            change_line[r][p][s] = -1;
            pending[p][s] = target[r][p][s] != target[r - 1][p][s];
            if (!pending[p][s]) {
                continue;
            }
            left++;
            uint8_t old_pal[3], new_pal[3], old_next[3], new_next[3];
            memcpy(old_pal, target[r - 1][p], 3);
            memcpy(new_pal, target[r - 1][p], 3);
            new_pal[s] = target[r][p][s];
            memcpy(new_next, target[r][p], 3);
            memcpy(old_next, target[r][p], 3);
            old_next[s] = target[r - 1][p][s];
            for (int y = lo; y <= hi; y++) {
                float c = 0.0f;
                for (int l = y; l < start; l++) {
                    c += line_loss(l, p, new_pal) - line_loss(l, p, old_pal);
                }
                for (int l = start; l < y; l++) {
                    c += line_loss(l, p, old_next) - line_loss(l, p, new_next);
                }
                cost[p][s][y - lo] = c;
            }
        }
    }
    while (left > 0) {
        float least = 0.0f;
        int bp = -1, bs = 0, by = 0;
        for (uint8_t p = 0; p < PALETTES; p++) {
            for (int s = 0; s < 3; s++) {
                if (!pending[p][s]) {
                    continue;
                }
                for (int y = lo; y <= hi; y++) {
                    if (load[y - lo] >= PER_LINE || !ALLOWED(y)) {
                        continue;
                    }
                    if (bp < 0 || cost[p][s][y - lo] < least) {
                        least = cost[p][s][y - lo];
                        bp = p;
                        bs = s;
                        by = y;
                    }
                }
            }
        }
        if (bp < 0) {
            break;
        }
        pending[bp][bs] = false;
        load[by - lo]++;
        change_line[r][bp][bs] = by;
        left--;
    }
    for (uint8_t p = 0; p < PALETTES; p++) {
        for (int s = 0; s < 3; s++) {
            if (pending[p][s]) {
                target[r][p][s] = target[r - 1][p][s];
                dropped++;
            }
        }
    }
#ifndef NO_REASSIGN
    /* The row's squares choose again, from the palettes they will have. */
    for (size_t bx = 0; bx < BLOCKS_X; bx++) {
        size_t sq = r * BLOCKS_X + bx;
        float best = -1.0f;
        for (uint8_t p = 0; p < PALETTES; p++) {
            float each = loss(&cur_work->bins[sq], target[r][p]);
            if (best < 0.0f || each < best) {
                best = each;
                attr[sq] = p;
            }
        }
    }
#endif
}

static void schedule(void)
{
    for (size_t r = 1; r < ROWS_SQ; r++) {
        align(r);
        schedule_row(r);
    }
    set_t now;
    memcpy(now, target[0], sizeof(now));
    for (int y = 0; y < HEIGHT; y++) {
        for (size_t r = 1; r < ROWS_SQ; r++) {
            for (uint8_t p = 0; p < PALETTES; p++) {
                for (int s = 0; s < 3; s++) {
                    if (change_line[r][p][s] == y) {
                        now[p][s] = target[r][p][s];
                    }
                }
            }
        }
        memcpy(line_set[y], now, sizeof(now));
    }
}

static void dither_lines(work_t *work)
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
            const uint8_t *palette = line_set[y][attr[(y / BLOCK) * BLOCKS_X + x / BLOCK]];
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
            spread(work, x + step, y, error, 7 * DIFFUSE / 16);
            spread(work, x - step, y + 1, error, 3 * DIFFUSE / 16);
            spread(work, x, y + 1, error, 5 * DIFFUSE / 16);
            spread(work, x + step, y + 1, error, DIFFUSE / 16);
        }
    }
}


/* The NES picture: each place's tile, each line's palettes. */
static void render(work_t *work, uint8_t *rgbout)
{
    memset(rgbout, 0, 256 * 240 * 3);
    for (size_t cell = 0; cell < CELLS; cell++) {
        size_t side = cell >= HALF_CELLS;
        const half_t *half = &work->halves[side];
        const uint8_t *planes = half->pattern[half->of_cell[cell - side * HALF_CELLS]];
        int top = (int)(cell / COLUMNS) * 8, left = (int)(cell % COLUMNS) * 8;
        for (int y = 0; y < 8; y++) {
            for (int x = 0; x < 8; x++) {
                int py = top + y, px = left + x;
                uint8_t c = pattern_pixel(planes, x, y);
                const uint8_t *pal = work->line_palette[py][work->square[(py / BLOCK) * BLOCKS_X + px / BLOCK]];
                memcpy(rgbout + (py * 256 + px) * 3, nes_rgb[choices[c == 0 ? 0 : pal[c - 1]]], 3);
            }
        }
    }
}

int main(int argc, char **argv)
{
    nesp_hal_t hal = {0};
    hal.alloc = al;
    hal.release = rel;
    static uint8_t file[1 << 20];
    static uint8_t out[NESP_COMMONS_SIZE];
    static uint8_t tgt[256 * 240 * 3];
    static uint8_t img[256 * 240 * 3];
    char name[1024];
    for (int arg = 1; arg < argc; arg++) {
        FILE *f = fopen(argv[arg], "rb");
        size_t len = fread(file, 1, sizeof(file), f);
        fclose(f);
        uint32_t w, h;
        uint8_t *rgb = nesp_picture_decode(&hal, file, len, &w, &h);
        nesp_picture_target(&hal, rgb, w, h, tgt);
        work_t *work = malloc(sizeof(work_t));
        make_choices();
        fit(work, w, h);
        resample(work, rgb, w, h);
        palettes(work);
        for (int y = 0; y < HEIGHT; y++) {
            for (int x = 0; x < WIDTH; x++) {
                weigh(work->rgb[y][x], points[y][x]);
                for (int k = 0; k < 3; k++) {
                    work->source[y][x][k] = (uint8_t)work->rgb[y][x][k];
                }
            }
        }
#if BAND_ROWS == 1
        memcpy(target, work->band_palette, sizeof(target));
        memcpy(attr, work->square, sizeof(attr));
        cur_work = work;
        schedule();
        memcpy(work->line_palette, line_set, sizeof(line_set));
        memcpy(work->square, attr, sizeof(attr));
#endif
        dither(work);
        static uint8_t dithered[256 * 240 * 3];
        for (int y = 0; y < 240; y++) {
            for (int x = 0; x < 256; x++) {
                uint8_t c = work->color[y][x];
                const uint8_t *pal = work->line_palette[y][work->square[(y / BLOCK) * BLOCKS_X + x / BLOCK]];
                memcpy(dithered + (y * 256 + x) * 3, nes_rgb[choices[c == 0 ? 0 : pal[c - 1]]], 3);
            }
        }
        patterns(work);
        lay_out(work, out);
        render(work, img);
        free(work);
        nesp_picture_release(&hal, rgb);
        {
            uint8_t sched[2 * HEIGHT];
            memset(sched, 0xFF, sizeof(sched));
            for (int y = 1; y < HEIGHT; y++) {
                for (int p = 0; p < PALETTES; p++) {
                    for (int k = 0; k < 3; k++) {
                        if (work->line_palette[y][p][k] != work->line_palette[y - 1][p][k]) {
                            if (sched[2 * y] != 0xFF) {
                                fprintf(stderr, "two changes on line %d\n", y);
                                exit(1);
                            }
                            sched[2 * y] = (uint8_t)(4 * p + 1 + k);
                            sched[2 * y + 1] = choices[work->line_palette[y][p][k]];
                        }
                    }
                }
            }
            uint8_t first[16];
            for (int p = 0; p < PALETTES; p++) {
                first[4 * p] = BLACK;
                for (int k = 0; k < 3; k++) {
                    first[4 * p + 1 + k] = choices[work->line_palette[0][p][k]];
                }
            }
            snprintf(name, sizeof(name), "%s.sched", argv[arg]);
            f = fopen(name, "wb");
            fwrite(sched, 1, sizeof(sched), f);
            fclose(f);
            snprintf(name, sizeof(name), "%s.pal", argv[arg]);
            f = fopen(name, "wb");
            fwrite(first, 1, sizeof(first), f);
            fclose(f);
        }
        const char *ext[4] = {"dithered", "bin", "target", "nes"};
        const uint8_t *data[4] = {dithered, out, tgt, img};
        size_t size[4] = {sizeof(dithered), sizeof(out), sizeof(tgt), sizeof(img)};
        for (int k = 0; k < 4; k++) {
            snprintf(name, sizeof(name), "%s.%s", argv[arg], ext[k]);
            f = fopen(name, "wb");
            fwrite(data[k], 1, size[k], f);
            fclose(f);
        }
    }
    fprintf(stderr, "dropped %.1f changes a picture\n", (double)dropped / (argc - 1));
    return 0;
}

/* Sound from one rate to another, for the console's sample channel: the
 * tuner's stations, decoded at whatever rate they have, and on a PAL
 * console the jukebox's sounds, made at an NTSC one's rates.
 *
 * The filter is a sinc under a Hann window, cut off below the lower of the
 * two rates' Nyquist, as tools/wav2pcm.py's is; worked out once for
 * NESP_RESAMPLE_PHASES places between two samples, and the nearest used.
 * Samples go in one at a time, and every one that comes out is taken
 * before the next goes in.
 */
#include <math.h>
#include <string.h>

#include "nesp_services.h"

#define ZEROS 8                     /* zero crossings each side of the middle */
#define PASSBAND 0.92f
#define PI 3.14159265f

void nesp_resample_init(nesp_resample_t *resample, float ratio, uint32_t step)
{
    float cutoff = PASSBAND * (ratio < 1.0f ? ratio : 1.0f) / 2.0f;     /* cycles a sample in */
    float half = (float)ZEROS / (2.0f * cutoff);
    uint32_t reach = (uint32_t)ceilf(half);
    if (reach > NESP_RESAMPLE_TAPS / 2) {
        reach = NESP_RESAMPLE_TAPS / 2;     /* a rate above any a station has: a narrower window */
        half = (float)reach;
    }
    for (int phase = 0; phase < NESP_RESAMPLE_PHASES; phase++) {
        float sum = 0.0f;
        for (uint32_t tap = 0; tap < 2 * reach; tap++) {
            float t = (float)((int)tap - (int)reach + 1) - (float)phase / (float)NESP_RESAMPLE_PHASES;
            float weight = 0.0f;
            if (fabsf(t) < half) {
                float x = 2.0f * PI * cutoff * t;
                weight = (x != 0.0f ? sinf(x) / x : 1.0f)
                         * (0.5f + 0.5f * cosf(PI * t / half));
            }
            resample->kernel[phase][tap] = weight;
            sum += weight;
        }
        for (uint32_t tap = 0; tap < 2 * reach; tap++) {
            resample->kernel[phase][tap] /= sum;
        }
    }
    resample->reach = reach;
    resample->step = step;
    resample->lag = 0;
    resample->newest = 0;
    memset(resample->history, 0, sizeof(resample->history));
}

void nesp_resample_put(nesp_resample_t *resample, float sample)
{
    resample->newest++;
    resample->history[resample->newest % NESP_RESAMPLE_HISTORY] = sample;
    resample->lag += (int32_t)NESP_RESAMPLE_ONE;
}

bool nesp_resample_take(nesp_resample_t *resample, float *out)
{
    const uint32_t one = NESP_RESAMPLE_ONE;
    if (resample->lag < (int32_t)(resample->reach * one)) {
        return false;
    }
    /* The next sample out lies `lag` behind the newest in: between `base`
     * and the one after it, at the nearest of the phases. */
    uint32_t whole = (uint32_t)resample->lag / one;
    uint32_t part = (uint32_t)resample->lag % one;
    uint32_t base = resample->newest - whole;
    uint32_t phase = 0;
    if (part != 0) {
        base--;
        phase = ((one - part) * NESP_RESAMPLE_PHASES + one / 2) / one;
        if (phase == NESP_RESAMPLE_PHASES) {
            phase = 0;
            base++;
        }
    }
    const float *weights = resample->kernel[phase];
    uint32_t first = base - resample->reach + 1;
    float sum = 0.0f;
    for (uint32_t tap = 0; tap < 2 * resample->reach; tap++) {
        sum += weights[tap] * resample->history[(first + tap) % NESP_RESAMPLE_HISTORY];
    }
    *out = sum;
    resample->lag -= (int32_t)resample->step;
    return true;
}

/* The DAC is not a straight line: the console's mixer squeezes the top of
 * its range. */
float nesp_dac_out(uint8_t level)
{
    return level == 0 ? 0.0f : (float)(159.79 / (22638.0 / level + 100.0));
}

void nesp_dac_levels(uint8_t *level)
{
    double dac[NESP_DAC_LEVELS];
    dac[0] = 0.0;
    for (int at = 1; at < NESP_DAC_LEVELS; at++) {
        dac[at] = 159.79 / (22638.0 / at + 100.0);
    }
    int above = 0;
    for (int place = 0; place < NESP_DAC_STEPS; place++) {
        double target = (double)place / (NESP_DAC_STEPS - 1) * dac[NESP_DAC_LEVELS - 1];
        while (above < NESP_DAC_LEVELS - 1 && dac[above] < target) {
            above++;
        }
        int below = above > 0 ? above - 1 : 0;
        level[place] = (uint8_t)(target - dac[below] <= dac[above] - target ? below : above);
    }
}

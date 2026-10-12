/* A measurement, not part of the firmware: can a nesp32 decode a radio
 * station as fast as it arrives? Built only when asked for:
 *
 *   idf.py -B build-spike -D SDKCONFIG=build-spike/sdkconfig \
 *          -D IDF_TARGET=esp32s3 -D NESP_SPIKE=1 build flash monitor
 *
 * Once the nesp32 has joined its network this fetches the station, decodes
 * it in the fetch task as a service's sink would, throws the samples away,
 * and logs every ten seconds what that cost. No console is needed.
 */
#include "spike.h"

#include <inttypes.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_clk_tree.h"
#include "esp_heap_caps.h"

#include "fetch.h"
#include "nesp_mp3.h"
#include "radio.h"

#define STATION "https://npr-ice.streamguys1.com/live.mp3"
#define AGENT "nesp32-npr/0.1 (NPR on a NES, on a nesp32; +https://github.com/Armitage64/nesp32)"
#define REPORT_US 10000000
#define AGAIN_US 5000000

static const char *TAG = "spike";

static nesp_mp3_t *mp3;
static volatile bool fetching;
static int64_t ended_at;
/* The fetch task's alone, but for the report's reading of them. */
static uint32_t bytes;
static uint64_t samples;            /* for one channel */
static int64_t busy_us;             /* in the decoder */
static int64_t slowest_us;          /* one piece of the stream, decoded */
static int rate, channels;
static int64_t began_at, reported_at;
static uint32_t bytes_then;
static uint64_t samples_then;
static int64_t busy_then;

static void heard(void *ctx, const int16_t *pcm, size_t count, int in_channels, int hz)
{
    (void)ctx;
    (void)pcm;
    samples += count;
    rate = hz;
    channels = in_channels;
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    (void)ctx;
    (void)id;
    int64_t from = esp_timer_get_time();
    nesp_mp3_feed(mp3, data, len, heard, NULL);
    int64_t took = esp_timer_get_time() - from;
    busy_us += took;
    if (took > slowest_us) {
        slowest_us = took;
    }
    bytes += (uint32_t)len;
    return true;
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    (void)ctx;
    (void)id;
    ESP_LOGW(TAG, "the stream ended (%s): %s", ok ? "whole" : "not whole", why);
    ended_at = esp_timer_get_time();
    fetching = false;
}

static const nesp_sink_t sink = {.ctx = NULL, .body = body, .done = done};

void spike_poll(void)
{
    int64_t now = esp_timer_get_time();
    if (!fetching) {
        nesp_wifi_t wifi;
        radio_wifi(&wifi);
        if (wifi.state != NESP_WIFI_JOINED || (ended_at != 0 && now - ended_at < AGAIN_US)) {
            return;
        }
        if (mp3 == NULL) {
            /* Where TUNER's is: in the PSRAM, if there is any. */
            mp3 = heap_caps_malloc(sizeof(*mp3), MALLOC_CAP_SPIRAM);
            if (mp3 == NULL) {
                mp3 = heap_caps_malloc(sizeof(*mp3), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
            }
            if (mp3 == NULL) {
                return;
            }
        }
        nesp_mp3_init(mp3);
        bytes = bytes_then = 0;
        samples = samples_then = 0;
        busy_us = busy_then = slowest_us = 0;
        began_at = reported_at = now;
        fetching = fetch_begin(NULL, STATION, AGENT, 1, &sink);
        ESP_LOGI(TAG, "fetching %s: %s", STATION, fetching ? "begun" : "refused");
        return;
    }
    if (now - reported_at < REPORT_US || rate == 0) {
        return;
    }
    /* Read while the fetch task writes them: a report may be a piece out. */
    uint32_t bytes_now = bytes;
    uint64_t samples_now = samples;
    int64_t busy_now = busy_us;
    /* In whole numbers of 32 bits: this firmware's printf has neither
     * floating point nor long long. */
    int64_t wall_us = now - reported_at;
    int64_t audio_us = (int64_t)((samples_now - samples_then) * 1000000 / (uint64_t)rate);
    int64_t busy = busy_now - busy_then;
    uint32_t core = (uint32_t)(busy * 1000 / wall_us);          /* tenths of a percent */
    uint32_t share = audio_us > 0 ? (uint32_t)(busy * 1000 / audio_us) : 0;
    uint32_t cpu_hz = 0;
    esp_clk_tree_src_get_freq_hz(SOC_MOD_CLK_CPU, ESP_CLK_TREE_SRC_FREQ_PRECISION_CACHED, &cpu_hz);
    ESP_LOGI(TAG, "%d Hz x%d, CPU at %" PRIu32 " MHz: in %" PRIu32 " ms, %" PRIu32
             " bytes and %" PRIu32 " ms of sound (%" PRIu32 " ms in all, in %" PRIu32 " ms)",
             rate, channels, cpu_hz / 1000000, (uint32_t)(wall_us / 1000),
             bytes_now - bytes_then, (uint32_t)(audio_us / 1000),
             (uint32_t)(samples_now * 1000 / (uint64_t)rate), (uint32_t)((now - began_at) / 1000));
    ESP_LOGI(TAG, "decoding took %" PRIu32 ".%" PRIu32 "%% of a core, %" PRIu32 ".%" PRIu32
             "%% of the sound's length; slowest piece %" PRIu32 " us; %" PRIu32 " frames, %"
             PRIu32 " bytes skipped; fetch stack left %" PRIu32,
             core / 10, core % 10, share / 10, share % 10, (uint32_t)slowest_us, mp3->frames,
             mp3->skipped, fetch_stack_left());
    reported_at = now;
    bytes_then = bytes_now;
    samples_then = samples_now;
    busy_then = busy_now;
}

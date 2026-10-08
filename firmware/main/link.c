/* The link task.
 *
 * One task owns the UART and the nesp_stick_t. It sleeps until the UART has
 * a byte, hands what has come to nesp_stick_feed, and writes the reply, if
 * there is one. Nothing it calls on the way to a reply waits for anything:
 * the services answer from what they hold, and what is slow is done by
 * other tasks (radio.c). It has a core to itself and the highest priority
 * there, so the time from a request's last byte to its reply's first is
 * the UART's interrupt, a task switch and the handler.
 *
 * The console listens for a reply only until its next vblank, a few
 * milliseconds; docs/PROTOCOL.md, "Timing".
 *
 * Once the reply is with the UART, and every so often besides, the
 * services get their tick (nesp_core.h). That is where the jukebox reads
 * its files, which takes a millisecond or two of flash: just after a reply
 * the console cannot ask again before its next vblank, and no tick is
 * given while a request is partway in. It is also where a
 * run of RAW's takes the line: the three functions at the end are what it
 * does that with.
 */
#include "link.h"

#include <string.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "board.h"

#define LINK_UART UART_NUM_1
#define LINK_CORE 1                 /* Wi-Fi has core 0 (sdkconfig.defaults) */
#define LINK_PRIORITY (configMAX_PRIORITIES - 2)
/* A hello runs every service's start from here, and a search builds an
 * address on it: 4096 was enough for the setup ROM and not for NESpedia.
 * The jukebox reads its files from here, through the filing system. */
#define LINK_STACK 12288
/* The ESP32's UART driver refuses a transmit buffer that is not larger than
 * its 128-byte FIFO (nes-drmario found this on a Plus2). A run of sampled
 * sound leaves at up to 20 KB a second, and this is topped up every
 * BUSY_WAIT_MS: a tenth of a second of it. */
#define RX_BUFFER 1024
#define TX_BUFFER 2048
/* The driver puts a few bytes of its own round what it is given to send. */
#define TX_SLACK 64
#define UART_EVENTS 32
/* How long the task sleeps with nothing heard before the services get a
 * tick anyway: while one of them wants it soon, and otherwise. */
#define BUSY_WAIT_MS 2
#define IDLE_WAIT_MS 100
#define EVENT_QUEUE 8
/* The console is still on its way from sending to listening for this long
 * after its request's last byte (docs/PROTOCOL.md, "Timing"). */
#define MIN_TURNAROUND_US 50

static const char *TAG = "link";

static nesp_stick_t stick;
static TaskHandle_t link_handle;
static QueueHandle_t uart_events;
static QueueHandle_t stick_events;
static size_t tx_empty;             /* what the driver says is free with nothing waiting */
static portMUX_TYPE stats_lock = portMUX_INITIALIZER_UNLOCKED;
static link_stats_t shared_stats;

static void publish_stats(bool heard)
{
    const nesp_counters_t *counters = &stick.link.counters;
    portENTER_CRITICAL(&stats_lock);
    shared_stats.requests = counters->requests;
    shared_stats.repeats = counters->repeats;
    shared_stats.noise = counters->noise;
    shared_stats.turnaround_us = counters->turnaround_us;
    shared_stats.turnaround_max_us = counters->turnaround_max_us;
    if (heard) {
        shared_stats.last_request_ms = (uint32_t)(esp_timer_get_time() / 1000);
    }
    portEXIT_CRITICAL(&stats_lock);
}

/* What the UART has heard: to the nesp32, and its reply back. */
static void hear(const uart_event_t *event, int64_t arrived)
{
    static uint8_t heard[RX_BUFFER];
    static uint8_t reply[NESP_FRAME_MAX];
    uint8_t pending[2];

    if (event->type == UART_FIFO_OVF || event->type == UART_BUFFER_FULL) {
        uart_flush_input(LINK_UART);
        xQueueReset(uart_events);
        return;
    }
    if (event->type != UART_DATA || event->size == 0) {
        return;                     /* a break or a framing error: the console's
                                       controller read, or a console that is off */
    }
    /* Everything that has come, not only what this event tells of: the
     * UART drops an event when its queue is full, and bytes read by the
     * event would then lag behind for good, each request answered when a
     * later one was heard. */
    size_t wanted = 0;
    uart_get_buffered_data_len(LINK_UART, &wanted);
    if (wanted > sizeof(heard)) {
        wanted = sizeof(heard);
    }
    int count = uart_read_bytes(LINK_UART, heard, wanted, 0);
    if (count <= 0) {
        return;
    }
    /* Buttons pressed since the last request, for the services. */
    while (xQueueReceive(stick_events, pending, 0) == pdTRUE) {
        nesp_stick_event(&stick, pending[0], pending[1]);
    }
    uint32_t before = stick.link.counters.requests;
    size_t length = nesp_stick_feed(&stick, heard, (size_t)count, reply);
    if (length != 0) {
        int64_t took = esp_timer_get_time() - arrived;
        if (took < MIN_TURNAROUND_US) {
            esp_rom_delay_us((uint32_t)(MIN_TURNAROUND_US - took));
        }
        uart_write_bytes(LINK_UART, reply, length);
        nesp_link_note_turnaround(&stick.link, (uint32_t)(esp_timer_get_time() - arrived));
    }
    if (stick.link.counters.requests != before) {
        publish_stats(true);
    }
}

static void link_task(void *arg)
{
    (void)arg;
    uart_event_t event;
    uint8_t pending[2];
    TickType_t wait = pdMS_TO_TICKS(IDLE_WAIT_MS);

    /* The UART has been open since before the files were made ready, which
     * can take seconds, with a console talking to it all the while: none
     * of that is wanted now. */
    uart_flush_input(LINK_UART);
    xQueueReset(uart_events);
    for (;;) {
        if (xQueueReceive(uart_events, &event, wait) == pdTRUE) {
            hear(&event, esp_timer_get_time());
            if (stick.link.rx_len != 0 && !nesp_raw_owns_line(&stick.raw)) {
                /* Part of a request has come, and the rest is a fraction
                 * of a millisecond behind it: nothing that could take
                 * longer than that is begun now. If no more comes, it was
                 * noise, and the wait below runs out. */
                wait = pdMS_TO_TICKS(BUSY_WAIT_MS);
                continue;
            }
        } else {
            /* Nothing from the console: a button still does what it does,
             * for a service that takes them (the jukebox's, in a sound). */
            while (xQueueReceive(stick_events, pending, 0) == pdTRUE) {
                nesp_stick_event(&stick, pending[0], pending[1]);
            }
            publish_stats(false);
        }
        bool soon = nesp_stick_tick(&stick, (uint32_t)(esp_timer_get_time() / 1000));
        wait = pdMS_TO_TICKS(soon ? BUSY_WAIT_MS : IDLE_WAIT_MS);
    }
}

void link_open(void)
{
    /* 2 stop bits out: the second is the console's time to store a byte. */
    const uart_config_t config = {
        .baud_rate = NESP_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_2,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    /* A console left waiting for the rest of a sound, by a nesp32 that was
     * switched off in the middle of one, takes these for its end: long
     * lows, which its routines read as a last sample at any rate. To any
     * other console they are noise. */
    static const uint8_t filler[4] = {0, 0, 0, 0};

    ESP_ERROR_CHECK(uart_driver_install(LINK_UART, RX_BUFFER, TX_BUFFER, UART_EVENTS,
                                        &uart_events, 0));
    ESP_ERROR_CHECK(uart_param_config(LINK_UART, &config));
#if BOARD_LINK_INVERTED
    /* Before the pins are attached, so that TX never rests at the wrong
     * level: with an inverting stage the pin idles low, which leaves the
     * transistor off and its pull-up holding D0 high at the console. */
    ESP_ERROR_CHECK(uart_set_line_inverse(LINK_UART, UART_SIGNAL_TXD_INV | UART_SIGNAL_RXD_INV));
#endif
    ESP_ERROR_CHECK(uart_set_pin(LINK_UART, BOARD_LINK_TX, BOARD_LINK_RX,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    /* An interrupt for every byte: a request is a dozen bytes, and what
     * matters is hearing its last one at once. */
    ESP_ERROR_CHECK(uart_set_rx_full_threshold(LINK_UART, 1));
    ESP_ERROR_CHECK(uart_set_rx_timeout(LINK_UART, 1));
    ESP_ERROR_CHECK(uart_get_tx_buffer_free_size(LINK_UART, &tx_empty));
    uart_write_bytes(LINK_UART, filler, sizeof(filler));
    ESP_LOGI(TAG, "%s: TX G%d, RX G%d, %d baud", BOARD_NAME, BOARD_LINK_TX, BOARD_LINK_RX,
             NESP_BAUD);
}

void link_start(const nesp_hal_t *hal)
{
    stick_events = xQueueCreate(EVENT_QUEUE, 2);
    nesp_stick_init(&stick, hal);
    xTaskCreatePinnedToCore(link_task, "link", LINK_STACK, NULL, LINK_PRIORITY, &link_handle,
                            LINK_CORE);
}

void link_event(uint8_t code, uint8_t arg)
{
    uint8_t event[2] = {code, arg};
    if (stick_events != NULL) {
        xQueueSend(stick_events, event, 0);
    }
}

void link_stats(link_stats_t *out)
{
    portENTER_CRITICAL(&stats_lock);
    *out = shared_stats;
    portEXIT_CRITICAL(&stats_lock);
}

uint32_t link_stack_left(void)
{
    return link_handle != NULL ? (uint32_t)uxTaskGetStackHighWaterMark(link_handle) : 0;
}

/* --- the line with framing off (nesp_hal_t's line_*): from the link task ------ */

void link_line_rate(void *ctx, uint8_t period)
{
    (void)ctx;
    uart_set_baudrate(LINK_UART, (NESP_CPU_HZ + period / 2u) / period);
    /* A change of rate leaves junk in the receiver, and what was heard at
     * the old one is of no use at the new. */
    uart_flush_input(LINK_UART);
    xQueueReset(uart_events);
}

/* The UART's stop bits are one setting for both ways. The console needs
 * two of what it is sent, and sends one itself: between the bytes of a
 * request it is slow enough that the UART finds a second anyway, and in a
 * run it is not. On a StickS3 the receiver waits for the second, and loses
 * its place in the byte that begins there: 194 of a run's 256 bytes came,
 * at 9622 baud as at 85227. Nothing is sent while a run from the console
 * is heard, so for that long the setting is one. */
void link_line_hear(void *ctx, bool hearing)
{
    (void)ctx;
    uart_set_stop_bits(LINK_UART, hearing ? UART_STOP_BITS_1 : UART_STOP_BITS_2);
}

size_t link_line_write(void *ctx, const uint8_t *data, size_t len)
{
    size_t room = 0;
    (void)ctx;
    /* uart_write_bytes waits for room it has not got, and this may not. */
    if (uart_get_tx_buffer_free_size(LINK_UART, &room) != ESP_OK || room <= TX_SLACK) {
        return 0;
    }
    if (len > room - TX_SLACK) {
        len = room - TX_SLACK;
    }
    int sent = uart_write_bytes(LINK_UART, data, len);
    return sent > 0 ? (size_t)sent : 0;
}

bool link_line_idle(void *ctx)
{
    size_t room = 0;
    (void)ctx;
    return uart_get_tx_buffer_free_size(LINK_UART, &room) == ESP_OK && room >= tx_empty
           && uart_wait_tx_done(LINK_UART, 0) == ESP_OK;
}

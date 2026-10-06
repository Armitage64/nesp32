/* The link task.
 *
 * One task owns the UART and the nesp_stick_t. It sleeps until the UART has
 * a byte, hands what has come to nesp_link_feed, and writes the reply, if
 * there is one. Nothing it calls waits for anything: the services answer
 * from what they hold, and what is slow is done by other tasks
 * (radio.c). It has a core to itself and the highest priority there, so
 * the time from a request's last byte to its reply's first is the UART's
 * interrupt, a task switch and the handler.
 *
 * The console listens for a reply only until its next vblank, a few
 * milliseconds; docs/PROTOCOL.md, "Timing".
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
#define LINK_STACK 4096
/* The ESP32's UART driver refuses a transmit buffer that is not larger than
 * its 128-byte FIFO (nes-drmario found this on a Plus2). */
#define RX_BUFFER 1024
#define TX_BUFFER 512
#define UART_EVENTS 32
#define EVENT_QUEUE 8
/* The console is still on its way from sending to listening for this long
 * after its request's last byte (docs/PROTOCOL.md, "Timing"). */
#define MIN_TURNAROUND_US 50

static const char *TAG = "link";

static nesp_stick_t stick;
static QueueHandle_t uart_events;
static QueueHandle_t stick_events;
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

static void link_task(void *arg)
{
    (void)arg;
    static uint8_t heard[RX_BUFFER];
    static uint8_t reply[NESP_FRAME_MAX];
    uart_event_t event;
    uint8_t pending[2];

    for (;;) {
        if (xQueueReceive(uart_events, &event, pdMS_TO_TICKS(100)) != pdTRUE) {
            publish_stats(false);
            continue;
        }
        int64_t arrived = esp_timer_get_time();
        if (event.type == UART_FIFO_OVF || event.type == UART_BUFFER_FULL) {
            uart_flush_input(LINK_UART);
            xQueueReset(uart_events);
            continue;
        }
        if (event.type != UART_DATA || event.size == 0) {
            continue;               /* a break or a framing error: the console's
                                       controller read, or a console that is off */
        }
        size_t wanted = event.size < sizeof(heard) ? event.size : sizeof(heard);
        int count = uart_read_bytes(LINK_UART, heard, wanted, 0);
        if (count <= 0) {
            continue;
        }
        /* Buttons pressed since the last request, for the services to hold. */
        while (xQueueReceive(stick_events, pending, 0) == pdTRUE) {
            nesp_stick_event(&stick, pending[0], pending[1]);
        }
        uint32_t before = stick.link.counters.requests;
        size_t length = nesp_link_feed(&stick.link, heard, (size_t)count, reply);
        if (length != 0) {
            int64_t took = esp_timer_get_time() - arrived;
            if (took < MIN_TURNAROUND_US) {
                esp_rom_delay_us((uint32_t)(MIN_TURNAROUND_US - took));
            }
            uart_write_bytes(LINK_UART, reply, length);
            nesp_link_note_turnaround(&stick.link,
                                      (uint32_t)(esp_timer_get_time() - arrived));
        }
        if (stick.link.counters.requests != before) {
            publish_stats(true);
        }
    }
}

void link_start(const nesp_hal_t *hal)
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

    stick_events = xQueueCreate(EVENT_QUEUE, 2);
    nesp_stick_init(&stick, hal);
    xTaskCreatePinnedToCore(link_task, "link", LINK_STACK, NULL, LINK_PRIORITY, NULL, LINK_CORE);
    ESP_LOGI(TAG, "%s: TX G%d, RX G%d, %d baud", BOARD_NAME, BOARD_LINK_TX, BOARD_LINK_RX,
             NESP_BAUD);
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

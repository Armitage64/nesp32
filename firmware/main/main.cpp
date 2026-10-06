// nesp32: one firmware for every NES application that uses a Stick.
//
// Three things run. The link task (link.c) answers the console and has a
// core to itself. Wi-Fi and its worker (radio.c) do everything slow. This
// task, the main one, owns M5Unified: the screen, the buttons, the battery
// gauge and the power.
//
// Nothing is chosen here. The ROM on the console says what it is and which
// services it needs (docs/PROTOCOL.md, "Hello"), and the screen shows it.
//
//   A (front)        told to the service in use that wants it (the jukebox's:
//                    play or pause), or else to the console
//   B (side)         the same (previous track); held for 2 s, power off
//   power, tapped    the same (next track)
#include <M5Unified.h>

#include <cstdio>
#include <cstring>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_heap_caps.h"

#include "board.h"
#include "fetch.h"
#include "link.h"
#include "radio.h"
#include "store.h"

namespace {

const char *TAG = "nesp32";
const uint32_t POWER_OFF_HOLD_MS = 2000;
const uint32_t SCREEN_MS = 500;
const uint32_t BATTERY_MS = 10000;
const uint32_t REPORT_MS = 10000;
const uint32_t CONSOLE_GONE_MS = 2000;  // no request for this long: not there
const int ROWS = 7;
const char *const WIFI_STATES[] = {"not set up", "not joined", "joining", "joined", "failed"};

char shown[ROWS][40];

// Write a line of the screen, if it has changed.
void line(int row, const char *text)
{
    if (std::strncmp(shown[row], text, sizeof(shown[row])) == 0) {
        return;
    }
    std::strncpy(shown[row], text, sizeof(shown[row]) - 1);
    int height = M5.Display.fontHeight() + 4;
    M5.Display.fillRect(0, row * height, M5.Display.width(), height, TFT_BLACK);
    M5.Display.setCursor(2, row * height + 2);
    M5.Display.print(text);
}

void draw()
{
    char text[40];
    nesp_wifi_t wifi;
    link_stats_t stats;
    char app[NESP_APP_ID + 1] = {0};
    uint8_t version = 0;
    radio_wifi(&wifi);
    radio_app(app, &version);
    link_stats(&stats);
    uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
    bool console = stats.last_request_ms != 0 && now - stats.last_request_ms < CONSOLE_GONE_MS;

    line(0, "NESP32 " NESP_FIRMWARE_TEXT);
    if (console) {
        std::snprintf(text, sizeof(text), "NES: %s v%u", app, version);
    } else {
        std::snprintf(text, sizeof(text), "NES: waiting");
    }
    line(1, text);
    std::snprintf(text, sizeof(text), "Wi-Fi: %s",
                  wifi.state < 5 ? WIFI_STATES[wifi.state] : "?");
    line(2, text);
    // The network's name and the nesp32's address, unless the service in use
    // has something of its own to say there (the jukebox: its track).
    char said[2][RADIO_SHOWN_MAX];
    radio_shown(0, said[0]);
    radio_shown(1, said[1]);
    if (console && (said[0][0] != 0 || said[1][0] != 0)) {
        line(3, said[0]);
        line(4, said[1]);
    } else {
        std::snprintf(text, sizeof(text), "%.*s", (int)wifi.name_len, wifi.name);
        line(3, text);
        if (wifi.state == NESP_WIFI_JOINED) {
            std::snprintf(text, sizeof(text), "%u.%u.%u.%u", wifi.address[0], wifi.address[1],
                          wifi.address[2], wifi.address[3]);
        } else {
            text[0] = 0;
        }
        line(4, text);
    }
    std::snprintf(text, sizeof(text), "%lu req, %lu again", (unsigned long)stats.requests,
                  (unsigned long)stats.repeats);
    line(5, text);
    std::snprintf(text, sizeof(text), "reply %lu us, max %lu",
                  (unsigned long)stats.turnaround_us, (unsigned long)stats.turnaround_max_us);
    line(6, text);
}

}  // namespace

extern "C" void app_main(void)
{
    auto config = M5.config();
    M5.begin(config);
    M5.Display.setRotation(1);
    M5.Display.setTextSize(1);
    M5.Display.setFont(&fonts::FreeSans9pt7b);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.fillScreen(TFT_BLACK);

    // The UART first, before anything slow, so that TX rests at mark. The
    // files next: a ROM that asks for them is not answered until they are
    // there to be listed.
    link_open();
    store_start();
    link_start(radio_hal());
    radio_start();
    ESP_LOGI(TAG, "nesp32 %s on a %s", NESP_FIRMWARE_TEXT, BOARD_NAME);

    uint32_t screen_at = 0;
    uint32_t battery_at = 0;
    uint32_t report_at = 0;
    for (;;) {
        M5.update();
        if (M5.BtnA.wasPressed()) {
            link_event(NESP_EVENT_BUTTON_A, 0);
        }
        if (M5.BtnB.wasPressed()) {
            link_event(NESP_EVENT_BUTTON_B, 0);
        }
        if (M5.BtnPWR.wasClicked()) {
            link_event(NESP_EVENT_BUTTON_POWER, 0);
        }
        if (M5.BtnB.pressedFor(POWER_OFF_HOLD_MS)) {
            // The UART stays open so TX rests at mark (D0 high at the console).
            M5.Display.fillScreen(TFT_BLACK);
            M5.Power.powerOff();        // on USB power the Stick stays on
        }
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
        if (now - battery_at >= BATTERY_MS || battery_at == 0) {
            battery_at = now | 1;
            int level = M5.Power.getBatteryLevel();
            radio_set_battery(level >= 0 && level <= 100 ? (uint8_t)level : 0xFF);
        }
        if (now - report_at >= REPORT_MS) {
            // For whoever is watching the log: what the two busy tasks
            // have left of their stacks, and what memory there is.
            report_at = now;
            link_stats_t stats;
            link_stats(&stats);
            ESP_LOGI(TAG, "%lu requests, %lu again, %lu noise; reply %lu us, slowest %lu; "
                     "stack left: link %lu, fetch %lu; free: %u internal, %u PSRAM",
                     (unsigned long)stats.requests, (unsigned long)stats.repeats,
                     (unsigned long)stats.noise, (unsigned long)stats.turnaround_us,
                     (unsigned long)stats.turnaround_max_us,
                     (unsigned long)link_stack_left(), (unsigned long)fetch_stack_left(),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        }
        if (now - screen_at >= SCREEN_MS) {
            screen_at = now;
            draw();
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

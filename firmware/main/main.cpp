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
//                    play or pause), or else to the console; while the files
//                    are a USB drive, the end of that (the nesp32 restarts)
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
#include "conn.h"
#include "fetch.h"
#include "link.h"
#include "radio.h"
#ifdef NESP_SPIKE
#include "spike.h"
#endif
#include "store.h"
#include "usb.h"

namespace {

const char *TAG = "nesp32";
const uint32_t POWER_OFF_HOLD_MS = 2000;
const uint32_t SCREEN_MS = 500;
const uint32_t BATTERY_MS = 10000;
const uint32_t REPORT_MS = 10000;
const uint32_t WATCH_MS = 2000;
const uint32_t CONSOLE_GONE_MS = 2000;  // no request for this long: not there
const int ROWS = 7;
const uint32_t TITLE_BLUE = 0x40A0FFu;  // the top line and the rule under it
// The battery's charge, by how much of it there is: over half, over a
// tenth, and less.
const uint32_t BATTERY_GREEN = 0x00FF40u;
const uint32_t BATTERY_YELLOW = 0xFFD000u;
const uint32_t BATTERY_RED = 0xFF3030u;
const int BATTERY_WIDE = 20;            // the picture of it, without its terminal
const int BATTERY_HIGH = 10;
// The applications the screen has a name for. Any other is shown by the id
// and version of its hello.
const struct {
    const char *id;
    const char *name;
} APP_NAMES[] = {{"CNTR", "Contra"}, {"DRMA", "Dr. Mario"}, {"JUKE", "Jukebox"},
                 {"NPR ", "NPR"}, {"RADR", "Radar"}, {"SETP", "Setup"}, {"THRU", "Throughput"},
                 {"TTRS", "Tetris"}, {"WIKI", "Wikipedia"}, {"WTHR", "Weather"}};
const char *const WIFI_STATES[] = {"not set up", "not joined", "joining", "joined", "failed"};

char shown[ROWS][RADIO_SHOWN_MAX];
bool flipped;           // the way up the screen is drawn
int battery_level = -1; // 0 to 100, or -1 while the charge is not known

// Write a line of the screen, if it has changed. The top one is the title:
// in blue, with a rule under it and the battery's charge at its right, as
// a number and a picture filled as far.
void line(int row, const char *text)
{
    if (std::strncmp(shown[row], text, sizeof(shown[row])) == 0) {
        return;
    }
    std::strncpy(shown[row], text, sizeof(shown[row]) - 1);
    int height = M5.Display.fontHeight() + 4;
    M5.Display.fillRect(0, row * height, M5.Display.width(), height, TFT_BLACK);
    M5.Display.setCursor(2, row * height + 2);
    M5.Display.setTextColor(row == 0 ? TITLE_BLUE : (uint32_t)0xFFFFFFu, (uint32_t)0x000000u);
    M5.Display.print(text);
    if (row == 0) {
        if (battery_level >= 0) {
            uint32_t colour = battery_level > 50 ? BATTERY_GREEN
                              : battery_level > 10 ? BATTERY_YELLOW : BATTERY_RED;
            char percent[16];
            std::snprintf(percent, sizeof(percent), "%d%%", battery_level);
            int x = M5.Display.width() - 4 - 2 - BATTERY_WIDE;
            int y = 2 + (M5.Display.fontHeight() - BATTERY_HIGH) / 2;
            M5.Display.drawRect(x, y, BATTERY_WIDE, BATTERY_HIGH, colour);
            M5.Display.fillRect(x + BATTERY_WIDE, y + 3, 2, BATTERY_HIGH - 6, colour);
            M5.Display.fillRect(x + 2, y + 2, (BATTERY_WIDE - 4) * battery_level / 100,
                                BATTERY_HIGH - 4, colour);
            M5.Display.setTextColor(colour, (uint32_t)0x000000u);
            M5.Display.setCursor(x - 4 - M5.Display.textWidth(percent), 2);
            M5.Display.print(percent);
        }
        M5.Display.drawFastHLine(0, height - 2, M5.Display.width(), TITLE_BLUE);
    }
}

// The battery's charge, 0 to 100, or anything else if not known. The title
// is written again the next time, if what it shows of it has changed.
void battery(int level)
{
    if (level < 0 || level > 100) {
        level = -1;
    }
    if (level != battery_level) {
        battery_level = level;
        shown[0][0] = 0;
    }
}

// A line too long for the screen, as two: broken at a space if it has one
// where it would do. Each holds RADIO_SHOWN_MAX bytes.
void split(const char *text, char *first, char *second)
{
    int room = M5.Display.width() - 2;
    size_t length = std::strlen(text);
    size_t fits = length;
    std::strcpy(first, text);
    while (fits > 0 && M5.Display.textWidth(first) > room) {
        first[--fits] = 0;
    }
    second[0] = 0;
    if (fits == length) {
        return;
    }
    size_t cut = fits;
    for (size_t at = fits; at > 0; at--) {
        if (text[at] == ' ') {
            cut = at;
            break;
        }
    }
    first[cut] = 0;
    std::strcpy(second, text + cut + (text[cut] == ' '));
}

// The screen the way up the console last chose (radio_screen_flipped): 1
// is M5Stack's landscape, and 3 the same turned a half turn round. Turned,
// it is cleared, and every line is written again.
void turn(bool first)
{
    bool wanted = radio_screen_flipped();
    if (!first && wanted == flipped) {
        return;
    }
    flipped = wanted;
    M5.Display.setRotation(flipped ? 3 : 1);
    M5.Display.fillScreen(TFT_BLACK);
    for (auto &row : shown) {
        row[0] = 0;
    }
}

// While the store makes the rips of music playable, at start.
void converting(unsigned rip, unsigned of)
{
    char text[40];
    std::snprintf(text, sizeof(text), "Converting %u/%u", rip, of);
    line(0, "NESP32 " NESP_FIRMWARE_TEXT);
    line(1, text);
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
        for (const auto &known : APP_NAMES) {
            if (std::strcmp(app, known.id) == 0) {
                std::snprintf(text, sizeof(text), "NES: %s", known.name);
            }
        }
    } else {
        std::snprintf(text, sizeof(text), "NES: waiting");
    }
    line(1, text);
    // Joined, the network's name says so; otherwise how far along it is.
    if (wifi.state == NESP_WIFI_JOINED) {
        std::snprintf(text, sizeof(text), "Wifi: %.*s", (int)wifi.name_len, wifi.name);
    } else {
        std::snprintf(text, sizeof(text), "Wifi: %s",
                      wifi.state < 5 ? WIFI_STATES[wifi.state] : "?");
    }
    line(2, text);
    // The nesp32's address, unless the service in use has something of its
    // own to say there (the jukebox: its track), which takes two lines and
    // moves the link's numbers down one. If it has only the one line, and
    // that a long one, it runs on into the second.
    int row = 3;
    char said[2][RADIO_SHOWN_MAX];
    radio_shown(0, said[0]);
    radio_shown(1, said[1]);
    uint8_t drive = usb_drive_state();
    if (drive != NESP_DRIVE_NONE && drive != NESP_DRIVE_OFF) {
        // The files are lent to a computer (usb.c), and that comes first.
        line(row++, "USB drive");
        line(row++, drive == NESP_DRIVE_WAITING ? "Plug into a computer"
                    : drive == NESP_DRIVE_MOUNTED ? "Eject it when done" : "Restarting");
    } else if (console && (said[0][0] != 0 || said[1][0] != 0)) {
        if (said[1][0] == 0) {
            char whole[RADIO_SHOWN_MAX];
            std::strcpy(whole, said[0]);
            split(whole, said[0], said[1]);
        }
        line(row++, said[0]);
        line(row++, said[1]);
    } else {
        if (wifi.state == NESP_WIFI_JOINED) {
            std::snprintf(text, sizeof(text), "%u.%u.%u.%u", wifi.address[0], wifi.address[1],
                          wifi.address[2], wifi.address[3]);
        } else {
            text[0] = 0;
        }
        line(row++, text);
    }
    // With another nesp32 connected, the ping: what the network last took
    // between the two, there and back, in milliseconds.
    uint8_t peer = conn_state(nullptr);
    conn_ping_t ping;
    conn_ping(&ping);
    if ((peer == NESP_CONN_ANSWERED || peer == NESP_CONN_CALLED) && ping.count != 0) {
        std::snprintf(text, sizeof(text), "req: %lu, ping: %lu", (unsigned long)stats.requests,
                      (unsigned long)((ping.last_us + 500) / 1000));
    } else {
        std::snprintf(text, sizeof(text), "req: %lu", (unsigned long)stats.requests);
    }
    line(row++, text);
    while (row < ROWS) {
        line(row++, "");
    }
}

}  // namespace

extern "C" void app_main(void)
{
    usb_start();
    auto config = M5.config();
    M5.begin(config);
    radio_settings();                   // the way up the screen is, among them
    M5.Display.setTextSize(1);
    M5.Display.setFont(&fonts::FreeSans9pt7b);
    M5.Display.setTextWrap(false);      // a long name is cut off, not run into the next line
    turn(true);

    // The UART first, before anything slow, so that TX rests at mark. The
    // files next: a ROM that asks for them is not answered until they are
    // there to be listed.
    link_open();
    store_start(converting);
    link_start(radio_hal());
    radio_start();
    ESP_LOGI(TAG, "nesp32 %s on a %s", NESP_FIRMWARE_TEXT, BOARD_NAME);

    uint32_t screen_at = 0;
    uint32_t battery_at = 0;
    uint32_t report_at = 0;
    uint32_t watch_at = 0;
    for (;;) {
        M5.update();
        usb_poll();
#ifdef NESP_SPIKE
        spike_poll();
#endif
        uint8_t drive = usb_drive_state();
        if (M5.BtnA.wasPressed()) {
            if (drive != NESP_DRIVE_NONE && drive != NESP_DRIVE_OFF) {
                usb_drive(nullptr, NESP_LEND_STOP);     // a way out with no console
            } else {
                link_event(NESP_EVENT_BUTTON_A, 0);
            }
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
            battery(level);
        }
        if (now - report_at >= REPORT_MS) {
            // For whoever is watching the log: what the two busy tasks
            // have left of their stacks, and what memory there is.
            report_at = now;
            link_stats_t stats;
            link_stats(&stats);
            ESP_LOGI(TAG, "%lu requests, %lu again, %lu noise; reply %lu us, slowest %lu; "
                     "stack left: link %lu, fetch %lu, conn %lu; free: %u internal, %u PSRAM",
                     (unsigned long)stats.requests, (unsigned long)stats.repeats,
                     (unsigned long)stats.noise, (unsigned long)stats.turnaround_us,
                     (unsigned long)stats.turnaround_max_us,
                     (unsigned long)link_stack_left(), (unsigned long)fetch_stack_left(),
                     (unsigned long)conn_stack_left(),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        }
        if (now - watch_at >= WATCH_MS) {
            // And for whoever is watching: the station's figures, from
            // TUNER, or what PEER says of a game, and how long the network
            // between the two nesp32s has taken.
            watch_at = now;
            char said[RADIO_WATCH_MAX];
            said[0] = 0;
            if (!radio_watch(said)) {
                said[0] = 0;        // nothing new: what it holds has been logged
            }
            if (strncmp(said, "npr: ", 5) == 0) {
                // The station's figures, which are whole as they come.
                ESP_LOGI(TAG, "%s", said);
            } else if (said[0] != 0) {
                conn_ping_t ping;
                conn_ping(&ping);
                // What it says of the console's buttons, from "; pad" on,
                // is for a firmware built to log at the debug level.
                char *pad = strstr(said, "; pad ");
                if (pad != NULL) {
                    *pad = 0;
                    pad += 2;
                }
                ESP_LOGI(TAG, "peer: %s", said);
                if (pad != NULL) {
                    ESP_LOGD(TAG, "peer: %s", pad);
                }
                ESP_LOGI(TAG, "peer: network %lu us there and back, least %lu, most %lu; "
                         "of %lu, %lu over 14 ms and %lu over 40 ms",
                         (unsigned long)ping.last_us, (unsigned long)ping.least_us,
                         (unsigned long)ping.most_us, (unsigned long)ping.count,
                         (unsigned long)ping.over_14ms, (unsigned long)ping.over_40ms);
            }
        }
        if (now - screen_at >= SCREEN_MS) {
            screen_at = now;
            turn(false);
            draw();
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

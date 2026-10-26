# esp_hid, with a fix to its NimBLE host

ESP-IDF's own `esp_hid` component, copied from ESP-IDF v5.5.5 so that it
takes the place of the one in ESP-IDF (a component of the project's has
the precedence). One file is not v5.5.5's: `src/nimble_hidh.c` is ESP-IDF
master's at commit 56f1ae2 ("fix(nimble): Fix nimble HID service
discovery", 2026-09-11), and that commit is the only difference.

In v5.5.5 (and in v6.0.3) the HID service's characteristics fall into the
Device Information service's branch and are passed over: a keyboard's
report map is never read, none of its reports is recorded, and none of
their notifications is turned on. The keyboard connects and pairs, and
nothing it types arrives (`firmware/main/keyboard.c`).

Delete this directory once the ESP-IDF the firmware is built with has the
fix.

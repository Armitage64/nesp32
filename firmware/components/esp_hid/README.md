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

`src/nimble_hidh.c` has three changes of nesp32's own too, each marked
"nesp32:". Two are since Wi-Fi shares the radio with Bluetooth. A connection is
looked for 10% of the time (20 ms in every 200), where NimBLE's own
parameters look all the time, for as long as a paired keyboard is asleep
(one being paired is looked for all the time: at 10% an MX Keys S was
missed half the time, and the pairing failed); and a
keyboard that asks for a connection interval shorter than 30 to 50 ms has
that, which is airtime Wi-Fi does without. A key is then at most some 50 ms
later, and waking a keyboard may take a fraction of a second more. The
third turns a keyboard's reports on only once the link is encrypted: one
pairing for the first time may finish after its services are read. A
TECKNET keyboard types nothing on that connection even so, and
`firmware/main/keyboard.c` connects to a keyboard again once it is paired.

Delete this directory once the ESP-IDF the firmware is built with has the
fix, keeping those three.

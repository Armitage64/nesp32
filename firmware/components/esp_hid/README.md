# esp_hid, with nesp32's changes to its NimBLE host

ESP-IDF's own `esp_hid` component, copied from ESP-IDF v6.1.1 so that it
takes the place of the one in ESP-IDF (a component of the project's has
the precedence). Only `src/nimble_hidh.c` differs from v6.1.1's, by the
three changes below; `test_apps` is left out.

Until v6.1.1 the copy was v5.5.5's with ESP-IDF master's `nimble_hidh.c`
from commit 56f1ae2 ("fix(nimble): Fix nimble HID service discovery",
2026-09-11). In v5.5.5 and v6.0.3 the HID service's characteristics fall
into the Device Information service's branch and are passed over: a
keyboard's report map is never read, none of its reports is recorded, and
none of their notifications is turned on. The keyboard connects and
pairs, and nothing it types arrives (`firmware/main/keyboard.c`). v6.1.1
has that fix, and its `esp_hid_common.c` checks a report map's sizes and
counts for overflow, where v5.5.5's did not.

`src/nimble_hidh.c` has three changes of nesp32's own, each marked
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
`firmware/main/keyboard.c` connects to one again once it is paired, but for
a Logitech one, which then sleeps until a key is pressed.

Delete this directory if ESP-IDF's own NimBLE HID host comes to do what
those three do. When the firmware moves to a newer ESP-IDF, copy that
version's `esp_hid` here and carry over the three changes marked
"nesp32:".

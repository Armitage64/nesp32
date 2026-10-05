# NESpedia on an M5Stack Stick

The reader's host: a Stick on M5Stack's **UIFlow 2.0** firmware
(MicroPython) that fetches articles from Wikipedia over Wi-Fi and answers
the NES's requests for their lines over the controller-port link.

**It works on an M5StickC Plus2 with a real NES.** The StickS3 has not
been tried. The parts that do not touch hardware (`wikitext.py`, `wrap.py`,
`proto.py`, `server.py`, `fetch.py`) are also tested on a desktop, the
server against the link ROM on a simulated console.

| Board | TX | RX |
|---|---|---|
| M5StickC Plus2 | G26 (hat slot 3) | G36 (hat slot 4) |
| M5StickS3 | G8 (hat slot 5) | G1 (hat slot 4) |

## The hat

nes-radar's two-transistor NPN hat, unchanged, wired as for the jukebox:
see [nes-jukebox's README](../../../nes-jukebox/firmware/stick/README.md),
"The hat", for the slots, and why **the TX wire is on a different slot for
each board** (G0, the boot-mode pin, must never be touched by the shifter).

The link runs at 85227 baud. The jukebox's throughput test carried
149148 baud to the console with a receiver of this kind and 223722 from
it, on a Plus2 hat, and this link works on that hat. The S3's hat design
uses a 100 kΩ RX base resistor, which slows that stage's edges, and is
untried at this rate.

## Setup

1. **UIFlow 2.0** on the Stick, flashed with
   [M5Burner](https://docs.m5stack.com/en/uiflow2/m5burner/intro).
2. **Wi-Fi.** Save a network in M5Burner's configure step, or from a
   terminal:

   ```sh
   python3 tools/set_wifi.py
   ```

   The firmware joins the network UIFlow has saved. The password is never
   in a file here or on the Stick's filesystem.
3. **Deploy**, with the Stick on USB:

   ```sh
   pip install mpremote
   tools/deploy.sh                      # or: tools/deploy.sh -p /dev/cu.usbserial-XXXX
   ```

   It copies the firmware to `/flash` and sets UIFlow to start it at
   power-on. `tools/restore_uiflow.sh` brings the UIFlow launcher back.
4. **Optional `config.json`** next to `config.example.json`: `board`
   (`"s3"` or `"plus2"`) if the screen says `unknown board`, `tx` and `rx`
   pin numbers for a hat wired some other way, and `invert` (`false` for a
   non-inverting shifter).
5. **Optional `/flash/ca.der`**: a CA certificate in DER form. With it the
   connection to Wikipedia is verified; without it the connection is
   encrypted but the server is not authenticated, as in nes-radar.

## Using it

Plug the hat into controller port 2 and start `build/nespedia_link.nes` on
the console. The order of powering up does not matter. Searching and
reading are done on the console; the Stick only shows what it is doing:

| Row | Meaning |
|---|---|
| STATE | `IDLE`, `NO WI-FI`, `FETCHING`, `READY`, `NOT FOUND` or `ERROR` |
| WI-FI | the network joined, or `not joined` |
| (title) | the search while it is fetched, then the article's title |
| LINES | lines in the article held; `so far` while more will be fetched as it is read |
| LINK | requests heard, lines served, and bytes that were not part of a request |

Bytes that are not part of a request climb by 60 a second while the
console is on: its controller read pulls the line low once a frame, and
the UART takes that for a byte. That is expected.

Hold **B** for 2 seconds to power off.

## The USB log

With the Stick on USB, `mpremote` shows what it prints (Ctrl-] leaves).
Attaching may restart a Plus2; to see the start-up lines, reset it while
attached. Two lines come every 5 seconds:

```text
req 873 lines 446 late 2 noise 1887 held 177 reached 121 reopened 0 connect 1466 ms; max us: turn ... poll ... chore ... work ... gc ...; slow turns 3; free 1231184 threshold ...
  turns 48000; answers 43 avg 1400 us; chores 35 avg 4452 us, buttons max 152, paint max 13444; late: away 0, together 2
```

| Field | Meaning |
|---|---|
| `req`, `lines` | requests heard, and how many were for lines. While part of an article is still to come the console asks its length four times a second, so `lines` climbs even with the screen still |
| `late` | requests found behind a newer one, and so never answered: the Stick went a frame without looking. **This is the number to watch.** It should hardly move |
| `held`, `reached` | lines laid out, and the furthest line the console has been given. `held` stays two pages or so ahead |
| `reopened` | times the search was made again because the waiting connection had gone |
| `connect` | milliseconds to reach Wikipedia for the last search |
| `max us` | the longest turn of the loop, poll of the link, housekeeping, piece of laying out, and collection, in these 5 seconds |
| `slow turns` | turns of the loop longer than 8 ms |
| `answers ... avg` | what answering a request takes. A millisecond or two; it was 26 when the loop was making garbage |
| `late: away`, `together` | late requests found after a long turn, and after a short one |

## Bring-up on hardware

Do these in order; each isolates one thing.

1. **The standalone ROM**, `build/nespedia.nes`, in Mesen 2 and then on the
   console from a flash cart, with no Stick. This is the first time the
   split under the header meets a real PPU: the header should stand still
   while the text scrolls, with no flicker on the line between them.
2. **Boot check.** With the hat on and the NES on, power-cycle the Stick.
   It must start and show `IDLE`. A black screen with the hat on, and a
   normal start with it off, means something reaches G0.
3. **NES to Stick only:** `mpremote run tools/link_monitor.py`, then start
   the link ROM and press Start on the console. Expect
   `SEARCH id 1 'Nintendo Entertainment System'` about seven times a
   second, and the count of other bytes climbing by 60 a second. This
   proves OUT0, the RX stage and the baud rate without the Stick sending
   anything. Run `mpremote reset` afterwards.
4. **A search.** Reset the NES and press Start. The Stick should say
   `FETCHING`, then `READY` with a line count (about 2500 for the
   default), and the console should open the article. If the console
   says `NO ANSWER FROM THE STICK` while the Stick shows requests arriving,
   the Stick-to-NES direction is at fault.
5. **Scroll.** Hold Down through the article and page both ways. Scrolling
   that pauses means replies are arriving too late in the frame: the Stick
   has about 5 ms from the end of a request, and the USB log's `late`
   count says how often it missed. If `late` climbs, `answers ... avg` and
   the `max us` figures say what the Stick was doing instead.

On a StickC Plus2 all five steps pass.

## Files

| Path | Purpose |
|---|---|
| `neswiki/linkrate.py` | the rate and sizes both ends share |
| `neswiki/wikitext.py` | the API request; from its reply, as it streams, to ASCII text |
| `neswiki/wrap.py` | the article as lines of 28 characters |
| `neswiki/proto.py` | the link's frames, and the decoder for what the UART hears |
| `neswiki/server.py` | answers the console from the article |
| `neswiki/fetch.py` | reads and lays out an article a few pages ahead of the reader |
| `neswiki/net.py` | Wi-Fi and HTTPS (UIFlow only) |
| `neswiki/board.py`, `ui.py`, `device.py` | pins and UART per board, the screen, and the main loop (UIFlow only) |
| `tools/deploy.sh` | copy everything to the Stick |
| `tools/link_monitor.py` | bench helper for step 3 |
| `tools/set_wifi.py`, `stick_repl.py`, `restore_uiflow.sh` | from nes-radar: save Wi-Fi settings; run code without a soft reset; go back to the UIFlow launcher |

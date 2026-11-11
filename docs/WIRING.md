# Wiring

This is the hat every nesp32 uses, between an M5StickS3 or an M5StickC Plus2
and controller port 2: its circuit, its pins, and why it is needed. The
board itself, with its parts and pictures, is in
[`hardware/`](../hardware/); this page also has how to wire the same
circuit by hand on M5Stack's proto hat, two other level shifters that
would do, and three resistors that do without one. The circuit was first
worked out for nes-radar.

Whether the link is inverted is `CONFIG_NESP_LINK_INVERTED`
([`firmware/main/Kconfig.projbuild`](../firmware/main/Kconfig.projbuild)):
on for the NPN shifter and the SN74LV1T04 alternative, which both invert,
and off for the single‑gate buffers and the resistor network, which do
not. The firmware for the hat has it on. The generic ESP32‑S3 firmware
(`firmware/sdkconfig.defaults.generic`, built in `build-esp32s3-generic`)
has it off, and is the one the [installer](https://nesp32.retrobits.tv/flash/)
writes when **Resistors (non‑inverting)** is chosen. It is ESP32‑S3 only,
on the StickS3's pins, G1 and G8.

The ESP32‑S3 is a 3.3 V part and **not 5 V tolerant**, and a 3.3 V high is not
guaranteed to register on the NES. Each direction goes through one NPN
transistor stage, all through‑hole, which fits the M5Stick proto hat's 5 × 8
board with no adapters. See [Why a level shifter](#why-a-level-shifter).

The link uses the StickS3's 16‑pin Hat2‑Bus, the GPIO header at the bottom
end, furthest from the LCD screen. The proto hat's 8‑pin plug
fits its odd row (pins 1–15), which keeps the old StickC hat order, and a
StickC Plus2's 8‑pin header takes it as it is. It does not use the Grove
port.

One hat serves both boards. Its slots reach different pins on each, the link
is on the same two slots, and the firmware picks the pins by the board it
was built for.

| Hat slot | Hat2 pin | StickS3 | StickC Plus2 | Use |
|---|---|---|---|---|
| 1 | 1 | GND | GND | common ground |
| 2 | 3 | EXT_5V | 5V OUT | **not connected.** On a StickS3, a power input by default. |
| 3 | 5 | G0 | G26 | **not connected.** The StickS3's boot‑mode pin; see below. |
| 4 | 7 | G1 | G36/G25 | RX, from the RX transistor's collector |
| 5 | 9 | G8 | G0 | TX, to the TX transistor's base resistor |
| 6 | 11 | BAT | BAT | not connected |
| 7 | 13 | 3V3_L2 | 3V3 | RX pull‑up (0.33 mA while OUT0 is high) |
| 8 | 15 | 5V_IN | 5V IN | not connected |

> [!WARNING]
> **Nothing may touch slot 3.** It is G0 on a StickS3, and if anything holds
> that low at power‑up, the StickS3 starts in firmware‑download mode instead
> of nesp32's firmware. Both stages would: a TX base resistor holds G0 near 1.2 V
> through the transistor's base junction, and the RX collector sits low
> whenever the NES idles OUT0 high.

On a **StickC Plus2**, G36 is input‑only and shares its pad with G25, which
must stay an input. G0 is that board's boot‑mode pin too, and it carries the
TX base resistor there; a Plus2 started from off a number of times with the
hat on, the console on and off, and came up in nesp32's firmware every time.
No level on it has been measured.

The rest of this page names the StickS3's pins. On a Plus2, read G8 as G0,
G1 as G36 and 3V3_L2 as 3V3.

G3 (a JTAG strapping pin) and G43/G44 (UART0, which carries the boot ROM's
log) are avoided on purpose. The even row is out of the proto hat's reach.

## The NES controller plug

The hat reaches the console through a controller pigtail: a controller plug
on a cable with bare wires at the other end. Four of its seven pins are used.
The pin numbers on this page are the ones below, **viewed looking into the
jack on the front of the console**:

```
               .
pin 1 GND  -- |o\
pin 2 CLK  -- |o o\ -- pin 5 +5V
pin 3 OUT0 -- |o o| -- pin 6 D3
pin 4 D0   -- |o o| -- pin 7 D4
               '--'
```

The pigtail's plug is the mirror image, **viewed looking at its pins**:

```
                .
               /o| -- pin 1 GND
pin 5 +5V -- /o o| -- pin 2 CLK
pin 6 D3  -- |o o| -- pin 3 OUT0
pin 7 D4  -- |o o| -- pin 4 D0
             '--'
```

> **Check your orientation before soldering.** The plug's mating face and its
> wire/solder side are mirrored. Confirm you are counting pins in the direction
> above — not from the back of the connector. See the
> [NESdev controller port pinout](https://www.nesdev.org/wiki/Controller_port_pinout).

The column of four, with GND at the end beside the slanted corner, carries
everything nesp32 uses except +5 V, which is at the top of the column of
three. CLK, D3 and D4 are not connected.

| Pin | Signal | Direction | Hat pad | Official wire colour |
|---|---|---|---|---|
| 1 | GND | – | GND(1) | brown |
| 2 | CLK | console → controller | – | red |
| 3 | OUT0 (strobe) | console → controller | OUT(3) | orange |
| 4 | D0 | controller → console | D0(4) | yellow |
| 5 | +5 V | console → controller | 5V(5) | white |
| 6 | D3 | controller → console | – | – |
| 7 | D4 | controller → console | – | – |

On the hat's board the four pads at the edge opposite the 8‑pin header are,
from the end nearest the header's GND pin, 5V(5), OUT(3), D0(4) and
GND(1), the last on the square pad. Each is labelled on the silkscreen.

**Find each wire with a multimeter, not by its colour.** The colours are the
ones Nintendo's own controllers use; aftermarket pigtails and extension
cables often use others. With the cable unplugged, set the meter to
continuity, hold one probe on a pin of the plug and touch the other to each
bare wire until it beeps. Mark each wire as you find it.

## NPN shifter (default, through‑hole)

This is the circuit on the hat's board in [`hardware/`](../hardware/),
which has the parts to buy.

```
 TX (Stick → NES)                          RX (NES → Stick)

 NES +5 V (pin 5)                          Stick 3V3_L2
     │                                         │
   [3.3 kΩ]                                  [10 kΩ]
     │                                         │
     ├──[1 kΩ]──► NES D0 (pin 4)               ├──────► Stick G1
     │                                         │
    C│                                        C│
 G8  ─[10 kΩ]─B  2N3904              NES OUT0─[100 kΩ]─B  2N3904
    E│                              (pin 3)   E│
    GND                                        GND

 Stick GND ── NES GND (pin 1)
 EXT_5V, 5V_IN, BAT, G0 ── not connected
```

**Parts:** two 2N3904 (TO‑92), two 10 kΩ, one 3.3 kΩ, one 100 kΩ, and one
1 kΩ resistor. Any small NPN works (2N2222A, BC547, PN2222); check the E‑B‑C lead
order, which differs between parts and makers.

| From | Through | To |
|---|---|---|
| Stick G8 | 10 kΩ | TX 2N3904 base |
| TX 2N3904 emitter | – | GND |
| TX 2N3904 collector | 3.3 kΩ | NES pin 5 (+5 V) |
| TX 2N3904 collector | 1 kΩ | NES pin 4 (D0) |
| NES pin 3 (OUT0) | 100 kΩ | RX 2N3904 base |
| RX 2N3904 emitter | – | GND |
| RX 2N3904 collector | 10 kΩ | Stick 3V3_L2 |
| RX 2N3904 collector | – | Stick G1 |
| Stick GND | – | NES pin 1 (GND) |

**How it works.** Each stage inverts, and the ESP32 UART inverts TX and RX in
hardware to cancel it (`CONFIG_NESP_LINK_INVERTED` on, the default).

- **TX:** the UART idles with G8 low, so the transistor is off and the
  3.3 kΩ pull‑up holds D0 at the NES's own 5 V, which is idle (mark). A space
  bit turns the transistor on and pulls D0 to about 0.1 V. A 2N3904 switches at
  about 0.7 V on its base, so 3.3 V drives it hard, and both levels sit far
  inside the NES input's limits.
- **RX:** OUT0 high turns the transistor on and pulls G1 low; the UART's RX
  inversion restores it. It works whenever OUT0 reaches about 1.5 V, so how
  high the NES CPU's unbuffered OUT0 really goes no longer matters. It draws
  about 30–45 µA from OUT0.
- **Why the RX base resistor is 100 kΩ:** OUT0 is the strobe shared by both
  controller ports, so the RX stage must load it lightly. A MiSTer SNAC
  adapter pulls its lines high through only 10 kΩ (BSS138 level shifters).
  With a 10 kΩ base resistor that formed a divider, and the strobe stopped at
  about 2.85 V, below the 3.5 V that a controller's CD4021 needs. Both
  controllers stopped responding. At 100 kΩ the strobe reaches about 4.6 V.
  The transistor still saturates: it sinks only 0.33 mA, and about 8 µA of
  base current is enough even at a 2N3904's minimum gain.
- **Idle and power states:**
  - While the Stick is off or booting, G8 floats, the TX transistor stays
    off, and D0 rests high, the correct idle level.
  - While the NES is off, OUT0 is low, so G1 reads a break, which the decoder
    ignores.
  - Pull‑ups come from the side they drive: D0's from the NES, G1's from the
    Stick. Nothing actively drives a powered‑down side. The small leftover paths
    through a transistor's base junction (a fraction of a milliamp, via
    10 kΩ) are about a tenth of what the tested FTDI cable pushes into an
    unpowered NES through its 1 kΩ.
- **Why the TX pull‑up is 3.3 kΩ:** D0 falls as fast as the transistor
  turns on, but rises only as fast as the pull‑up charges the cable and the
  console's input. With 10 kΩ the throughput test's climb on a real NES
  stopped at 149148 baud to the console, and on another hat and two other
  consoles at 111861. With about 3.2 kΩ (a 4.7 kΩ across the 10 kΩ) it
  reached 198864; about 2.1 kΩ, or a 470 Ω in place of the 1 kΩ, did no
  better. The rates it gained, 162707 to 198864, are ones the jukebox and
  NPR play at with receivers that hunt for each start bit, which a late
  edge costs most. The transistor sinks about 1.5 mA when D0 is low, a
  milliamp more than with 10 kΩ and under one on average, and its 0.26 mA
  of base current still saturates it, with five times what it needs.
- **Speed:** the board carries 298296 baud to the console, the last rate
  the console's CPU can take, on a real NES as on the MiSTer through a SNAC
  adapter ([the throughput test](../apps/throughput/README.md)). On a real
  NES the climb stopped at 198864 all the same: a sweep passed every rate
  from 14 cycles a bit to 6 but 8, which lost about one byte in nine,
  every time. 8 cycles had the receiver that hunts for each start
  bit, and 7 and 6 the one that tracks it, so it was the hunt that failed
  there, not the line; why a real console's hunt fails at 8 cycles and the
  MiSTer's does not is not known. From 8 cycles down the console's
  receivers track now, in the throughput test and in the jukebox's and
  NPR's sound, whose fastest rate is 7 cycles, 255682 baud; with them the
  climb on a real NES reaches 298296 baud, and sound and NPR play at
  255682. The 100 kΩ base
  resistor slows the RX transistor's edges to a few µs (estimated, not
  measured); the slowest is turn‑off, when OUT0 falls. From the console
  the board carries 223722 baud, on a real NES as on the MiSTer, and
  298296 fails; nothing the console sends is near that fast, its
  requests going at 85227.
- **Not every 2N3904 is fast enough:** the speed depends on which 2N3904s
  you fit. Cheap no‑name 2N3904s from Amazon (BOJACK brand, marked H331)
  were too slow: on a hat built with them, the jukebox's 20338 Hz sound
  failed and only its 10169 Hz sound played. Swapping in 2N3904s marked
  K02 fixed it, and the 20338 Hz sound plays. The likely cause is
  turn‑off delay (storage time), which varies a lot from one maker or
  batch to another, but it was not measured. If a hat passes at low rates
  and fails at high ones, try 2N3904s from another source first.
- **Why the 1 kΩ stays:** it is the same fault‑current limiter the FTDI
  cable uses on D0. On the RX side the 100 kΩ base resistor does that job.

**Fit on the 5 × 8 proto hat**, to wire it by hand in place of the board:
- Each TO‑92 takes 3 holes in a row. After soldering, bend it over flat so it
  stands about 3 mm tall.
- Use 1/8 W mini resistors laid flat across 3 holes (0.3″); they stand about
  2 mm tall.
- The whole circuit uses about 21 of the 40 holes.
- Make all connections with the NES off and the Stick off. Identify leads by
  continuity, not color.

## Alternative: SN74LV1T04 (surface mount, inverting)

Two TI SN74LV1T04 single inverters (`SN74LV1T04DBVR`, SOT‑23‑5, 0.95 mm
pitch), one per direction, each on its own SOT‑23‑5‑to‑DIP adapter. Each
stage inverts, as the NPN stages do, so this uses the same firmware: the
hat's, with **`CONFIG_NESP_LINK_INVERTED` on**. Only the supply differs between the two: the TX
part is powered by the NES and the RX part by the Stick.

```
 TX (Stick → NES): powered by the NES

                           NES +5 V (pin 5)
                                   │
                                   ├──┤├── GND (0.1 µF)
                                 5 │
                             ┌─────┴─────┐
 Stick G8 ──────────┬──── 2 ─┤ A  >o  Y  ├─ 4 ──[1 kΩ]──► NES D0 (pin 4)
                    │        │ LV1T04    │
                [100 kΩ]     └─────┬─────┘
                    │            3 │
                   GND            GND

 RX (NES → Stick): powered by the Stick

                             Stick 3V3_L2
                                   │
                                   ├──┤├── GND (0.1 µF)
                                 5 │
                             ┌─────┴─────┐
 NES OUT0 ──[1 kΩ]──┬──── 2 ─┤ A  >o  Y  ├─ 4 ─────────► Stick G1
                    │        │ LV1T04    │
                [100 kΩ]     └─────┬─────┘
                    │            3 │
                   GND            GND

 NES GND (pin 1) ── Stick GND
 EXT_5V, 5V_IN, BAT, G0 ── not connected
```

**Parts:** two SN74LV1T04DBVR, two 1 kΩ, two 100 kΩ, and two 0.1 µF ceramic
capacitors. There is no through‑hole version; to breadboard it, solder the
parts onto SOT‑23‑5 breakout boards.

| From | Through | To |
|---|---|---|
| Stick G8 | – | TX LV1T04 pin 2 (A) |
| TX LV1T04 pin 2 (A) | 100 kΩ | GND |
| TX LV1T04 pin 4 (Y) | 1 kΩ | NES pin 4 (D0) |
| TX LV1T04 pin 5 (VCC) | – | NES pin 5 (+5 V) |
| TX LV1T04 pin 5 (VCC) | 0.1 µF | GND |
| TX LV1T04 pin 3 (GND) | – | GND |
| NES pin 3 (OUT0) | 1 kΩ | RX LV1T04 pin 2 (A) |
| RX LV1T04 pin 2 (A) | 100 kΩ | GND |
| RX LV1T04 pin 4 (Y) | – | Stick G1 |
| RX LV1T04 pin 5 (VCC) | – | Stick 3V3_L2 |
| RX LV1T04 pin 5 (VCC) | 0.1 µF | GND |
| RX LV1T04 pin 3 (GND) | – | GND |
| Stick GND | – | NES pin 1 (GND) |

Pin 1 is not connected inside the part; leave it open or ground it. Fit each
capacitor right at its part's pins 5 and 3.

- **Why it works both ways:** the LV1T family's inputs switch at lower
  levels than ordinary CMOS and take up to 5.5 V whatever the supply (rated
  to 7 V absolute). Per TI's datasheet (SCLS738E):
  - **TX**, at 4.5–5 V: the input reads a high at 2.03 V or more, so G8's
    3.3 V has margin. The output is guaranteed 3.95 V or more while sourcing
    8 mA at 4.5 V, and 4.5 V or more at 5 V; the real load is microamps, so
    it sits within 0.1 V of the supply, well above the 3.5 V the NES's '368
    needs.
  - **RX**, at 3–3.3 V: the input reads a high at 1.37 V or more, so how high
    the NES CPU's unbuffered OUT0 goes matters even less than with the NPN.
- **Speed:** propagation delay is 7 ns or less into 30 pF, and the output
  drives D0 both ways, so its rising edge no longer waits on a pull‑up as
  the NPN stage's does. The RX stage has no transistor storage time.
- **Results.** Tested with [the throughput test](../apps/throughput/README.md)
  on a breadboard wired to a StickS3, each part on its own SOT‑23‑5
  breakout board.
  - **Real NES:** 298296 baud both ways, over several climbs. That is the
    fastest rate the test has in each direction. From the console the NPN
    board stops at 223722.
  - **MiSTer, through a SNAC adapter:** 298296 baud from the console and
    255682 to it. That was with the first build, before the fault below
    was found, and has not been run again since.
  - **A bad breadboard contact looked like a slow line.** The first build
    reached only 149148 baud to a real NES. Its sweep was the same every
    time: 10, 7 and 6 cycles a bit failed, with about 100, 260 and 400 of
    1024 bytes wrong; 8 cycles was always clean; 11 and 9 changed from
    run to run. The throughput test's simulator gives that pattern when
    D0's falling edges arrive about 2–2.5 CPU cycles (1.1–1.4 µs) late,
    which shortens every low bit. The gate itself switches in
    nanoseconds. The TX side was rebuilt from the same parts, with nothing
    changed, and passed 298296 every time after that. The likely cause is
    a high‑resistance contact in the TX gate's ground: pin 3, its rail,
    or the ground wire to the console. The gate pulls D0 and the cable
    low through that path, so only falling edges slow. A bad contact on
    VCC would slow the rising edges instead, and lengthen the lows, as the
    NPN stage's pull‑up does. If a breadboard build's sweep shows this
    pattern, measure from the TX gate's pin 3 to the console's GND pin
    with everything on; it should read a few millivolts. The MiSTer did
    not show the fault, perhaps because the SNAC adapter's 10 kΩ pull‑up
    slows the rising edges and makes up for it.
- **Why the 100 kΩ pull‑downs:** a CMOS input must not float. On TX it holds
  G8's input low while the Stick is off or booting, so D0 rests high, the
  correct idle level. On RX it holds the input low while the NES is off, so
  G1 reads a break, which the decoder ignores. Together with the 1 kΩ it
  draws about 50 µA from OUT0, about what the NPN's 100 kΩ base resistor
  draws; with a MiSTer SNAC adapter's 10 kΩ pull‑up the strobe still
  reaches about 4.5 V.
- **Why the 1 kΩ resistors:** the one on D0 is the same fault‑current
  limiter the FTDI cable uses. The one on OUT0 limits current into the RX
  input, the job the NPN's 100 kΩ base resistor does.
- **Power states:** each part is powered by the side it drives, so nothing
  actively drives a powered‑down side. The inverted UART idles G8 low, so
  it pushes almost nothing into the TX part while the NES is off.
- **Extra supply current:** a 3.3 V high on an input of a part running at
  5 V makes it draw up to about 1.5 mA more from the NES's 5 V. That
  happens only while G8 is high, during space bits. It is harmless.
- **On a StickC Plus2** the TX slot is G0, that board's boot‑mode pin, and
  the 100 kΩ pull‑down loads it. That is a lighter load than the NPN
  stage's 10 kΩ into the transistor's base, which boots reliably, so it
  should boot too, but it has not been tried.
- **OUT0's edge rate, tested on one console.** The datasheet asks that
  inputs rise and fall no slower than 20 ns per volt; a slower edge on a
  gate without hysteresis can make its output glitch. OUT0 comes from the
  2A03, an NMOS part, and drives the cable and both controllers; how fast
  its edges are has not been measured. The RX stage carried 298296 baud
  from the console on one NES‑001 and on the MiSTer, so there it needed
  no hysteresis. Other consoles have not been tried. If one's OUT0 is too
  slow, fit a Schmitt‑trigger
  SN74LVC1G14 for RX: it has the same SOT‑23‑5 footprint and pinout,
  inverts, reads a high at 1.87 V or less at a 3 V supply, has at least
  0.56 V of hysteresis, and takes 5.5 V on its input even unpowered. It
  cannot do TX: at a 5 V supply its rising threshold can be about 3.0 V,
  too close to G8's 3.3 V. The SN74LV1T14 would do both, but TI publishes
  no datasheet for it and no distributor lists it.

## Alternative: two single‑gate buffers (surface mount, non‑inverting)

Two SOT‑23‑5 (0.95 mm pitch) buffers, each on its own SOT‑23‑5/6‑to‑DIP
adapter. Use the generic ESP32‑S3 firmware, which has
**`CONFIG_NESP_LINK_INVERTED` off** (untried with these parts).

| Pin | TX: 74AHCT1G125, powered from NES pin 5 | RX: 74LVC1G125, powered from Stick 3V3_L2 |
|---|---|---|
| 1 OE (active low) | GND | GND |
| 2 A | Stick G8 | 1 kΩ from NES OUT0, plus 100 kΩ to GND |
| 3 GND | common GND | common GND |
| 4 Y | 1 kΩ, then NES D0 | Stick G1 |
| 5 VCC | NES pin 5, with 0.1 µF to GND | Stick 3V3_L2, with 0.1 µF to GND |

- Pinouts are for TI's `DBV` package, SN74AHCT1G125DBVR and SN74LVC1G125DBVR.
- The AHCT input needs only 2.0 V for a high, and its output swings to 5 V.
  Powered from the NES, it switches off with the console.
- LVC inputs tolerate 5.5 V even when unpowered and need only 2.0 V for a high
  at a 3.3 V supply. The 100 kΩ holds the input low when the NES is off.
- The DIP‑14 SN74AHCT125N can replace the TX part: use one gate, tie its OE
  low, and tie each unused gate's input to GND and its OE high.

**Not recommended:** a 1 kΩ series resistor plus 2 kΩ to GND on the RX side.
It only guarantees a high if OUT0 stays **at or above 3.7 V** under that
1.7 mA load, which is undocumented.

## Alternative: three resistors (no level shifter)

No transistors and no chips: a divider takes OUT0 down to the Stick's
level, and G8 drives D0 straight, through a resistor. Neither direction
inverts, so use the generic ESP32‑S3 firmware, which has
**`CONFIG_NESP_LINK_INVERTED` off**: **Resistors (non‑inverting)** in the
[installer](https://nesp32.retrobits.tv/flash/), or
`firmware/deploy.sh --generic`.

```
 TX (ESP32 → NES)                      RX (NES → ESP32)

 GPIO8 ──[1 kΩ]──► NES D0 (pin 4)      NES OUT0 ──[47 kΩ]──┬──► GPIO1
                                       (pin 3)             │
                                                        [100 kΩ]
                                                           │
                                                          GND

 ESP32 GND ── NES GND (pin 1)
```

**Parts:** one 1 kΩ, one 47 kΩ and one 100 kΩ resistor.

| From | Through | To |
|---|---|---|
| ESP32 GPIO8 | 1 kΩ | NES pin 4 (D0) |
| NES pin 3 (OUT0) | 47 kΩ | ESP32 GPIO1 |
| ESP32 GPIO1 | 100 kΩ | GND |
| ESP32 GND | – | NES pin 1 (GND) |

**What each resistor is for:**
- **47 kΩ and 100 kΩ, the RX divider.** Together they take OUT0's 5 V to
  5 × 100 / 147 ≈ 3.4 V at G1, inside the 3.6 V the ESP32‑S3 takes on a
  pin and above the 2.48 V it needs for a high. The ratio sets the level,
  and the values are high so that the divider loads OUT0 lightly: about
  34 µA, as the NPN shifter's 100 kΩ base resistor does. OUT0 is the strobe
  both controllers share, and a MiSTer SNAC adapter pulls it high through
  only 10 kΩ; with this load it still reaches about 4.7 V there. The 47 kΩ
  also limits the current into G1 when the Stick is off, to under 0.1 mA.
  Higher values would slow G1's edges: the divider's 32 kΩ into a pin's
  few picofarads is about 0.3 µs, half a CPU cycle (estimated, not
  measured).
- **100 kΩ, also:** it holds G1 low when the NES is off, so G1 reads a
  break, which the decoder ignores.
- **1 kΩ on D0.** The same fault‑current limiter the FTDI cable and the
  NPN shifter use. G8 drives both ways, so D0 rises as fast as it falls
  and no pull‑up is needed; 470 Ω did no better on the NPN shifter.

**Results.** Tested with [the throughput test](../apps/throughput/README.md)
on an ESP32‑S3 dev board wired straight to the controller port, on the
same G1 and G8 the StickS3 uses, on the MiSTer through
a SNAC adapter and on a real NES‑001.
- **NES to nesp32:** 298296 baud on the MiSTer, the fastest rate the test
  has, where the NPN shifter stops at 223722.
- **nesp32 to NES, real NES:** five climbs, all to 298296 baud.
- **nesp32 to NES, MiSTer:** of 18 climbs after a night powered off, 8
  reached 298296, 6 stopped at 255682, 1 at 223722 and 3 at 178977.
  Nothing about it changed as the hardware warmed up. Every rate a program
  uses passed every time but 7 cycles a bit, the jukebox's and NPR's
  fastest sound, which failed once in 15 trials. The faster rates failed
  in two ways: at 6 cycles, in 6 trials of 14, a whole block came wrong
  (246–248 of its 248 bytes) from its first byte, which points at the
  console's tracking receiver settling on the block's start rather than at
  the line; at 9, a rate no program uses, one byte now and then. The real
  NES showed neither.

**Risks:**
- **D0's high is only 3.3 V.** The NES‑001's 74HC368 is guaranteed to read
  a high only from about 3.5 V ([why](#why-a-level-shifter)). One
  front‑loader read it at every rate, but that is typical behaviour, not
  the datasheet's; other consoles, the top‑loader, the Famicom and PAL
  consoles have not been tried.
- **G1 is guaranteed a high only while OUT0 is 3.64 V or more**, and how
  high the 2A03's OUT0 stays is not documented. It reached about 4.6 V
  under the NPN shifter's similar load.
- **G8 drives a console that is off.** It idles high, so with the NES off
  it pushes up to about 2.7 mA through the 1 kΩ into the console, as the
  FTDI cable does. The shifters take their power from the side they drive
  and do not.
- **D0 is not held at idle while the Stick is off or booting.** G8 floats
  then, and D0 rests wherever the console leaves it. The NPN shifter's
  pull‑up holds it high.
- **Not for a StickC Plus2.** Its TX is G0, the boot‑mode pin, and the
  1 kΩ ties it to D0: a low there at power‑up would start the board in
  firmware‑download mode. Not tried.

**Benefits over the shifters:**
- Three resistors: nothing to orient, no lead order to check, nothing to
  go wrong with a transistor's make, and no surface‑mount parts.
- Three wires to the controller plug (GND, OUT0, D0), and no supply wiring:
  neither the NES's +5 V nor the Stick's 3.3 V.
- No transistor storage time and no slow pull‑up: it carries 298296 baud
  from the console, where the NPN shifter stops at 223722, and its edges
  do not depend on which 2N3904s were fitted.

## Why a level shifter

**Stick → NES (D0).** On an NES‑001 front‑loader, D0 goes into a 74HC368
inverting buffer powered at 5 V. TI's SN74HC368 datasheet guarantees a high
only above 3.15 V at a 4.5 V supply and 4.2 V at 6 V, which is about 3.5 V at
the NES's 5 V. The ESP32‑S3 drives about 3.3 V (guaranteed only
0.8 × 3.3 V ≈ 2.64 V). Straight 3.3 V would probably work, because HC gates
typically switch near 2.5 V, but it would rely on typical behaviour rather than
the datasheet. A marginal level shows up as bad samples in the ROM's
cycle‑timed receiver. One NES‑001 took it at every rate the throughput test
has ([the resistor network](#alternative-three-resistors-no-level-shifter)).
The top‑loader, Famicom, and PAL consoles have not been checked.

**NES → Stick (OUT0).** OUT0 comes straight from the NES's 2A03 CPU with no
buffer, and how high that NMOS output stays under load is not documented. The
ESP32‑S3 is not 5 V tolerant and needs at least 0.75 × 3.3 V ≈ 2.48 V for a
guaranteed high. The FTDI cable working does not settle this, because the
FT232R's input switches at a lower voltage.

**Why NPN rather than MOSFET:** the through‑hole MOSFETs (2N7000, BS170) are
only guaranteed to switch fully on by around 3 V, which leaves no margin at
3.3 V. The BSS138 used on level‑shift boards switches reliably at 3.3 V but is
surface mount. A bipolar transistor needs only about 0.7 V on its base.

Sources: [TI SN74LV1T04 datasheet](https://www.ti.com/lit/ds/symlink/sn74lv1t04.pdf),
[NESdev CPU pinout](https://www.nesdev.org/wiki/CPU_pinout),
[NESdev controller port pinout](https://www.nesdev.org/wiki/Controller_port_pinout),
[NESdev forum on the inverted '368 inputs](https://forums.nesdev.org/viewtopic.php?t=16734),
[raphnet NES VS mod (74HC368 at U7)](https://www.raphnet.net/electronique/nes_vs/nes_vs_en.php?section_id=5),
[TI SN74HC368 datasheet](https://www.ti.com/lit/ds/symlink/sn74hc368.pdf).

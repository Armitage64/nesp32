# NESP32 Build Guide

This guide is for building the NESP32 **hat**, the small circuit board
that connects an M5Stack Stick to the NES controller plug. If you already
have a finished, tested hat, you don't need this guide; go straight to
the [User Guide](USER_GUIDE.md).

## Contents

1. [Is this for you?](#1-is-this-for-you)
2. [What you need](#2-what-you-need)
3. [Before you start](#3-before-you-start)
4. [Building the hat](#4-building-the-hat)
5. [Checking your work](#5-checking-your-work)
6. [If the Stick starts in download mode](#6-if-the-stick-starts-in-download-mode)
7. [Next steps](#7-next-steps)

---

## 1. Is this for you?

You'll need to be comfortable with two things:

- **Basic through-hole soldering.** All the parts have wire legs that go
  through holes in the board. There are no tiny surface-mount parts,
  though the transistor pads are small.
- **Using a multimeter's continuity mode.** In this mode the meter beeps
  when its two probes are touching points that are electrically
  connected. You'll use it to work out which wire is which, and to check
  for mistakes before powering anything.

If either is new to you, it's worth practicing on scrap first, or asking
someone with experience to help. The hat sits between the NES's 5-volt
signals and the Stick's 3.3-volt electronics, so a wiring mistake can
damage the Stick.

---

## 2. What you need

### Parts for one hat

| Qty | Part |
|---:|---|
| 1 | NESP32 hat circuit board ([order from PCBWay](https://www.pcbway.com/project/shareproject/NESP32_Hat_for_M5_StickS3_d23db4e5.html)) |
| 2 | 2N3904 NPN transistors |
| 1 | 1 kΩ resistor |
| 2 | 10 kΩ resistors |
| 1 | 3.3 kΩ resistor |
| 1 | 100 kΩ resistor |
| 1 | Reverse 8-pin, 2.54 mm, right-angle male header |
| 1 | NES controller pigtail, or a controller extension cable cut to make one |

Use high quality transistors from a reputable vendor such as Digikey or Mouser. Generic / bulk components from Amazon, etc. can be relabeled general-purpose or audio spec parts with sub-par switching speeds that result in a lower maximum throughput. See [WIRING.md](WIRING.md) for details.

Part references and photos of both sides of a finished board are in
[hardware/README.md](../hardware/README.md). Keep the photos open while
you work.

### Tools

- Soldering iron, solder and flux
- Wire cutters and strippers
- A multimeter with continuity mode
- Good light, and ideally a magnifier for inspecting joints

---

## 3. Before you start

Read these before you pick up the iron:

- **Work with everything unplugged.** Switch off and unplug the NES and
  the Stick whenever you solder or check wires.
- **Never connect an NES wire straight to the Stick.** Protecting the
  Stick from the NES's 5 volts is the hat's whole job.
- **Don't trust the wire colors** on your pigtail. Aftermarket cables
  often use different colors from Nintendo's originals. You'll identify
  each wire with the meter instead.
- **Don't let solder join neighboring pads or pins.**
- **One position on the 8-pin header must stay unconnected.** On a
  StickS3 it's the position marked **G0 (slot 3)**. If it's connected to
  ground, for example by a stray blob of solder, the Stick starts in
  "download mode" instead of running the NESP32.

---

## 4. Building the hat

1. **Get your bearings.** Compare the bare board with the top and bottom
   photos so you know where each part goes and which way round.
2. **Sort the resistors by value.** The colored bands tell you the value,
   but if you're new to reading them, measure each one with the
   multimeter instead.
3. **Solder the resistors** into their marked positions.
4. **Solder the two transistors**, turned the way the board's outline and
   the photos show. The pads are small, so use extra flux. If you
   substitute a different transistor, check its leg order: it may not
   match the 2N3904.
5. **Solder the 8-pin connector**, facing the same way as in the photos.
   This decides which way the hat sits on the Stick, so double-check it
   before soldering.
6. **Identify the cable's wires.** With the meter in continuity mode, put
   one probe on a pin of the NES plug and touch the bare wire ends until
   it beeps. Note which wire goes to pins 1, 3, 4 and 5. The NES plug's
   pin numbering is drawn in
   [WIRING.md](WIRING.md#the-nes-controller-plug).
7. **Solder the four wires** to the hat:

   | NES plug pin | What it carries | Hat pad |
   |---:|---|---|
   | 1 | Ground | `GND(1)` |
   | 3 | Signal from the NES to the Stick | `OUT(3)` |
   | 4 | Signal from the Stick to the NES | `D0(4)` |
   | 5 | +5 V | `5V(5)` |

   Pins 2, 6 and 7 aren't used. Trim or insulate those wires so they
   can't touch anything.

> **Note:** even though the +5 V wire is connected to the hat, the hat
> does **not** power the Stick. That connection is deliberately left
> unused on the Stick's side. The Stick always runs from its own battery
> or a USB charger.

---

## 5. Checking your work

Do these checks before you connect the hat to anything.

**Look:**

- Check both sides of the board in good light.
- Look for solder joining two pads, joints that didn't flow properly,
  clipped legs touching another pad, and a transistor or connector the
  wrong way round.
- Look closely at the **G0 (slot 3)** position. Nothing should be
  touching it.

**Measure**, with nothing powered and the meter in continuity mode:

- Each of the four NES plug pins (1, 3, 4, 5) beeps to its own hat pad,
  and to no other pad.
- The +5 V pad does **not** beep to ground.

**Then fit it.** The hat goes on the Stick's **bottom connector**, at the
end furthest from the screen. Don't use the small Grove socket.

**Then test it.** Follow the [User Guide](USER_GUIDE.md) to install the
firmware and start the cartridge, then run **Setup → TEST INTERFACE**.
The **GOOD** count should keep rising along with **REQUESTS**, and
**NO REPLY** and **WRONG** should stay at zero.

If errors keep appearing, the fault is in the hat or cable, not the Wi-Fi.
Recheck the wire identification, the solder joints, which way round the
transistors and the 8-pin connector are, and the four cable connections.
Never bypass the hat to test a direct connection.

---

## 6. If the Stick starts in download mode

If the Stick goes into download mode instead of starting the NESP32
whenever the hat is fitted:

1. Unplug everything and remove the hat.
2. Switch the Stick on without the hat. If the NESP32 starts normally, the
   problem is on the hat.
3. On a StickS3, something on the hat is connecting the **G0 (slot 3)**
   position to ground. Look for a solder bridge, or a connector that's
   misaligned or soldered the wrong way round.

---

## 7. Next steps

Once the hat passes its checks, go to the [User Guide](USER_GUIDE.md) and
start at [Putting it together](USER_GUIDE.md#3-putting-it-together).

For the full circuit, and other ways to do the voltage conversion, see
[WIRING.md](WIRING.md). For help, ask on the
[NESP32 Discord](https://discord.gg/kwSC7pwtmb).

The NESP32 comes without a warranty. Build and connect the hardware
carefully, especially where the NES's 5-volt signals meet the Stick's
3.3-volt pins.

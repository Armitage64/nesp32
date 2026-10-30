# NESP32 User Guide

This guide is for people who want to **use** a NESP32. You don't need to
know how to program, build software or understand electronics. If you're
building the hat yourself, that has its own guide, the
[NESP32 Build Guide](BUILD_GUIDE.md). If you want the technical side,
see [Further reading](#14-further-reading) at the end.

## Contents

1. [What the NESP32 is](#1-what-the-nesp32-is)
2. [What you need](#2-what-you-need)
3. [Putting it together](#3-putting-it-together)
4. [Installing the firmware](#4-installing-the-firmware)
5. [Getting the cartridge onto your NES](#5-getting-the-cartridge-onto-your-nes)
6. [First power-on and the cartridge menu](#6-first-power-on-and-the-cartridge-menu)
7. [Setup: Wi-Fi and the status screen](#7-setup-wi-fi-and-the-status-screen)
8. [Pairing a Bluetooth keyboard](#8-pairing-a-bluetooth-keyboard)
9. [Buttons and keys: the quick reference](#9-buttons-and-keys-the-quick-reference)
10. [The programs](#10-the-programs)
11. [Playing online with a friend](#11-playing-online-with-a-friend)
12. [Putting music on the NESP32](#12-putting-music-on-the-nesp32)
13. [Troubleshooting](#13-troubleshooting)
14. [Further reading](#14-further-reading)

---

## 1. What the NESP32 is

The NESP32 is a small Wi-Fi gadget that plugs into **controller port 2**
of an ordinary NES. Nothing inside the console is changed. With it, NES
software can reach the Internet, so the console can:

- read Wikipedia articles,
- show the weather for your zip code,
- show live air traffic around an airport,
- play live Internet radio and NES music through its own sound chip,
- read Bluesky posts,
- play Dr. Mario, Tetris, Contra and TMNT II online against a friend.

A NESP32 is an **M5Stack StickS3** (a small ready-made computer, about
$20, with its own screen, battery and buttons) plus a little circuit board
called the **hat**. The hat connects the Stick to the NES controller plug
and safely converts between the NES's 5-volt signals and the Stick's
3.3-volt ones.

The older **M5Stack StickC Plus2** works too, with two limits:

| | StickS3 | StickC Plus2 |
|---|:---:|:---:|
| All the cartridge programs and online play | Yes | Yes |
| Bluetooth keyboard | Yes | No |
| Shows up as a USB drive for copying music | Yes | No |
| Still on sale | Yes | Mostly not |

This guide describes the StickS3 and points out where the Plus2 differs.

> **Note:** the NESP32 is for **NTSC** consoles (North American and
> Japanese) for now. PAL support is planned.

> **Note:** the NESP32 is a hobby project that's still growing, not a
> finished store-bought product. A few features are marked as
> experimental below.

### Words used in this guide

| Word | Meaning |
|---|---|
| **Stick** | The M5Stack StickS3 or StickC Plus2 |
| **Hat** | The small circuit board between the Stick and the NES cable |
| **Firmware** | The software that runs on the Stick |
| **Cartridge ROM** | The file `nesp32.nes`, which the NES runs |
| **Bluetooth LE** | Bluetooth Low Energy, the kind of Bluetooth the StickS3 uses |

---

## 2. What you need

| Item | Notes |
|---|---|
| An NES | NTSC. A MiSTer FPGA running the NES core with a SNAC adapter also works |
| An M5Stack StickS3 | [Buy one here](https://amzn.to/3TVUV0y). The StickC Plus2 also works, without Bluetooth or the USB drive |
| The NESP32 hat, with its cable | Build it with the [Build Guide](BUILD_GUIDE.md), or get one already built and tested |
| A way to run a ROM file on the NES | A flash cartridge such as an Everdrive, or a MiSTer |
| A computer with Chrome, Edge or Opera | Only for installing the firmware |
| A USB-C **data** cable | Some cables only carry power. If the computer can't see the Stick, try another cable |
| A Wi-Fi network with Internet access | It must be **2.4 GHz** |
| A normal NES controller | In port 1, as usual |
| *Optional:* a Bluetooth keyboard | Makes typing much easier. It must be **Bluetooth LE**, which most keyboards from the last few years are. StickS3 only |

> **Important: the NES does not power the Stick.** The Stick runs on its
> own battery, or from a USB charger. Charge it before you start. If the
> Stick's screen is dark, the NESP32 won't work, however the cable is
> connected.

---

## 3. Putting it together

You'll need a finished hat with its cable attached. If you're building
one, follow the [Build Guide](BUILD_GUIDE.md) first, including its
checks at the end, and then come back here.

1. **Fit the hat to the Stick.** It goes on the Stick's **bottom
   connector**, the end furthest from the screen. Don't use the small
   Grove socket.
2. **Plug the hat's cable into controller port 2** on the NES. Your normal
   controller stays in **port 1**.
3. **Make sure the Stick is charged**, or plugged into a USB charger.

You can power up the NES and the NESP32 in either order.

---

## 4. Installing the firmware

The firmware is the software that runs on the Stick. You install it once
from your web browser, and again whenever there's an update. You don't
need to download or build anything.

1. Open the **[Online Firmware Installer](https://nesp32.retrobits.tv/flash/)**
   in **Chrome, Edge or Opera** on a computer. Safari and Firefox can't
   reach USB devices.
2. Connect the Stick to the computer with a USB data cable.
3. **The first time on a StickS3 only:** put it in "boot mode". Press and
   hold the **power button** on its side until the **green light
   flashes**. The StickC Plus2 doesn't need this.
4. Press **Connect** and choose the Stick from the list. The right
   firmware for your Stick is picked for you.
5. The browser asks whether to **erase** the Stick first:
   - **First install:** either answer is fine.
   - **Updating an existing NESP32:** answer **No**. Answering Yes wipes
     your saved Wi-Fi, your paired keyboard, your settings and your
     music.
6. Wait for the installation to finish, then unplug the Stick.

> **Good to know:** installing the firmware replaces whatever was on the
> Stick before, including M5Stack's own UIFlow software. M5Stack's
> M5Burner tool can put UIFlow back later if you want it.
>
> On Windows, a StickC Plus2 may need the driver for its USB chip
> (CH9102) before the browser can see it.

### Updating later

1. If you've been copying music, eject the USB drive first.
2. Install the new firmware as above, answering **No** to erase.
3. Download the `nesp32.nes` cartridge from the **same release** and
   replace the old copy on your flash cartridge.
4. Run **Setup** and check that the NESP32 line says **CONNECTED** and
   the firmware version is the new one.

---

## 5. Getting the cartridge onto your NES

All the NESP32's programs come together in one file, the **cartridge
ROM**, `nesp32.nes`. Download it from the
[NESP32 home page](https://nesp32.retrobits.tv/) ("Download the
cartridge") and copy it to your flash cartridge's SD card, or to your
MiSTer, as you would any NES game.

The online games (Dr. Mario, Tetris, Contra and TMNT II) are **not** on
the cartridge, because they contain the original games. See
[Chapter 11](#11-playing-online-with-a-friend).

> **Keep the firmware and the cartridge in step.** When you update one,
> update the other too, from the same release. A mismatched pair can show
> **UPDATE NESP32** or **NEEDS AN UPDATE**, or behave oddly.

---

## 6. First power-on and the cartridge menu

1. Make sure the Stick is switched on. Press its power button if its
   screen is dark. The Stick's screen shows **NESP32** and waits for the
   console.
2. Start `nesp32.nes` on the NES.
3. The **cartridge menu** appears, listing every program. The Stick's
   screen changes to show which program is running.

| On the menu | Controller | Keyboard |
|---|---|---|
| Move up or down the list | **Up**, **Down** | arrow keys |
| Run the highlighted program | **A** or **Start** | **Enter** |

In most programs, **Select** (or **Ctrl+Esc** on a keyboard) brings you
back to this menu. **Reset** on the console always does.

A small **Bluetooth badge** in the top-right corner shows whether a
keyboard is connected ([Chapter 8](#8-pairing-a-bluetooth-keyboard)).

**The very first thing to do is run Setup** and join your Wi-Fi network.

---

## 7. Setup: Wi-Fi and the status screen

Choose **Setup** from the cartridge menu. It opens on the **STATUS**
screen.

### The status screen

| Line | What it tells you |
|---|---|
| NESP32 | **CONNECTED** if the console can talk to the NESP32. **NOT FOUND** means check the cable and that the Stick is on. **NEEDS AN UPDATE** means install newer firmware |
| FIRMWARE | The firmware version on the Stick |
| BOARD | StickS3 or StickC Plus2 |
| WI-FI | **NOT SET UP**, **JOINING...**, **JOINED**, **NOT JOINED** or **COULD NOT JOIN** |
| NETWORK | The Wi-Fi network's name |
| ADDRESS | The NESP32's address on your network |
| SIGNAL | Wi-Fi signal strength (closer to 0 is stronger) |
| BATTERY | The Stick's battery level |

Underneath is a menu. Use **Up**/**Down** to move and **A** to choose:

| Menu item | What it does |
|---|---|
| **WI-FI SETUP** | Join a Wi-Fi network (below) |
| **TEST INTERFACE** | Checks that the connection between the console and the NESP32 is healthy (below) |
| **ENABLE USB DRIVE** | Lets a computer copy music onto a StickS3 ([Chapter 12](#12-putting-music-on-the-nesp32)) |
| **BLUETOOTH** | Pair or forget a keyboard ([Chapter 8](#8-pairing-a-bluetooth-keyboard)) |
| **FLIP LCD** | Turns the Stick's own screen upside down. The Stick remembers this |
| **QUIT** | Back to the cartridge menu |

### Joining a Wi-Fi network

Two kinds of network won't work:

- **5 GHz-only networks.** The NESP32 needs **2.4 GHz**.
- **Networks with a sign-in web page**, like many hotels, cafés and
  dorms. The Stick has no web browser to sign in with. A phone hotspot
  is a good fallback.

1. Choose **WI-FI SETUP**. The NESP32 looks for networks
   (**LOOKING FOR NETWORKS...**) and lists them, strongest first. A lock
   means the network needs a password.
2. Use **Up**/**Down** to pick yours and press **A**. **Start** looks
   again. If your network hides its name, choose **OTHER NETWORK...** and
   type its name.
3. **Type the password** on the on-screen keyboard:

   | To... | Press |
   |---|---|
   | Move around the keys | the **D-pad** |
   | Type the highlighted key | **A** |
   | Delete the last character | **B** |
   | Switch between `abc`, `ABC` and `#+=` | **A** on the set key, left of the space bar |
   | Join the network | **Start** |

4. The screen says **TELLING THE NESP32...**, then **JOINING...**. When it
   has joined, the status screen's WI-FI line says **JOINED**.

You only do this once. The NESP32 remembers the network and joins it by
itself every time it's switched on. Your password is stored on the Stick
and is never shown again.

If it fails you'll see **WRONG PASSWORD**, **NETWORK NOT FOUND**,
**COULD NOT JOIN** or **CANNOT JOIN THAT KIND** (a type of network
security it can't use). Press **A** to try again or **B** to go back.

> **Tip:** a Bluetooth keyboard doesn't type letters straight into the
> password. On this screen its arrow keys move around the on-screen
> keyboard and **Enter** types the highlighted key, just like the
> controller.

### Testing the connection to the console

Choose **TEST INTERFACE** and let it run for a little while. The **GOOD**
count should keep rising along with **REQUESTS**, and **NO REPLY** and
**WRONG** should stay at zero. Press **B** to go back.

If errors keep appearing, the problem is in the hardware (the hat, the
cable, the soldering, or the hat sitting the wrong way round), not your
Wi-Fi. The [Build Guide](BUILD_GUIDE.md#5-checking-your-work) has the
checks to run.

---

## 8. Pairing a Bluetooth keyboard

A Bluetooth keyboard makes typing much easier in NESpedia, Weather and
NES Radar, and it can stand in for the controller in every program on
the cartridge.

**Before you start:**

- You need a **StickS3**. The StickC Plus2 has no Bluetooth.
- The keyboard must be **Bluetooth LE** (Low Energy). Most keyboards made
  in the last few years are. An older "Bluetooth Classic" keyboard won't
  appear in the list.
- The NESP32 uses the **US keyboard layout**. On a keyboard made for
  another country, some symbols won't match what's printed on the keys.
- You don't type a pairing code. The NESP32 pairs without one.

### Pairing, step by step

1. Run **Setup** and choose **BLUETOOTH**. The screen is titled
   **PAIR BLUETOOTH KEYBOARD**.
2. **Put the keyboard in pairing mode.** On most keyboards you hold the
   Bluetooth or channel key until its light blinks quickly. See your
   keyboard's manual if you're not sure.
3. Choose **PAIR DEVICE**. The NESP32 searches (**LOOKING FOR
   KEYBOARDS...**) and then shows **CHOOSE A KEYBOARD**, strongest first.
4. Highlight your keyboard with **Up**/**Down** and press **A**.
5. STATUS shows **PAIRING...**. When the keyboard is ready, the screen says
   **THE KEYBOARD IS PAIRED** and STATUS changes to **CONNECTED**.
6. Try it: what you type appears in the box on this screen.

Some keyboards go to sleep straight after pairing. Then STATUS says
**PRESS A KEY ON IT** after a few seconds. Press any key, wait a moment,
and it will connect.

The NESP32 remembers the keyboard. From then on it reconnects by itself
whenever a program that uses the keyboard is running.

### What the keyboard status means

| STATUS says | Meaning |
|---|---|
| **NONE PAIRED** | No keyboard is paired yet |
| **STARTING...** | Bluetooth is switching on |
| **LOOKING...** | Searching for keyboards |
| **PAIRING...** | Pairing is in progress. Leave the keyboard in pairing mode |
| **CONNECTED** | Ready to type |
| **PRESS A KEY ON IT** | Paired, but the keyboard is asleep or out of range. Press a key to wake it |
| **PAIRING FAILED** | Try again: put the keyboard back in pairing mode and choose PAIR DEVICE |
| **NO BLUETOOTH** | This Stick has no Bluetooth (StickC Plus2), or its firmware is too old |

### The Bluetooth badge

The cartridge menu and Setup show a small badge in the top-right corner:

| Badge | Meaning |
|---|---|
| None | No keyboard paired |
| Grey | Paired, not connected right now (press a key to wake it) |
| Flashing blue | Connecting |
| Solid blue | Connected |
| Yellow | The last pairing failed, or the NESP32 has stopped answering |

### Forgetting a keyboard

Choose **FORGET DEVICE** on the Bluetooth screen. The screen says
**THE KEYBOARD IS FORGOTTEN**. Only one keyboard is remembered at a time,
so pairing a new one replaces the old one.

Some keyboards keep their own list of devices they've paired with. If
yours won't pair again after you've forgotten it, remove the NESP32 from
the keyboard's list too (see its manual), then pair again.

If you've installed firmware with "erase" answered Yes, the Stick will
have forgotten the keyboard too: pair it again, and put the keyboard in
pairing mode first.

> **Good to know:** a keyboard that has gone to sleep can take up to
> about ten seconds to come back, and the key that wakes it isn't typed.
> Wait for the solid blue badge before typing anything important.
> Bluetooth is only switched on while a program that uses the keyboard is
> running.

---

## 9. Buttons and keys: the quick reference

### The same almost everywhere

The programs on the cartridge use the controller the same way:

| Button | What it does |
|---|---|
| **A** | OK: choose, play, look up, type a key |
| **B** | Back one step, or delete when typing. B never leaves a program, so pressing it repeatedly stops at the program's first screen |
| **Start** | Start, or send what you've typed |
| **Select** | Back to the cartridge menu |
| **Reset** (on the console) | Back to the cartridge menu, always |

There are three exceptions:

- In the **NESpedia article reader**, Select goes back to the search
  screen instead. Press it again there to reach the menu.
- While **sound is streaming** (NESradio, or recorded sound in the
  Jukebox), only **A** works. See [below](#while-sound-is-playing).
- In the **online games**, the game's own buttons apply.

The bottom of each screen reminds you of its buttons, for example
`A : PLAY` and `SELECT : MENU`. If the screen and this table disagree,
go by the screen.

### The keyboard as a controller

A paired Bluetooth keyboard works as controller 1 in every program on the
cartridge:

| Keyboard | Same as |
|---|---|
| **Arrow keys** | the D-pad |
| **Enter** | **A** |
| **Esc** | **B** |
| **Ctrl + Enter** | **Start** |
| **Ctrl + Esc** | **Select** (back to the cartridge menu) |

Hold **Ctrl**, tap **Enter** or **Esc**, then let go of Ctrl. A key held
down repeats, as on a computer (except Enter and Esc).

Where a program has a box to type into, the keyboard types into it
directly: NESpedia's search, Weather's zip code and NES Radar's airport
code. There, **Enter** sends what you typed and **Backspace** deletes.

Two screens don't take typing directly. On the **Wi-Fi password** screen
and Bluesky's **handle form**, the keyboard works like the controller
instead: arrows move, Enter picks.

### While sound is playing

When the **Jukebox** plays sampled sound, or **NESradio** plays a station,
the console can only read the **A** button. The sound arrives on the same
wire the controller uses. Press **A** to pause or stop first, and then the
other buttons work again. The keyboard can't stop a radio station: use
**A** on the controller, or the Stick's front button.

### The Stick's own buttons

| Stick button | What it does |
|---|---|
| **A** (front) | Play or pause in the Jukebox, tune in or stop in NESradio, start the Throughput test. Ends USB drive mode |
| **B** | Previous track in the Jukebox |
| **Power**, tapped | Next track in the Jukebox. Switches the Stick on when it's off |
| **B**, held 2 seconds | Switches the Stick off (it stays on while plugged into USB) |

The Stick's screen shows which program is running and how it's doing.

---

## 10. The programs

Everything here needs the NESP32 on Wi-Fi (Chapter 7), except the
Jukebox's music and the Throughput test.

These programs rely on outside services: Wikipedia, weather and flight
data providers, radio stations and Bluesky. If one stops working while
Setup still says **JOINED**, that service is probably down. Try another
station, airport or article, or try again later.

### Setup

Status, Wi-Fi, the link test, the USB drive and the Bluetooth keyboard.
See [Chapter 7](#7-setup-wi-fi-and-the-status-screen) and
[Chapter 8](#8-pairing-a-bluetooth-keyboard).

### NESpedia (Wikipedia)

Search for and read English Wikipedia articles.

**Search screen:** type a word or two on the on-screen keyboard and press
**Start**. On a keyboard, just type and press **Enter**.

| Controller | Keyboard | Search screen |
|---|---|---|
| D-pad | arrows | Move over the on-screen keys |
| **A** | letters, digits, space | Type. **A** on ⇧ (under Z) switches capitals |
| **B** | **Backspace** or **Esc** | Delete. While searching, give up |
| **Start** | **Enter** or **Ctrl+Enter** | Search |
| **Select** | **Ctrl+Esc** | Back to the cartridge menu |

**Reading an article:**

| Controller | Keyboard | Reader |
|---|---|---|
| **Up**, **Down** (hold) | **Up**, **Down** | Scroll |
| **A** or **Right** | **Enter**, **Page Down** or **Right** | A page down |
| **B** or **Left** | **Esc**, **Page Up** or **Left** | A page up |
| **Start** | **Ctrl+Enter** | Back to the top |
| **Select** | **Ctrl+Esc** | Back to the search screen |

The marker at the right edge shows how far through the article you are.

### Weather

Current conditions and a 5-day forecast for a **US zip code**, in °F and
miles per hour. The NESP32 remembers your zip code.

| Controller | What it does |
|---|---|
| **Left**, **Right** | Move to the next digit |
| **Up**, **Down** | Change the digit |
| **A** or **Start** | Get the weather |
| **B** | From a report, back to the zip code |
| **Select** | Back to the cartridge menu |

On a keyboard, just **type the five digits** and press **Enter**.
**Backspace** goes back a digit. On a report, typing a digit starts a new
zip code. The weather refreshes by itself every 15 minutes.

### NES Radar

Live air traffic around an airport, on a radar scope drawn by the NES.

1. Enter a four-letter airport code (its ICAO code, such as `KLAX` or
   `KSFO`). **Up**/**Down** change a letter and **Left**/**Right** move.
   On a keyboard, type the letters.
2. Press **Start** or **A** (**Enter** on a keyboard).
3. On the scope, the D-pad picks an aircraft. **B** goes back to the
   airport code.

The NESP32 remembers the last airport. **INVALID AIRPORT** means that
code isn't known. **LOOKUP FAILED** means the service that looks up airports
didn't answer; press **Start** or **A** to try again. The scope covers 9 nautical miles,
shows up to eight aircraft, and updates about every 8 seconds.

### NESradio

Live Internet radio stations, including NPR, KEXP and BBC World Service,
on a radio dial.

| Before tuning in | What it does |
|---|---|
| **Left**, **Right** | Choose a station |
| **Up**, **Down** | Choose the quality: `23kHz` (better sound) or `12kHz + INFO` (shows what's playing) |
| **A** or **Start** | Tune in. It says **TUNING**, then **ON THE AIR** |
| **B** (while tuning) | Give up and go back |
| **Select** | Back to the cartridge menu |

**While a station plays, only A works:** press **A** on the controller,
or the Stick's front button, to stop it. The keyboard works on the menu,
but can't stop a station that's playing.

A station can be off the air even when everything else is working. If
one won't tune in, try another.

### Jukebox

Plays NES game music, and recorded sound, through the console's own sound
chip. You copy the music onto the NESP32 first
([Chapter 12](#12-putting-music-on-the-nesp32)).

| Button | On the track list | While playing |
|---|---|---|
| **Up**, **Down** | Choose a track | |
| **Left**, **Right** | A page of eight up or down | Previous or next track |
| **A** or **Start** | Play | Pause or resume |
| **B** | | Stop, back to the list |
| **Select** | Cartridge menu | Cartridge menu |

During recorded (sampled) sound, press **A** to pause before B or Select
will work. The Stick's own buttons also control the music (see
[Chapter 9](#the-sticks-own-buttons)). **NO MUSIC FOUND** means no
playable tracks have been copied yet.

### Bluesky

Read recent posts from your favorite Bluesky accounts. You don't need a
Bluesky account, and it can only read: no posting, liking, following or
pictures. The NESP32 remembers up to ten favorites, and starts with four.

| Screen | Buttons |
|---|---|
| Favorites | **Up**/**Down** choose. **A** reads that account's posts. **Start** twice removes a favorite. On the last line, **A** opens the form for a new handle |
| The form | **Left**/**Right** move. **Up**/**Down** change a letter. **A** reads that account. **Start** saves it as a favorite. **B** goes back |
| A post | **Left**/**Right**: previous or next post. **Up**/**Down**: more of its text. **Start** saves the account as a favorite. **B** goes back |

A name with no dot in it is taken as `name.bsky.social`.

> **Experimental:** Bluesky has so far been tested only in simulation,
> not on a real console.

### Throughput

A speed test of the connection between the console and the NESP32. It
doesn't test your Internet speed; it's mostly useful for troubleshooting
the hardware. Press **Start** or **A** to run it. A full run takes about a
minute. When both halves say **DONE**, **A** runs it again.

If the Stick loses power during the test and the screen freezes, press
**Reset** on the console.

---

## 11. Playing online with a friend

Dr. Mario, Tetris, Contra and TMNT II have special two-console versions.
Each player needs:

- their own NES, with a NESP32 in port 2 and a controller in port 1,
- the same version of the online game on their flash cartridge,
- working Wi-Fi.

**Getting the games:** these contain the original games, so they can't
be handed out ready-made:

- **TMNT II:** apply the patch `apps/tmnt2/dist/tmnt2_net.bps` to your own
  copy of the US game with a BPS patcher such as Floating IPS or
  RomPatcher.js (it runs in a web browser). Then put the result on your
  flash cartridge.
- **Dr. Mario, Tetris and Contra** have to be built from source
  ([the README](../README.md#building)). Contra also needs your own copy
  of the game. Ask on the [Discord](https://discord.gg/kwSC7pwtmb) if you
  need help.

Contra and TMNT II need a flash cartridge or emulator that supports their
cartridge type (MMC3).

**Starting a game:**

1. On the title screen, choose the two-player option: **2 PLAYERS**
   (Contra, Tetris), **2 PLAYER GAME** (Dr. Mario) or **2 TURTLES**
   (TMNT II).
2. One player chooses **HOST GAME**. Their screen, and the Stick's screen,
   show a **four-character room code**. Codes never use easily confused
   pairs like 0 and O, or 1 and I.
3. The other player chooses **JOIN GAME**, enters the code (**Left**/**Right**
   move, **Up**/**Down** change a character) and presses **Start**.
4. When the two connect, both consoles go straight into the game. The
   host is player 1.

Room codes work across the Internet with no router setup. They do need
Internet access, even when both consoles are in the same house.

**LOCAL GAME** is the normal two-controller game on one console. The
second controller needs port 2, so unplug the NESP32 for this.

### Playing by address

Press **Select** on the host or join screen to switch to **by address**
mode. Both players must use the same mode.

- **On the same network:** no setup needed, and no Internet access
  needed either.
- **Across the Internet:** the host has to set up their router to forward
  **UDP port 6502** to their NESP32, and give the other player their
  public address. Use this only if room codes don't work for you.

### What the messages mean

| The menu says | Meaning |
|---|---|
| `NO WIFI` | Run Setup and join a network |
| `NO NESP32` | The console can't reach the NESP32. Check the Stick is on and the cable is in port 2 |
| `UPDATE NESP32` | Install newer firmware |
| `OPENING A ROOM` | Wait a moment while it sets up |
| `NO RENDEZVOUS` | The room service can't be reached. Check your Internet connection, or try later |
| `NO SUCH ROOM` | Check the room code |
| `ROOM IS FULL` | Someone else already joined |
| `NOT THIS GAME` | The code belongs to a different game, or a different version |
| `CANNOT REACH IT` | The two NESP32s can't connect directly. Try by-address mode with port forwarding |
| `ROOM CLOSED` | The host's room has ended |

---

## 12. Putting music on the NESP32

The Jukebox plays:

- NES music rips (`.vgm` or `.vgz` files, easy to find online),
- recorded sound prepared for the NESP32 (`.pcm` files),
- `.jbs` files, which the NESP32 makes itself from `.vgm` files.

**Ordinary MP3 and WAV files won't play** if you just copy them over.
They have to be converted to `.pcm` on a computer first; the
[Jukebox's README](../apps/jukebox/README.md) explains how.

There's room for about 4 MB of music, and up to 200 tracks.

**On a StickS3:**

1. Run **Setup** and choose **ENABLE USB DRIVE**.
2. Plug the Stick into a computer with a USB data cable. A drive called
   **NESP32** appears, and the screen says **THE USB DRIVE IS MOUNTED**.
3. Copy your music files into the **`tracks`** folder on that drive (not
   next to it). The tracks play in the alphabetical order of their file
   names.
4. Wait until the copying has finished. Don't unplug the Stick while it's
   copying.
5. **Eject the drive** on the computer. The NESP32 restarts. The first
   time, its screen shows `Converting 3/12` and so on while it prepares
   each track. This happens only once per track.

Press **B** on the controller, or the Stick's front button, to leave USB
drive mode without copying anything. Eject the drive first.

**On a StickC Plus2:** it can't act as a USB drive. Music has to be
copied with a tool on a computer; see the
[Jukebox's README](../apps/jukebox/README.md#music-on-a-nesp32).

---

## 13. Troubleshooting

| Problem | Try this |
|---|---|
| The Stick's screen stays dark | Charge it or plug it into a USB charger, then tap its power button. The NES doesn't power it |
| **WAITING FOR LINK**, **NO NESP32** or **NOT FOUND** | Check the Stick is switched on, the hat is firmly on its bottom connector (not the Grove socket), and the cable is in **port 2**. Then run **TEST INTERFACE** in Setup |
| **TEST INTERFACE** shows errors | The hat or its cable has a fault. Run the checks in the [Build Guide](BUILD_GUIDE.md#5-checking-your-work). Never bypass the hat to test a direct connection |
| The Stick starts in download mode instead of the NESP32 | Try the Stick without the hat. If it starts normally, the hat needs fixing: see the [Build Guide](BUILD_GUIDE.md#6-if-the-stick-starts-in-download-mode) |
| **UPDATE NESP32** or **NEEDS AN UPDATE** | Install the latest firmware ([Chapter 4](#4-installing-the-firmware)) and the matching cartridge or game from the same release |
| **NO WI-FI** | Run Setup and join a network. Check WI-FI says **JOINED** |
| Wi-Fi won't join | Make sure the network is **2.4 GHz** and doesn't use a sign-in web page. Retype the password carefully (capitals count). Move closer to the router. For **CANNOT JOIN THAT KIND**, try a phone hotspot |
| Wi-Fi was forgotten | Installing firmware with "erase" answered Yes wipes it. Join the network again in Setup |
| The browser can't find the Stick | Use Chrome, Edge or Opera, try a different USB cable (some only carry power) and a different USB port, and close any other program using the Stick. On a StickS3, hold the power button until the green light flashes. On Windows, a Plus2 needs the CH9102 driver |
| Your keyboard isn't in the list | Put it back in pairing mode, check it's Bluetooth LE, and choose PAIR DEVICE again. Disconnect it from any computer or tablet nearby that might grab it first. A StickC Plus2 can't use a keyboard |
| Keyboard shows **CONNECTED** but nothing types | Switch the keyboard off and on, or restart the Stick. If it keeps happening, choose FORGET DEVICE, remove the NESP32 from the keyboard's own list, and pair it again |
| Keyboard stopped responding after a while | It's probably asleep. Press a key and wait a few seconds |
| Buttons don't work while music or radio plays | That's expected. Only **A** works during sampled sound and radio. Press **A** first |
| New music doesn't appear | Check the files are inside the `tracks` folder, are `.vgm`, `.vgz` or `.pcm` (not MP3 or WAV), and that you ejected the drive and let the Stick finish converting. If it's full, remove some tracks |
| A program that uses the Internet stopped working | If Setup still says **JOINED**, the outside service is probably down. Try another station, airport or article, or try later |
| The Stick's screen is upside down | Setup, then **FLIP LCD** |
| Something stuck | Press **Reset** on the console. If that doesn't help, switch the Stick off (hold **B** for 2 seconds) and on again |

For anything else, ask on the **[NESP32 Discord](https://discord.gg/kwSC7pwtmb)**.

---

## 14. Further reading

For the technically curious:

| Document | What's in it |
|---|---|
| [README.md](../README.md) | Overview and building from source |
| [BUILD_GUIDE.md](BUILD_GUIDE.md) | Building and checking the hat, step by step |
| [hardware/README.md](../hardware/README.md) | The hat, its parts and photos |
| [docs/WIRING.md](WIRING.md) | How the hat is wired |
| [docs/MULTIPLAYER.md](MULTIPLAYER.md) | How online play works |
| [firmware/README.md](../firmware/README.md) | The Stick's firmware |
| [apps/](../apps/) | Each program's own detailed notes |
| [NESP32 Discord](https://discord.gg/kwSC7pwtmb) | Community help |

The NESP32 comes without a warranty. Build and connect the hardware
carefully, especially where the NES's 5-volt signals meet the Stick's
3.3-volt pins.

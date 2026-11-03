# Chat: one Discord channel on a NES

A plan for issue #44: a chat room for NESP32 owners, on a Discord server so
that the same room can be used from a console and from a phone or a
computer. The console shows the channel's latest messages and sends what is
typed on it. There is one channel on one server, fixed when the relay is set
up. Choosing a server or a channel can come later.

**Status: a plan. Nothing is built yet.**

## Context

The issue asks for an app in which a user "logs into Discord with an
existing account". That part is left out, for two reasons:

- **Discord does not allow it.** A program that logs into a user's own
  account and acts as a client ("self-botting") is against Discord's terms,
  and accounts that do it are banned. Only Discord's own apps may use a
  user's account, and a bot has to log in with a bot token.
- **A console cannot log in anyway.** A Discord login has a captcha, often a
  code from a second device, and a token that would then live in the Stick's
  flash.

What is left that Discord allows: **a bot reads the channel, and a webhook
posts in it**, each under the name the player chose (`levi [NES]`). The bot
and the webhook belong to the server's owner, not to each player. Phase 6
below lets a player link their Discord account so that their messages carry
their own Discord name and picture, still without the console ever holding
a Discord login.

### Why a relay, and not Discord on the nesp32

Discord could in principle be reached from the nesp32 directly: the bot's
gateway (a websocket, compressed with zlib) for what is said, and its REST
API for posting. Against that:

- **The token.** Every nesp32 would carry the bot's token, which can do
  everything the bot can, and anyone with a serial cable could read it from
  the flash. Or every owner would make a bot of their own and be invited to
  the server, which few would.
- **Memory.** A TLS websocket that stays open, and zlib's 32 KB window, on
  top of Wi-Fi, and of Bluetooth when a keyboard is connected (about 67 KB
  of internal RAM free then, `firmware/README.md`).
- **Discord's own rules.** Each gateway connection to the same bot counts
  against its limits, and Discord changes its API, so every nesp32 would
  need its firmware updated each time.

So, as with PEER's rendezvous (`server/rendezvous`), a small service of ours
on Cloudflare sits between them. The nesp32 does no more than it does for
Bluesky: a GET over HTTPS that answers plain text, read as it comes in and
laid out into lines for the console.

```text
 NES ──link── nesp32 ──HTTPS GET──> relay (Worker + one Durable Object) ──REST──> Discord
                                      │  reads the channel as the bot
                                      └─ posts through the webhook as "name [NES]"
 phones, computers ─────────────────────────────────────────── Discord, as usual
```

## The relay (`server/chat`)

A Cloudflare Worker and **one** Durable Object that keeps the room. It is on
the Workers Free plan and the same account as the rendezvous. It is a
separate Worker so that a bug in chat cannot take netplay down.

**Every request is a GET, and every answer is plain text**, because that is
all the nesp32's fetch does (`firmware/main/fetch.c`: GET only, a 10 s
timeout, one fetch at a time).

| Request | Answers |
|---|---|
| `/v1/chat/hello?d=DEVICE&n=NAME` | `OK CHANNEL`, `NAME_TAKEN`, `BAD_NAME` or `BANNED` |
| `/v1/chat/read?d=DEVICE&after=ID` | `MSG ...` lines, oldest first, then `END LAST_ID`. If there is nothing new it waits up to 8 s first (a long poll, under the fetch's 10 s) |
| `/v1/chat/say?d=DEVICE&m=MSGID&t=TEXT` | `SENT ID`, `SLOW SECONDS`, `TOO_LONG` or `BANNED` |

- **`DEVICE`**: 16 hex digits, random, made by the nesp32 the first time
  and kept in its flash. It is the only thing the relay knows a console
  by, for its name, its rate limit, and a ban. It is not a secret worth
  anything: it does not reach Discord, and it buys nothing a new random one
  would not.
- **`NAME`**: 2 to 16 of `A-Z a-z 0-9 _ -`. On Discord it shows as
  `NAME [NES]`, so it cannot be taken for a Discord user's name. A name
  belongs to the device that first used it. Names are kept in the DO's
  storage.
- **`MSGID`**: the console's own count. A `say` sent again after a lost
  answer, with the same `d` and `m`, gets the same answer and is not posted
  twice. This is needed because a GET is retried.
- **`TEXT`**: up to 120 characters, ASCII, percent-encoded.
- **A `MSG` line**: `MSG ID KIND AUTHOR<TAB>TEXT`. `ID` is Discord's message
  id (a snowflake, in decimal). `KIND` is `D` for a Discord user, `N` for
  one of ours, or `S` for the relay itself (joins and similar). `TEXT` is
  UTF-8 with Discord's markup resolved by the relay:
  - `<@id>` becomes `@name` (from the message's `mentions`).
  - `<#id>` becomes `#channel`.
  - `<:smile:id>` becomes `:smile:`.
  - An attachment or embed becomes `[picture]` or `[link]`.
  - A reply starts with `> @name `.
  - A newline is kept as `\n`.

  Folding the text to ASCII is left to the nesp32, which already does it
  for WIKI and BSKY (`text.c`).
- **The first `read`** (`after=0`) answers the last 30 messages.

**Discord is asked only while someone is reading.** While any console has
read in the last 30 s, the DO asks Discord's REST API
(`GET /channels/{id}/messages?after=`) at most once every 2 s and keeps the
last 100 messages. Every long poll waiting in the DO is answered from that
store. Ten consoles cost Discord what one does. With no console reading,
the DO asks nothing and sleeps.

**Posting** goes to the webhook (`POST {webhook}?wait=true`) with
`username: "NAME [NES]"` and `allowed_mentions: {parse: []}`, so that no
console can ping `@everyone` or anyone else. The relay holds each device to
one message in 3 s, and the room to 20 a minute, under the webhook's 30 a
minute. An answer of `SLOW` says how long to wait.

**Secrets** are the Worker's own (`wrangler secret put`):
`DISCORD_BOT_TOKEN`, `DISCORD_WEBHOOK_URL` and `DISCORD_CHANNEL_ID`. The
bot needs only View Channel and Read Message History on that one channel,
plus the Message Content intent. The intent is privileged, but a bot in
fewer than 100 servers turns it on from its own page with no review.

**Moderation** is Discord's: the server's moderators delete what they would
anyway. A ban of a device is a line in the DO's storage, set by a request
signed with a moderator's key (`/v1/chat/ban?d=...&k=...`), and on Discord
the device's messages can be deleted as any webhook's can. Edits and
deletions made on Discord after a console has read a message are not sent
again in version 1: the console keeps what it saw, until it reads afresh.

**What it costs on the Free plan** (an estimate, not measured): a console
with chat open and the room quiet makes one request every 8 s, 450 an hour.
Ten consoles for eight hours a day is 36,000 of the 100,000 Worker requests
a day. The one DO is awake while anyone reads; at 128 MB that is 0.125
GB-s a second, so the 13,000 GB-s a day lasts about 29 hours, more than a
day. Past either limit, requests fail until the next day, and nothing is
billed.

Tests, as the rendezvous has them: `server/chat/test/` for the rules
(markup, rate limits, names, the repeat of a `say`), with Discord faked.
`host/chat_relay.py` is a stand-in in Python for the nesp32's tests and
the ROM's.

## The nesp32: the CHAT service (`$16`)

It works like BSKY and WIKI: the nesp32 does the fetching and the laying
out, and the console asks for numbered lines of 28 characters, one at a
time.

| `OP` | Name | Request | Reply |
|---|---|---|---|
| `$00` | STATE | | `STATE`, `FIRST` (2), `COUNT` (2), and with FAILED 28 characters for the screen |
| `$01` | NAME | a name, or nothing | `STATE`, and the name kept (empty if none) |
| `$02` | LINE | `NUMBER` (2) | `NUMBER`, `KIND`, `TEXT[28]`; BAD_ARG if the line is no longer held or not yet there |
| `$03` | SAY | `ID`, text | `ID`, `SAID` (enum: SENDING, SENT, SLOW and its seconds, TOO_LONG, BANNED, FAILED) |

| `STATE` | Meaning |
|---|---|
| NO_WIFI | the nesp32 is not on a network |
| NO_NAME | no name is kept: the console asks for one |
| JOINING | hello sent, no answer yet |
| NAME_TAKEN / BAD_NAME / BANNED | as the relay answered |
| READING | in the room. `FIRST` and `COUNT` say which lines are held |
| FAILED | the relay did not answer, or answered what it should not; the reply says how |

- **Lines are numbered from the hello on and never renumbered.** The
  nesp32 keeps the last 256 lines (7 KB), so `FIRST` moves up as old ones
  go. A console that is at the bottom when `COUNT` grows scrolls on, and
  one that has scrolled back stays where it is.
- **A message is laid out as BSKY's posts are**, wrapped at spaces:
  - its first line starts `name: `, coloured by `KIND`;
  - the lines after it are indented by two;
  - `\n` ends a line;
  - what is not ASCII becomes the nearest thing that is, through `text.c`.
- **SAY is "send this" and "how did it go" at once**, as FEED is: a new
  `ID` is a new message. The text goes into the `say` request's `m`, so a
  repeat posts nothing twice. The console's own message comes back as
  Discord has it in the next `read`, so the console never draws its own
  copy. That way the order is always the room's.
- **One fetch at a time.** The long poll is stopped for a `say`
  (`fetch_stop`) and started again after it, from the last `ID` read.
- **What is kept over power-off**: the name and the device id, written when
  they change, through the hal as BSKY's favorites are (a `chat_keep`).
- **Cost**: a few KB of code, the 7 KB of lines, and parsing as it comes in
  (as `bsky.c` does) with no reply held whole. The 7 KB of lines go in
  PSRAM where the board has it, which matters with a keyboard connected.

`proto/nesp.toml` gets the service, its ops, the enums and
`CHAT_COLUMNS = 28`, `CHAT_LINES_HELD = 256` and `CHAT_TEXT_MAX = 120`.
`docs/PROTOCOL.md` gets a section, as every service has.

## The ROM (`apps/chat`, `build/chat.nes`)

An NROM-128, as Bluesky is, from NESpedia's parts: its font with small
letters, its scrolling, and its on-screen keyboard.

```text
 row 1    NESP32 CHAT        #nesp32         ● badge
 row 3-24 the room: 22 lines of 28, scrolled a line at a time
 row 25   ────────────────────────────────
 row 26-29 what is being typed: up to 4 lines (the 120 characters)
```

- **Typing**: a Bluetooth keyboard through KBD on a StickS3, where Enter
  sends, Backspace deletes, and Up and Down (or Page Up and Page Down)
  scroll the room. A StickC Plus2 has no KBD, so for it, or with no
  keyboard paired, Select opens NESpedia's on-screen keyboard over the
  bottom rows.
- **Controller**: Up and Down scroll, Start sends, B deletes, and Select is
  the on-screen keyboard.
- **The first time**, the screen asks for a name (NAME) before the room is
  shown.
- **One line a frame**, as NESpedia asks for its lines. A screenful of the
  room comes in under half a second.
- **Hello** asks for CHAT and KBD, so the keyboard stays connected, as
  every program on the cartridge does.

## The cartridge

The cartridge is full. It has 16 banks of 16 KB, and Bluesky took the last
free one (`nes/cart/gen_cart.py`). So Chat starts as a ROM of its own, and
what the cartridge does about it is a choice for later:

1. **A 512 KB MMC1 (SUROM)**: bit 4 of the CHR register picks the half of
   the PRG. That is room for eight more programs, at the cost of the menu
   and the programs' reset code learning about halves, and a board that has
   the chip for it.
2. **Take a program off** the cartridge, so it stays its own ROM.
3. **Chat, Bluesky and Weather as one program** of 32 KB, sharing their
   font and their screens.

## Phases

1. **The relay.** `server/chat` with its tests and Discord faked, then
   deployed against a test server and channel. Done when a computer with
   `curl` can read the channel and post in it.
2. **CHAT in the firmware**, tested on a computer against
   `host/chat_relay.py`, and with what Discord really sends (a fixture, as
   `tests/fixtures/bsky_feed.json` is for Bluesky).
3. **The ROM**, on the simulated console against the firmware's code over
   the simulated line, as Bluesky's tests do: the name, the room, scrolling,
   a message sent, and every write to the screen inside a vblank.
4. **On hardware**, with a StickS3 and a keyboard, and with a StickC Plus2
   and the on-screen keyboard.
5. **On the cartridge**, as decided above.
6. **Later: a Discord account linked.** The console shows a six-letter
   code. On a phone, a page of the relay's asks Discord to log in (OAuth2,
   the `identify` scope only, so it can read the user's name and picture
   and nothing else), and the code is typed there. From then on the
   device's messages are posted with the user's Discord name and avatar,
   still through the webhook. This is the nearest thing to "their own
   account" that Discord allows, and the console never holds a Discord
   login. More rooms, and choosing among them, would come after.

## For Armitage64 to decide

- Which server and channel, and who owns the bot and the webhook.
- Whether the relay goes on the rendezvous's Cloudflare account.
- Whether a message from a console is posted straight away, or held for a
  moderator at first.
- What the cartridge does (above).

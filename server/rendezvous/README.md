# The rendezvous

Where two nesp32s meet across the Internet with no port forwarded (issue
#12). The host opens a room and is given a four-letter code to show on its
console. Player 2 enters the code, and each nesp32 is handed the other's
*candidates*, the addresses it might be reached at: its own on its network,
and what STUN said of it from outside (`firmware/main/conn.c`). Then the
two send to each other at once, and each one's datagrams open its own
router to the other's. Nothing of the game passes through here.

It is a Cloudflare Worker and a Durable Object for each room, on the
Workers Free plan. Past the free plan's daily limits, requests fail until
the next day. Nothing is billed, as long as the account has no paid plan.

| File | What it is |
|---|---|
| `src/room.js` | the rules: codes, rooms, what each request is answered |
| `src/index.js` | the Worker, and the Durable Object that keeps a room |
| `test/room.test.js` | `room.js`'s tests (`npm test`) |
| `../../host/rendezvous.py` | a stand-in for it, in Python, for the tests of the nesp32's side |
| `../../tests/test_rendezvous.py` | the requests and answers, asked of the stand-in or of a real one |

## Requests

Every request is a GET, and every answer is one line of plain text. That's
all the nesp32's fetch does.

| Request | Answers |
|---|---|
| `/v1/host?app=DRMA&ver=1&c=CANDIDATES` | `ROOM CODE SESSION`, or `BUSY` |
| `/v1/room/CODE?s=SESSION&c=CANDIDATES` | `WAIT`, `GUEST CANDIDATES`, or `GONE` |
| `/v1/join/CODE?app=DRMA&ver=1&c=CANDIDATES` | `HOST SESSION CANDIDATES`, `NOROOM`, `MISMATCH`, or `FULL` |

- **`CANDIDATES`** is up to four `a.b.c.d:port`, comma-separated, the one on
  the nesp32's own network first.
- **`app` and `ver`** are the console's, from its hello. A join for another
  game, or another version, is answered `MISMATCH`.
- **`SESSION`** is eight hex digits, chosen here. It is the name both
  nesp32s' datagrams carry, so the host answers only player 2.
- **The host asks with `room`** every second or two until player 2 comes.
  Each time it gives its candidates afresh, since its router's way in may
  have moved.
- **A host that stops asking** for 30 seconds has gone, and its room with
  it. No room waits longer than 15 minutes.
- **A room that met** answers the same again for a minute, for a nesp32
  whose answer was lost. Then it is forgotten.
- **Anything else** is answered `BAD`, with status 400 or 404.

Codes are four of `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`: no 0 or O, no 1 or I.

## Setting it up, once

1. **Install Node.js**, if it isn't installed: `brew install node`.
2. **Install Wrangler**, Cloudflare's command-line tool, into this
   directory, and run the tests:

   ```sh
   cd server/rendezvous
   npm install
   npm test
   ```

3. **Make a Cloudflare account** at <https://dash.cloudflare.com/sign-up>,
   if you have none. The Workers Free plan needs no payment method.
   **Don't add one, and don't subscribe to Workers Paid.** With no payment
   method, a limit can only stop the rendezvous for the rest of the day, and
   never cost anything.
4. **Sign Wrangler in**: `npx wrangler login`. It opens the browser to
   allow it.
5. **Deploy**: `npx wrangler deploy`.
   - On an account's first Worker, it asks for a `workers.dev` subdomain.
     The subdomain becomes part of the address, so choose one you don't mind
     being in the firmware.
   - It ends with the Worker's address, like
     `https://nesp32-rendezvous.<subdomain>.workers.dev`. The firmware will
     need it in phase 3.
6. **Check it**, with your address in place of the example:

   ```sh
   curl "https://nesp32-rendezvous.<subdomain>.workers.dev/v1/host?app=TEST&ver=1&c=1.2.3.4:5"
   # ROOM K7QF 1A2B3C4D
   RENDEZVOUS_URL=https://nesp32-rendezvous.<subdomain>.workers.dev \
       .venv/bin/python -m pytest tests/test_rendezvous.py      # from the repo's top
   ```

   The tests that need the clock moved are skipped against a real one. The
   rooms they open are forgotten 30 seconds later.

## From then on

- **`npx wrangler deploy`** after a change, from this directory.
- **`npx wrangler dev`** runs it on this computer, at
  `http://localhost:8787`. `RENDEZVOUS_URL=http://localhost:8787` asks the
  tests of it.
- **`npx wrangler tail`** shows the requests as they come.

## What the free plan allows

The Free plan's limits are per day. See Cloudflare's
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
and [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/)
for the figures as they stand.

What this server uses:
- **Requests:** every request is one to the Worker and one to a room's
  Durable Object.
- **Waiting:** a host asks every second or two while it waits, so a minute
  of waiting costs about 40 requests.
- **Writes:** a room is written when it opens, when player 2 joins, and
  when the host's candidates change. Otherwise it is written at most once
  in 10 seconds as the host asks.

At 100,000 requests a day, which was the Free plan's figure when this was
written, and a few minutes' wait for each game, that's a few hundred games
a day.

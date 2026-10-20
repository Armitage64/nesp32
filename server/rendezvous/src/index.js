// The rendezvous for nesp32's PEER: room codes, and the addresses behind
// them (room.js). A Cloudflare Worker, and a Durable Object for each room,
// named by its code, so that the two nesp32s asking about one room are
// always answered by the one object that holds it.
//
// On the Workers Free plan: past its daily limits requests fail, and
// nothing is billed. Every request is a GET with a line of plain text back,
// which is all the nesp32's fetch does (firmware/main/fetch.c):
//
//   /v1/host?app=DRMA&ver=1&c=CANDIDATES          ROOM CODE SESSION | BUSY
//   /v1/room/CODE?s=SESSION&c=CANDIDATES          WAIT | GUEST CANDIDATES | GONE
//   /v1/join/CODE?app=DRMA&ver=1&c=CANDIDATES     HOST SESSION CANDIDATES | NOROOM | MISMATCH | FULL
//
// CANDIDATES is up to four a.b.c.d:port, comma-separated, the one on its
// own network first. Anything else is answered BAD, with status 400.

import { DurableObject } from "cloudflare:workers";
import * as room from "./room.js";

const TRIES = 8;                    // codes tried before a host is told BUSY

export class Room extends DurableObject {
  async run(action, args) {
    const now = Date.now();
    const stored = (await this.ctx.storage.get("room")) ?? null;
    const { room: kept, reply } = room[action](stored, now, args);
    if (kept === null) {
      await this.ctx.storage.deleteAll();
      await this.ctx.storage.deleteAlarm();
    } else if (kept !== stored) {
      await this.ctx.storage.put("room", kept);
      await this.ctx.storage.setAlarm(room.forgetAt(kept));
    }
    return reply;
  }

  async alarm() {
    const stored = (await this.ctx.storage.get("room")) ?? null;
    if (room.expired(stored, Date.now())) {
      await this.ctx.storage.deleteAll();
    } else {
      await this.ctx.storage.setAlarm(room.forgetAt(stored));
    }
  }
}

function answer(text, status = 200) {
  return new Response(`${text}\n`, {
    status,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });
}

function random(count) {
  return crypto.getRandomValues(new Uint8Array(count));
}

function stub(env, code) {
  return env.ROOMS.get(env.ROOMS.idFromName(code));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET") {
      return answer("BAD", 405);
    }
    const query = url.searchParams;
    const parts = url.pathname.split("/").filter((part) => part !== "");
    if (parts[0] !== "v1") {
      return answer("BAD", 404);
    }
    const candidates = room.parseCandidates(query.get("c"));
    if (candidates === null) {
      return answer("BAD", 400);
    }

    if (parts[1] === "host" && parts.length === 2) {
      const game = room.parseGame(query.get("app"), query.get("ver"));
      if (game === null) {
        return answer("BAD", 400);
      }
      const session = room.sessionFrom(random(4));
      for (let tries = 0; tries < TRIES; tries++) {
        const code = room.codeFrom(random(room.CODE_LENGTH));
        const reply = await stub(env, code).run("open", { game, candidates, session });
        if (reply !== "TAKEN") {
          return answer(`ROOM ${code} ${session}`);
        }
      }
      return answer("BUSY", 503);
    }

    const code = parts[2]?.toUpperCase();
    if (parts.length !== 3 || !room.isCode(code)) {
      return answer("BAD", 400);
    }
    if (parts[1] === "room") {
      const session = query.get("s")?.toUpperCase();
      if (!/^[0-9A-F]{8}$/.test(session ?? "")) {
        return answer("BAD", 400);
      }
      return answer(await stub(env, code).run("poll", { session, candidates }));
    }
    if (parts[1] === "join") {
      const game = room.parseGame(query.get("app"), query.get("ver"));
      if (game === null) {
        return answer("BAD", 400);
      }
      return answer(await stub(env, code).run("join", { game, candidates }));
    }
    return answer("BAD", 404);
  },
};

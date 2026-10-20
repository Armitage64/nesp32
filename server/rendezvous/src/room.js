// A room: where two nesp32s that want to play the same game are told each
// other's addresses (issue #12). The host opens it and is given a code to
// show on its console; player 2 enters the code, and each is handed the
// other's candidates, the addresses at which it might be reached: its own
// on its network, and what STUN said of it from outside. They take it from
// there themselves, by sending to each other at once.
//
// Nothing here touches storage or a clock: the Durable Object (index.js)
// keeps the state, says when it is, and stores what comes back. So the
// tests, and the nesp32 repo's fake of this server, can drive it as it is.

export const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O, no 1/I
export const CODE_LENGTH = 4;
export const MAX_CANDIDATES = 4;
export const HOST_QUIET_MS = 30_000;   // a host that has not asked for this long has gone
export const LONGEST_MS = 15 * 60_000; // no room waits longer than this for player 2
export const MET_MS = 60_000;          // once met, a room answers again for this long
export const SEEN_EVERY_MS = 10_000;   // a host's asking is stored no oftener than this

const CANDIDATE = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3}):(\d{1,5})$/;

// "a.b.c.d:port,..." as a list, or null if it is not one.
export function parseCandidates(text) {
  if (typeof text !== "string" || text === "") {
    return null;
  }
  const list = text.split(",");
  if (list.length > MAX_CANDIDATES) {
    return null;
  }
  for (const each of list) {
    const parts = CANDIDATE.exec(each);
    if (parts === null) {
      return null;
    }
    const numbers = parts.slice(1).map(Number);
    if (numbers.slice(0, 4).some((byte) => byte > 255) || numbers[4] < 1 || numbers[4] > 65535) {
      return null;
    }
  }
  return list;
}

// The game, as its console's hello names it: four letters or digits, and a
// version from 0 to 255. Null if not.
export function parseGame(app, version) {
  if (typeof app !== "string" || !/^[A-Z0-9]{4}$/.test(app)
      || typeof version !== "string" || !/^\d{1,3}$/.test(version) || Number(version) > 255) {
    return null;
  }
  return { app, version: Number(version) };
}

export function isCode(text) {
  return typeof text === "string" && text.length === CODE_LENGTH
    && [...text].every((letter) => ALPHABET.includes(letter));
}

// A code, from random numbers 0..255 (CODE_LENGTH of them).
export function codeFrom(bytes) {
  return [...bytes].slice(0, CODE_LENGTH).map((byte) => ALPHABET[byte % ALPHABET.length]).join("");
}

// A session, from 4 random bytes: the name the two nesp32s' datagrams
// carry, as eight hex digits. Never 0.
export function sessionFrom(bytes) {
  const value = ((bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3] | 1) >>> 0;
  return value.toString(16).toUpperCase().padStart(8, "0");
}

export function expired(room, now) {
  if (room === null || room === undefined) {
    return true;
  }
  if (room.metAt !== null) {
    return now - room.metAt > MET_MS;
  }
  return now - room.hostSeen > HOST_QUIET_MS || now - room.madeAt > LONGEST_MS;
}

// Each of these takes the room as stored (or null) and returns
// { room, reply }: the room to store (null to forget it) and the line to
// answer with.

export function open(room, now, { game, candidates, session }) {
  if (!expired(room, now)) {
    return { room, reply: "TAKEN" };
  }
  const made = {
    app: game.app,
    version: game.version,
    session,
    host: candidates,
    guest: null,
    madeAt: now,
    hostSeen: now,
    metAt: null,
  };
  return { room: made, reply: "OPEN" };
}

// The host asks whether player 2 has come, and says where it is now: its
// router's way in may have moved since it opened the room. A room that is
// the same as it was is handed back as it was, and not stored again: the
// free plan counts what is written, and a host asks every second or two.
export function poll(room, now, { session, candidates }) {
  if (expired(room, now)) {
    return { room: null, reply: "GONE" };
  }
  if (room.session !== session) {
    return { room, reply: "GONE" };
  }
  const reply = room.guest !== null ? `GUEST ${room.guest.join(",")}` : "WAIT";
  const moved = room.host.join(",") !== candidates.join(",");
  if (!moved && now - room.hostSeen < SEEN_EVERY_MS) {
    return { room, reply };
  }
  return { room: { ...room, hostSeen: now, host: candidates }, reply };
}

// Player 2. Asked again with the same candidates, as when its answer was
// lost, it is answered again.
export function join(room, now, { game, candidates }) {
  if (expired(room, now)) {
    return { room: null, reply: "NOROOM" };
  }
  if (room.app !== game.app || room.version !== game.version) {
    return { room, reply: "MISMATCH" };
  }
  const host = `HOST ${room.session} ${room.host.join(",")}`;
  if (room.guest !== null) {
    const same = room.guest.join(",") === candidates.join(",");
    return { room, reply: same ? host : "FULL" };
  }
  return { room: { ...room, guest: candidates, metAt: now }, reply: host };
}

// When the room is to be forgotten if nothing more happens.
export function forgetAt(room) {
  if (room.metAt !== null) {
    return room.metAt + MET_MS;
  }
  return Math.min(room.hostSeen + HOST_QUIET_MS, room.madeAt + LONGEST_MS);
}

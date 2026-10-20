// room.js on its own, with the test as the clock: `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as room from "../src/room.js";

const DRMA = { app: "DRMA", version: 1 };
const HOST = ["192.168.1.20:6502", "96.231.60.51:6502"];
const GUEST = ["10.0.0.7:6502", "172.56.33.198:41747"];

function opened(now = 0) {
  return room.open(null, now, { game: DRMA, candidates: HOST, session: "1A2B3C4D" }).room;
}

test("candidates are up to four a.b.c.d:port", () => {
  assert.deepEqual(room.parseCandidates("1.2.3.4:5,6.7.8.9:6502"), ["1.2.3.4:5", "6.7.8.9:6502"]);
  for (const bad of ["", "1.2.3.4", "1.2.3.256:1", "1.2.3.4:0", "1.2.3.4:65536", "a:1",
                     "1.1.1.1:1,1.1.1.1:2,1.1.1.1:3,1.1.1.1:4,1.1.1.1:5", null]) {
    assert.equal(room.parseCandidates(bad), null, String(bad));
  }
});

test("a game is four letters or digits and a version", () => {
  assert.deepEqual(room.parseGame("DRMA", "1"), DRMA);
  for (const [app, version] of [["drma", "1"], ["DRM", "1"], ["DRMA", "256"], ["DRMA", "-1"],
                                ["DRMA", null]]) {
    assert.equal(room.parseGame(app, version), null);
  }
});

test("codes keep to the alphabet, which has no look-alikes", () => {
  assert.equal(room.ALPHABET.length, 32);
  for (const letter of "01IO") {
    assert.ok(!room.ALPHABET.includes(letter));
  }
  assert.equal(room.codeFrom([0, 31, 32, 255]), "A9A9");
  assert.ok(room.isCode("K7QF"));
  assert.ok(!room.isCode("K7Q0") && !room.isCode("K7Q") && !room.isCode("k7qf"));
});

test("a session is never 0", () => {
  assert.equal(room.sessionFrom([0, 0, 0, 0]), "00000001");
  assert.equal(room.sessionFrom([0xAB, 0xCD, 0xEF, 0x10]), "ABCDEF11");
});

test("player 2 is given the host's candidates, and the host player 2's", () => {
  let kept = opened();
  assert.equal(room.poll(kept, 1000, { session: "1A2B3C4D", candidates: HOST }).reply, "WAIT");
  const joined = room.join(kept, 2000, { game: DRMA, candidates: GUEST });
  assert.equal(joined.reply, `HOST 1A2B3C4D ${HOST.join(",")}`);
  kept = joined.room;
  assert.equal(room.poll(kept, 3000, { session: "1A2B3C4D", candidates: HOST }).reply,
               `GUEST ${GUEST.join(",")}`);
});

test("a room in use is not opened again", () => {
  const kept = opened();
  assert.equal(room.open(kept, 1000, { game: DRMA, candidates: HOST, session: "FFFFFFFF" }).reply,
               "TAKEN");
});

test("another game, or another version, is refused", () => {
  const kept = opened();
  for (const game of [{ app: "TTRS", version: 1 }, { app: "DRMA", version: 2 }]) {
    assert.equal(room.join(kept, 1000, { game, candidates: GUEST }).reply, "MISMATCH");
  }
});

test("a join asked again is answered again, and a third player is not", () => {
  const kept = room.join(opened(), 1000, { game: DRMA, candidates: GUEST }).room;
  assert.match(room.join(kept, 2000, { game: DRMA, candidates: GUEST }).reply, /^HOST /);
  assert.equal(room.join(kept, 2000, { game: DRMA, candidates: ["8.8.8.8:1"] }).reply, "FULL");
});

test("only the host's session may ask after player 2", () => {
  assert.equal(room.poll(opened(), 1000, { session: "00000001", candidates: HOST }).reply, "GONE");
});

test("a host's candidates are taken afresh when they move", () => {
  const moved = ["192.168.1.20:6502", "96.231.60.51:7000"];
  const kept = room.poll(opened(), 1000, { session: "1A2B3C4D", candidates: moved }).room;
  assert.match(room.join(kept, 2000, { game: DRMA, candidates: GUEST }).reply, /:7000$/);
});

test("a host that asks often is stored seldom", () => {
  const kept = opened();
  assert.equal(room.poll(kept, 2000, { session: "1A2B3C4D", candidates: HOST }).room, kept);
  assert.notEqual(room.poll(kept, room.SEEN_EVERY_MS, { session: "1A2B3C4D", candidates: HOST })
    .room, kept);
});

test("a room is forgotten when its host stops asking", () => {
  const kept = opened();
  const late = room.HOST_QUIET_MS + 1;
  assert.equal(room.forgetAt(kept), room.HOST_QUIET_MS);
  assert.equal(room.join(kept, late, { game: DRMA, candidates: GUEST }).reply, "NOROOM");
  assert.equal(room.poll(kept, late, { session: "1A2B3C4D", candidates: HOST }).reply, "GONE");
});

test("a host that keeps asking waits no longer than LONGEST_MS", () => {
  let kept = opened();
  for (let now = room.SEEN_EVERY_MS; now <= room.LONGEST_MS; now += room.SEEN_EVERY_MS) {
    kept = room.poll(kept, now, { session: "1A2B3C4D", candidates: HOST }).room;
  }
  assert.equal(room.forgetAt(kept), room.LONGEST_MS);
  assert.equal(room.join(kept, room.LONGEST_MS + 1, { game: DRMA, candidates: GUEST }).reply,
               "NOROOM");
});

test("a room that met is forgotten MET_MS after", () => {
  const kept = room.join(opened(), 1000, { game: DRMA, candidates: GUEST }).room;
  assert.equal(room.forgetAt(kept), 1000 + room.MET_MS);
  assert.equal(room.join(kept, 1001 + room.MET_MS, { game: DRMA, candidates: GUEST }).reply,
               "NOROOM");
});

test("a code that has been forgotten may be opened again", () => {
  const kept = opened();
  assert.equal(room.open(kept, room.HOST_QUIET_MS + 1,
                         { game: DRMA, candidates: HOST, session: "FFFFFFFF" }).reply, "OPEN");
});

// Tests for the board's client-side recompute (run: `npm test`, i.e. node --test).
// These mirror the backend bands in app/arrivals.py (_minutes_until, _classify)
// and the drop-departed rule, so the JS and Python sides can't silently diverge.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  minutesUntil,
  classify,
  countdownLabel,
  liveArrivals,
  agoLabel,
  bulletTextColor,
  catchabilityLabel,
  clockTime,
  leaveInMinutes,
  stationWalkMinutes,
  DEFAULT_WALK_DELTA,
  GLANCE_LIMIT,
} from "./format.js";

const NOW = Date.UTC(2026, 7, 30, 16, 0, 0); // fixed epoch ms
const iso = (mins, secs = 0) =>
  new Date(NOW + mins * 60000 + secs * 1000).toISOString();

test("minutesUntil floors to whole minutes, like the backend", () => {
  assert.equal(minutesUntil(iso(2, 45), NOW), 2); // 2m45s -> 2
  assert.equal(minutesUntil(iso(0, 59), NOW), 0);
  assert.equal(minutesUntil(iso(5), NOW), 5);
});

test("minutesUntil goes negative once the arrival has passed", () => {
  assert.equal(minutesUntil(iso(-1, 0), NOW), -1);
  assert.equal(minutesUntil(iso(0, -30), NOW), -1); // 30s ago floors to -1
});

test("classify returns null when no walk time is configured", () => {
  assert.equal(classify(3, null), null);
  assert.equal(classify(3, undefined), null);
});

test("classify bands match the backend (CATCHABLE/HURRY/MISSED)", () => {
  // walk 5, default grace 1 -> HURRY band is [4, 5].
  assert.equal(classify(6, 5), "CATCHABLE"); // minutes > walk
  assert.equal(classify(5, 5), "HURRY"); // == walk
  assert.equal(classify(4, 5), "HURRY"); // == walk - delta
  assert.equal(classify(3, 5), "MISSED"); // < walk - delta
});

test("classify honors a custom grace window", () => {
  assert.equal(classify(3, 5, 2), "HURRY"); // walk-2 = 3
  assert.equal(classify(2, 5, 2), "MISSED");
  assert.equal(DEFAULT_WALK_DELTA, 1);
});

test("countdownLabel shows Due under a minute out, the number otherwise", () => {
  assert.equal(countdownLabel(0), "Due"); // <1 min -> "Due", never "0"
  assert.equal(countdownLabel(1), "1");
  assert.equal(countdownLabel(12), "12");
});

test("liveArrivals drops departed trains and attaches fresh minutes/catchability", () => {
  const group = {
    walk_minutes: 5,
    arrivals: [
      { trip_id: "a", arrival: iso(-1) }, // departed -> dropped
      { trip_id: "b", arrival: iso(6) }, // CATCHABLE
      { trip_id: "c", arrival: iso(4, 30) }, // 4 -> HURRY
      { trip_id: "d", arrival: iso(2) }, // MISSED
    ],
  };
  const live = liveArrivals(group, NOW);
  assert.deepEqual(
    live.map((a) => [a.trip_id, a.minutes, a.catchability]),
    [
      ["b", 6, "CATCHABLE"],
      ["c", 4, "HURRY"],
      ["d", 2, "MISSED"],
    ],
  );
});

test("liveArrivals leaves catchability null when the station has no walk time", () => {
  const group = { walk_minutes: null, arrivals: [{ trip_id: "a", arrival: iso(3) }] };
  assert.equal(liveArrivals(group, NOW)[0].catchability, null);
});

test("agoLabel reads naturally across ranges", () => {
  assert.equal(agoLabel(2), "just now");
  assert.equal(agoLabel(12), "12s ago");
  assert.equal(agoLabel(125), "2m ago");
});

test("bulletTextColor picks a legible contrast per MTA color", () => {
  assert.equal(bulletTextColor("#FCCC0A"), "#000000"); // yellow (NQRW) -> black
  assert.equal(bulletTextColor("#0039A6"), "#ffffff"); // blue (ACE) -> white
});

test("catchabilityLabel names each band, nothing when unclassified", () => {
  assert.equal(catchabilityLabel("CATCHABLE"), "Catchable");
  assert.equal(catchabilityLabel("HURRY"), "Run");
  assert.equal(catchabilityLabel("MISSED"), "Missed");
  assert.equal(catchabilityLabel(null), null); // no walk time -> no label
});

test("clockTime pins the wall clock to New York, not the host's zone", () => {
  // NOW is 16:00 UTC -> 12:00 in America/New_York (EDT), regardless of TZ.
  assert.match(clockTime(NOW), /\b12:00\b/);
});

test("GLANCE_LIMIT is smaller than the cached depth, so the detail shows more", () => {
  // The board renders GLANCE_LIMIT per row; the server caches BOARD_LIMIT (10)
  // so tapping a row reveals more without another fetch (issue #9).
  assert.ok(GLANCE_LIMIT >= 1 && GLANCE_LIMIT < 10);
});

test("leaveInMinutes counts down and never goes negative (issue #27)", () => {
  assert.equal(leaveInMinutes(iso(4, 30), NOW), 4); // 4m30s -> 4
  assert.equal(leaveInMinutes(iso(0, 20), NOW), 0);
  assert.equal(leaveInMinutes(iso(-3), NOW), 0); // already past -> "leave now"
});

test("clockTime renders a NY wall-clock label and empty for missing input", () => {
  // 13:05 UTC == 09:05 America/New_York (EDT) on this summer date.
  assert.equal(clockTime(new Date(Date.UTC(2026, 7, 30, 13, 5)).toISOString()), "9:05 AM");
  assert.equal(clockTime(null), "");
});

test("stationWalkMinutes returns the shared value, else null (issue #10)", () => {
  // The common case: every group at the station carries the same walk time.
  assert.equal(
    stationWalkMinutes({ arrivals: [{ walk_minutes: 5 }, { walk_minutes: 5 }] }),
    5,
  );
  // No group has a walk time -> nothing to show.
  assert.equal(
    stationWalkMinutes({ arrivals: [{ walk_minutes: null }, {}] }),
    null,
  );
  // Groups disagree (misconfig) -> omit rather than pick one arbitrarily.
  assert.equal(
    stationWalkMinutes({ arrivals: [{ walk_minutes: 5 }, { walk_minutes: 8 }] }),
    null,
  );
  // A single group with a walk time still resolves.
  assert.equal(stationWalkMinutes({ arrivals: [{ walk_minutes: 4 }] }), 4);
});

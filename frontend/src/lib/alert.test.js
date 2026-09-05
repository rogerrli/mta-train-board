// Tests for the focus-mode leave-by alert arming (issue #54). Run: `npm test`
// (node --test). Covers the "once per departure / re-arm on a new train / only
// when actionable" rules that keep the beep from repeating or firing on a train
// you can't make.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createLeaveAlert } from "./alert.js";

const NOW = Date.UTC(2026, 0, 5, 13, 0, 0); // fixed wall clock for the tests
const LEAD = 10;

// A focus trip whose recommendation leaves `leaveInMin` minutes from NOW.
function trip(leaveInMin, status = "on_time") {
  return tripLeavingAt(NOW + leaveInMin * 60000, status);
}

// A focus trip whose recommendation leaves at an absolute epoch-ms `leaveByMs` --
// lets a test jitter leave_by by seconds (as a live feed does) independent of now.
function tripLeavingAt(leaveByMs, status = "on_time") {
  return { status, recommended: { leave_by: new Date(leaveByMs).toISOString() } };
}

test("fires once when the on-time rec first reaches the lead time", () => {
  const alert = createLeaveAlert();
  // 11 min out -> not yet; 10 min out -> fire.
  assert.equal(alert.shouldFire(trip(11), LEAD, NOW), false);
  assert.equal(alert.shouldFire(trip(10), LEAD, NOW), true);
});

test("does not repeat for the same departure on later ticks", () => {
  const alert = createLeaveAlert();
  const t = trip(10);
  assert.equal(alert.shouldFire(t, LEAD, NOW), true);
  // Same leave_by, even as it ticks further down -> stays quiet.
  assert.equal(alert.shouldFire(t, LEAD, NOW + 60000), false);
  assert.equal(alert.shouldFire(t, LEAD, NOW + 5 * 60000), false);
});

test("does not re-fire when the feed jitters leave_by within the window", () => {
  const alert = createLeaveAlert();
  const leaveBy = NOW + 10 * 60000;
  // First poll fires at the 10-min mark.
  assert.equal(alert.shouldFire(tripLeavingAt(leaveBy, "on_time"), LEAD, NOW), true);
  // Next polls: same train, predicted departure nudged a few seconds either way
  // (still inside the lead) and the clock advanced -> must stay quiet.
  assert.equal(
    alert.shouldFire(tripLeavingAt(leaveBy + 3000, "on_time"), LEAD, NOW + 30000),
    false,
  );
  assert.equal(
    alert.shouldFire(tripLeavingAt(leaveBy - 4000, "on_time"), LEAD, NOW + 60000),
    false,
  );
});

test("re-arms once a genuinely later train pushes leave-by back above the lead", () => {
  const alert = createLeaveAlert();
  assert.equal(alert.shouldFire(trip(10), LEAD, NOW), true); // fire for train A
  // Train A departs; the next pick (train B) leaves 20 min out -> back above lead.
  assert.equal(alert.shouldFire(trip(20), LEAD, NOW), false); // re-armed, quiet
  // Train B ticks down into the window -> its own heads-up.
  assert.equal(alert.shouldFire(trip(9), LEAD, NOW), true);
});

test("a brief non-on_time status flap does not re-arm within the window", () => {
  const alert = createLeaveAlert();
  const leaveBy = NOW + 10 * 60000;
  assert.equal(alert.shouldFire(tripLeavingAt(leaveBy, "on_time"), LEAD, NOW), true);
  // One poll where nothing makes it (late), then back to on_time, same window.
  assert.equal(alert.shouldFire(trip(9, "late"), LEAD, NOW + 30000), false);
  assert.equal(
    alert.shouldFire(tripLeavingAt(leaveBy, "on_time"), LEAD, NOW + 60000),
    false,
  );
});

test("stays silent for non-actionable statuses", () => {
  for (const status of ["late", "no_service", "no_estimate", "no_target"]) {
    const alert = createLeaveAlert();
    assert.equal(alert.shouldFire(trip(2, status), LEAD, NOW), false, status);
  }
});

test("stays silent with no focused trip", () => {
  const alert = createLeaveAlert();
  assert.equal(alert.shouldFire(null, LEAD, NOW), false);
});

test("stays silent while still outside the lead window", () => {
  const alert = createLeaveAlert();
  assert.equal(alert.shouldFire(trip(15), LEAD, NOW), false);
});

test("honors a custom lead time", () => {
  const alert = createLeaveAlert();
  assert.equal(alert.shouldFire(trip(6), 5, NOW), false);
  assert.equal(alert.shouldFire(trip(5), 5, NOW), true);
});

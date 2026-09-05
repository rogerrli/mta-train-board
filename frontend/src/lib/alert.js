// Focus-mode leave-by alert arming (issue #54).
//
// When the board is dedicated to one trip (scheduled focus, #39), we beep once
// as a heads-up `alert_lead_minutes` before you need to leave to catch the
// recommended train (#27). This module owns just the *when*: the pure decision
// of whether it's time to fire, plus the "once per departure" bookkeeping. The
// sound itself lives in sound.js; the wiring in App.svelte.
//
// Arming rules (from the issue):
//   - Only an actionable, on-time recommendation warrants a warning -- never
//     late / no_service / no_estimate / no_target (no point warning about a
//     train you can't make).
//   - Fire once per departure, then stay quiet no matter how the tick or the
//     next poll nudges things.
//   - Re-arm when the recommended train changes: a later train gets its own
//     heads-up.
//
// We arm on the *lead threshold*, not on the `leave_by` timestamp. Keying on the
// exact leave_by looks tempting but breaks under live feeds: GTFS-RT nudges the
// predicted departure by seconds between polls, so leave_by would keep changing
// within the window and re-fire every poll. Instead: fire when leave-by is within
// the lead, then stay fired until leave-by climbs back *above* the lead -- which
// only a genuinely later recommended train does (time only moves forward, so the
// next pick always leaves later). Second-level jitter and a brief status flap
// stay inside the window and don't re-trigger.

import { leaveInMinutes } from "./format.js";

export function createLeaveAlert() {
  // Whether we've already beeped for the current departure. Cleared (re-armed)
  // only when an on-time recommendation is comfortably before its leave-by again.
  let fired = false;

  return {
    // Decide whether to beep right now for the focus trip. Returns true at most
    // once per departure -- the first tick at which an on-time recommendation is
    // within `leadMinutes` of its leave-by. `trip` is the focus trip's #27
    // recommendation (or null when no trip is focused); `now` is the shared
    // wall-clock tick so this ticks down between polls like the countdown.
    shouldFire(trip, leadMinutes, now) {
      // Only the focus trip, and only when there's a train worth catching. When
      // there's no actionable rec (late/no_service/.../no focus), hold the fired
      // state as-is -- a momentary status flap must not re-arm us.
      const rec = trip && trip.status === "on_time" ? trip.recommended : null;
      if (!rec) return false;
      // Still comfortably before leave-by -- or a newly recommended later train
      // pushed the window back out. Arm for this departure (leaveInMinutes is
      // never negative).
      if (leaveInMinutes(rec.leave_by, now) > leadMinutes) {
        fired = false;
        return false;
      }
      // Within the lead window: beep once, then stay quiet for this departure.
      if (fired) return false;
      fired = true;
      return true;
    },
  };
}

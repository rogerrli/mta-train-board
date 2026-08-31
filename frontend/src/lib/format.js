// Client-side recompute of countdowns + catchability.
//
// The server (issue #6) polls the feeds only every `refresh_interval_seconds`,
// so the numbers in a payload are frozen at poll time. Per the #8 decision, the
// board recomputes the countdown minutes every second from each train's absolute
// `arrival` timestamp, and reclassifies catchability off that fresh number, so a
// train visibly ticks down and crosses CATCHABLE -> HURRY -> MISSED between polls
// instead of jumping only when new data arrives.

// Default best-case grace window (minutes) for the HURRY band. Mirrors the
// backend's DEFAULT_WALK_BEST_CASE_DELTA (app/arrivals.py). A user who overrides
// `walk_best_case_delta_minutes` in config has it applied server-side on every
// poll; between polls we use this default, which self-corrects on the next poll.
export const DEFAULT_WALK_DELTA = 1;

// Floored whole minutes from `now` to an ISO arrival time. Matches the backend's
// _minutes_until (int(seconds // 60)): a 2m45s gap reads "2". Negative means the
// train's arrival time has already passed.
export function minutesUntil(arrivalIso, now = Date.now()) {
  const arrivalMs = new Date(arrivalIso).getTime();
  return Math.floor((arrivalMs - now) / 60000);
}

// Classify a train `minutes` out against a station's `walkMinutes`. Mirrors the
// backend's _classify bands (app/arrivals.py). Returns null when no walk time is
// configured (nothing to flag).
export function classify(minutes, walkMinutes, delta = DEFAULT_WALK_DELTA) {
  if (walkMinutes == null) return null;
  if (minutes > walkMinutes) return "CATCHABLE";
  if (minutes >= walkMinutes - delta) return "HURRY";
  return "MISSED";
}

// Recompute one arrival group's live view: drop trains whose arrival has passed
// (minutes < 0, matching the backend), and attach fresh minutes + catchability.
// Reclassification uses the default grace window (DEFAULT_WALK_DELTA); the server
// applies any configured walk_best_case_delta_minutes and its authoritative
// catchability re-syncs on every poll, so a non-default grace only affects the
// between-poll HURRY edge.
export function liveArrivals(group, now) {
  const out = [];
  for (const a of group.arrivals) {
    const minutes = minutesUntil(a.arrival, now);
    if (minutes < 0) continue; // already departed -> drop, as the backend does
    out.push({
      ...a,
      minutes,
      catchability: classify(minutes, group.walk_minutes),
    });
  }
  return out;
}

// "just now" / "12s ago" / "3m ago" for the freshness indicator.
export function agoLabel(seconds) {
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  const mins = Math.floor(seconds / 60);
  return `${mins}m ago`;
}

// Text color (black/white) for a line bullet, picked for contrast against the
// route's background color via relative luminance. The MTA's yellow (NQRW) and
// grey (L, shuttles) lines take black text; the dark trunks take white.
export function bulletTextColor(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.45 ? "#000000" : "#ffffff";
}

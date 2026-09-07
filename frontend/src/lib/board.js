import { writable } from "svelte/store";
import { clockOffsetMs } from "./format.js";

// Polls GET /api/state on the interval the server reports (refresh_interval_seconds)
// and exposes the board state as a Svelte store. The server answers from its
// background poll cache, so this is a cheap same-origin read, not a live feed
// fetch. States:
//
//   loading  first request in flight, nothing to show yet
//   waiting  server returned 503 (cold start: no successful poll yet) and we have
//            no prior data -- keep retrying
//   ready    we have a payload to render (possibly flagged stale by the server)
//
// A transient fetch failure (network blip) keeps the last good payload on screen
// flagged `offline`; the server's own `stale` flag covers a feed outage where our
// fetch still works. App.svelte turns either into a banner + dimmed countdowns
// and recovers automatically on the next good poll (issue #14).
//
// Each good poll also carries `clockOffset` (ms): the gap between the server's
// `server_time` and the device clock when the response landed, which App.svelte
// adds to `Date.now()` so countdowns stay right on a kiosk with a drifted clock
// (issue #14).

const FALLBACK_REFRESH_SECONDS = 30;

export function createBoard() {
  const { subscribe, update, set } = writable({
    status: "loading",
    payload: null, // last good /api/state payload
    offline: false, // last fetch attempt failed (transient)
    clockOffset: 0, // ms to add to Date.now() to match the server clock (#14)
  });

  let timer = null;
  let stopped = false;

  function schedule(seconds) {
    clearTimeout(timer);
    if (stopped) return;
    timer = setTimeout(tick, Math.max(seconds, 1) * 1000);
  }

  async function tick() {
    let refresh = FALLBACK_REFRESH_SECONDS;
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      if (stopped) return; // torn down mid-flight: don't write the dead store
      if (res.status === 503) {
        // Cold start: no successful poll yet. Show "waiting" only if we have
        // nothing; if we already had data, keep it and just mark offline.
        update((s) => ({
          ...s,
          status: s.payload ? "ready" : "waiting",
          offline: true,
        }));
      } else if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      } else {
        const payload = await res.json();
        // Measure the device-clock offset right when the body lands, before any
        // further awaits (#14).
        const clockOffset = clockOffsetMs(payload.server_time);
        refresh = payload.refresh_interval_seconds || FALLBACK_REFRESH_SECONDS;
        if (stopped) return;
        set({ status: "ready", payload, offline: false, clockOffset });
      }
    } catch {
      // Network/parse error: keep the last good payload (and its clock offset),
      // flag offline.
      if (stopped) return;
      update((s) => ({ ...s, status: s.payload ? "ready" : "loading", offline: true }));
    } finally {
      schedule(refresh);
    }
  }

  return {
    subscribe,
    start() {
      stopped = false;
      tick();
    },
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
  };
}

import { writable } from "svelte/store";

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
// A transient fetch failure (network blip) keeps the last good payload on screen;
// the server's own `stale` flag and our "updated Xs ago" line signal age. Richer
// offline UX is issue #14.

const FALLBACK_REFRESH_SECONDS = 30;

export function createBoard() {
  const { subscribe, update, set } = writable({
    status: "loading",
    payload: null, // last good /api/state payload
    offline: false, // last fetch attempt failed (transient)
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
        refresh = payload.refresh_interval_seconds || FALLBACK_REFRESH_SECONDS;
        if (stopped) return;
        set({ status: "ready", payload, offline: false });
      }
    } catch {
      // Network/parse error: keep the last good payload, flag offline.
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

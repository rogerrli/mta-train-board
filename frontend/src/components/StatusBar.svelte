<script>
  import { agoLabel } from "../lib/format.js";

  let { payload, offline, now } = $props();

  // Live "updated Xs ago", ticking off the shared clock rather than the frozen
  // age_seconds in the payload.
  const ageSeconds = $derived(
    payload ? Math.max(0, (now - new Date(payload.updated_at).getTime()) / 1000) : 0,
  );

  // The server flags `stale` once its cache ages past the configured threshold;
  // a failed fetch adds `offline`. Either one dims the board's freshness dot.
  const state = $derived(
    offline ? "offline" : payload?.stale ? "stale" : "live",
  );
  const label = $derived(
    { live: "LIVE", stale: "DATA IS OLD", offline: "OFFLINE" }[state],
  );

  // Pin the wall clock to New York regardless of the device's timezone -- the
  // whole app is America/New_York-anchored (the countdowns already are).
  const clock = $derived(
    new Date(now).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "America/New_York",
    }),
  );
</script>

<header class="bar">
  <div class="brand">
    <span class="dot {state}" aria-hidden="true"></span>
    <span class="status">{label}</span>
    <span class="ago">updated {agoLabel(ageSeconds)}</span>
  </div>
  <div class="clock tnum">{clock}</div>
</header>

<style>
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 clamp(0.3rem, 1vw, 0.8rem);
    color: var(--text-dim);
    font-size: clamp(0.8rem, 1.8vh, 1.15rem);
    letter-spacing: 0.02em;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.5em;
  }

  .status {
    font-weight: 700;
  }

  .ago {
    color: var(--text-faint);
  }

  .dot {
    width: 0.7em;
    height: 0.7em;
    border-radius: 50%;
    background: #35c759; /* live: green */
  }
  .dot.stale {
    background: #ffb020; /* amber */
  }
  .dot.offline {
    background: var(--hurry);
    animation: blink 1.4s ease-in-out infinite;
  }

  .clock {
    font-weight: 700;
    color: var(--text);
    font-size: 1.3em;
  }

  @keyframes blink {
    50% {
      opacity: 0.3;
    }
  }
</style>

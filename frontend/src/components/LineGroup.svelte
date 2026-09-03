<script>
  import {
    liveArrivals,
    bulletTextColor,
    countdownLabel,
    GLANCE_LIMIT,
  } from "../lib/format.js";

  // One line + direction: the route bullet, the direction, and the next few
  // countdowns. Minutes and catchability are recomputed every second off the
  // shared `now` clock (issue #8), so trains tick down and cross
  // CATCHABLE -> HURRY -> MISSED between server polls.
  //
  // The whole row is a button: tapping it opens the detail breakdown (issue #9)
  // via `onselect`. The cached payload carries a deeper list than the glance
  // shows, so the glance renders only the first GLANCE_LIMIT here and the detail
  // overlay shows the full group.
  let { group, now, onselect } = $props();

  const arrivals = $derived(liveArrivals(group, now));
  const glance = $derived(arrivals.slice(0, GLANCE_LIMIT));
  const textColor = $derived(bulletTextColor(group.color));
  // Terminal-station label (#41): show the configured destination + borough,
  // falling back to the compass word ("Northbound") when unconfigured.
  const primary = $derived(group.terminal ?? group.direction_label);
</script>

<button type="button" class="group tap-reset" onclick={onselect}>
  <span
    class="bullet"
    style="background:{group.color}; color:{textColor}"
    title={primary}
  >
    {group.line}
  </span>
  <span class="dir" class:named={group.terminal}>
    <span class="terminal">{primary}</span>
    {#if group.borough}<span class="borough">{group.borough}</span>{/if}
  </span>
  <div class="times">
    {#if glance.length === 0}
      <span class="none">No trains</span>
    {:else}
      {#each glance as a, i (a.trip_id)}
        <span
          class="min tnum {a.catchability?.toLowerCase() ?? 'calm'}"
          class:lead={i === 0}
        >
          {countdownLabel(a.minutes)}
        </span>
      {/each}
    {/if}
  </div>
</button>

<style>
  /* The row is a button (tap -> detail breakdown, issue #9) that must read as a
     plain board row. Chrome reset + tap/hover/focus feedback come from the shared
     .tap-reset (app.css); this only sets its layout. */
  .group {
    display: flex;
    align-items: center;
    gap: clamp(0.4rem, 1vw, 0.8rem);
    min-width: 0;
    width: 100%;
    padding: clamp(0.15rem, 0.6vh, 0.4rem) clamp(0.2rem, 0.6vw, 0.5rem);
    border-radius: clamp(0.3rem, 0.8vw, 0.6rem);
  }

  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(1.6rem, 4.6vh, 3rem);
    height: clamp(1.6rem, 4.6vh, 3rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(0.95rem, 2.7vh, 1.7rem);
    line-height: 1;
  }

  .dir {
    flex: none;
    width: clamp(4.5rem, 12vw, 8rem);
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.15em;
    min-width: 0;
    color: var(--text-dim);
    font-weight: 600;
  }

  .terminal {
    font-size: clamp(0.7rem, 1.8vh, 1.05rem);
    line-height: 1.1;
    /* Keep a long terminal name from blowing out the fixed column: wrap to at
       most two lines, then ellipsize. */
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }

  /* The compass fallback ("Northbound") keeps its original all-caps treatment;
     real terminal names are mixed-case and read better left as written. */
  .dir:not(.named) .terminal {
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .borough {
    font-size: clamp(0.55rem, 1.3vh, 0.8rem);
    line-height: 1;
    color: var(--text-faint);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .times {
    display: flex;
    align-items: baseline;
    gap: clamp(0.5rem, 1.6vw, 1.2rem);
    min-width: 0;
    overflow: hidden;
  }

  .min {
    font-size: clamp(1.4rem, 4.6vh, 3.1rem);
    font-weight: 800;
    line-height: 1;
    color: var(--calm);
  }

  /* The soonest train is the one you act on: make it the biggest thing here. */
  .min.lead {
    font-size: clamp(1.9rem, 6.4vh, 4.4rem);
  }

  /* HURRY: only makeable if you move now. Loud + pulsing. */
  .min.hurry {
    color: var(--hurry);
    animation: pulse 1.1s ease-in-out infinite;
  }

  /* MISSED: not feasible at walking pace. De-emphasize (owner's #7 call), keep
     it visible so the pattern of service still reads. */
  .min.missed {
    color: var(--text-faint);
    text-decoration: line-through;
    text-decoration-thickness: 0.06em;
    font-weight: 600;
  }

  .none {
    font-size: clamp(0.9rem, 2.4vh, 1.4rem);
    color: var(--text-faint);
    font-style: italic;
  }

  @keyframes pulse {
    50% {
      opacity: 0.45;
    }
  }
</style>

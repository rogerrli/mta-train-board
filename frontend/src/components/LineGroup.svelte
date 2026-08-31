<script>
  import { liveArrivals, bulletTextColor } from "../lib/format.js";

  // One line + direction: the route bullet, the direction, and the next few
  // countdowns. Minutes and catchability are recomputed every second off the
  // shared `now` clock (issue #8), so trains tick down and cross
  // CATCHABLE -> HURRY -> MISSED between server polls.
  let { group, now } = $props();

  const arrivals = $derived(liveArrivals(group, now));
  const textColor = $derived(bulletTextColor(group.color));
  // Terminal-station label (#41): show the configured destination + borough,
  // falling back to the compass word ("Northbound") when unconfigured.
  const primary = $derived(group.terminal ?? group.direction_label);
</script>

<div class="group">
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
    {#if arrivals.length === 0}
      <span class="none">No trains</span>
    {:else}
      {#each arrivals as a, i (a.trip_id)}
        <span
          class="min tnum {a.catchability?.toLowerCase() ?? 'calm'}"
          class:lead={i === 0}
        >
          {a.minutes}
          {#if a.catchability === "HURRY"}<span class="tag">run</span>{/if}
        </span>
      {/each}
      <span class="unit">min</span>
    {/if}
  </div>
</div>

<style>
  .group {
    display: flex;
    align-items: center;
    gap: clamp(0.4rem, 1vw, 0.8rem);
    min-width: 0;
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
    position: relative;
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

  .tag {
    position: absolute;
    top: -0.35em;
    right: -1.4em;
    font-size: 0.28em;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--hurry);
  }

  /* MISSED: not feasible at walking pace. De-emphasize (owner's #7 call), keep
     it visible so the pattern of service still reads. */
  .min.missed {
    color: var(--text-faint);
    text-decoration: line-through;
    text-decoration-thickness: 0.06em;
    font-weight: 600;
  }

  .unit {
    font-size: clamp(0.7rem, 1.8vh, 1.05rem);
    color: var(--text-dim);
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

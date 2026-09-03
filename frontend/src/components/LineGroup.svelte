<script>
  import {
    liveArrivals,
    bulletTextColor,
    countdownLabel,
    GLANCE_LIMIT,
  } from "../lib/format.js";
  import SplitFlap from "./SplitFlap.svelte";

  // One line + direction: the route bullet, the direction, and the next few
  // countdowns. Minutes and catchability are recomputed every second off the
  // shared `now` clock (issue #8), so trains tick down and cross
  // CATCHABLE -> HURRY -> MISSED between server polls.
  //
  // The whole row is a button: tapping it opens the detail breakdown (issue #9)
  // via `onselect`. The cached payload carries a deeper list than the glance
  // shows, so the glance renders only the first GLANCE_LIMIT here and the detail
  // overlay shows the full group. `alerts` are the service alerts (#13) for this
  // group's line -- the row badges itself when there are any; the text shows in
  // the tap detail (a badge, not the alert text, to keep the glance uncluttered).
  let { group, now, onselect, alerts = [] } = $props();

  const arrivals = $derived(liveArrivals(group, now));
  const glance = $derived(arrivals.slice(0, GLANCE_LIMIT));
  const textColor = $derived(bulletTextColor(group.color));
  // Terminal-station label (#41): show the configured destination + borough,
  // falling back to the compass word ("Northbound") when unconfigured.
  const primary = $derived(group.terminal ?? group.direction_label);

  // Line-level match (#13): an alert on this line badges the row. A live
  // disruption (`active`) fills the badge amber; an upcoming/planned-only change
  // dims it, so a real delay reads louder than a heads-up at a glance.
  const lineAlerts = $derived(alerts.filter((a) => a.lines.includes(group.line)));
  const hasActiveAlert = $derived(lineAlerts.some((a) => a.active));
</script>

<button type="button" class="group tap-reset" onclick={onselect}>
  <span class="bullet-wrap">
    <span
      class="bullet"
      style="background:{group.color}; color:{textColor}"
      title={primary}
    >
      {group.line}
    </span>
    {#if lineAlerts.length > 0}
      <span
        class="alert-badge"
        class:active={hasActiveAlert}
        title="Service alert"
        aria-label="Service alert">!</span
      >
    {/if}
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
          <SplitFlap value={countdownLabel(a.minutes)} />
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
    padding: clamp(0.1rem, 0.4vh, 0.3rem) clamp(0.2rem, 0.6vw, 0.5rem);
    border-radius: clamp(0.3rem, 0.8vw, 0.6rem);
  }

  /* Anchors the alert badge (#13) to the bullet's top-right corner. */
  .bullet-wrap {
    flex: none;
    position: relative;
    display: inline-flex;
  }

  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(1.4rem, 3.6vh, 2.5rem);
    height: clamp(1.4rem, 3.6vh, 2.5rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(0.85rem, 2.2vh, 1.4rem);
    line-height: 1;
  }

  /* Service-alert badge (#13): a small corner marker on the line bullet. Amber
     and filled for a live disruption; dim for an upcoming/planned-only change. */
  .alert-badge {
    position: absolute;
    top: -0.2em;
    right: -0.2em;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: clamp(0.9rem, 2.2vh, 1.4rem);
    height: clamp(0.9rem, 2.2vh, 1.4rem);
    padding: 0 0.15em;
    border-radius: 999px;
    border: 1.5px solid var(--panel);
    background: var(--text-faint);
    color: #000;
    font-size: clamp(0.6rem, 1.6vh, 1rem);
    font-weight: 900;
    line-height: 1;
  }
  .alert-badge.active {
    background: var(--alert);
  }

  .dir {
    /* The countdowns are what matters (issue #50): give them priority and let
       this label yield first. It has a preferred width but may shrink (its
       terminal text clamps to two lines, borough ellipsizes) so the times keep
       their room and never clip at the card edge. */
    flex: 0 1 clamp(4.5rem, 12vw, 8rem);
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
    /* Never shrink the countdowns (issue #50): they hold their natural width so
       all GLANCE_LIMIT of them stay fully visible; the .dir label yields instead. */
    flex: none;
    display: flex;
    /* Sit the countdowns on a common bottom line. The flip digits (#53) are
       inline-blocks whose baseline is their bottom edge, so bottom-align keeps
       the lead number and the rest aligned regardless of that baseline. */
    align-items: flex-end;
    gap: clamp(0.5rem, 1.6vw, 1.2rem);
  }

  .min {
    font-size: clamp(1.2rem, 3.4vh, 2.4rem);
    font-weight: 800;
    line-height: 1;
    color: var(--calm);
  }

  /* The soonest train is the one you act on: make it the biggest thing here. */
  .min.lead {
    font-size: clamp(1.6rem, 4.6vh, 3.2rem);
  }

  /* HURRY: only makeable if you move now. Loud + pulsing. */
  .min.hurry {
    color: var(--hurry);
    animation: pulse 1.1s ease-in-out infinite;
  }

  /* MISSED: not feasible at walking pace. De-emphasize (owner's #7 call), keep
     it visible so the pattern of service still reads. The strike is drawn as an
     overlay line rather than text-decoration: the flip digits (#53) are absolutely
     positioned, so a plain line-through wouldn't paint through them. */
  .min.missed {
    position: relative;
    color: var(--text-faint);
    font-weight: 600;
  }
  .min.missed::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 0.06em;
    background: currentColor;
    transform: translateY(-50%);
    z-index: 1;
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

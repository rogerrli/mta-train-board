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
        role="img"
        title="Service alert"
        aria-label="Service alert"
      ></span>
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
    /* A subgrid over the card's column tracks (issue #67): the row spans all of
       the card's columns and borrows their sizing, so its bullet, direction, and
       countdowns land in the same columns as every other row in the card. The
       column gap is inherited from the card (Station.svelte). */
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: subgrid;
    align-items: center;
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

  /* Service-alert marker (#13, #66): a small dot tucked into the bullet's
     top-right, sized to signal an alert at a glance without covering the route
     glyph. Amber for a live disruption; dim for an upcoming/planned-only change.
     The dot is a fixed fraction of the bullet, so it stays clear of the letter
     across the whole responsive clamp. */
  .alert-badge {
    position: absolute;
    top: 6%;
    right: 6%;
    width: clamp(0.4rem, 1vh, 0.65rem);
    height: clamp(0.4rem, 1vh, 0.65rem);
    border-radius: 50%;
    border: 1.5px solid var(--panel);
    background: var(--text-faint);
  }
  .alert-badge.active {
    background: var(--alert);
  }

  .dir {
    /* Column 2 of the card grid (issue #67). The countdowns are what matters
       (issue #50): this column's preferred width lives on the card track and may
       shrink to nothing (its terminal text clamps to two lines, borough
       ellipsizes) so the times keep their room and never clip at the card edge. */
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
    /* The countdown columns (issue #67): a subgrid over the card's time tracks
       (cols 3-6) so all GLANCE_LIMIT countdowns line up down the card. Each
       countdown auto-places into the next track; the lead sits in the first,
       widest one (it's the biggest number) and still aligns. A short line leaves
       its trailing tracks blank, keeping the columns straight. Never shrinks, so
       the times stay fully visible and the .dir label yields instead (issue #50).
       Bottom-align so the larger lead and the rest sit on a common line -- the
       flip digits (#53) are inline-blocks whose baseline is their bottom edge. */
    grid-column: 3 / -1;
    display: grid;
    grid-template-columns: subgrid;
    align-items: end;
  }

  .min {
    /* Sit at the start of the countdown's column so the numbers line up on a
       common left edge and the MISSED strike wraps just the number, not the
       track's trailing space. */
    justify-self: start;
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
    /* No countdowns to place -- span the card's time tracks so the message reads
       across the row instead of being squeezed into the first column. */
    grid-column: 1 / -1;
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

<script>
  import {
    liveArrivals,
    bulletTextColor,
    catchabilityLabel,
    clockTime,
    countdownLabel,
  } from "../lib/format.js";

  // Tap-a-train detail overlay (issue #9): a fuller breakdown for one
  // station x line x direction than the glance board shows. `group` is the live
  // group object from the latest payload, so the list ticks down and refreshes
  // on every poll just like the board; `station` is its station name (the group
  // itself doesn't carry it -- the API nests groups under the station).
  //
  // Dismiss three ways for the touchscreen: the ✕ button, a tap on the backdrop
  // outside the panel, or Escape.
  let { group, station, now, onclose } = $props();

  const arrivals = $derived(liveArrivals(group, now));
  const textColor = $derived(bulletTextColor(group.color));
  // Terminal-station label (#41) as the primary destination text, matching the
  // board; falls back to the compass word ("Northbound") when unconfigured.
  const primary = $derived(group.terminal ?? group.direction_label);

  function onKeydown(e) {
    if (e.key === "Escape") onclose();
  }

  // Move focus into the dialog on open (it declares aria-modal) so a keyboard
  // user starts inside it; the ✕ is the natural landing spot.
  let closeButton = $state();
  $effect(() => closeButton?.focus());
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay" role="dialog" aria-modal="true" aria-label="{group.line} to {primary} at {station}">
  <!-- A real button behind the panel captures "tap outside to dismiss" without
       an a11y-questionable click handler on a plain div. Hidden from AT and the
       tab order -- the header ✕ is the announced, keyboard-reachable close. -->
  <button class="backdrop" aria-hidden="true" tabindex="-1" onclick={onclose}
  ></button>

  <div class="panel">
    <header class="head">
      <span
        class="bullet"
        style="background:{group.color}; color:{textColor}"
      >
        {group.line}
      </span>
      <div class="titles">
        <h2 class="dir">{primary}</h2>
        {#if group.borough}<p class="borough">{group.borough}</p>{/if}
        <p class="station">at {station}</p>
      </div>
      <button
        class="close"
        aria-label="Close"
        bind:this={closeButton}
        onclick={onclose}>✕</button
      >
    </header>

    {#if arrivals.length === 0}
      <p class="empty">No upcoming trains.</p>
    {:else}
      <ul class="list">
        {#each arrivals as a (a.trip_id)}
          {@const label = catchabilityLabel(a.catchability)}
          <li class="row {a.catchability?.toLowerCase() ?? 'calm'}">
            <span class="count tnum">
              <span class="mins">{countdownLabel(a.minutes)}</span>
              {#if a.minutes >= 1}<span class="unit">min</span>{/if}
            </span>
            <span class="mid">
              <span class="dest">{a.headsign ?? primary}</span>
              <span class="at tnum">{clockTime(a.arrival)}</span>
            </span>
            {#if label}
              <span class="tag">{label}</span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--gap);
  }

  .backdrop {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    background: rgba(0, 0, 0, 0.66);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .panel {
    position: relative;
    z-index: 1;
    width: min(46rem, 92vw);
    max-height: 92vh;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-radius: clamp(0.6rem, 1.4vw, 1.1rem);
    padding: clamp(0.8rem, 2.2vh, 1.4rem);
    box-shadow: 0 1.5rem 3rem rgba(0, 0, 0, 0.5);
  }

  .head {
    display: flex;
    align-items: center;
    gap: clamp(0.6rem, 1.6vw, 1rem);
    margin-bottom: clamp(0.6rem, 1.6vh, 1rem);
  }

  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(2.4rem, 6vh, 3.4rem);
    height: clamp(2.4rem, 6vh, 3.4rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(1.3rem, 3.4vh, 2rem);
    line-height: 1;
  }

  .titles {
    flex: 1;
    min-width: 0;
  }

  .dir {
    margin: 0;
    font-size: clamp(1.2rem, 3.4vh, 2rem);
    font-weight: 800;
    line-height: 1.05;
  }

  .borough {
    margin: 0.15em 0 0;
    color: var(--text-faint);
    font-size: clamp(0.7rem, 1.7vh, 1rem);
    font-weight: 600;
  }

  .station {
    margin: 0.1em 0 0;
    color: var(--text-dim);
    font-size: clamp(0.8rem, 2vh, 1.15rem);
    font-weight: 600;
  }

  .close {
    flex: none;
    width: clamp(2.2rem, 5.4vh, 3rem);
    height: clamp(2.2rem, 5.4vh, 3rem);
    border: 1px solid var(--panel-edge);
    border-radius: 50%;
    background: transparent;
    color: var(--text-dim);
    font-size: clamp(1rem, 2.6vh, 1.4rem);
    line-height: 1;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .close:active {
    background: var(--panel-edge);
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .row {
    display: flex;
    align-items: center;
    gap: clamp(0.7rem, 2vw, 1.3rem);
    padding: clamp(0.5rem, 1.6vh, 0.9rem) clamp(0.1rem, 0.6vw, 0.4rem);
    border-top: 1px solid var(--panel-edge);
  }
  .row:first-child {
    border-top: none;
  }

  .count {
    flex: none;
    width: clamp(4.5rem, 14vw, 6.5rem);
    display: flex;
    align-items: baseline;
    gap: 0.3em;
    color: var(--calm);
  }
  .mins {
    font-size: clamp(1.6rem, 5vh, 2.8rem);
    font-weight: 800;
    line-height: 1;
  }
  .unit {
    font-size: clamp(0.7rem, 1.7vh, 1rem);
    color: var(--text-dim);
    font-weight: 600;
  }

  .mid {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15em;
  }
  .dest {
    font-size: clamp(1rem, 2.6vh, 1.5rem);
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .at {
    font-size: clamp(0.8rem, 1.9vh, 1.1rem);
    color: var(--text-dim);
  }

  .tag {
    flex: none;
    font-size: clamp(0.7rem, 1.7vh, 1rem);
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-dim);
  }

  /* Catchability accents mirror the board (issue #8): HURRY loud, MISSED dimmed
     and struck through, CATCHABLE/unclassified calm. */
  .row.hurry .count,
  .row.hurry .tag {
    color: var(--hurry);
  }
  .row.missed .count,
  .row.missed .dest,
  .row.missed .at {
    color: var(--text-faint);
  }
  .row.missed .mins,
  .row.missed .dest {
    text-decoration: line-through;
    text-decoration-thickness: 0.06em;
  }
  .row.missed .tag {
    color: var(--text-faint);
  }

  .empty {
    color: var(--text-faint);
    font-style: italic;
    font-size: clamp(0.9rem, 2.4vh, 1.4rem);
    padding: clamp(0.6rem, 2vh, 1.2rem) 0;
  }
</style>

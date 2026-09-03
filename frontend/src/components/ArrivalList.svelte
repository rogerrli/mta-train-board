<script>
  import { catchabilityLabel, clockTime, countdownLabel } from "../lib/format.js";

  // The full per-line/direction arrival breakdown: one row per upcoming train
  // (countdown + destination + clock time + catchable/hurry/missed tag). Shared
  // by the single-train detail overlay (issue #9) and the consolidated station
  // view (issue #10), so a train reads the same in both.
  //
  // `arrivals` are already live-computed (minutes + catchability) by the caller
  // via `liveArrivals`, so this stays a dumb presentational list. `fallbackDest`
  // is the group's terminal/direction text, shown when a train carries no
  // headsign of its own.
  let { arrivals, fallbackDest } = $props();
</script>

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
          <span class="dest">{a.headsign ?? fallbackDest}</span>
          <span class="at tnum">{clockTime(a.arrival)}</span>
        </span>
        {#if label}
          <span class="tag">{label}</span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
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

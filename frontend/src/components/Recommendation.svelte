<script>
  import {
    clockTime,
    leaveInMinutes,
    bulletTextColor,
    formatDuration,
  } from "../lib/format.js";

  // One arrive-by recommendation (issue #27): the ideal train to catch for a
  // target arrival time, plus a safer earlier fallback. "Leave in N min" ticks
  // down every second off the shared `now` clock (from the train's absolute
  // leave_by), like the board's countdowns; the other times are NY wall-clocks.
  let { trip, now } = $props();

  const rec = $derived(trip.recommended);
  const textColor = $derived(bulletTextColor(trip.color));
  const leaveIn = $derived(rec ? leaveInMinutes(rec.leave_by, now) : null);
  const target = $derived(clockTime(trip.target));
</script>

<section class="rec {trip.status}">
  <span
    class="bullet"
    style="background:{trip.color}; color:{textColor}"
    title={trip.direction}
  >
    {trip.line}
  </span>

  <div class="body">
    {#if trip.status === "on_time" || trip.status === "late"}
      <div class="headline">
        <span class="verb">{trip.status === "on_time" ? "Catch" : "Best"}</span>
        <span class="train tnum">{clockTime(rec.departure)} {trip.line}</span>
        <span class="dest">→ {trip.destination}</span>
      </div>
      <div class="sub">
        arrives {clockTime(rec.arrival)}
        {#if trip.status === "on_time"}
          <span class="ok">· on time</span>
        {:else}
          <span class="warn"
            >· {formatDuration(rec.lateness_minutes)}{rec.lateness_minutes < 60
              ? " min"
              : ""} late</span
          >
        {/if}
        <span class="target">for {target}</span>
      </div>
      {#if trip.fallback}
        <div class="fallback">
          or the {clockTime(trip.fallback.departure)} — arrives {clockTime(
            trip.fallback.arrival,
          )}
        </div>
      {/if}
    {:else if trip.status === "no_service"}
      <div class="headline">
        <span class="verb warn">No catchable {trip.line}</span>
        <span class="dest">→ {trip.destination}</span>
      </div>
      <div class="sub">nothing you can still board for {target}</div>
    {:else}
      <!-- no_estimate -->
      <div class="headline">
        <span class="verb warn">No travel estimate</span>
        <span class="dest">→ {trip.destination}</span>
      </div>
      <div class="sub">can’t recommend a train for {target}</div>
    {/if}
  </div>

  {#if rec}
    <div class="leave">
      {#if leaveIn === 0}
        <span class="big">leave now</span>
      {:else}
        <span class="big tnum">{formatDuration(leaveIn)}</span>
        <span class="lunit">{leaveIn < 60 ? "min to leave" : "to leave"}</span>
      {/if}
    </div>
  {/if}
</section>

<style>
  .rec {
    display: flex;
    align-items: center;
    gap: clamp(0.5rem, 1.4vw, 1.1rem);
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-left: clamp(0.25rem, 0.6vw, 0.5rem) solid var(--calm);
    border-radius: clamp(0.4rem, 1vw, 0.9rem);
    padding: clamp(0.4rem, 1.4vh, 1rem) clamp(0.6rem, 1.6vw, 1.2rem);
  }
  /* On-time gets a calm green edge; the can't-make-it states go urgent red. */
  .rec.on_time {
    border-left-color: #35c759;
  }
  .rec.late,
  .rec.no_service,
  .rec.no_estimate {
    border-left-color: var(--hurry);
  }

  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(1.8rem, 5vh, 3.2rem);
    height: clamp(1.8rem, 5vh, 3.2rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(1rem, 3vh, 1.9rem);
    line-height: 1;
  }

  .body {
    flex: 1;
    min-width: 0;
  }

  .headline {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.3em;
    font-size: clamp(1.1rem, 3.2vh, 2.1rem);
    font-weight: 800;
    line-height: 1.1;
  }
  .verb {
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    font-size: 0.72em;
  }
  .verb.warn {
    color: var(--hurry);
  }
  .train {
    color: var(--text);
  }
  .dest {
    color: var(--text-dim);
    font-weight: 700;
  }

  .sub {
    margin-top: 0.15em;
    color: var(--text-dim);
    font-size: clamp(0.72rem, 1.9vh, 1.1rem);
    font-weight: 600;
  }
  .ok {
    color: #35c759;
  }
  .warn {
    color: var(--hurry);
  }
  .target {
    color: var(--text-faint);
    margin-left: 0.3em;
  }

  .fallback {
    margin-top: 0.2em;
    color: var(--text-faint);
    font-size: clamp(0.68rem, 1.7vh, 1rem);
  }

  .leave {
    flex: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding-left: clamp(0.4rem, 1.2vw, 1rem);
    border-left: 1px solid var(--panel-edge);
  }
  .big {
    font-size: clamp(1.6rem, 5.4vh, 3.6rem);
    font-weight: 800;
    line-height: 1;
    color: var(--text);
  }
  .lunit {
    font-size: clamp(0.6rem, 1.5vh, 0.9rem);
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }
</style>

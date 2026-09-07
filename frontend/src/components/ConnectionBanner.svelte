<script>
  import {
    agoLabel,
    elapsedSeconds,
    formatDuration,
    isClockSkewed,
  } from "../lib/format.js";

  // Loud degraded-state banner for the wall board (issue #14). The StatusBar dot
  // is a glance cue; this is the across-the-room "don't trust these numbers"
  // line. Two independent axes, shown stacked when both hold:
  //
  //   degraded     the board isn't showing live data -- either the last
  //                /api/state fetch failed (`offline`) or the server's cache has
  //                aged past stale_after_seconds. App owns this predicate; the
  //                `offline` flag also picks the wording (reconnecting vs. behind)
  //   clock skew   the device clock is off from the server's by over a minute;
  //                `now` is already corrected so the countdowns are right, this
  //                just flags that the kiosk needs its time synced
  //
  // Renders nothing when the board is healthy, so it costs no space in the
  // normal case and disappears on its own the moment a good poll lands.
  let {
    offline = false,
    degraded = false,
    updatedAt = null,
    clockOffset = 0,
    now = Date.now(),
  } = $props();

  const ageLabel = $derived(
    updatedAt ? agoLabel(elapsedSeconds(updatedAt, now)) : null,
  );

  const clockSkewed = $derived(isClockSkewed(clockOffset));

  // Whole minutes the device clock is off, for the "sync me" note. formatDuration
  // rolls it into "1h 20m" past an hour; under an hour it returns a bare count,
  // so tack on the unit.
  const skewLabel = $derived.by(() => {
    const mins = Math.max(1, Math.round(Math.abs(clockOffset) / 60000));
    return mins < 60 ? `${mins} min` : formatDuration(mins);
  });

  const show = $derived(degraded || clockSkewed);
</script>

{#if show}
  <div class="banner" role="status">
    {#if offline}
      <span class="line">
        <span class="spinner" aria-hidden="true"></span>
        Reconnecting… {#if ageLabel}showing arrivals from {ageLabel}{/if}
      </span>
    {:else if degraded}
      <span class="line">
        Feed is behind — {#if ageLabel}arrivals from {ageLabel}{:else}data is old{/if}
      </span>
    {/if}
    {#if clockSkewed}
      <span class="line clock">
        Device clock is off by ~{skewLabel} — countdowns auto-corrected, sync the
        device time
      </span>
    {/if}
  </div>
{/if}

<style>
  .banner {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 0.2em;
    padding: clamp(0.4rem, 1.3vh, 0.8rem) clamp(0.6rem, 2vw, 1.1rem);
    border-radius: clamp(0.3rem, 0.8vw, 0.6rem);
    /* Amber wash over the panel -- the --alert hue (#f5a623) at low alpha, same
       family as the service-alert badge, loud enough to catch the eye across
       the room without the red urgency reserved for HURRY trains. */
    background: rgba(245, 166, 35, 0.15);
    border: 1px solid rgba(245, 166, 35, 0.45);
    color: var(--text);
    font-size: clamp(0.85rem, 2vh, 1.2rem);
    font-weight: 600;
    letter-spacing: 0.01em;
    animation: fade-in 0.3s ease;
  }

  .line {
    display: flex;
    align-items: center;
    gap: 0.5em;
  }

  .clock {
    color: var(--text-dim);
    font-weight: 500;
    font-size: 0.85em;
  }

  .spinner {
    flex: none;
    width: 0.9em;
    height: 0.9em;
    border: 0.16em solid rgba(245, 247, 250, 0.3);
    border-top-color: var(--text);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  @keyframes fade-in {
    from {
      opacity: 0;
    }
  }
</style>

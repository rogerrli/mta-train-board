<script>
  // Return-to-focus affordance (#60). Shown on the glance board only while a
  // focus window is still active but the owner has dismissed the focus view. It
  // does double duty:
  //   - a tap jumps straight back into focus, and
  //   - a ring wipes away clockwise over `seconds`; when it empties we auto-return.
  // Any interaction anywhere (pointer/key) re-arms the idle countdown from the
  // top -- so it only snaps back once you've actually stopped touching the board.
  //
  // The wipe is a pure CSS animation; bumping `token` on interaction re-keys the
  // element so the animation restarts. `animationend` is the auto-return trigger,
  // so the timer and the visible ring are the same clock -- they can't drift.
  let { seconds = 30, onreturn } = $props();

  let wipe = $state();
  // Re-arm the idle countdown on activity anywhere on the board -- except taps on
  // this button itself (a tap here returns rather than restarting the timer).
  // Rewind the ring's CSS animation in place rather than rebuilding the DOM: a
  // mid-tap remount would destroy the button before its `click` (which fires
  // after `pointerdown`) could fire.
  function rearm(e) {
    if (e.target?.closest?.(".return")) return;
    const anim = wipe?.getAnimations?.()[0];
    if (anim) anim.currentTime = 0;
  }
</script>

<svelte:window onpointerdown={rearm} onkeydown={rearm} />

<button
  class="return tap-reset"
  style="--secs:{seconds}s"
  onclick={onreturn}
  onanimationend={onreturn}
  aria-label="Return to focus now"
>
  <svg class="ring" viewBox="0 0 36 36" aria-hidden="true">
    <circle class="track" cx="18" cy="18" r="16" />
    <circle bind:this={wipe} class="wipe" cx="18" cy="18" r="16" pathLength="100" />
  </svg>
  <span class="label">Focus</span>
</button>

<style>
  .return {
    position: fixed;
    z-index: 90;
    bottom: var(--gap);
    right: var(--gap);
    display: flex;
    align-items: center;
    gap: 0.5em;
    padding: 0.5em 0.9em 0.5em 0.55em;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    color: var(--text);
    font-size: clamp(0.85rem, 2.4vh, 1.15rem);
    font-weight: 700;
    box-shadow: 0 0.5rem 1.4rem rgba(0, 0, 0, 0.45);
    /* Big finger target on the wall touchscreen. */
    min-height: clamp(2.8rem, 7vh, 3.6rem);
  }

  .ring {
    width: clamp(1.8rem, 4.6vh, 2.6rem);
    height: clamp(1.8rem, 4.6vh, 2.6rem);
    flex: none;
  }
  .track {
    fill: none;
    stroke: var(--panel-edge);
    stroke-width: 3;
  }
  /* Starts as a full ring at the top and erases clockwise as the offset grows. */
  .wipe {
    fill: none;
    stroke: var(--calm);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-dasharray: 100;
    transform: rotate(-90deg);
    transform-origin: center;
    animation: wipe var(--secs) linear forwards;
  }
  @keyframes wipe {
    from {
      stroke-dashoffset: 0;
    }
    to {
      stroke-dashoffset: 100;
    }
  }

  .label {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  @media (prefers-reduced-motion: reduce) {
    /* Respect reduced-motion: no visible sweep, but keep the timing so the
       auto-return still fires on `animationend`. */
    .wipe {
      animation-name: wipe-hold;
    }
    @keyframes wipe-hold {
      from {
        stroke-dashoffset: 0;
      }
      to {
        stroke-dashoffset: 0;
      }
    }
  }
</style>

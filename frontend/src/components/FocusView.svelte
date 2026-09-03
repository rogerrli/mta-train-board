<script>
  import {
    clockTime,
    leaveInMinutes,
    bulletTextColor,
    formatDuration,
  } from "../lib/format.js";
  import SplitFlap from "./SplitFlap.svelte";
  import CloseButton from "./CloseButton.svelte";

  // Scheduled focus mode (issue #39): during a configured window the board drops
  // everything else and dedicates the whole screen to one trip's arrive-by
  // recommendation (#27). `trip` is that trip's recommendation from /api/state's
  // trips[]; it carries the #41 terminal-station label (terminal/borough) so the
  // header reads "1 → Van Cortlandt Park" / "Bronx" rather than a compass word.
  // The layout is a full-screen sibling of Recommendation.svelte (the glance-strip
  // card) -- they share the status/leave logic below, so keep them in sync.
  // "Leave in N min" ticks down every second off the shared `now` clock.
  //
  // Dismiss (#60): during an active focus window the owner can drop back to the
  // glance board without waiting for the window to end. `ondismiss` fires from
  // either affordance -- the corner ✕ or a tap anywhere on the card (a full-bleed
  // button behind the display-only content). App owns the dismiss state and the
  // auto-return.
  let { trip, now, ondismiss } = $props();

  const rec = $derived(trip.recommended);
  const textColor = $derived(bulletTextColor(trip.color));
  const leaveIn = $derived(rec ? leaveInMinutes(rec.leave_by, now) : null);
  const target = $derived(clockTime(trip.target));
  // Prefer the #41 terminal label; fall back to the destination so the header is
  // never blank when a (line, direction) has no configured label.
  const heading = $derived(trip.terminal ?? trip.destination);
</script>

<section class="focus {trip.status}">
  <!-- Tap-anywhere dismiss: a full-bleed button behind the display-only content
       (which is pointer-events:none, see .content), so any tap on the card lands
       here. Hidden from AT and the tab order (mirrors Modal's backdrop) -- the
       corner ✕ (shared CloseButton) is the announced, keyboard-reachable close. -->
  <button
    class="dismiss-layer"
    aria-hidden="true"
    tabindex="-1"
    onclick={ondismiss}
  ></button>
  <CloseButton label="Back to the board" onclose={ondismiss} />

  <div class="content">
    <header class="head">
    <span
      class="bullet"
      style="background:{trip.color}; color:{textColor}"
      title={trip.direction}
    >
      {trip.line}
    </span>
    <div class="dest">
      <div class="terminal">→ {heading}</div>
      {#if trip.borough}
        <div class="borough">{trip.borough}</div>
      {/if}
    </div>
  </header>

  <div class="body">
    {#if trip.status === "on_time" || trip.status === "late"}
      <div class="verb">{trip.status === "on_time" ? "Catch" : "Best you can do"}</div>
      <div class="train tnum">{clockTime(rec.departure)} {trip.line}</div>
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
      <div class="verb warn">No catchable {trip.line}</div>
      <div class="sub">nothing you can still board for {target}</div>
    {:else if trip.status === "no_estimate"}
      <div class="verb warn">No travel estimate</div>
      <div class="sub">can’t recommend a train for {target}</div>
    {:else}
      <!-- no_target: focus window is active but the trip has no target today -->
      <div class="verb warn">No target scheduled today</div>
      <div class="sub">this trip has no arrival time for today</div>
    {/if}
  </div>

  {#if rec}
    <div class="leave">
      {#if leaveIn === 0}
        <span class="big">leave now</span>
      {:else}
        <span class="big tnum"><SplitFlap value={formatDuration(leaveIn)} /></span>
        <span class="lunit">{leaveIn < 60 ? "min to leave" : "to leave"}</span>
      {/if}
    </div>
    {/if}
  </div>
</section>

<style>
  /* Full-bleed, high-contrast focus card: the whole board area is one trip. A
     calm green edge when on time; the can't-make-it states go urgent red. Every
     status sets the edge, so green is the base and only the urgent ones override. */
  .focus {
    /* The card sits on --panel; match it so the flip tiles occlude cleanly. */
    --flap-bg: var(--panel);
    /* Bump the shared CloseButton up from its modal-panel default -- this card is
       full-screen, so the ✕ wants a bigger touch target. */
    --close-size: clamp(2.6rem, 6vh, 3.4rem);
    --close-font: clamp(1.1rem, 2.8vh, 1.5rem);
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: clamp(1rem, 4vh, 3rem);
    text-align: center;
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-radius: clamp(0.6rem, 1.4vw, 1.2rem);
    border-top: clamp(0.4rem, 1vh, 0.8rem) solid #35c759;
    padding: clamp(1rem, 4vh, 3rem);
  }
  .focus.late,
  .focus.no_service,
  .focus.no_estimate,
  .focus.no_target {
    border-top-color: var(--hurry);
  }

  /* Display-only content: neutralize its pointer events so every tap on the card
     reaches the dismiss layer. Not redundant with the dismiss layer -- the flip
     digits (SplitFlap tiles) are `position: relative`, so they'd otherwise paint
     above the layer and swallow taps that land on the countdown numbers.
     `display: contents` keeps head/body/leave as direct flex children of .focus,
     so the centered layout is unchanged; pointer-events:none inherits into them. */
  .content {
    display: contents;
  }
  .content > * {
    pointer-events: none;
  }

  /* Full-bleed tap target behind the content -- tap anywhere to dismiss; the
     shared CloseButton (z-index 2) still sits above it. */
  .dismiss-layer {
    position: absolute;
    inset: 0;
    z-index: 0;
    border: none;
    padding: 0;
    background: transparent;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .head {
    display: flex;
    align-items: center;
    gap: clamp(0.6rem, 2vw, 1.4rem);
  }
  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(3rem, 12vh, 6rem);
    height: clamp(3rem, 12vh, 6rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(1.8rem, 7vh, 3.6rem);
    line-height: 1;
  }
  .dest {
    text-align: left;
  }
  .terminal {
    font-size: clamp(1.6rem, 6vh, 3.6rem);
    font-weight: 800;
    line-height: 1.05;
    color: var(--text);
  }
  .borough {
    font-size: clamp(0.9rem, 2.4vh, 1.4rem);
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 0.3em;
  }
  .verb {
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 700;
    font-size: clamp(1rem, 3vh, 1.8rem);
  }
  .verb.warn {
    color: var(--hurry);
  }
  .train {
    color: var(--text);
    font-weight: 800;
    font-size: clamp(2.6rem, 11vh, 6rem);
    line-height: 1;
  }
  .sub {
    color: var(--text-dim);
    font-size: clamp(1rem, 3vh, 1.9rem);
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
    font-size: clamp(0.85rem, 2.2vh, 1.3rem);
  }

  .leave {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .big {
    font-size: clamp(3rem, 16vh, 9rem);
    font-weight: 800;
    line-height: 1;
    color: var(--text);
  }
  .lunit {
    font-size: clamp(0.8rem, 2.4vh, 1.4rem);
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }
</style>

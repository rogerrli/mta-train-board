<script>
  import { createBoard } from "./lib/board.js";
  import StatusBar from "./components/StatusBar.svelte";
  import Station from "./components/Station.svelte";
  import TrainDetail from "./components/TrainDetail.svelte";
  import StationDetail from "./components/StationDetail.svelte";
  import Recommendation from "./components/Recommendation.svelte";
  import FocusView from "./components/FocusView.svelte";
  import FocusReturn from "./components/FocusReturn.svelte";
  import { createBeeper } from "./lib/sound.js";
  import { createLeaveAlert } from "./lib/alert.js";

  const board = createBoard();
  // Focus-mode leave-by alert (issue #54): a two-note chime as a heads-up
  // `alert_lead_minutes` before you need to leave for the focused trip's #27
  // recommendation. `beeper` owns the Web Audio sound + kiosk unlock; `leaveAlert`
  // owns the "once per departure" arming. Both are plain objects, created once.
  const beeper = createBeeper();
  const leaveAlert = createLeaveAlert();

  // Wall-clock tick: drives the per-second countdown recompute across the board.
  let now = $state(Date.now());

  // Whether audio is unlocked and can play without a user gesture. False until a
  // tap on "Enable sound" resumes the context -- unless the Chromium kiosk flag
  // (--autoplay-policy=no-user-gesture-required) started it running already, which
  // the mount below detects so no tap is needed on the wall board.
  let audioReady = $state(false);

  $effect(() => {
    board.start();
    const id = setInterval(() => (now = Date.now()), 1000);
    // Detect the kiosk-flag case: creating the context reveals whether it starts
    // "running" (flag set) or "suspended" (needs the tap). Harmless either way.
    beeper.unlock();
    audioReady = beeper.ready();
    return () => {
      board.stop();
      clearInterval(id);
    };
  });

  const stations = $derived($board.payload?.stations ?? []);

  // Service alerts (issue #13), matched to the watched lines server-side and
  // sorted current-first. Each carries the affected `lines`, so a station's line
  // group badges itself (LineGroup) and the tap-through detail overlays show the
  // text. Line-level matching (owner's call): an alert on a watched line badges
  // every group on that line, whichever station shows it.
  const alerts = $derived($board.payload?.alerts ?? []);

  // Tapped-train detail overlay (issue #9). We remember the selection by station
  // name + group index, not the group object, then re-derive the live group from
  // the latest payload each render -- so the overlay ticks and refreshes on every
  // poll, and closes on its own if a config change drops that group.
  let selected = $state(null); // { station, index } | null

  const selectedGroup = $derived.by(() => {
    if (!selected) return null;
    const s = stations.find((st) => st.name === selected.station);
    return s?.arrivals[selected.index] ?? null;
  });

  // Tapped-station consolidated view (issue #10). Same pattern as the train
  // overlay: remember the station by name and re-derive the live station object
  // each render, so its arrival lists tick and refresh on every poll and it
  // closes on its own if a config change drops the station. The two overlays are
  // separate tap targets (name vs. group row) and mutually exclusive -- opening
  // one clears the other.
  let selectedStation = $state(null); // station name | null

  const selectedStationObj = $derived(
    selectedStation ? (stations.find((st) => st.name === selectedStation) ?? null) : null,
  );

  // Arrive-by recommendations (issue #27). The server marks each trip `visible`
  // (issue #50): false on a no-target day (e.g. a weekend) and outside the trip's
  // configured lead-in window, so the strip only takes board space when a train
  // is actually in play -- then the station grid reclaims the rest. Note the
  // banner is *also* gated on an active focus window below (issue #55): outside
  // every focus window the board is plain glance-only, no arrive-by strip.
  const trips = $derived(
    ($board.payload?.trips ?? []).filter((t) => t.visible),
  );

  // Scheduled focus mode (issue #39). When a focus rule is active the server sets
  // `focus` = { trip }, naming which trip to dedicate the whole board to (its
  // recommendation, terminal label and all, is in trips[]); we render only that
  // trip and hide every other station and trip. Look the trip up in the unfiltered
  // trips[] (a focus rule can fire on a no-target misconfig, and we still show that
  // state rather than silently reverting). If the named trip is somehow absent,
  // fall through to the normal board.
  const focus = $derived($board.payload?.focus ?? null);
  const focusTrip = $derived.by(() => {
    if (!focus) return null;
    return ($board.payload?.trips ?? []).find((t) => t.name === focus.trip) ?? null;
  });

  // Dismiss the focus view mid-window (issue #60). The server keeps sending the
  // focus directive for the whole window; the frontend decides whether to honor
  // it. `dismissed` drops us back to the glance board without waiting for the
  // window to end and survives polls/ticks (plain in-memory state, per-session --
  // a reload starts fresh, fine for a wall device that rarely reloads). A new
  // window re-arms focus automatically: when `focus` transitions from absent to
  // present we clear the flag. While dismissed, a return affordance (FocusReturn)
  // sits on the glance board and auto-returns after an idle timeout.
  let dismissed = $state(false);
  let focusWasActive = false;
  $effect(() => {
    const active = focus != null;
    if (active && !focusWasActive) dismissed = false; // off -> on: new window re-arms
    focusWasActive = active;
  });

  // The takeover shows only when a focus trip resolves and we haven't dismissed it.
  const showFocus = $derived(!!focusTrip && !dismissed);

  // Audible leave-by alert (issue #54). Server-configured lead time (default 10);
  // the board beeps once when the focused trip's on-time recommendation is first
  // within this many minutes of its leave-by. `leaveAlert` de-dupes per departure
  // and re-arms when a new train is recommended. We gate on `audioReady` before
  // asking so a muted board doesn't consume a departure's one alert -- if you tap
  // "Enable sound" while still inside the window, the next tick can still fire.
  // Keyed on `focusTrip` (the focus window being active), not `showFocus`: a #60
  // dismiss hides the takeover but you still want the across-the-room heads-up.
  const leadMinutes = $derived($board.payload?.alert_lead_minutes ?? 10);

  $effect(() => {
    if (!audioReady) return;
    if (leaveAlert.shouldFire(focusTrip, leadMinutes, now)) {
      beeper.beep();
    }
  });

  // One-time "Enable sound" tap: satisfies the browser autoplay gesture rule and
  // confirms with a chime so you know the board can now be heard. This runs inside
  // the click gesture, so we trust unlock()'s success rather than the context's
  // state flag (resume() resolves async -- ready() can still read "suspended" for a
  // tick right after the tap, which would wrongly leave the button up).
  function enableSound() {
    if (beeper.unlock()) {
      audioReady = true;
      beeper.beep();
    }
  }
</script>

<div class="board">
  {#if $board.status === "loading"}
    <div class="center">
      <div class="spinner" aria-hidden="true"></div>
      <p>Loading board…</p>
    </div>
  {:else if $board.status === "waiting"}
    <div class="center">
      <div class="spinner" aria-hidden="true"></div>
      <p>Waiting for the first arrivals…</p>
      <p class="hint">The feed poller hasn’t reported yet. Retrying.</p>
    </div>
  {:else}
    <StatusBar payload={$board.payload} offline={$board.offline} {now} />
    {#if showFocus}
      <FocusView trip={focusTrip} {now} ondismiss={() => (dismissed = true)} />
    {:else}
      <!-- Arrive-by strip only while a focus window is active (issue #55). The
           `focus` directive is non-null exactly when a focus rule is firing; a
           window the user dismissed back to the glance board (#60) still counts
           as active, so the banner rides along there. Outside every window the
           board is plain glance-only -- no stale "late for 9:30 AM" strip. -->
      {#if focus != null && trips.length > 0}
        <div class="recommendations">
          {#each trips as trip (trip.name)}
            <Recommendation {trip} {now} />
          {/each}
        </div>
      {/if}
      {#if stations.length === 0}
        <div class="center">
          <p>No stations configured.</p>
          <p class="hint">Add <code>[[stations]]</code> blocks to your config.</p>
        </div>
      {:else}
        <div class="stations" style="--cols: {Math.min(stations.length, 2)}">
          {#each stations as station (station.name)}
            <Station
              {station}
              {now}
              {alerts}
              onselect={(name, index) => {
                selectedStation = null;
                selected = { station: name, index };
              }}
              onstationselect={(name) => {
                selected = null;
                selectedStation = name;
              }}
            />
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>

<!-- Focus window active but dismissed: offer a way back in, and auto-return when
     the idle countdown empties (#60). -->
{#if focusTrip && dismissed}
  <FocusReturn onreturn={() => (dismissed = false)} />
{/if}

{#if selectedGroup && !showFocus}
  <TrainDetail
    group={selectedGroup}
    station={selected.station}
    {now}
    {alerts}
    onclose={() => (selected = null)}
  />
{/if}

{#if selectedStationObj && !showFocus}
  <StationDetail
    station={selectedStationObj}
    {now}
    {alerts}
    onclose={() => (selectedStation = null)}
  />
{/if}

<!-- One-time audio unlock (issue #54). Shown with the focus takeover while audio
     is still blocked -- the natural moment to grant the gesture so the leave-by
     chime can play. (The alert itself keys on the focus window, not the takeover,
     so a #60 dismiss doesn't silence an already-enabled board.) A Chromium kiosk
     launched with --autoplay-policy=no-user-gesture-required never sees this. -->
{#if showFocus && !audioReady}
  <button class="enable-sound" onclick={enableSound}>🔊 Enable sound</button>
{/if}

<style>
  .board {
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: var(--gap);
    gap: var(--gap);
  }

  /* Uniform grid of equal cells (issue #50, reverting the #40 proportional
     flex-wrap that made uneven cards and clipped countdowns). `--cols` is the
     station count capped at 2, so the typical ~4 stations sit in a compact 2x2.
     `align-content: center` sizes the rows to their content -- cards stay only
     as tall as they need instead of stretching to fill, so the countdowns get
     their horizontal room back (the #50 goal) -- while splitting the leftover
     vertical space top/bottom instead of pooling it below the cards (issue #71,
     the dead gap left once #55 hid the arrive-by banner outside focus windows).
     `safe` falls back to top-alignment if the rows ever overflow the height (many
     stations on a short viewport), so a centered block can't clip the top row
     off the kiosk's overflow:hidden and hide the first station. */
  .stations {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: repeat(var(--cols), 1fr);
    align-content: safe center;
    gap: var(--gap);
  }

  .recommendations {
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    flex: none;
  }

  .center {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.6rem;
    color: var(--text-dim);
    font-size: clamp(1.2rem, 3vw, 2rem);
  }

  .hint {
    font-size: 0.6em;
    color: var(--text-faint);
  }

  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--text-dim);
  }

  /* Unobtrusive audio-unlock pill, bottom-center over the focus board (#54). */
  .enable-sound {
    position: fixed;
    bottom: calc(var(--gap) * 1.5);
    left: 50%;
    transform: translateX(-50%);
    padding: 0.6rem 1.2rem;
    font: inherit;
    font-weight: 600;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-radius: 2rem;
    cursor: pointer;
    opacity: 0.85;
  }
  .enable-sound:hover {
    opacity: 1;
  }

  .spinner {
    width: 2.4rem;
    height: 2.4rem;
    border: 0.28rem solid var(--panel-edge);
    border-top-color: var(--text);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>

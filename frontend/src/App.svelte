<script>
  import { createBoard } from "./lib/board.js";
  import StatusBar from "./components/StatusBar.svelte";
  import Station from "./components/Station.svelte";
  import TrainDetail from "./components/TrainDetail.svelte";
  import StationDetail from "./components/StationDetail.svelte";
  import Recommendation from "./components/Recommendation.svelte";
  import FocusView from "./components/FocusView.svelte";
  import FocusReturn from "./components/FocusReturn.svelte";

  const board = createBoard();

  // Wall-clock tick: drives the per-second countdown recompute across the board.
  let now = $state(Date.now());

  $effect(() => {
    board.start();
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => {
      board.stop();
      clearInterval(id);
    };
  });

  const stations = $derived($board.payload?.stations ?? []);

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

  // Arrive-by recommendations (issue #27). A trip with no target today (e.g. a
  // weekend) reports status "no_target" -- drop those so the strip only shows
  // trips that are actually in play right now.
  const trips = $derived(
    ($board.payload?.trips ?? []).filter((t) => t.status !== "no_target"),
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
      {#if trips.length > 0}
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
        <div class="stations">
          {#each stations as station (station.name)}
            <Station
              {station}
              {now}
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
    onclose={() => (selected = null)}
  />
{/if}

{#if selectedStationObj && !showFocus}
  <StationDetail
    station={selectedStationObj}
    {now}
    onclose={() => (selectedStation = null)}
  />
{/if}

<style>
  .board {
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: var(--gap);
    gap: var(--gap);
  }

  /* Content-proportional cards: a flex row that wraps, where each station grows
     by its own weight (set on .station in Station.svelte from its group/arrival
     counts). Denser stations claim more width; the shared flex-basis + wrap keep
     it responsive as the station count changes. */
  .stations {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-wrap: wrap;
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

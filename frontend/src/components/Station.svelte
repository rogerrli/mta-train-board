<script>
  import LineGroup from "./LineGroup.svelte";

  // One station card: its name plus each watched line/direction group (the API
  // nests groups under `arrivals`, config order preserved). `onselect(name, i)`
  // bubbles a tapped group up to the board so it can open the single-train detail
  // overlay (issue #9); the index disambiguates a line/direction that repeats
  // across config blocks (see the key note below). `onstationselect(name)` fires
  // when the station name is tapped, opening the consolidated station view
  // (issue #10) -- a separate target from the group rows so both coexist.
  // `alerts` are the board's service alerts (#13), passed to each group so it can
  // badge itself when one names its line (LineGroup filters by line).
  let { station, now, onselect, onstationselect, alerts = [] } = $props();

  // Weight for content-proportional sizing (issue #40): each group contributes
  // its row plus its trains, so a station we watch more heavily claims more of
  // the board. Off the raw payload counts (not the per-second `liveArrivals`),
  // so the weight only shifts on a poll, not every tick — no countdown jitter.
  const weight = $derived(
    Math.max(
      1,
      station.arrivals.reduce((n, g) => n + 1 + g.arrivals.length, 0),
    ),
  );
</script>

<section class="station" style="flex-grow: {weight}">
  <h2 class="name">
    <button type="button" class="name-btn tap-reset" onclick={() => onstationselect(station.name)}>
      {station.name}
    </button>
  </h2>
  <div class="groups">
    <!-- Index in the key: line+direction alone can repeat if a station is listed
         in two config blocks with an overlapping direction, and a duplicate key
         is a hard render error. Group order is config-stable, so the index is. -->
    {#each station.arrivals as group, i (group.line + group.direction + i)}
      <LineGroup
        {group}
        {now}
        {alerts}
        onselect={() => onselect(station.name, i)}
      />
    {/each}
  </div>
</section>

<style>
  .station {
    /* flex-grow is set inline from the station's content weight (issue #40); a
       shared basis + a floor width let dense stations widen without starving
       sparse ones, and wrap instead of shrinking to slivers on a narrow board. */
    flex-grow: 1;
    flex-shrink: 1;
    flex-basis: 20rem;
    min-width: min(100%, 18rem);
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-radius: clamp(0.4rem, 1vw, 0.9rem);
    padding: clamp(0.4rem, 1.4vh, 1rem) clamp(0.5rem, 1.4vw, 1.1rem);
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .name {
    margin: 0 0 clamp(0.2rem, 1vh, 0.6rem);
    font-size: clamp(1.1rem, 3.4vh, 2.1rem);
    font-weight: 800;
    line-height: 1.05;
    letter-spacing: -0.01em;
  }

  /* The name is a button (tap -> consolidated station view, issue #10) but must
     read as the plain card heading. Chrome reset + tap/hover/focus feedback come
     from the shared .tap-reset (app.css); this only sets its box + type. */
  .name-btn {
    display: block;
    width: 100%;
    padding: clamp(0.1rem, 0.5vh, 0.3rem) clamp(0.15rem, 0.5vw, 0.4rem);
    border-radius: clamp(0.3rem, 0.8vw, 0.6rem);
    letter-spacing: inherit;
  }

  .groups {
    display: flex;
    flex-direction: column;
    gap: clamp(0.25rem, 1vh, 0.7rem);
    min-height: 0;
    overflow: hidden;
  }
</style>

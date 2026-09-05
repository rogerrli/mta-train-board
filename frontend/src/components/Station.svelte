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
</script>

<section class="station">
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
    /* A plain grid cell (issue #50): its width comes from the 2-column track in
       App.svelte, its height from its own content. min-width:0 lets the cell
       shrink to its track instead of being forced wide by a long line row. */
    min-width: 0;
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
    /* Aligned countdown columns (issue #67): the card owns the column grid so
       every line row drops its bullet, direction, and each countdown into the
       same tracks. col 1 = route bullet (content-sized), col 2 = the direction
       label (a preferred width that yields to 0 so the times never clip --
       issue #50), cols 3-6 = the GLANCE_LIMIT countdowns. Each .group is a
       subgrid spanning all six columns, so the tracks are shared down the whole
       card and the times line up into scannable columns. The `repeat(4, ...)`
       tracks the GLANCE_LIMIT (format.js) -- keep them in step. */
    display: grid;
    grid-template-columns: auto minmax(0, clamp(4.5rem, 12vw, 8rem)) repeat(4, auto);
    row-gap: clamp(0.2rem, 0.7vh, 0.5rem);
    /* A fixed, modest column gap: enough that the countdowns read as separate,
       the same down every card -- not scaled per card or per viewport. */
    column-gap: 0.7rem;
    min-height: 0;
    overflow: hidden;
  }
</style>

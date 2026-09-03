<script>
  import { liveArrivals, bulletTextColor } from "../lib/format.js";
  import Modal from "./Modal.svelte";
  import ArrivalList from "./ArrivalList.svelte";

  // Tap-a-train detail overlay (issue #9): a fuller breakdown for one
  // station x line x direction than the glance board shows. `group` is the live
  // group object from the latest payload, so the list ticks down and refreshes
  // on every poll just like the board; `station` is its station name (the group
  // itself doesn't carry it -- the API nests groups under the station). The Modal
  // shell owns dismiss (✕ / backdrop / Escape).
  let { group, station, now, onclose } = $props();

  const arrivals = $derived(liveArrivals(group, now));
  const textColor = $derived(bulletTextColor(group.color));
  // Terminal-station label (#41) as the primary destination text, matching the
  // board; falls back to the compass word ("Northbound") when unconfigured.
  const primary = $derived(group.terminal ?? group.direction_label);
</script>

<Modal label="{group.line} to {primary} at {station}" {onclose}>
  <header class="head">
    <span class="bullet" style="background:{group.color}; color:{textColor}">
      {group.line}
    </span>
    <div class="titles">
      <h2 class="dir">{primary}</h2>
      {#if group.borough}<p class="borough">{group.borough}</p>{/if}
      <p class="station">at {station}</p>
    </div>
  </header>

  <div class="body">
    <ArrivalList {arrivals} fallbackDest={primary} />
  </div>
</Modal>

<style>
  .head {
    display: flex;
    align-items: center;
    gap: clamp(0.6rem, 1.6vw, 1rem);
    margin-bottom: clamp(0.6rem, 1.6vh, 1rem);
    /* Room for the Modal's pinned ✕ in the panel's top-right corner. */
    padding-right: clamp(2.6rem, 7vh, 3.6rem);
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

  /* The row list itself lives in ArrivalList.svelte (shared with the station
     view, issue #10); this wrapper just makes a long list scroll inside the
     fixed-height panel. */
  .body {
    overflow-y: auto;
  }
</style>

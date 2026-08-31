<script>
  import LineGroup from "./LineGroup.svelte";

  // One station card: its name plus each watched line/direction group (the API
  // nests groups under `arrivals`, config order preserved).
  let { station, now } = $props();
</script>

<section class="station">
  <h2 class="name">{station.name}</h2>
  <div class="groups">
    <!-- Index in the key: line+direction alone can repeat if a station is listed
         in two config blocks with an overlapping direction, and a duplicate key
         is a hard render error. Group order is config-stable, so the index is. -->
    {#each station.arrivals as group, i (group.line + group.direction + i)}
      <LineGroup {group} {now} />
    {/each}
  </div>
</section>

<style>
  .station {
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

  .groups {
    display: flex;
    flex-direction: column;
    gap: clamp(0.25rem, 1vh, 0.7rem);
    min-height: 0;
    overflow: hidden;
  }
</style>

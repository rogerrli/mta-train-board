<script>
  import Flap from "./Flap.svelte";

  // Split-flap countdown (issue #53): render a short string — a countdown like
  // "10", or the "Due" label — as a row of Solari flip tiles. Each character is
  // its own <Flap>, so a per-second tick from "10" to "9" flips only the ones
  // place; a static number doesn't animate at all. Inherits font-size and color
  // from the parent, so it drops into the board countdowns (LineGroup), the
  // arrive-by "leave in" number (#27) and focus mode (#39) unchanged.
  let { value } = $props();

  // Key each tile by its distance from the right (0 = ones place) so the ones
  // digit keeps its identity as a number grows or shrinks; the extra tens tile
  // is mounted/removed on the left rather than shoving the row (no layout jump
  // between 1- and 2-digit values).
  const tiles = $derived.by(() => {
    const s = String(value);
    return s.split("").map((ch, i) => ({ key: s.length - 1 - i, ch }));
  });
</script>

<span class="flaps">
  {#each tiles as t (t.key)}
    <Flap char={t.ch} />
  {/each}
  <!-- The tiles are aria-hidden; give assistive tech the plain value. -->
  <span class="sr">{value}</span>
</span>

<style>
  .flaps {
    display: inline-flex;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>

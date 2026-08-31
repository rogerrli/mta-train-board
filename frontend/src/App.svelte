<script>
  import { createBoard } from "./lib/board.js";
  import StatusBar from "./components/StatusBar.svelte";
  import Station from "./components/Station.svelte";

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
    {#if stations.length === 0}
      <div class="center">
        <p>No stations configured.</p>
        <p class="hint">Add <code>[[stations]]</code> blocks to your config.</p>
      </div>
    {:else}
      <div class="stations" style="--cols: {Math.min(stations.length, 2)}">
        {#each stations as station (station.name)}
          <Station {station} {now} />
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .board {
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: var(--gap);
    gap: var(--gap);
  }

  .stations {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: repeat(var(--cols), 1fr);
    gap: var(--gap);
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

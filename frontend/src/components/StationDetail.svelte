<script>
  import {
    liveArrivals,
    bulletTextColor,
    stationWalkMinutes,
  } from "../lib/format.js";
  import Modal from "./Modal.svelte";
  import ArrivalList from "./ArrivalList.svelte";
  import AlertList from "./AlertList.svelte";

  // Tap-a-station consolidated view (issue #10): everything happening at one
  // stop, in one place. Every watched line/direction group at the station, each
  // with its full upcoming-arrivals breakdown (the same rows as the single-train
  // detail, #9, via ArrivalList) and catchable/hurry/missed tags. `station` is
  // the live station object from the latest payload, so the lists tick down and
  // refresh on every poll just like the board. The Modal shell owns dismiss.
  // `alerts` are the board's service alerts (#13); we show any on this station's
  // lines above the groups.
  let { station, now, alerts = [], onclose } = $props();

  // Per-group primary label + live arrivals, recomputed each tick. Terminal-station
  // label (#41) as the destination text, falling back to the compass word.
  const groups = $derived(
    station.arrivals.map((g) => ({
      group: g,
      primary: g.terminal ?? g.direction_label,
      textColor: bulletTextColor(g.color),
      arrivals: liveArrivals(g, now),
    })),
  );

  // One station-level walk time when the groups agree (the common case); null
  // otherwise, so the header simply omits it.
  const walk = $derived(stationWalkMinutes(station));

  // Service alerts (#13) touching any line this station watches, current-first
  // (the API already sorts them). Shown above the groups so a disruption reads
  // before the countdowns.
  const stationLines = $derived(new Set(station.arrivals.map((g) => g.line)));
  const stationAlerts = $derived(
    alerts.filter((a) => a.lines.some((line) => stationLines.has(line))),
  );
</script>

<Modal label="All trains at {station.name}" {onclose}>
  <header class="head">
    <h2 class="name">{station.name}</h2>
    {#if walk != null}
      <p class="walk">{walk} min walk</p>
    {/if}
  </header>

  <div class="body">
    <AlertList alerts={stationAlerts} />
    {#each groups as g, i (g.group.line + g.group.direction + i)}
      <section class="group">
        <div class="group-head">
          <span
            class="bullet"
            style="background:{g.group.color}; color:{g.textColor}"
          >
            {g.group.line}
          </span>
          <div class="dir">
            <span class="terminal">{g.primary}</span>
            {#if g.group.borough}<span class="borough">{g.group.borough}</span
              >{/if}
          </div>
        </div>
        <ArrivalList arrivals={g.arrivals} fallbackDest={g.primary} />
      </section>
    {/each}
  </div>
</Modal>

<style>
  .head {
    /* Room for the Modal's pinned ✕ so a long station name never runs under it. */
    margin-bottom: clamp(0.4rem, 1.4vh, 0.9rem);
    padding-right: clamp(2.6rem, 7vh, 3.6rem);
  }

  .name {
    margin: 0;
    font-size: clamp(1.4rem, 4vh, 2.4rem);
    font-weight: 800;
    line-height: 1.05;
    letter-spacing: -0.01em;
  }

  .walk {
    margin: 0.15em 0 0;
    color: var(--text-dim);
    font-size: clamp(0.8rem, 2vh, 1.15rem);
    font-weight: 600;
  }

  /* The groups scroll as one column inside the fixed-height panel -- a busy
     station can watch several lines, each with a full arrival list. */
  .body {
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: clamp(0.6rem, 1.8vh, 1.2rem);
  }

  .group {
    display: flex;
    flex-direction: column;
  }
  /* Divider between line/direction sections; the first needs none. */
  .group + .group {
    border-top: 1px solid var(--panel-edge);
    padding-top: clamp(0.6rem, 1.8vh, 1.2rem);
  }

  .group-head {
    display: flex;
    align-items: center;
    gap: clamp(0.5rem, 1.4vw, 0.9rem);
    margin-bottom: clamp(0.1rem, 0.6vh, 0.3rem);
  }

  .bullet {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: clamp(2.2rem, 5.4vh, 3.1rem);
    height: clamp(2.2rem, 5.4vh, 3.1rem);
    border-radius: 50%;
    font-weight: 800;
    font-size: clamp(1.2rem, 3vh, 1.8rem);
    line-height: 1;
  }

  .dir {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.1em;
  }
  .terminal {
    font-size: clamp(1rem, 2.6vh, 1.5rem);
    font-weight: 800;
    line-height: 1.1;
  }
  .borough {
    color: var(--text-faint);
    font-size: clamp(0.65rem, 1.5vh, 0.9rem);
    font-weight: 600;
  }
</style>

<script>
  import { alertTiming } from "../lib/format.js";

  // Service alerts (issue #13) for one line/station, shown in a detail overlay
  // (the single-train view #9 or the consolidated station view #10). The board
  // itself only badges an affected line; the text lives here, on tap. `alerts`
  // arrive current-first from the API; each is a live disruption (`active`) or an
  // upcoming/planned change. Renders nothing when there are none.
  let { alerts = [] } = $props();
</script>

{#if alerts.length > 0}
  <ul class="alerts" aria-label="Service alerts">
    {#each alerts as a (a.id)}
      {@const timing = alertTiming(a)}
      <li class="alert" class:active={a.active}>
        <div class="row">
          <span class="chip">{a.active ? "Now" : "Planned"}</span>
          <span class="type">{a.alert_type}</span>
        </div>
        {#if a.header}<p class="header">{a.header}</p>{/if}
        {#if a.description && a.description !== a.header}
          <p class="desc">{a.description}</p>
        {/if}
        {#if timing}<p class="timing">{timing}</p>{/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .alerts {
    list-style: none;
    margin: 0 0 clamp(0.6rem, 1.8vh, 1.2rem);
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: clamp(0.4rem, 1.2vh, 0.7rem);
  }

  .alert {
    border: 1px solid var(--panel-edge);
    /* A live disruption gets an amber left rule so it reads first; an upcoming
       planned change stays quiet. */
    border-left: 4px solid var(--text-faint);
    border-radius: clamp(0.3rem, 0.8vw, 0.5rem);
    padding: clamp(0.4rem, 1.2vh, 0.7rem) clamp(0.5rem, 1.2vw, 0.8rem);
    background: var(--bg);
  }
  .alert.active {
    border-left-color: var(--alert);
  }

  .row {
    display: flex;
    align-items: center;
    gap: clamp(0.4rem, 1vw, 0.6rem);
    margin-bottom: 0.25em;
  }

  .chip {
    flex: none;
    font-size: clamp(0.6rem, 1.4vh, 0.8rem);
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0.15em 0.5em;
    border-radius: 999px;
    background: var(--panel-edge);
    color: var(--text-dim);
  }
  .alert.active .chip {
    background: var(--alert);
    color: #000;
  }

  .type {
    font-size: clamp(0.7rem, 1.6vh, 0.95rem);
    font-weight: 700;
    color: var(--text-dim);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header {
    margin: 0;
    font-size: clamp(0.9rem, 2.2vh, 1.25rem);
    font-weight: 700;
    line-height: 1.25;
  }

  .desc {
    margin: 0.25em 0 0;
    font-size: clamp(0.75rem, 1.8vh, 1.05rem);
    line-height: 1.3;
    color: var(--text-dim);
  }

  .timing {
    margin: 0.3em 0 0;
    font-size: clamp(0.7rem, 1.6vh, 0.95rem);
    font-weight: 600;
    color: var(--text-faint);
  }
</style>

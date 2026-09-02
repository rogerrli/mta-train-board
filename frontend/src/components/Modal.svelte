<script>
  // Shared full-screen modal shell for the tap-to-drill overlays: the
  // single-train detail (issue #9) and the consolidated station view (#10).
  // Owns the dismiss affordances so every overlay behaves identically on the
  // touchscreen -- the ✕ button, a tap on the backdrop outside the panel, or
  // Escape -- plus moving focus into the dialog on open. Each caller renders its
  // own header + body inside via `children`.
  let { label, onclose, children } = $props();

  function onKeydown(e) {
    if (e.key === "Escape") onclose();
  }

  // Move focus into the dialog on open (it declares aria-modal) so a keyboard
  // user starts inside it; the ✕ is the natural landing spot.
  let closeButton = $state();
  $effect(() => closeButton?.focus());
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay" role="dialog" aria-modal="true" aria-label={label}>
  <!-- A real button behind the panel captures "tap outside to dismiss" without
       an a11y-questionable click handler on a plain div. Hidden from AT and the
       tab order -- the ✕ is the announced, keyboard-reachable close. -->
  <button class="backdrop" aria-hidden="true" tabindex="-1" onclick={onclose}
  ></button>

  <div class="panel">
    <button
      class="close"
      aria-label="Close"
      bind:this={closeButton}
      onclick={onclose}>✕</button
    >
    {@render children()}
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--gap);
  }

  .backdrop {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    background: rgba(0, 0, 0, 0.66);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }

  .panel {
    position: relative;
    z-index: 1;
    width: min(48rem, 93vw);
    max-height: 92vh;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--panel-edge);
    border-radius: clamp(0.6rem, 1.4vw, 1.1rem);
    padding: clamp(0.8rem, 2.2vh, 1.4rem);
    box-shadow: 0 1.5rem 3rem rgba(0, 0, 0, 0.5);
  }

  /* Pinned to the panel's top-right corner so the shell owns the close control
     regardless of what header the caller renders; callers leave room for it. */
  .close {
    position: absolute;
    top: clamp(0.8rem, 2.2vh, 1.4rem);
    right: clamp(0.8rem, 2.2vh, 1.4rem);
    z-index: 2;
    flex: none;
    width: clamp(2.2rem, 5.4vh, 3rem);
    height: clamp(2.2rem, 5.4vh, 3rem);
    border: 1px solid var(--panel-edge);
    border-radius: 50%;
    background: var(--panel);
    color: var(--text-dim);
    font-size: clamp(1rem, 2.6vh, 1.4rem);
    line-height: 1;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .close:active {
    background: var(--panel-edge);
  }
</style>

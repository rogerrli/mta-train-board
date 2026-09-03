<script>
  import CloseButton from "./CloseButton.svelte";

  // Shared full-screen modal shell for the tap-to-drill overlays: the
  // single-train detail (issue #9) and the consolidated station view (#10).
  // Owns the dismiss affordances so every overlay behaves identically on the
  // touchscreen -- the ✕ button (shared CloseButton, autofocused so a keyboard
  // user lands inside the dialog), a tap on the backdrop outside the panel, or
  // Escape. Each caller renders its own header + body inside via `children`.
  let { label, onclose, children } = $props();

  function onKeydown(e) {
    if (e.key === "Escape") onclose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay" role="dialog" aria-modal="true" aria-label={label}>
  <!-- A real button behind the panel captures "tap outside to dismiss" without
       an a11y-questionable click handler on a plain div. Hidden from AT and the
       tab order -- the ✕ is the announced, keyboard-reachable close. -->
  <button class="backdrop" aria-hidden="true" tabindex="-1" onclick={onclose}
  ></button>

  <div class="panel">
    <CloseButton label="Close" autofocus {onclose} />
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
  /* The pinned ✕ (top-right) is the shared CloseButton; callers leave room for
     it in their own header. */
</style>

<script>
  // Shared circular ✕ close control for the board's overlays -- the tap-to-drill
  // Modal shell (#9/#10) and the focus-view dismiss (#60). Owns the pinned
  // top-right chrome and the touch / hover / focus states so every overlay
  // dismisses identically on the wall touchscreen. Callers place it inside a
  // positioned ancestor and vary only the `label`; size is themeable via the
  // --close-size / --close-font custom properties (defaults suit a modal panel;
  // the full-screen focus view bumps them up).
  //
  // `autofocus` moves focus here on mount -- the Modal declares aria-modal, so a
  // keyboard user should land on the close control.
  let { label, autofocus = false, onclose } = $props();

  let el = $state();
  $effect(() => {
    if (autofocus) el?.focus();
  });
</script>

<button class="close" aria-label={label} bind:this={el} onclick={onclose}>✕</button>

<style>
  .close {
    position: absolute;
    top: clamp(0.8rem, 2.2vh, 1.4rem);
    right: clamp(0.8rem, 2.2vh, 1.4rem);
    z-index: 2;
    flex: none;
    width: var(--close-size, clamp(2.2rem, 5.4vh, 3rem));
    height: var(--close-size, clamp(2.2rem, 5.4vh, 3rem));
    border: 1px solid var(--panel-edge);
    border-radius: 50%;
    background: var(--panel);
    color: var(--text-dim);
    font-size: var(--close-font, clamp(1rem, 2.6vh, 1.4rem));
    line-height: 1;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .close:active {
    background: var(--panel-edge);
  }
  .close:focus-visible {
    outline: 2px solid var(--text-dim);
    outline-offset: 2px;
  }
  @media (hover: hover) {
    .close:hover {
      background: var(--panel-edge);
    }
  }
</style>

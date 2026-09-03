<script>
  import { untrack } from "svelte";

  // One split-flap character tile (issue #53) — the classic Solari fold. The tile
  // shows `char`; when `char` changes, the old glyph's top half falls forward and
  // the new glyph's bottom half drops into place. Purely visual: transforms +
  // opacity only, so it stays cheap on the wall panel (Raspberry Pi). Under
  // `prefers-reduced-motion` the fold layer is hidden and the swap is instant
  // (see CSS).
  //
  // Inherits font-size and color from the parent, so the same tile serves the
  // board countdowns and the big focus/arrive-by numbers unchanged. The parent
  // sets --flap-bg to the surrounding background so the folding leaves occlude
  // the layer beneath instead of ghosting through it.
  let { char } = $props();

  // Seed both from the first glyph; later changes flow through the effect below.
  // svelte-ignore state_referenced_locally
  let current = $state(char); // the settled glyph (also the new one mid-fold)
  // svelte-ignore state_referenced_locally
  let previous = $state(char); // the glyph we're folding away from
  // A fold counter. Its *parity* selects the keyframe (see .p1 in CSS), so a real
  // change restarts the fold with a class swap — no {#key} DOM rebuild each tick,
  // which matters on a board where every countdown ticks every second.
  let seq = $state(0);
  // Last change crossed digit<->letter: swap instantly instead of folding.
  let instant = $state(false);

  const digit = (c) => /^[0-9]$/.test(c);

  // React to the incoming glyph without depending on our own writes (untrack),
  // so setting current/previous here doesn't re-run the effect.
  $effect(() => {
    const next = char;
    untrack(() => {
      if (next === current) return;
      // Fold only within a type (digit->digit, letter->letter). A digit<->letter
      // step (e.g. "Due" -> "12", or "59" -> "1h") would fold a letter into a
      // digit and flash a mixed glyph, so swap those instantly instead.
      const sameType = digit(current) === digit(next);
      previous = current;
      current = next;
      instant = !sameType;
      if (sameType) seq += 1;
    });
  });

  // Digits get a fixed one-character width (tabular, no jump as values change); a
  // blank tile (from "1h 15m") holds a slim inter-word gap; other glyphs (the
  // "Due" letters) size to their content.
  const isDigit = $derived(digit(current));
  const isSpace = $derived(current === " ");
</script>

<span class="tile" class:digit={isDigit} class:space={isSpace} aria-hidden="true">
  <!-- Static halves: the resting glyph (the new value). Revealed as the fold
       plays; shown on their own once it settles, under reduced motion, or on an
       instant (type-crossing) swap. -->
  <span class="half top"><span class="glyph">{current}</span></span>
  <span class="half bottom"><span class="glyph">{current}</span></span>

  <!-- Fold layer over the static halves. .go arms it once a real fold has
       happened; the seq-parity class (.p1) swaps the keyframe so the next fold
       restarts without rebuilding the DOM. .instant hides it for a type-crossing
       change, leaving the static halves to swap instantly. -->
  <span class="anim" class:go={seq > 0} class:p1={seq % 2 === 1} class:instant>
    <span class="leaf top"><span class="glyph">{previous}</span></span>
    <span class="cover bottom"><span class="glyph">{previous}</span></span>
    <span class="leaf bottom"><span class="glyph">{current}</span></span>
  </span>
</span>

<style>
  .tile {
    position: relative;
    display: inline-block;
    height: 1em;
    min-width: 1ch;
    line-height: 1;
    perspective: 14em;
    /* Keep the leaves' z-order (and the 3D context) contained to this tile, so a
       parent can paint over the whole number — e.g. the MISSED strike in
       LineGroup — without fighting each leaf. */
    isolation: isolate;
  }
  .tile.digit {
    width: 1ch;
  }
  .tile.space {
    /* A blank tile only reserves inter-word space; a full 1ch reads too wide. */
    width: 0.4ch;
  }

  /* A glyph is a full-height line; each "half" is a 0.5em window showing either
     its top or bottom slice. The opaque background matches the surrounding board
     so a folding leaf hides what's behind it (no double image). */
  .half,
  .leaf,
  .cover {
    position: absolute;
    left: 0;
    right: 0;
    height: 0.5em;
    overflow: hidden;
    background: var(--flap-bg, var(--bg));
  }
  .top {
    top: 0;
  }
  .bottom {
    bottom: 0;
  }

  .glyph {
    position: absolute;
    left: 0;
    right: 0;
    height: 1em;
    text-align: center;
    color: currentColor;
  }
  .top .glyph {
    top: 0;
  }
  .bottom .glyph {
    bottom: 0;
  }

  .anim {
    position: absolute;
    inset: 0;
  }
  .leaf.top {
    transform-origin: bottom center;
    backface-visibility: hidden;
    z-index: 2;
  }
  .cover.bottom {
    z-index: 1;
  }
  .leaf.bottom {
    transform-origin: top center;
    transform: rotateX(90deg);
    backface-visibility: hidden;
    z-index: 3;
  }

  /* The fold: the top leaf falls (0 -> -90deg) over the first half of the run,
     then the bottom leaf drops in (90 -> 0) over the second half. One duration
     drives both, kept short so it never lags the per-second tick. The -a/-b
     keyframe pairs are identical; alternating between them on each fold (by seq
     parity) is what restarts the animation without recreating the element. */
  @media (prefers-reduced-motion: no-preference) {
    .go:not(.p1) .leaf.top {
      animation: flap-top-a var(--flap-dur, 320ms) ease-in forwards;
    }
    .go.p1 .leaf.top {
      animation: flap-top-b var(--flap-dur, 320ms) ease-in forwards;
    }
    .go:not(.p1) .leaf.bottom {
      animation: flap-bottom-a var(--flap-dur, 320ms) ease-out forwards;
    }
    .go.p1 .leaf.bottom {
      animation: flap-bottom-b var(--flap-dur, 320ms) ease-out forwards;
    }
  }

  /* Reduced motion, or a type-crossing swap: drop the fold entirely; the static
     halves show the new value instantly. */
  @media (prefers-reduced-motion: reduce) {
    .anim {
      display: none;
    }
  }
  .anim.instant {
    display: none;
  }

  @keyframes flap-top-a {
    0% {
      transform: rotateX(0deg);
    }
    50%,
    100% {
      transform: rotateX(-90deg);
    }
  }
  @keyframes flap-top-b {
    0% {
      transform: rotateX(0deg);
    }
    50%,
    100% {
      transform: rotateX(-90deg);
    }
  }
  @keyframes flap-bottom-a {
    0%,
    50% {
      transform: rotateX(90deg);
    }
    100% {
      transform: rotateX(0deg);
    }
  }
  @keyframes flap-bottom-b {
    0%,
    50% {
      transform: rotateX(90deg);
    }
    100% {
      transform: rotateX(0deg);
    }
  }
</style>

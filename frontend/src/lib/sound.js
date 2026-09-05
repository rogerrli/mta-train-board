// A short Web Audio chime and the one-gesture unlock the kiosk needs (#54).
//
// No asset, no dependency (YAGNI) -- a two-note beep synthesized on the fly.
// Browsers block audio until a user gesture, so a fresh AudioContext starts
// "suspended"; `unlock()` (called from a tap) resumes it. On the Pi/Chromium
// kiosk launched with --autoplay-policy=no-user-gesture-required the context
// starts "running" already, so unlock is a no-op and no tap is needed.
//
// Everything degrades gracefully to silence: no Web Audio support, a context
// that won't build, or a blocked/failed resume all just mean no sound, no error.

export function createBeeper() {
  let ctx = null;

  function ensureCtx() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      ctx = new AC();
    } catch {
      return null;
    }
    return ctx;
  }

  function tone(c, freq, start, duration) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    // Quick attack + exponential decay so it reads as a "ping", not a buzz.
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.3, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain).connect(c.destination);
    osc.start(start);
    osc.stop(start + duration);
  }

  return {
    // Resume the context from a user gesture (or confirm the kiosk flag already
    // started it running). Returns whether audio is usable at all.
    unlock() {
      const c = ensureCtx();
      if (!c) return false;
      if (c.state === "suspended") c.resume().catch(() => {});
      return true;
    },
    // Whether audio is unlocked and ready to make sound without a gesture.
    ready() {
      return ctx != null && ctx.state === "running";
    },
    // Play the two-note heads-up chime. No-op (silent) if audio isn't available.
    beep() {
      const c = ensureCtx();
      if (!c) return;
      if (c.state === "suspended") c.resume().catch(() => {});
      try {
        const t = c.currentTime;
        tone(c, 880, t, 0.2); // A5
        tone(c, 1319, t + 0.22, 0.28); // E6 -- rising second note
      } catch {
        // Ignore: a hostile audio state shouldn't break the board.
      }
    },
  };
}

// Emscripten --pre-js for the CTR web build: the VBlank clock the game waits on.
//
// The PS1 emits a VBlank every 897619 GPU cycles at 53.693175 MHz (~16.718 ms,
// ~59.817 Hz) and CTR runs its race at one frame per two VBlanks. Here VBlanks
// are counted off requestAnimationFrame: on a ~60 Hz or ~120 Hz display they are
// locked to every first or second display frame, so each game frame stays on
// screen for the same number of refreshes (the game runs 0.3% faster than a PS1);
// on other refresh rates they follow elapsed time.
//
// Module.ctrTurbo = true makes every wait return at once (tests run the game as
// fast as the machine allows).

(function () {
  const VBLANK_MS = (1000 * 897619) / 53693175;

  const clock = {
    running: false,
    last: null,
    period: null,
    samples: [],
    lockAcc: 0,
    timeAcc: 0,
    due: 0,
    waiter: null,
  };

  function estimatePeriod(dt) {
    if (dt <= 0 || dt > 250) return;
    if (clock.period !== null && dt > clock.period * 1.6) return; // a dropped frame
    clock.samples.push(dt);
    if (clock.samples.length > 30) clock.samples.shift();
    if (clock.samples.length >= 8) {
      const sorted = clock.samples.slice().sort((a, b) => a - b);
      clock.period = sorted[sorted.length >> 1];
    }
  }

  function vblanksFor(dt) {
    const p = clock.period;
    if (p !== null) {
      const ratio = VBLANK_MS / p;
      const k = Math.round(ratio);
      if (k >= 1 && Math.abs(ratio - k) < 0.05 * k) {
        clock.lockAcc += Math.max(1, Math.round(dt / p));
        const n = Math.floor(clock.lockAcc / k);
        clock.lockAcc -= n * k;
        return n;
      }
    }
    clock.timeAcc += dt / VBLANK_MS;
    const n = Math.floor(clock.timeAcc);
    clock.timeAcc -= n;
    return n;
  }

  function onFrame(t) {
    if (clock.last !== null) {
      const dt = t - clock.last;
      estimatePeriod(dt);
      clock.due += vblanksFor(dt);
    }
    clock.last = t;
    if (clock.waiter && clock.due > 0) {
      const resolve = clock.waiter;
      const n = clock.due;
      clock.waiter = null;
      clock.due = 0;
      resolve(n);
    }
    requestAnimationFrame(onFrame);
  }

  function ensureRunning() {
    if (clock.running) return;
    clock.running = true;
    requestAnimationFrame(onFrame);
  }

  const yieldNow = (() => {
    if (typeof setImmediate === 'function') return () => new Promise((r) => setImmediate(r));
    if (typeof MessageChannel === 'function') {
      const ch = new MessageChannel();
      const queue = [];
      ch.port1.onmessage = () => queue.shift()();
      return () => new Promise((r) => { queue.push(r); ch.port2.postMessage(0); });
    }
    return () => new Promise((r) => setTimeout(r, 0));
  })();

  Module.ctrVBlankMs = VBLANK_MS;
  Module.ctrClock = clock;

  Module.ctrTakeDueVBlanks = function () {
    if (Module.ctrTurbo) return 0;
    const n = clock.due;
    clock.due = 0;
    return n;
  };

  Module.ctrWaitForVBlanks = function () {
    if (Module.ctrTurbo || typeof requestAnimationFrame !== 'function') {
      return yieldNow().then(() => 1);
    }
    ensureRunning();
    if (clock.due > 0) {
      const n = clock.due;
      clock.due = 0;
      return Promise.resolve(n);
    }
    return new Promise((resolve) => { clock.waiter = resolve; });
  };
})();

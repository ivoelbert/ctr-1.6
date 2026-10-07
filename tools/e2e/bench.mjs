// Turbo benchmark: how many VBlanks per second the game sustains in a race.
//   node tools/e2e/bench.mjs "query" [vblanks]
import { launch } from './lib.mjs';
const query = process.argv[2] ?? 'level=0&mode=1&dust2=1';
const count = Number(process.argv[3] ?? 1200);
const { browser, page } = await launch({ query: `?${query}`, log: false });
await page.waitForFunction(() => window.ctr && ctr.state().eventTime > 0, { timeout: 120000, polling: 250 });
const r = await page.evaluate(async (count) => {
  ctr.hold('cross');
  const v0 = ctr.state().vblank;
  const t0 = performance.now();
  ctr.turbo(true);
  while (ctr.state().vblank - v0 < count) await new Promise((r) => setTimeout(r, 50));
  ctr.turbo(false);
  const t1 = performance.now();
  return { vblanks: ctr.state().vblank - v0, ms: t1 - t0 };
}, count);
console.log(JSON.stringify(r), 'vblanks/s', (r.vblanks / r.ms * 1000).toFixed(0), 'ms per game frame (2 vblanks)', (2 * r.ms / r.vblanks).toFixed(2));
await browser.close();

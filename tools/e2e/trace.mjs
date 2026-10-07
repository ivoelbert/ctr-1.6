// Drives a scripted Time Trial and prints the kart's trace, in step with the game's VBlanks.
//   node tools/e2e/trace.mjs LEVEL "extra query" [vblanks after the start]
// The script holds the gas from boot, then steers by race VBlank: see SCRIPT below.
import { launch, sleep } from './lib.mjs';

const level = Number(process.argv[2] ?? 0);
const extra = process.argv[3] ? `&${process.argv[3]}` : '';
const length = Number(process.argv[4] ?? 900);
const script = process.env.SCRIPT ?? '0:cross;300:cross,left;360:cross;600:cross,right;640:cross';
const turbo = process.env.TURBO !== '0';

const { browser, page } = await launch({ query: `?level=${level}&mode=0${extra}`, log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
await page.evaluate((script, length, turbo) => {
  const steps = script.split(';').map((s) => { const [t, b] = s.split(':'); return [Number(t), b ? b.split(',') : []]; });
  window.__trace = [];
  window.__done = false;
  let start = null;
  ctr.turbo(turbo);
  Module.ctrOnVBlank = (n) => {
    const s = ctr.state();
    if (!s.kart) { ctr.hold('cross'); return; }
    // the race starts when the event clock runs
    if (start === null) { if (s.eventTime > 0) start = n; else { ctr.hold('cross'); return; } }
    const t = n - start;
    let held = [];
    for (const [at, b] of steps) if (t >= at) held = b;
    ctr.hold(...held);
    if (t % 30 === 0) window.__trace.push({ t, ...s.kart, eventTime: s.eventTime });
    if (t >= length) { window.__done = true; ctr.turbo(false); Module.ctrOnVBlank = null; ctr.release(); }
  };
}, script, length, turbo);
await page.waitForFunction(() => window.__done, { timeout: 600000, polling: 500 });
const trace = await page.evaluate(() => window.__trace);
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
for (const r of trace) {
  console.log([r.t, r.x.toFixed(0), r.y.toFixed(0), r.z.toFixed(0), r.speed, r.angle, r.quad, r.lap, r.checkpoint, r.distToFinish, r.state].join('\t'));
}

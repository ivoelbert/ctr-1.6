// A race to the finish by autopilot, then CTR's end-of-race menu: Retry, and the race again.
//   node tools/e2e/retry.mjs [route.json]     OUT=dir   QUERY="?dust2&level=0&mode=1&laps=1"
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

const routeFile = process.argv[2] ?? 'build/lev/dust2_route.json';
const route = JSON.parse(fs.readFileSync(routeFile, 'utf8'));
const outDir = process.env.OUT || 'build/shots/retry';
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: process.env.QUERY ?? '?dust2&level=0&mode=1&laps=1', log: false });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
const state = () => page.evaluate(() => { const s = ctr.state(); return { mode: (s.gameMode1 >>> 0).toString(16), time: s.eventTime, kart: s.kart && { lap: s.kart.lap, actions: s.kart.actions >>> 0, x: s.kart.x | 0, z: s.kart.z | 0 } }; });

// drive: pure pursuit round the route until the race is over (as pursuit.mjs, briefly)
await page.evaluate((path) => {
  const TAU = 4096;
  const wrap = (a) => ((a % TAU) + TAU + TAU / 2) % TAU - TAU / 2;
  let idx = 0;
  window.__finished = false;
  ctr.turbo(true);
  Module.ctrOnVBlank = () => {
    const s = ctr.state();
    if (!s.kart) return;
    if (s.eventTime <= 0) { ctr.hold('cross'); return; }
    if (s.kart.actions & 0x2000000) { window.__finished = true; ctr.release(); ctr.turbo(false); Module.ctrOnVBlank = null; return; }
    const k = s.kart;
    let best = idx, bestD = Infinity;
    for (let i = idx; i < Math.min(path.length, idx + 60); i++) {
      const d = Math.hypot(path[i][0] - k.x, path[i][2] - k.z);
      if (d < bestD) { bestD = d; best = i; }
    }
    idx = best % path.length;
    const j = (idx + 12) % path.length;
    const want = (Math.atan2(path[j][0] - k.x, path[j][2] - k.z) / (2 * Math.PI)) * TAU;
    const diff = wrap(want - k.angle);
    const held = [k.speed < 6000 ? 'cross' : null];
    if (Math.abs(diff) > 600 && k.speed > 5000) held[0] = 'square';
    if (diff > 48) held.push('left'); else if (diff < -48) held.push('right');
    ctr.hold(...held.filter(Boolean));
    if (idx > path.length - 20) idx = 0;
  };
}, route.path);
await page.waitForFunction(() => window.__finished, { timeout: 600000, polling: 500 });
console.log('finished', JSON.stringify(await state()));

// the results, then the menu: press cross every couple of seconds until a new race runs
const press = (button) => page.evaluate((button) => new Promise((done) => {
  let n = 0;
  ctr.hold(button);
  Module.ctrOnVBlank = () => { if (++n === 6) { ctr.release(); Module.ctrOnVBlank = null; done(); } };
}), button);
// a Time Trial record asks for a name: Start saves it (SubmitName)
const sequence = (process.env.PRESSES ?? 'cross cross start start cross cross cross cross cross cross').split(' ');
let restarted = false;
for (let i = 0; i < 20 && !restarted; i++) {
  await sleep(2000);
  await page.screenshot({ path: `${outDir}/after-${String(i).padStart(2, '0')}.png` });
  const s = await state();
  console.log(i, JSON.stringify(s));
  if (s.kart && s.time > 0 && s.time < 20000 && !(s.kart.actions & 0x2000000) && i > 1) { restarted = true; break; }
  await press(sequence[Math.min(i, sequence.length - 1)]);
}
console.log(restarted ? 'RETRY OK: a new race is running' : 'NO RESTART');
await page.screenshot({ path: `${outDir}/end.png` });
await browser.close();

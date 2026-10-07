// Drives Dust 2 along waypoints with a simple autopilot, in step with the game, and reports
// where the kart got stuck. Waypoints are Hammer (x, y) pairs; the run starts at the first.
//   node tools/e2e/autopilot.mjs "x,y x,y x,y ..." [max frames]     OUT=trace.txt
// Steering: CTR yaw grows when turning left; forward is (sin, cos) of yaw in (x, z).
import fs from 'node:fs';
import { launch } from './lib.mjs';

const meta = JSON.parse(fs.readFileSync('build/lev/dust2.json', 'utf8'));
const S = meta.scale;
const [CX, CY] = meta.center;
const toCtr = ([x, y]) => [(x - CX) * S, -(y - CY) * S];
const route = process.argv[2].trim().split(/\s+/).map((p) => toCtr(p.split(',').map(Number)));
const maxFrames = Number(process.argv[3] ?? 3600);
const startY = Number(process.env.START_Y ?? 600);

const { browser, page } = await launch({ query: '?level=0&mode=0&dust2=1', log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
await page.evaluate((route, maxFrames, startY) => {
  const TAU = 4096;
  const wrap = (a) => ((a % TAU) + TAU + TAU / 2) % TAU - TAU / 2;
  window.__trace = [];
  window.__events = [];
  window.__done = false;
  let start = null;
  let wp = 1;
  let stuckSince = null;
  ctr.turbo(true);
  Module.ctrOnVBlank = (n) => {
    const s = ctr.state();
    if (!s.kart) return;
    if (start === null) {
      if (s.eventTime <= 0) return;
      start = n;
      const [x0, z0] = route[0];
      const [x1, z1] = route[1];
      ctr.teleport(x0, startY, z0, Math.round(Math.atan2(x1 - x0, z1 - z0) / (2 * Math.PI) * TAU) & 4095);
      return;
    }
    const t = n - start;
    const k = s.kart;
    const [tx, tz] = route[wp];
    const dx = tx - k.x, dz = tz - k.z;
    const dist = Math.hypot(dx, dz);
    if (dist < 500) {
      window.__events.push(`t=${t} reached waypoint ${wp}`);
      wp++;
      if (wp >= route.length) { window.__done = true; ctr.release(); ctr.turbo(false); Module.ctrOnVBlank = null; return; }
    }
    const want = Math.atan2(dx, dz) / (2 * Math.PI) * TAU;
    const diff = wrap(want - k.angle);
    const held = ['cross'];
    if (diff > 60) held.push('left'); else if (diff < -60) held.push('right');
    ctr.hold(...held);
    if (t % 15 === 0) window.__trace.push([t, k.x | 0, k.y | 0, k.z | 0, k.speed, k.angle, k.quad, wp]);
    if (Math.abs(k.speed) < 1500 && t > 60) {
      if (stuckSince === null) stuckSince = t;
      else if (t - stuckSince > 240) {
        window.__events.push(`t=${t} STUCK at ${k.x | 0},${k.y | 0},${k.z | 0} heading to waypoint ${wp}`);
        window.__done = true; ctr.release(); ctr.turbo(false); Module.ctrOnVBlank = null;
      }
    } else stuckSince = null;
    if (t > maxFrames) { window.__events.push(`t=${t} out of time at waypoint ${wp}`); window.__done = true; ctr.release(); Module.ctrOnVBlank = null; }
  };
}, route, maxFrames, startY);
await page.waitForFunction(() => window.__done, { timeout: 900000, polling: 500 });
const { trace, events } = await page.evaluate(() => ({ trace: window.__trace, events: window.__events }));
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
for (const e of events) console.log(e);
if (process.env.OUT) fs.writeFileSync(process.env.OUT, trace.map((r) => r.join('\t')).join('\n') + '\n');

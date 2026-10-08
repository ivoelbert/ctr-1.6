// Drives a map's free-drive route (build/lev/MAP_free_route.json: a dense CTR path, and the AI's
// lines) by pure pursuit, in step with the game, and reports how far the kart got and where it
// got stuck.
//   node tools/e2e/pursuit.mjs MAP [max frames] [look-ahead units]   OUT=trace.txt SHOT=end.png
//   OFFSET=n (drive n units right of the route, negative: left). Reports SNAGs: the speed
//   falling by 40% in 8 frames with the gas held (a wall or an obstacle hit).
//   CONTINUE=1: when stuck, report it and carry on from further along (a tour of the map).
// Steering: CTR yaw grows when turning left; forward is (sin, cos) of yaw in (x, z).
import fs from 'node:fs';
import { launch } from './lib.mjs';

const map = process.argv[2] ?? 'dust2';
const maxFrames = Number(process.argv[3] ?? 12000);
const lookahead = Number(process.argv[4] ?? 640);
const route = JSON.parse(fs.readFileSync(`build/lev/${map}_free_route.json`, 'utf8'));
// the line to follow: the AI's middle racing line (smoothed, clear of corners) when the route
// has one, densified to a point every 64 units; LINE=path for the raw grid path
function densify(points, step = 64) {
  const out = [];
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    const n = Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[2] - a[2]) / step));
    for (let k = 0; k < n; k++) out.push([0, 1, 2].map((j) => a[j] + (b[j] - a[j]) * (k / n)));
  }
  return out;
}
const line = route.ai && process.env.LINE !== 'path' ? densify(route.ai[0]) : route.path;
// start where the route starts (the AI line begins at its first frame, near the start)
let path = line.map(([x, y, z]) => [x, y, z]);
// OFFSET=n drives n units to the right of the route (negative: left), to rub along walls
const offset = Number(process.env.OFFSET ?? 0);
if (offset) {
  path = path.map(([x, y, z], i) => {
    const a = path[Math.max(0, i - 3)], b = path[Math.min(path.length - 1, i + 3)];
    const dx = b[0] - a[0], dz = b[2] - a[2], len = Math.hypot(dx, dz) || 1;
    // right of heading (dx, dz) in CTR's x/z: (-dz, dx) is left when yaw grows to the left
    return [x + (dz / len) * offset, y, z - (dx / len) * offset];
  });
}
const { browser, page } = await launch({ query: `?map=${map}`, log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
if (process.env.SHOTS_DIR) await page.evaluate(() => { window.__noTurbo = true; });
if (process.env.CONTINUE) await page.evaluate(() => { window.__continue = true; });
await page.evaluate((path, maxFrames, lookahead) => {
  const TAU = 4096;
  const wrap = (a) => ((a % TAU) + TAU + TAU / 2) % TAU - TAU / 2;
  window.__trace = [];
  window.__events = [];
  window.__done = false;
  let start = null;
  let idx = 0;
  let stuckSince = null;
  let lastIdxReport = 0;
  const finish = (msg) => {
    window.__events.push(msg);
    window.__done = true;
    ctr.release();
    ctr.turbo(false);
    Module.ctrOnVBlank = null;
  };
  ctr.turbo(!window.__noTurbo);
  Module.ctrOnVBlank = (n) => {
    const s = ctr.state();
    if (!s.kart) return;
    if (start === null) {
      if (s.eventTime <= 0) { ctr.hold('cross'); return; }
      start = n;
      const [x0, y0, z0] = path[0];
      const [x1, , z1] = path[Math.min(8, path.length - 1)];
      ctr.teleport(x0, y0 + 100, z0, Math.round((Math.atan2(x1 - x0, z1 - z0) / (2 * Math.PI)) * TAU) & 4095);
      return;
    }
    if (s.kart.item !== window.__item || s.kart.wumpa !== window.__wumpa) {
      window.__events.push(`t=${n - start} item ${s.kart.item} wumpa ${s.kart.wumpa}`);
      window.__item = s.kart.item; window.__wumpa = s.kart.wumpa;
    }
    const t = n - start;
    const k = s.kart;
    // advance along the path: nearest point a little ahead of where we were
    let best = idx;
    let bestD = Infinity;
    for (let i = idx; i < Math.min(path.length, idx + 60); i++) {
      const d = Math.hypot(path[i][0] - k.x, path[i][2] - k.z) + Math.abs(path[i][1] - k.y) * 0.5;
      if (d < bestD) { bestD = d; best = i; }
    }
    idx = best;
    if (idx >= path.length - 3) return finish(`t=${t} finished the route`);
    if (idx - lastIdxReport >= 100) { lastIdxReport = idx; window.__events.push(`t=${t} at path ${idx}/${path.length}`); }
    let j = idx;
    let acc = 0;
    while (j < path.length - 1 && acc < lookahead) {
      acc += Math.hypot(path[j + 1][0] - path[j][0], path[j + 1][2] - path[j][2]);
      j++;
    }
    const [tx, , tz] = path[j];
    const want = (Math.atan2(tx - k.x, tz - k.z) / (2 * Math.PI)) * TAU;
    const diff = wrap(want - k.angle);
    // throttle from the turn ahead: how much the path's heading changes over the next ~1000 units
    const heading = (a, b) => Math.atan2(path[b][0] - path[a][0], path[b][2] - path[a][2]);
    const ahead = Math.min(path.length - 1, idx + 20);
    const far = Math.min(path.length - 1, idx + 44);
    let turn = 0;
    if (far - ahead >= 2 && ahead - idx >= 2) {
      turn = Math.abs(wrap(((heading(ahead, far) - heading(idx, ahead)) / (2 * Math.PI)) * TAU));
    }
    // snags: speed falling by more than 40% in a few frames with the gas held
    const hist = (window.__speeds = window.__speeds || []);
    hist.push(k.speed);
    if (hist.length > 8) hist.shift();
    if (hist.length === 8 && hist[0] > 4000 && k.speed < hist[0] * 0.6 && (window.__lastSnag ?? -999) < t - 60) {
      window.__lastSnag = t;
      window.__events.push(`t=${t} SNAG ${hist[0]}->${k.speed} at ${k.x | 0},${k.y | 0},${k.z | 0} touching ${k.touching} quad ${k.quad}`);
    }
    const sharp = Math.abs(diff);
    const target = turn > 900 ? 4000 : turn > 600 ? 5500 : turn > 300 ? 7500 : 20000;
    const held = [];
    if (k.speed > target + 1500 || (sharp > 700 && k.speed > 6000)) held.push('square');
    else if (k.speed < target) held.push('cross');
    if (diff > 48) held.push('left');
    else if (diff < -48) held.push('right');
    ctr.hold(...held);
    if (t % 15 === 0) window.__trace.push([t, k.x | 0, k.y | 0, k.z | 0, k.speed, k.angle, k.quad, idx, k.checkpoint]);
    if (Math.abs(k.speed) < 1500 && t > 60) {
      if (stuckSince === null) stuckSince = t;
      else if (t - stuckSince > 240) {
        const msg = `t=${t} STUCK at ${k.x | 0},${k.y | 0},${k.z | 0} (path ${idx}/${path.length}, off by ${bestD | 0})`;
        if (!window.__continue) return finish(msg);
        // CONTINUE=1: note it and carry on from further along the path
        window.__events.push(msg);
        idx = Math.min(path.length - 4, idx + 30);
        const [x0, y0, z0] = path[idx];
        const [x1, , z1] = path[Math.min(idx + 8, path.length - 1)];
        ctr.teleport(x0, y0 + 100, z0, Math.round((Math.atan2(x1 - x0, z1 - z0) / (2 * Math.PI)) * TAU) & 4095);
        stuckSince = null;
      }
    } else stuckSince = null;
    if (t > maxFrames) finish(`t=${t} out of time at path ${idx}/${path.length}`);
  };
}, path, maxFrames, lookahead);
if (process.env.SHOTS_DIR) {
  // screenshots every few seconds of real time while it drives (turbo off so frames show)
  fs.mkdirSync(process.env.SHOTS_DIR, { recursive: true });
  let k = 0;
  while (!(await page.evaluate(() => window.__done))) {
    await new Promise((r) => setTimeout(r, Number(process.env.SHOTS_EVERY ?? 3000)));
    await page.screenshot({ path: `${process.env.SHOTS_DIR}/shot-${String(k++).padStart(3, '0')}.png` });
  }
}
await page.waitForFunction(() => window.__done, { timeout: 900000, polling: 500 });
const { trace, events } = await page.evaluate(() => ({ trace: window.__trace, events: window.__events }));
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
for (const e of events) console.log(e);
if (process.env.OUT) fs.writeFileSync(process.env.OUT, trace.map((r) => r.join('\t')).join('\n') + '\n');

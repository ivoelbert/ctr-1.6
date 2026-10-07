// Drives a planned route (tools/route.py's json: a dense CTR path) by pure pursuit, in step
// with the game, and reports how far round the kart got and where it got stuck.
//   node tools/e2e/pursuit.mjs ROUTE.json [max frames] [look-ahead units]   OUT=trace.txt SHOT=end.png
//   MODE=1 (Arcade) LAPS=3 NO_TELEPORT=1 (start from the grid) DUST2=free (the free-drive level)
//   OFFSET=n (drive n units right of the route, negative: left). Reports SNAGs: the speed
//   falling by 40% in 8 frames with the gas held (a wall or an obstacle hit).
// Steering: CTR yaw grows when turning left; forward is (sin, cos) of yaw in (x, z).
import fs from 'node:fs';
import { launch } from './lib.mjs';

const routeFile = process.argv[2];
const maxFrames = Number(process.argv[3] ?? 12000);
const lookahead = Number(process.argv[4] ?? 640);
const route = JSON.parse(fs.readFileSync(routeFile, 'utf8'));
const laps = Number(process.env.LAPS ?? 1);
let path = [];
for (let l = 0; l < laps; l++) path = path.concat(route.path.map(([x, y, z]) => [x, y, z]));
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
// and on past the line, so the last lap counts
if (process.env.LAPS) path = path.concat(route.path.slice(1, 40));
const noTeleport = process.env.NO_TELEPORT === '1';

const mode = Number(process.env.MODE ?? 0);
const { browser, page } = await launch({ query: `?level=0&mode=${mode}&dust2=${process.env.DUST2 ?? 1}`, log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
if (process.env.SHOTS_DIR) await page.evaluate(() => { window.__noTurbo = true; });
await page.evaluate((path, maxFrames, lookahead, noTeleport) => {
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
      if (!noTeleport) {
        const [x0, y0, z0] = path[0];
        const [x1, , z1] = path[Math.min(8, path.length - 1)];
        ctr.teleport(x0, y0 + 100, z0, Math.round((Math.atan2(x1 - x0, z1 - z0) / (2 * Math.PI)) * TAU) & 4095);
      }
      window.__lap = s.kart.lap;
      return;
    }
    if (s.kart.item !== window.__item || s.kart.wumpa !== window.__wumpa) {
      window.__events.push(`t=${n - start} item ${s.kart.item} wumpa ${s.kart.wumpa} rank ${s.kart.rank}`);
      window.__item = s.kart.item; window.__wumpa = s.kart.wumpa;
    }
    if (s.kart.lap !== window.__lap) { window.__events.push(`t=${n - start} lap ${s.kart.lap} (race time ${s.eventTime})`); window.__lap = s.kart.lap; }
    if ((s.kart.actions & 0x2000000) && !window.__finished) {
      window.__finished = true;
      window.__events.push(`t=${n - start} race finished, rank ${s.kart.rank + 1} (END_OF_RACE ${(s.gameMode1 & 0x200000) !== 0})`);
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
    if (t % 15 === 0) window.__trace.push([t, k.x | 0, k.y | 0, k.z | 0, k.speed, k.angle, k.quad, idx, k.checkpoint, k.distToFinish, k.lap]);
    // the AI racers: any that stops getting anywhere for 5 s
    if (t % 60 === 0) {
      const ds = ctr.drivers();
      window.__ai = window.__ai || {};
      ds.forEach((d, i) => {
        if (i === 0 || d.actions & 0x2000000) return;
        const a = (window.__ai[i] = window.__ai[i] || { x: d.x, z: d.z, since: t, reported: false });
        if (Math.hypot(d.x - a.x, d.z - a.z) > 300) { a.x = d.x; a.z = d.z; a.since = t; a.reported = false; }
        else if (t - a.since > 300 && !a.reported) { a.reported = true; window.__events.push(`t=${t} AI ${i} STUCK at ${d.x},${d.y},${d.z} (lap ${d.lap})`); }
        a.lap = d.lap;
      });
    }
    if (Math.abs(k.speed) < 1500 && t > 60) {
      if (stuckSince === null) stuckSince = t;
      else if (t - stuckSince > 240) finish(`t=${t} STUCK at ${k.x | 0},${k.y | 0},${k.z | 0} (path ${idx}/${path.length}, off by ${bestD | 0})`);
    } else stuckSince = null;
    if (t > maxFrames) finish(`t=${t} out of time at path ${idx}/${path.length}`);
  };
}, path, maxFrames, lookahead, noTeleport);
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
const ai = await page.evaluate(() => ctr.drivers().map((d, i) => `${i}: lap ${d.lap} rank ${d.rank + 1}${d.actions & 0x2000000 ? ' finished' : ''}`));
events.push('drivers at the end: ' + ai.join(', '));
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
for (const e of events) console.log(e);
if (process.env.OUT) fs.writeFileSync(process.env.OUT, trace.map((r) => r.join('\t')).join('\n') + '\n');

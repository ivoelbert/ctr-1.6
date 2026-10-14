// Tracks to start from (the Open dialog's): each built piece by piece, as you would, and joined
// back to the start with a bridge.

import { makePiece, sweepFrame, sweepLength } from './pieces.js';
import { newTrack, worldConnectors, attachTo, bridge, demoTrack } from './track.js';
import { norm, madd, transformOf, yawOf } from './geom.js';

// a track from a start and a list of [type, extra] laid one after another, closed with a bridge
function chain(name, start, steps, settings = {}, retex = null) {
  const t = { ...newTrack(name), ...settings };
  const exit = (pc) => worldConnectors(pc).find((c) => c.end === 1);
  const first = makePiece('start', start);
  t.pieces.push(first);
  let pc = first;
  for (const [type, extra] of steps) {
    pc = attachTo(exit(pc), type, extra || {});
    t.pieces.push(pc);
  }
  // closed by a bridge, unless the pieces already meet the start
  const end = exit(pc), startIn = worldConnectors(first).find((c) => c.end === 0);
  if (Math.hypot(end.p[0] - startIn.p[0], end.p[1] - startIn.p[1], end.p[2] - startIn.p[2]) > 64) t.pieces.push(bridge(end, startIn));
  if (retex) for (const p of t.pieces) retex(p);
  return t;
}

// up and over itself: a right-hand loop that climbs and crosses the start straight on a bridge,
// then a left-hand one back down
function figureEight() {
  return chain('Figure eight', { x: 0, y: 0, z: 6144, yaw: 0 }, [
    ['straight2'],
    ['slopeUp', { rise: 768, length: 3072 }],
    ['curve2', { angle: -90 }],
    ['curve2', { angle: -90 }],
    ['curve2', { angle: -90, bank: -12, bankMode: 'arc' }],
    ['straight2', { wallL: 128, wallR: 128 }],
    ['straight2', { wallL: 128, wallR: 128 }],
    ['curve2', { angle: 90 }],
    ['slopeDown', { rise: -768, length: 3072 }],
    ['curve2', { angle: 90 }],
    ['curve2', { angle: 90 }],
  ]);
}

// a loop in the night sky: no ground, banked turns, a jump, a rainbow road
function rainbow() {
  const t = chain('Night rainbow', { x: 0, y: 2048, z: 4096, yaw: 0 }, [
    ['straight2'],
    ['bankedCurve', { angle: 90, bank: 30 }],
    ['hump', { rise: 512 }],
    ['straight'],
    ['bankedCurve', { angle: 90, bank: 30 }],
    ['straight2'],
    ['boost'],
    ['straight'],
    ['bankedCurve', { angle: 90, bank: 30 }],
    ['bumps', { tex: 'rainbow', rise: 160 }],
    ['bankedCurve', { angle: 90, bank: 30 }],
  ], { ground: false, sky: '#0c0b2b', light: 0.85 }, (p) => {
    if (p.kind === 'sweep' && !p.boost) p.tex = 'rainbow';
    if (p.kind === 'sweep') { p.wallL = 96; p.wallR = 96; p.wallTex = 'white'; }
  });
  return t;
}

// a beach in Crash Cove's own textures (when play.sh has taken them from the disc)
function beach(textures) {
  const cc = textures.filter((x) => x.group === 'Crash Cove').map((x) => x.id);
  const road = cc[0] || 'sand', edge = cc[3] || 'wood';
  const t = chain('Beach', { x: 0, y: 0, z: 6144, yaw: 0 }, [
    ['straight2'],
    ['curve4', { angle: 60 }],
    ['hump', { rise: 320 }],
    ['curve2', { angle: 120 }],
    ['straight2'],
    ['curve4', { angle: 90, bank: 15, bankMode: 'arc' }],
    ['straight'],
  ], { groundTex: 'sand', sky: '#7cc8f0' }, (p) => {
    if (p.kind === 'sweep') p.tex = road;
    if (p.kind === 'sweep') p.sideTex = edge;
  });
  // a pond and a few trees round it
  t.pieces.push(makePiece('pond', { x: -9000, y: 0, z: -3000 }));
  for (const [x, z] of [[-6000, 2000], [-11000, 1000], [-8000, -7000], [3000, -9000], [5000, 3000]]) t.pieces.push(makePiece('tree', { x, y: 0, z }));
  return t;
}

export function examples(textures) {
  return [
    ['The demo loop', () => demoTrack()],
    ['Figure eight', figureEight],
    ['Night rainbow', rainbow],
    ['Beach (Crash Cove textures)', () => beach(textures)],
    ['Temple spiral', () => templeSpiral(textures)],
    ['Canyon run', () => canyonRun(textures)],
    ['Neon city', () => neonCity(textures)],
    ['Sky islands', () => skyIslands(textures)],
    ['Frozen pass', () => frozenPass(textures)],
  ];
}

// ---- the showcase tracks: what a track can be with some work ----

// a course laid as you'd lay it: next() snaps a piece onto the end, leap() puts one across a gap
// ahead, put() places one anywhere, close() bridges the end back to the start
class Course {
  constructor(name, start, settings = {}) {
    this.t = { ...newTrack(name), ...settings };
    this.first = this.pc = this.put('start', start);
  }
  put(type, at = {}) { const p = makePiece(type, at); this.t.pieces.push(p); return p; }
  get end() { return worldConnectors(this.pc).find((c) => c.end === 1); }
  next(type, extra = {}) { this.pc = attachTo(this.end, type, extra); this.t.pieces.push(this.pc); return this.pc; }
  run(steps, common = {}) { return steps.map(([type, extra]) => this.next(type, { ...common, ...extra })); }
  // the next piece `gap` ahead of the end (level), `drop` lower, facing on
  leap(gap, drop, type, extra = {}) {
    const e = this.end, fh = norm([e.f[0], 0, e.f[2]]);
    this.pc = this.put(type, { x: e.p[0] + fh[0] * gap, y: e.p[1] - drop, z: e.p[2] + fh[2] * gap, yaw: yawOf(fh), ...extra });
    return this.pc;
  }
  // a curve round to a heading (degrees, as a piece's yaw: 0 north, 90 west, 180 south, -90 east)
  turnTo(yaw, type = 'curve4', extra = {}) {
    const a = ((((yaw - yawOf(this.end.f)) % 360) + 540) % 360) - 180;
    return Math.abs(a) < 0.5 ? this.pc : this.next(type, { ...extra, angle: a });
  }
  // a straight on till the end's x (or z) is `value`
  straightTo(axis, value, extra = {}) {
    const e = this.end, k = axis === 'x' ? 0 : 2;
    const length = (value - e.p[k]) / e.f[k];
    return length > 32 ? this.next('straight', { ...extra, length }) : this.pc;
  }
  // a jump: off a kicker, over `gap`, onto a landing ramp `drop` lower than the lip that runs
  // down `down` more, solid to the ground under it (a short jump hits its face, not under it)
  jump(gap, drop, down, extra = {}, kicker = 'kicker') {
    this.next(kicker, { ...extra, tex: extra.kickTex || 'hazard' });
    const lip = this.end.p[1];
    return this.leap(gap, drop, 'landing', { rise: -down, length: Math.max(2048, down * 4), thick: Math.max(96, lip - drop), ...extra });
  }
  close(extra = {}) {
    const startIn = worldConnectors(this.first).find((c) => c.end === 0), e = this.end;
    if (Math.hypot(e.p[0] - startIn.p[0], e.p[1] - startIn.p[1], e.p[2] - startIn.p[2]) > 64) this.t.pieces.push(bridge(e, startIn, extra));
    return this.t;
  }
}

// points along roads: every `every` units, `off` right of the middle (left when negative), with
// the road's heading there
function along(pieces, every, off, fn) {
  for (const pc of pieces) {
    const n = Math.max(1, Math.round(sweepLength(pc) / every)), T = transformOf(pc);
    for (let k = 0; k < n; k++) {
      const fr = sweepFrame(pc, (k + 0.5) / n);
      fn(T.point(madd(fr.p, fr.r, off)), yawOf(T.dir(fr.f)), pc, k);
    }
  }
}

// a test for "nothing's there": no road within r (across the ground) of x, z, nor (bodies) a
// circle already taken
function freeSpots(t) {
  const pts = [];
  for (const pc of t.pieces) {
    if (pc.kind !== 'sweep') continue;
    const n = Math.max(2, Math.ceil(sweepLength(pc) / 256)), T = transformOf(pc), W = (pc.width || 1024) / 2;
    for (let k = 0; k <= n; k++) {
      const fr = sweepFrame(pc, k / n);
      const p = T.point(fr.p);
      pts.push([p[0], p[2], W]);
    }
  }
  // what's there already (hills, blocks, pillars): a circle round each
  const taken = t.pieces.filter((pc) => pc.kind !== 'sweep').map((pc) => [pc.x, pc.z, pc.radius ?? 0.6 * Math.hypot(pc.width || 0, pc.length || 0)]);
  const free = (x, z, r) => pts.every(([px, pz, w]) => Math.hypot(px - x, pz - z) > r + w) && taken.every(([tx, tz, tr]) => Math.hypot(tx - x, tz - z) > r + tr);
  free.take = (x, z, r) => taken.push([x, z, r]);
  return free;
}

// a box or platform (made from its entry edge) with its middle at x, z
function centred(type, x, z, yaw, extra) {
  const l = extra.length ?? 1024, a = yaw * Math.PI / 180;
  return makePiece(type, { ...extra, x: x + Math.sin(a) * l / 2, z: z + Math.cos(a) * l / 2, yaw });
}

// the same random numbers every time (the examples come out the same)
function random(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// one of CTR's textures (taken from the disc by play.sh) when there, else the editor's own
const texPick = (textures) => (id, fallback) => (textures.some((t) => t.id === id) ? id : fallback);

// up a spiral round a temple's tower (a turn and a half), down a stone toboggan run, off a jump
// over the road home, and round the temple grounds
function templeSpiral(textures) {
  const T = texPick(textures);
  const paving = T('ctr-papuspyramid-2', 'stone'), blocks = T('ctr-tigertemple-8', 'stone');
  const braid = T('ctr-papuspyramid-5', 'brick'), glyph = T('ctr-tigertemple-10', 'stone');
  const faces = T('ctr-papuspyramid-15', 'stone'), pale = T('ctr-tigertemple-7', 'concrete');
  const path = T('ctr-tigertemple-14', 'dirt');
  const road = { tex: paving, sideTex: blocks };
  const Z0 = -4096;    // the start line's entry
  const c = new Course('Temple spiral', { x: 0, y: 0, z: Z0, yaw: 0, ...road }, { groundTex: 'grass', sky: '#f2b56b', light: 0.95 });
  c.next('straight', road);
  // the spiral: six quarter turns left, half a level each, round the tower
  const R = 3072, W = 1280;
  for (let k = 0; k < 6; k++) {
    c.next('curve2', { ...road, angle: 90, radius: R, width: W, rise: 512, bank: 8,
      bankMode: k === 0 ? 'in' : k === 5 ? 'out' : 'const', wallR: 192, wallTex: braid, supports: false });
  }
  const centre = [-R, Z0 - 3072];
  c.put('pillar', { x: centre[0], y: 0, z: centre[1], radius: 2200, height: 3600, tex: blocks });
  c.put('pillar', { x: centre[0], y: 3600, z: centre[1], radius: 1500, height: 900, tex: glyph });
  c.put('pillar', { x: centre[0], y: 4500, z: centre[1], radius: 800, height: 700, tex: faces });
  // off the top (heading south) along a causeway, and down the toboggan run, round to the east
  const top = c.next('straight', { ...road, length: 2048, wallL: 128, wallR: 128, wallTex: braid, supports: false });
  const run = c.run([
    ['halfpipe', { length: 3072, rise: -640 }],
    ['pipeCurve', { angle: 90, radius: 3072, rise: -768 }],
    ['halfpipe', { length: 2048, rise: -384 }],
  ], { tex: pale, sideTex: blocks });
  c.next('straight', { ...road, width: 1280 });
  // the jump: off the run, over the road that comes back up to the start
  c.jump(896, 512, 1024, { ...road, width: 1280 });
  // round the temple grounds: south, west, and north onto the start's line (under the jump)
  const grounds = [];
  const go = (fn) => { const before = c.t.pieces.length; fn(); grounds.push(...c.t.pieces.slice(before)); };
  go(() => {
    c.next('straight', { ...road, tex: path });
    c.turnTo(180, 'bankedCurve', { ...road, bank: 18 });
    c.next('boost', road);
    c.next('hump', { ...road, rise: 256 });
    c.turnTo(90, 'curve4', road);
    c.straightTo('x', 4096, { ...road, tex: path });
    c.turnTo(0, 'curve4', road);
    c.straightTo('z', Z0, { ...road, tex: path });
  });
  c.close(road);
  // the temple: columns along the run, statues' heads and trees round the grounds, braziers
  along([top, ...run], 1600, 1500, (p) => c.put('pillar', { x: p[0], y: 0, z: p[2], radius: 220, height: Math.max(600, p[1] - 160), tex: braid }));
  along([top, ...run], 1600, -1500, (p) => c.put('pillar', { x: p[0], y: 0, z: p[2], radius: 220, height: Math.max(600, p[1] - 160), tex: braid }));
  const free = freeSpots(c.t), rnd = random(3);
  for (let i = 0, n = 0; i < 800 && n < 46; i++) {
    const x = -16000 + rnd() * 32000, z = Z0 - 14000 + rnd() * 30000;
    if (!free(x, z, n % 4 === 0 ? 700 : 600)) continue;
    free.take(x, z, 500); n++;
    if (n % 4 === 0) {
      c.put('block', { x, y: 0, z, yaw: Math.round(rnd() * 4) * 90 + 180, width: 700, length: 700, height: 300, tex: blocks });
      c.put('block', { x, y: 300, z, yaw: Math.round(rnd() * 4) * 90 + 180, width: 600, length: 600, height: 700, tex: faces });
    } else if (n % 4 === 1) {
      c.put('pillar', { x, y: 0, z, radius: 200, height: 300 + rnd() * 1200, tex: rnd() < 0.5 ? braid : blocks });
    } else {
      c.put('tree', { x, y: 0, z, height: 1400 + rnd() * 900, radius: 420 + rnd() * 200, tex: n % 3 ? 'green' : T('ctr-tigertemple-6', 'green') });
    }
  }
  // fire bowls by the start, glowing
  for (const side of [-1, 1]) {
    c.put('pillar', { x: side * 900, y: 0, z: Z0 - 1000, radius: 120, height: 500, tex: blocks });
    c.put('pillar', { x: side * 900, y: 500, z: Z0 - 1000, radius: 220, height: 120, tex: 'orange', glow: true });
  }
  c.put('bigSign', { x: 3000, y: 0, z: Z0 - 3600, yaw: 150, text: 'TEMPLE', bg: '#5a3a1a', fg: '#ffd34d' });
  return c.t;
}

// through a gorge, over washboard, up onto a mesa, off its edge, and home past the rocks
function canyonRun(textures) {
  const T = texPick(textures);
  const asphalt = T('ctr-dingocanyon-5', 'road-plain'), stripes = T('ctr-dingocanyon-16', 'hazard');
  const rock = T('ctr-dingocanyon-1', 'sand'), rock2 = T('ctr-dingocanyon-4', 'dirt'), dust = T('ctr-dingocanyon-2', 'sand');
  const c = new Course('Canyon run', { x: -14336, y: 0, z: 14336, yaw: 0, tex: asphalt, wallTex: stripes },
    { groundTex: 'sand', sky: '#f39a5a', light: 0.95 });
  const road = { tex: asphalt, wallTex: stripes, sideTex: rock2 };
  // the gorge: walls of rock both sides, a bend through it
  const gorge = c.run([['straight2'], ['straight2'], ['bend', { angle: -30 }], ['bend', { angle: 30 }], ['straight2']], road);
  along(gorge, 2048, 0, (p, yaw, pc, k) => {
    for (const side of [-1, 1]) {
      const r = side * (1024 + 1700);
      const q = [p[0] + Math.cos(yaw * Math.PI / 180) * r, p[2] - Math.sin(yaw * Math.PI / 180) * r];
      c.put('ridge', { x: q[0], y: 0, z: q[1], yaw, width: 3400, length: 3200, height: 2048 + ((k * 7 + side * 3) % 5) * 256, tex: k % 2 ? rock : rock2 });
    }
  });
  // washboard out of the gorge, then up onto the mesa
  c.run([['bumps', { tex: dust, rise: 96 }], ['curve4', { angle: -60 }], ['straight'], ['slopeUp', { rise: 1008, length: 4096, wallL: 96, wallR: 96 }]], road);
  const top = c.end, fh = norm([top.f[0], 0, top.f[2]]);
  const half = 0.7 * 6144;
  c.put('mesa', { x: top.p[0] + fh[0] * half, y: 0, z: top.p[2] + fh[2] * half, yaw: yawOf(fh), width: 12288, length: 12288, height: 1000, slope: 0.3, tex: rock });
  // across the top, a turn right, and off the edge
  c.run([['straight2', { tex: dust }], ['curve2', { angle: -90, tex: dust }], ['straight', { tex: dust, length: half - 2048 - 1024 }]], road);
  c.jump(896, 384, 1008 + 256 - 384, { ...road, kickTex: stripes });
  // the plain: a sweeping bend, a hump, under a rock arch, dunes, and back
  const plain = c.run([['straight2'], ['bankedCurve', { angle: -90, bank: 18, radius: 4096 }], ['straight2'], ['hump', { rise: 320 }], ['straight2'], ['curve4', { angle: 60 }], ['boost'], ['straight2']], road);
  // a rock arch over the road
  const arch = plain[4];
  {
    const fr = sweepFrame(arch, 0.5), mid = transformOf(arch).point(fr.p), yaw = arch.yaw, a = yaw * Math.PI / 180;
    for (const side of [-1, 1]) c.t.pieces.push(centred('block', mid[0] + Math.cos(a) * side * 1150, mid[2] - Math.sin(a) * side * 1150, yaw, { y: 0, width: 800, length: 1400, height: 1500, tex: rock }));
    c.t.pieces.push(centred('platform', mid[0], mid[2], yaw, { y: 1900, width: 3100, length: 1800, height: 420, tex: rock, sideTex: rock2 }));
  }
  // home: south, west along the bottom, and north onto the start's line
  c.turnTo(180, 'curve4', road);
  c.straightTo('z', 14336, road);
  c.turnTo(90, 'curve2', road);
  c.straightTo('x', -14336 + 2048, road);
  c.turnTo(0, 'curve2', road);
  c.close(road);
  // the scenery: mesas and buttes off the road, rocks, cacti
  const free = freeSpots(c.t), rnd = random(7);
  for (let i = 0, n = 0; i < 400 && n < 9; i++) {
    const w = 4096 + rnd() * 4096, x = (rnd() * 2 - 1) * (24000 - w / 2), z = (rnd() * 2 - 1) * (24000 - w / 2);
    if (!free(x, z, w * 0.75)) continue;
    free.take(x, z, w * 0.75); n++;
    c.put('mesa', { x, y: 0, z, yaw: rnd() * 90, width: w, length: w * (0.7 + rnd() * 0.6), height: 1024 + Math.round(rnd() * 8) * 256, slope: 0.25, tex: n % 2 ? rock : rock2 });
  }
  for (let i = 0, n = 0; i < 600 && n < 40; i++) {
    const x = (rnd() * 2 - 1) * 23000, z = (rnd() * 2 - 1) * 23000;
    if (!free(x, z, 500)) continue;
    free.take(x, z, 300); n++;
    if (n % 3) {
      const h = 600 + rnd() * 700;
      c.put('pillar', { x, y: 0, z, radius: 90, height: h, tex: 'green' });
      c.put('pillar', { x: x + 160, y: h * 0.45, z, radius: 60, height: h * 0.35, tex: 'green' });
      if (n % 2) c.put('pillar', { x: x - 150, y: h * 0.3, z, radius: 55, height: h * 0.3, tex: 'green' });
    } else {
      c.put('block', { x, y: 0, z, yaw: rnd() * 90, width: 300 + rnd() * 500, length: 300 + rnd() * 500, height: 200 + rnd() * 400, tex: rock2 });
    }
  }
  c.put('bigSign', { x: -14336 + 2600, y: 0, z: 11400, yaw: 200, text: 'CANYON RUN', bg: '#7a2e12', fg: '#ffd34d' });
  return c.t;
}

// a city at night in the rain: streets between towers, a tunnel through one, neon signs, and a
// freeway that climbs over the city and crosses the street below
function neonCity(textures) {
  const T = texPick(textures);
  const truss = T('ctr-nginlabs-10', 'metal'), panels = T('ctr-nginlabs-12', 'metal'), plates = T('ctr-nginlabs-15', 'concrete');
  const quilt = T('ctr-hotairskyway-7', 'purple'), gold = T('ctr-hotairskyway-12', 'brick');
  const G = 12288;    // the streets: x and z at -G, 0 and G
  const c = new Course('Neon city', { x: -G, y: 0, z: -2048, yaw: 0, wallL: 64, wallR: 64 }, { groundTex: 'road-plain', sky: '#1b0f3d', light: 0.6, weather: 'rain' });
  const street = { wallL: 64, wallR: 64, wallTex: 'kerb' };
  const streets = [];
  const lay = (steps) => { const ps = c.run(steps, street); streets.push(...ps); return ps; };
  // north up the west side, east along the top through a tunnel, south down the middle
  c.straightTo('z', -G + 2048, street); streets.push(c.pc);
  lay([['curve2', { angle: -90 }], ['boost']]);
  const tunnel = lay([['walled', { length: 3072, wallL: 320, wallR: 320, wallTex: 'metal' }]])[0];
  c.straightTo('x', -2048, street); streets.push(c.pc);
  lay([['curve2', { angle: -90 }], ['straight2'], ['bumps', { rise: 64, tex: 'road' }]]);
  c.straightTo('z', G - 2048, street); streets.push(c.pc);
  // east along the bottom, north up the east side
  lay([['curve2', { angle: 90 }], ['superBoost']]);
  c.straightTo('x', G - 2048, street); streets.push(c.pc);
  lay([['curve2', { angle: 90 }]]);
  c.straightTo('z', 2048, street); streets.push(c.pc);
  // the freeway: up, west over the city (over the middle street), a chicane, and down
  const hw = { wallL: 192, wallR: 192, wallTex: 'concrete', tex: 'road-blue', sideTex: 'concrete' };
  const freeway = c.run([
    ['curve2', { angle: 90, ...street }],
    ['climb', { rise: 1536, length: 4096 }],
    ['bend', { angle: -30 }], ['bend', { angle: 30 }], ['bend', { angle: 30 }], ['bend', { angle: -30 }],
    ['straight'],
    ['climb', { rise: -1536, length: 4096 }],
  ], hw);
  c.straightTo('x', -G + 2048, street); streets.push(c.pc);
  c.turnTo(0, 'curve2', street); streets.push(c.pc);
  c.close(street);
  // the tunnel's roof: a building over the road
  {
    const fr = sweepFrame(tunnel, 0.5), mid = transformOf(tunnel).point(fr.p);
    c.t.pieces.push(centred('block', mid[0], mid[2], tunnel.yaw, { y: 560, width: 3600, length: 3072, height: 3000, tex: panels }));
    c.t.pieces.push(centred('block', mid[0], mid[2], tunnel.yaw, { y: 3560, width: 1800, length: 1500, height: 1600, tex: truss }));
  }
  // the blocks: towers on a grid where the roads aren't, each with a neon strip up a corner
  const free = freeSpots(c.t), rnd = random(11);
  const skins = [truss, panels, plates, quilt, gold, 'metal', 'concrete', 'brick', 'black'];
  const neon = ['purple', 'blue', 'red', 'yellow', 'orange', 'green'];
  const towers = [];
  // lots in rows along the streets' edges (three a block), and a ring of taller ones outside
  const rows = [2560, 6144, 9728, 14848, 18432, 22016].flatMap((v) => [v, -v]);
  for (const gx of rows) {
    for (const gz of rows) {
      const outer = Math.max(Math.abs(gx), Math.abs(gz)) > G + 4096;
      if (outer && rnd() < 0.45) continue;
      const w = 2048 + Math.round(rnd() * 3) * 256, d = 2048 + Math.round(rnd() * 3) * 256;
      const x = gx + (rnd() - 0.5) * 256, z = gz + (rnd() - 0.5) * 256;
      if (!free(x, z, Math.hypot(w, d) / 2 + 300)) continue;
      const h = (outer ? 4096 : 1536) + Math.round(rnd() * (outer ? 10 : 12)) * 512;
      towers.push([x, z, w, d, h]);
      c.t.pieces.push(centred('block', x, z, 0, { y: 0, width: w, length: d, height: h, tex: skins[Math.floor(rnd() * skins.length)] }));
      const sx = rnd() < 0.5 ? -1 : 1, sz = rnd() < 0.5 ? -1 : 1;
      c.put('block', { x: x + sx * (w / 2 + 40), y: 0, z: z + sz * (d / 2 + 40) + 48, width: 96, length: 96, height: h * (0.5 + rnd() * 0.5), tex: neon[Math.floor(rnd() * neon.length)], glow: true });
    }
  }
  // neon signs on the roofs nearest the roads, facing them
  const names = [['OXIDE', '#ff3df2'], ['HOTEL', '#46f0ff'], ['RAMEN', '#ffd34d'], ['24H', '#5dff6e'], ['ARCADE', '#ff6a3d'], ['TAXI', '#ffe600'],
    ['CLUB', '#b26bff'], ['CTR', '#ff3d6e'], ['SUSHI', '#46f0ff'], ['DISCO', '#ff3df2'], ['PIZZA', '#ffd34d'], ['NITRO', '#5dff6e']];
  const pts = [];
  along(streets, 512, 0, (p) => pts.push(p));
  const near = towers.map((tw) => {
    let best = null, bd = Infinity;
    for (const p of pts) { const d = Math.hypot(p[0] - tw[0], p[2] - tw[1]); if (d < bd) { bd = d; best = p; } }
    return { tw, p: best, d: bd };
  }).filter((e) => e.tw[4] < 7000).sort((a, b) => a.d - b.d);
  near.slice(0, names.length).forEach(({ tw, p }, i) => {
    const [x, z, w, d, h] = tw, yaw = yawOf(norm([p[0] - x, 0, p[2] - z]));
    c.put('sign', { x, y: h - 300, z, yaw, width: Math.min(w, 2048), height: 768, lift: 300, text: names[i][0], bg: '#120822', fg: names[i][1], glow: true });
  });
  // street lights, and the freeway's
  along(streets, 3072, -760, (p, yaw) => {
    c.put('post', { x: p[0], y: p[1], z: p[2], height: 900, tex: 'black' });
    c.put('pillar', { x: p[0], y: p[1] + 900, z: p[2], radius: 120, height: 50, tex: 'yellow', glow: true });
  });
  along(freeway.slice(1), 2048, 0, (p, yaw, pc, k) => {
    for (const side of [-1, 1]) {
      const a = yaw * Math.PI / 180, q = [p[0] + Math.cos(a) * side * 820, p[2] - Math.sin(a) * side * 820];
      if (k % 2 === 0) c.put('post', { x: q[0], y: p[1], z: q[1], height: 700, radius: 30, tex: side < 0 ? 'purple' : 'blue', glow: true });
    }
  });
  c.put('bigSign', { x: -G - 2400, y: 0, z: -3500, yaw: -100, text: 'NEON CITY', bg: '#120822', fg: '#ff3df2', glow: true });
  return c.t;
}

// islands in the sky: no ground, a jump off the first, a rope bridge, a half pipe round a corner,
// a boosted leap down to the lowest, and a climb back up over little islands to the start
function skyIslands(textures) {
  const T = texPick(textures);
  const grass = T('ctr-tigertemple-5', 'grass'), earth = T('ctr-dingocanyon-4', 'dirt'), planks = T('ctr-blizzardbluff-6', 'wood');
  const top = 2048;
  const c = new Course('Sky islands', { x: 0, y: top + 8, z: 14336, yaw: 0, sideTex: earth }, { ground: false, sky: '#86c8f5', light: 1 });
  const road = { sideTex: earth };
  const islands = [];
  // an island under some roads: their footprint and a margin each side (none where a road
  // leaves it over the void: w, e, n, s), its top just under the lowest
  const island = (pieces, m = {}, depth = 1400) => islands.push({ pieces, m: { w: 1280, e: 1280, n: 1280, s: 1280, ...m }, depth });
  const home = [c.first, c.next('straight', road)];
  c.jump(896, 384, 512, { ...road, thick: 400 });
  island([c.pc, ...c.run([['straight'], ['curve2', { angle: -90 }], ['straight']], road)], { s: 0, e: 0 });
  // the rope bridge: planks sagging between two islands
  c.next('dip', { width: 768, length: 6144, rise: -320, tex: planks, wallL: 160, wallR: 160, wallTex: planks, thick: 32 });
  island(c.run([['straight'], ['pipeCurve', { angle: 90, radius: 3072, tex: T('ctr-tigertemple-3', 'concrete') }], ['straight'], ['superBoost']], road), { w: 0, n: 0 }, 1800);
  // the leap down to the lowest island
  c.jump(1280, 640, 1024, { ...road, thick: 500 }, 'bigKicker');
  island([c.pc, ...c.run([['straight'], ['curve2', { angle: 90 }]], road)], { s: 0, w: 0, e: 1536 }, 1200);
  // the climb back: over little islands, west, then south
  c.next('slopeUp', { ...road, rise: 512, length: 4096 });
  island([c.next('straight', road)], { w: 0, e: 0, n: 900, s: 900 }, 900);
  c.next('slopeUp', { ...road, rise: 512, length: 4096 });
  const legs = [c.straightTo('x', -6144 + 3072, road)];
  island([c.next('bankedCurve', { ...road, angle: 90, radius: 3072, bank: 20 })], { e: 0, s: 0 }, 1100);
  c.next('slopeUp', { ...road, rise: 512, length: 4096 });
  legs.push(c.straightTo('z', 14336, road));
  home.push(c.turnTo(-90, 'curve2', road));
  c.straightTo('x', -2048, road); home.push(c.pc);
  home.push(c.turnTo(0, 'curve2', road));
  c.close(road);
  island(home, { n: 0 }, 1600);
  // the islands themselves, and what grows on them
  const rnd = random(5);
  for (const is of islands) {
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity, y = Infinity;
    along(is.pieces, 256, 0, (p) => { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); z0 = Math.min(z0, p[2]); z1 = Math.max(z1, p[2]); y = Math.min(y, p[1]); });
    for (const pc of is.pieces) y = Math.min(y, pc.y);
    x0 -= is.m.w; x1 += is.m.e; z0 -= is.m.n; z1 += is.m.s;
    const yTop = y - 8;
    c.put('platform', { x: (x0 + x1) / 2, y: yTop, z: z1, width: x1 - x0, length: z1 - z0, height: is.depth, tex: grass, sideTex: earth });
    // a rocky underside, narrower as it goes down
    c.put('platform', { x: (x0 + x1) / 2, y: yTop - is.depth, z: z1 - (z1 - z0) * 0.15, width: (x1 - x0) * 0.7, length: (z1 - z0) * 0.7, height: is.depth * 0.6, tex: earth, sideTex: earth });
    c.put('platform', { x: (x0 + x1) / 2, y: yTop - is.depth * 1.6, z: z1 - (z1 - z0) * 0.3, width: (x1 - x0) * 0.4, length: (z1 - z0) * 0.4, height: is.depth * 0.5, tex: earth, sideTex: earth });
    is.box = [x0, x1, z0, z1, yTop];
  }
  // stepping stones under the long roads home, and rocks floating off them
  along(legs, 4608, 0, (p, yaw, pc, k) => {
    if (k === 0) return;
    const w = 1600 + rnd() * 900, side = (rnd() - 0.5) * 500;
    c.put('platform', { x: p[0] + side, y: p[1] - 8, z: p[2] + w / 2, width: w, length: w, height: 700, tex: grass, sideTex: earth });
    c.put('platform', { x: p[0] + side, y: p[1] - 708, z: p[2] + w * 0.35, width: w * 0.6, length: w * 0.6, height: 500, tex: earth, sideTex: earth });
  });
  for (let i = 0; i < 14; i++) {
    const x = (rnd() * 2 - 1) * 20000, z = (rnd() * 2 - 1) * 20000, w = 1200 + rnd() * 2000, y = rnd() * 3500;
    if (!freeSpots(c.t)(x, z, w)) continue;
    c.put('platform', { x, y, z: z + w / 2, width: w, length: w * (0.7 + rnd() * 0.6), height: 600 + rnd() * 600, tex: grass, sideTex: earth });
    c.put('tree', { x, y, z, height: 900 + rnd() * 600, radius: 320 + rnd() * 120 });
  }
  const free = freeSpots(c.t);
  for (const is of islands) {
    const [x0, x1, z0, z1, yTop] = is.box;
    for (let i = 0, n = 0; i < 60 && n < Math.ceil((x1 - x0) * (z1 - z0) / 2.5e6); i++) {
      const x = x0 + 500 + rnd() * (x1 - x0 - 1000), z = z0 + 500 + rnd() * (z1 - z0 - 1000);
      if (!free(x, z, 450)) continue;
      free.take(x, z, 400); n++;
      c.put('tree', { x, y: yTop, z, height: 1100 + rnd() * 700, radius: 380 + rnd() * 160, tex: n % 3 ? 'green' : grass });
    }
    // a waterfall off one side
    c.put('block', { x: (x0 + x1) / 2 + (rnd() - 0.5) * (x1 - x0) * 0.5, y: yTop - is.depth - 2400, z: z1 + 40, width: 500, length: 60, height: is.depth + 2400 + 4, tex: 'water' });
  }
  // clouds below, and far off
  for (let i = 0; i < 18; i++) {
    const x = (rnd() * 2 - 1) * 22000, z = (rnd() * 2 - 1) * 22000;
    c.put('block', { x, y: -1400 + rnd() * 600, z, yaw: rnd() * 90, width: 2500 + rnd() * 4000, length: 1500 + rnd() * 2500, height: 200 + rnd() * 200, tex: 'white' });
  }
  return c.t;
}

// a mountain pass in the snow: through the pines, up switchbacks on stilts, along the top, down a
// ski jump onto a frozen lake, and back across the ice
function frozenPass(textures) {
  const T = texPick(textures);
  const snowRoad = T('ctr-blizzardbluff-7', 'road-plain'), icyRock = T('ctr-polarpass-2', 'stone'), icyRock2 = T('ctr-polarpass-6', 'stone');
  const snow = T('ctr-blizzardbluff-1', 'snow'), ice = T('ctr-blizzardbluff-15', 'ice'), pine = T('ctr-blizzardbluff-5', 'green');
  const logs = T('ctr-blizzardbluff-4', 'wood'), lane = T('ctr-polarpass-5', 'ice');
  const road = { tex: snowRoad, sideTex: icyRock, wallTex: snow };
  const c = new Course('Frozen pass', { x: 12288, y: 0, z: 14336, yaw: 0, ...road }, { groundTex: 'snow', sky: '#aebfd3', light: 0.9, weather: 'snow' });
  // through the pines and to the foot of the mountain
  const forest = c.run([['straight2'], ['curve4', { angle: 90 }], ['straight2'], ['curve2', { angle: -90 }]], road);
  // the switchbacks: three climbs, two hairpins, on stilts
  const climb = { ...road, wallL: 128, wallR: 128, supportTex: logs };
  const pass = c.run([
    ['slopeUp', { rise: 768, length: 4096 }],
    ['curve2', { angle: 180, radius: 1536, bank: 12, bankMode: 'arc' }],
    ['slopeUp', { rise: 768, length: 4096 }],
    ['curve2', { angle: -180, radius: 1536, bank: 12, bankMode: 'arc' }],
    ['slopeUp', { rise: 768, length: 4096 }],
    // along the top, then down the ski jump onto the lake
    ['curve2', { angle: 90 }],
    ['straight2', { tex: snow }],
    ['curve2', { angle: 90, tex: snow }],
    ['climb', { rise: -1536, length: 4096, tex: lane }],
  ], climb);
  c.jump(1024, 512, 1024, { ...road, tex: lane, thick: 1024 }, 'bigKicker');
  // across the frozen lake, and home
  const lake = [c.pc];
  lake.push(c.straightTo('z', 14336, { ...road, tex: ice }));
  lake.push(c.turnTo(-90, 'curve4', { ...road, tex: ice }));
  c.straightTo('x', 12288 - 4096, road);
  const home = [c.pc, c.turnTo(0, 'curve4', road)];
  c.close(road);
  // the lake under the ice road
  c.t.pieces.push(centred('pond', -7500, 15000, 0, { y: -1, width: 9000, length: 9000, height: 8, tex: ice }));
  // the mountains: the one the pass climbs, peaks behind it
  c.put('hill', { x: -1000, y: 0, z: -9000, width: 14000, length: 12000, height: 1700, tex: snow });
  const peak = (x, z, w, l, h, tex) => c.put('mountain', { x, y: 0, z, width: w, length: l, height: h, tex, capTex: snow, capAt: 0.5 });
  peak(-9000, -12000, 12288, 12288, 5120, icyRock);
  peak(7000, -17000, 14000, 11000, 6144, icyRock2);
  peak(-18500, -4000, 10000, 14000, 4096, icyRock);
  peak(18000, -5000, 9000, 12000, 3584, icyRock2);
  peak(-1500, -19500, 9000, 9000, 4608, icyRock);
  // pines: thick in the forest, scattered elsewhere; snow drifts
  const free = freeSpots(c.t), rnd = random(23);
  for (let i = 0, n = 0; i < 1500 && n < 70; i++) {
    const x = (rnd() * 2 - 1) * 23000, z = -4000 + rnd() * 27000;
    if (!free(x, z, 520)) continue;
    free.take(x, z, 450); n++;
    c.put('tree', { x, y: 0, z, height: 1500 + rnd() * 1300, radius: 380 + rnd() * 200, tex: n % 4 ? pine : 'green' });
  }
  for (let i = 0, n = 0; i < 300 && n < 10; i++) {
    const x = (rnd() * 2 - 1) * 22000, z = (rnd() * 2 - 1) * 22000;
    if (!free(x, z, 1600)) continue;
    free.take(x, z, 1500); n++;
    c.put('dune', { x, y: 0, z, yaw: rnd() * 180, width: 3000 + rnd() * 2000, length: 1500 + rnd() * 1000, height: 200 + rnd() * 250, tex: snow });
  }
  // a log cabin by the lake, its window lit
  c.t.pieces.push(centred('block', 3000, 20500, 15, { y: 0, width: 2200, length: 1600, height: 900, tex: logs }));
  c.t.pieces.push(centred('block', 3000, 20500, 15, { y: 900, width: 2400, length: 1800, height: 250, tex: snow }));
  c.t.pieces.push(centred('block', 3000 - 0.26 * 820, 20500 - 0.97 * 820, 15, { y: 300, width: 500, length: 40, height: 350, tex: 'yellow', glow: true }));
  c.put('bigSign', { x: 12288 + 2600, y: 0, z: 11500, yaw: 160, text: 'FROZEN PASS', bg: '#1d3f6e', fg: '#e8f4ff' });
  return c.t;
}

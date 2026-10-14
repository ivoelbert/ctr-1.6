// A track (the editor's pieces) to what the game reads (engine/platform/native_world.c):
// the tiles (assets/world/T_i_j.lev, mesh-only levels), index.bin, map.bin (the minimap) and
// route.bin (the start and the checkpoints the laps go by), all in the page, in milliseconds.
//
// The field is the 3 x 3 tiles round the origin (48 x 48 blocks): the whole of it is one of the
// engine's windows, so nothing streams and the origin never moves (16-bit checkpoints).

import { writeTile, FLAG_GROUND, FLAG_CAMERA_SEARCH, FLAG_COLLISION_SURFACE, FLAG_TRIGGER, FLAG_KILL_PLANE, FLAG_SKIP_WATER_LIST } from './lev.js';
import { add, sub, scale, cross, dot, norm, madd, len, transformOf, apply3 } from './geom.js';
import { emitPiece, sweepFrame, sweepLength, connectors, CATALOGUE } from './pieces.js';

export const TILE = 16384;
export const FIELD = 24576;          // the field reaches +-FIELD in x and z
export const GROUND_Y = -4;          // the grass, a hair under a road laid on the ground
const GROUND_NY = 0.3;               // floors up to about 72 degrees are driven on (quarter pipes)
const KILL_Y = -1600;
const NODE_SPACING = 800;
const MAP_UNIT = 512;

// quadblock slot of grid point (i, j) (i along u, j along v): 0 4 1 / 5 6 7 / 2 8 3
const SLOT = [[0, 5, 2], [4, 6, 8], [1, 7, 3]];
const FACE_CORNERS = [[0, 4, 5, 6], [4, 1, 6, 7], [5, 6, 2, 8], [6, 7, 8, 3]];

const SUN = norm([0.35, 0.85, 0.4]);

// What the pieces make, as quadblocks in world units (unrounded), with what they came from.
class Emitter {
  constructor(textures) {
    this.textures = textures;     // id -> { terrain }
    this.quads = [];
    this.xf = null;
    this.piece = null;
  }
  // world: the piece's real place (supports reach the ground from it); the quadblocks are
  // made in the piece's place too, unless local (the editor's view moves them as a whole)
  begin(piece, local = false) {
    this.piece = piece;
    const T = transformOf(piece);
    this.world = T;
    this.groundY = GROUND_Y;
    this.stack = local ? [{ point: (p) => p, dir: (d) => d }] : [{ point: T.point, dir: T.dir }];
  }
  get top() { return this.stack[this.stack.length - 1]; }
  // draws fn in a frame of the piece's (fr: p, f, r, u: local -z is f)
  withLocal(fr, fn) {
    const outer = this.top;
    const point = (q) => outer.point(add(add(add(fr.p, scale(fr.r, q[0])), scale(fr.u, q[1])), scale(fr.f, -q[2])));
    const dir = (d) => outer.dir(add(add(scale(fr.r, d[0]), scale(fr.u, d[1])), scale(fr.f, -d[2])));
    this.stack.push({ point, dir });
    try { fn(); } finally { this.stack.pop(); }
  }
  surface(nu, nv, fn, opts) {
    const { point, dir } = this.top;
    const N = 2 * nu, M = 2 * nv;
    const P = [], UV = [];
    for (let i = 0; i <= N; i++) {
      P.push([]); UV.push([]);
      for (let j = 0; j <= M; j++) {
        const s = fn(i / N, j / M);
        P[i].push(point(s.p));
        UV[i].push(s.uv);
      }
    }
    const outOf = typeof opts.out === 'function' ? opts.out : () => opts.out;
    for (let a = 0; a < nu; a++) {
      for (let b = 0; b < nv; b++) {
        const pos = new Array(9), uv = new Array(9);
        for (let i = 0; i < 3; i++) {
          for (let j = 0; j < 3; j++) {
            pos[SLOT[i][j]] = P[2 * a + i][2 * b + j];
            uv[SLOT[i][j]] = UV[2 * a + i][2 * b + j];
          }
        }
        // the side the piece says is the front
        const uc = (2 * a + 1) / N, vc = (2 * b + 1) / M;
        const localOut = outOf(fn(uc, vc).p, uc, vc);
        const want = dir(localOut);
        let n = frontOf(pos);
        if (dot(n, want) < 0) {
          // transposed: u and v swap roles, the front turns over
          const t = [0, 2, 1, 3, 5, 4, 6, 8, 7];
          const p2 = t.map((k) => pos[k]), u2 = t.map((k) => uv[k]);
          pos.splice(0, 9, ...p2); uv.splice(0, 9, ...u2);
          n = frontOf(pos);
        }
        const nl = len(n);
        if (nl < 1e-6) continue;   // collapsed
        this.quads.push({
          pos, uv, n: scale(n, 1 / nl), tex: opts.tex, kind: opts.kind, super: opts.super, double: !!opts.double,
          piece: this.piece, along: opts.along ? opts.along(uc) : null,
        });
      }
    }
  }
}

// the quadblock's front, summed over its four faces: (p2 - p0) x (p1 - p0) per face
function frontOf(pos) {
  let n = [0, 0, 0];
  for (const [c0, c1, c2] of [[0, 4, 5], [4, 1, 6], [5, 6, 2], [6, 7, 8]]) {
    n = add(n, cross(sub(pos[c2], pos[c0]), sub(pos[c1], pos[c0])));
  }
  return n;
}

// a piece as it's built: a sweep laid on the ground needs no slab under it
export function asBuilt(pc) {
  const onGround = pc.kind === 'sweep' && Math.abs(pc.y || 0) < 8 && !(pc.rise > 0) && !(pc.pitch || pc.roll);
  return onGround ? { ...pc, thick: pc.wallL || pc.wallR ? (pc.thick ?? 96) : 0, noBottom: true } : pc;
}

// a piece's quadblocks in its own coordinates (the editor's view moves them as a whole)
export function localQuads(pc) {
  const E = new Emitter({});
  const built = asBuilt(pc);
  E.begin(built, true);
  emitPiece(built, E);
  return E.quads;
}

// ---- the route: the chain of sweeps from the start round back to it ----

function worldSweep(pc) {
  const T = transformOf(pc);
  return {
    at: (s) => {
      const fr = sweepFrame(pc, s);
      return { p: T.point(fr.p), f: T.dir(fr.f), u: T.dir(fr.u) };
    },
    length: sweepLength(pc),
  };
}

export function findRoute(pieces) {
  const start = pieces.find((p) => p.type === 'start');
  if (!start) return null;
  const sweeps = pieces.filter((p) => p.kind === 'sweep');
  const W = new Map(sweeps.map((p) => [p, worldSweep(p)]));
  const seq = [{ piece: start, dir: 1 }];
  let end = W.get(start).at(1);
  const used = new Set([start]);
  let closed = false;
  for (let guard = 0; guard < 2000; guard++) {
    let next = null;
    for (const pc of sweeps) {
      const w = W.get(pc);
      const a = w.at(0), b = w.at(1);
      if (len(sub(a.p, end.p)) < 96 && dot(a.f, end.f) > 0.9) {
        if (pc === start) { closed = true; break; }
        if (!used.has(pc)) { next = { piece: pc, dir: 1, end: b }; break; }
      }
      if (pc !== start && !used.has(pc) && len(sub(b.p, end.p)) < 96 && dot(b.f, end.f) < -0.9) {
        next = { piece: pc, dir: -1, end: { p: a.p, f: scale(a.f, -1) } };
        break;
      }
    }
    if (!closed && !next) {
      // a jump: an entry ahead (up to 10 blocks), near the line the end points along, facing on
      let best = null, bd = Infinity;
      const fh = norm([end.f[0], 0, end.f[2]]);
      for (const pc of sweeps) {
        const w = W.get(pc);
        for (const [s, dir] of [[0, 1], [1, -1]]) {
          if (pc !== start && used.has(pc)) continue;
          if (pc === start && s !== 0) continue;
          const c = w.at(s);
          const cf = dir > 0 ? c.f : scale(c.f, -1);
          const d = sub(c.p, end.p);
          const ahead = d[0] * fh[0] + d[2] * fh[2];
          const side = Math.abs(d[0] * fh[2] - d[2] * fh[0]);
          if (ahead < 256 || ahead > 10 * 1024 || side > 768 + ahead * 0.15 || dot(norm([cf[0], 0, cf[2]]), fh) < 0.7) continue;
          const score = ahead + side * 3;
          if (score < bd) { bd = score; best = { piece: pc, dir, end: dir > 0 ? w.at(1) : { p: w.at(0).p, f: scale(w.at(0).f, -1) } }; }
        }
      }
      if (best && best.piece === start) { closed = true; break; }
      if (best) next = best;
    }
    if (closed || !next) break;
    used.add(next.piece);
    seq.push({ piece: next.piece, dir: next.dir });
    end = next.end;
  }
  // the middle line from the start's line round to it: samples { p, piece, s } and their arc
  const samples = [];
  const push = (pc, s) => samples.push({ p: W.get(pc).at(s).p, f: W.get(pc).at(s).f, piece: pc, s });
  const steps = (pc) => Math.max(4, Math.ceil(W.get(pc).length / 128));
  const ns = steps(start);
  for (let k = Math.ceil(ns / 2); k <= ns; k++) push(start, k / ns);
  for (const { piece, dir } of seq.slice(1)) {
    const n = steps(piece);
    for (let k = 1; k <= n; k++) push(piece, dir > 0 ? k / n : 1 - k / n);
  }
  if (closed) for (let k = 1; k <= Math.floor(ns / 2); k++) push(start, k / ns);
  const arc = [0];
  for (let i = 1; i < samples.length; i++) arc.push(arc[i - 1] + len(sub(samples[i].p, samples[i - 1].p)));
  return { start, seq, closed, samples, arc, length: arc[arc.length - 1], end };
}

// ---- texture layouts ----

function layoutsOf(uv9, rect) {
  const size = rect.size;
  let mu = Infinity, mv = Infinity;
  for (const [u, v] of uv9) { if (u < mu) mu = u; if (v < mv) mv = v; }
  const ou = Math.floor(mu / size) * size, ov = Math.floor(mv / size) * size;
  let mx = 0;
  for (const [u, v] of uv9) mx = Math.max(mx, u - ou, v - ov);
  let shift = 0;
  while (shift < 3 && mx / (1 << shift) > 255) shift++;
  const q = (k) => [
    Math.max(0, Math.min(255, Math.round((uv9[k][0] - ou) / (1 << shift)))),
    Math.max(0, Math.min(255, Math.round((uv9[k][1] - ov) / (1 << shift)))),
  ];
  const lg = Math.log2(size / 32);
  const tpage = (3 << 7) | 16 | lg | (lg << 2);
  const clut = (shift << 14) | (rect.layer << 8) | ((rect.y >> 6) << 4) | (rect.x >> 6);
  return {
    faces: FACE_CORNERS.map((c) => ({ uv: c.map(q), clut, tpage })),
    low: { uv: [0, 1, 2, 3].map(q), clut, tpage },
  };
}

const INVISIBLE = { uv: [[0, 0], [0, 0], [0, 0], [0, 0]], clut: 15 << 10, tpage: 3 << 7 };

// ---- the whole compile ----

// track: { pieces, ground: true|false, name }; atlas: { rects }; textures: [{ id, terrain }]
// test: { p: [x, y, z], yaw } to start from there instead of the start line
export function compileTrack(track, atlas, textures, test = null) {
  const t0 = performance.now();
  const terrainOf = Object.fromEntries(textures.map((t) => [t.id, t.terrain]));
  const E = new Emitter(terrainOf);
  for (const pc of track.pieces) {
    if (!CATALOGUE[pc.type]) continue;
    E.begin(pc);
    emitPiece(asBuilt(pc), E);
  }
  const route = findRoute(track.pieces);

  // checkpoints: a node every NODE_SPACING along a closed route; else free drive's nodes
  let nodes = [];
  let nodeOf = () => 0xff;
  let spawn;
  if (route && route.closed && route.length > 1024) {
    const L = route.length;
    const count = Math.max(8, Math.min(250, Math.round(L / NODE_SPACING)));
    const step = L / count;
    const virt = Math.max(1, 40000 / L);   // a lap counts from 32000 (PlayLevel.c): short tracks stretch
    const at = (a) => {
      let i = 0;
      while (i < route.arc.length - 2 && route.arc[i + 1] < a) i++;
      const f = (a - route.arc[i]) / Math.max(1e-6, route.arc[i + 1] - route.arc[i]);
      return { p: madd(route.samples[i].p, sub(route.samples[i + 1].p, route.samples[i].p), Math.min(1, Math.max(0, f))), i };
    };
    for (let i = 0; i < count; i++) {
      const { p } = at(i * step);
      nodes.push({ p: p.map(Math.round), dist: Math.round(((L - i * step) * virt) / 8), fwd: (i + 1) % count, back: (i - 1 + count) % count });
    }
    // where a piece's s lies along the route
    const pieceArc = new Map();
    route.samples.forEach((smp, i) => {
      if (!pieceArc.has(smp.piece)) pieceArc.set(smp.piece, []);
      pieceArc.get(smp.piece).push([smp.s, route.arc[i]]);
    });
    nodeOf = (q, c) => {
      const list = q.piece && pieceArc.get(q.piece);
      if (list && q.along !== null) {
        let best = list[0], bd = Infinity;
        for (const e of list) { const d = Math.abs(e[0] - q.along); if (d < bd) { bd = d; best = e; } }
        return Math.min(count - 1, Math.floor(best[1] / step));
      }
      // other floors near the route take the node behind the nearest point of it
      let bi = -1, bd = 1500;
      for (let i = 0; i < route.samples.length; i += 2) {
        const p = route.samples[i].p;
        const d = Math.hypot(p[0] - c[0], p[2] - c[2]) + Math.abs(p[1] - c[1]) * 2;
        if (d < bd) { bd = d; bi = i; }
      }
      return bi < 0 ? 0xff : Math.min(count - 1, Math.floor(route.arc[bi] / step));
    };
    // the start: behind the line, facing along
    const fr = worldSweep(route.start).at(Math.max(0, 0.5 - 360 / sweepLength(route.start)));
    spawn = { p: madd(fr.p, fr.u, 40), f: fr.f };
  } else {
    // free drive: nodes over the floors, all the same distance (no laps), each pointing at a
    // twin straight above (tools/track.py free_setup: never "wrong way")
    const seen = new Map();
    for (const q of E.quads) {
      if (q.kind !== 'floor' || q.n[1] < GROUND_NY) continue;
      const c = q.pos[6];
      const key = `${Math.round(c[0] / 2048)},${Math.round(c[2] / 2048)},${Math.round(c[1] / 1024)}`;
      if (!seen.has(key)) seen.set(key, c);
    }
    const picks = [...seen.values()].slice(0, 120);
    if (picks.length === 0) picks.push([0, 0, 0]);
    const n = picks.length;
    picks.forEach((p, i) => nodes.push({ p: p.map(Math.round), dist: 4000, fwd: n + i, back: n + i }));
    picks.forEach((p, i) => nodes.push({ p: [Math.round(p[0]), Math.round(p[1]) + 1000, Math.round(p[2])], dist: 4000, fwd: i, back: i }));
    nodeOf = (q, c) => {
      let bi = 0, bd = Infinity;
      picks.forEach((p, i) => { const d = Math.hypot(p[0] - c[0], p[2] - c[2]) + Math.abs(p[1] - c[1]) * 3; if (d < bd) { bd = d; bi = i; } });
      return bi;
    };
    const s = track.pieces.find((p) => p.type === 'start');
    if (s) {
      const fr = worldSweep(s).at(0.3);
      spawn = { p: madd(fr.p, fr.u, 40), f: fr.f };
    } else {
      spawn = { p: [0, 40, 0], f: [0, 0, -1] };
    }
  }
  if (test) spawn = { p: test.p, f: [-Math.sin(test.yaw), 0, -Math.cos(test.yaw)] };

  // the ground
  const quads = [];
  const groundTex = track.groundTex || 'grass';
  const rect = (id) => atlas.rects[id] || atlas.rects.white;
  const shadeOf = (n, kind) => {
    const k = kind === 'floor' && n[1] > GROUND_NY ? 0.92 + 0.08 * Math.max(0, dot(n, SUN)) : 0.55 + 0.45 * Math.max(0, dot(n, SUN));
    return Math.max(24, Math.min(255, Math.round(128 * k)));
  };
  if (track.ground !== false) {
    const r = rect(groundTex);
    const c = shadeOf([0, 1, 0], 'floor');
    const cells = [];
    const G = 1024, n = (2 * FIELD) / G;
    for (let a = 0; a < n; a++) for (let b = 0; b < n; b++) cells.push([-FIELD + a * G, -FIELD + b * G, G]);
    // past the field, a ring of bigger squares towards the horizon: as far as the window's
    // 16-bit positions go (the engine puts the 3 x 3 tiles together round the middle one's)
    const H = 4096, OUT = FIELD + H;
    for (let x0 = -OUT; x0 < OUT; x0 += H) {
      for (let z0 = -OUT; z0 < OUT; z0 += H) {
        if (x0 >= -FIELD && x0 + H <= FIELD && z0 >= -FIELD && z0 + H <= FIELD) continue;
        cells.push([x0, z0, H]);
      }
    }
    for (const [x0, z0, G] of cells) {
      {
        const pos = new Array(9), uv = new Array(9);
        for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
          // u along x, v along z: the front, (v) x (u), faces up
          const x = x0 + (i * G) / 2, z = z0 + (j * G) / 2;
          pos[SLOT[i][j]] = [x, GROUND_Y, z];
          uv[SLOT[i][j]] = [(x + FIELD) / 4, (z + FIELD) / 4];
        }
        const L = layoutsOf(uv, r);
        quads.push({ pos, faces: L.faces, low: L.low, color: new Array(9).fill([c, c, c]), flags: FLAG_GROUND | FLAG_CAMERA_SEARCH,
          terrain: terrainOf[groundTex] ?? 2, checkpoint: 0xff, kindTag: 'ground', world: true });
      }
    }
  }
  // the pieces' quadblocks
  let minY = 0;
  for (const q of E.quads) {
    const r = rect(q.tex);
    const L = layoutsOf(q.uv, r);
    let flags = 0, terrain = terrainOf[q.tex] ?? 0;
    if (q.kind === 'floor') flags = q.n[1] > GROUND_NY ? FLAG_GROUND | FLAG_CAMERA_SEARCH : FLAG_COLLISION_SURFACE;
    else if (q.kind === 'wall') flags = FLAG_COLLISION_SURFACE;
    else if (q.kind === 'boost') { flags = FLAG_SKIP_WATER_LIST | FLAG_COLLISION_SURFACE | FLAG_TRIGGER; terrain = q.super ? 2 : 1; }
    const c = shadeOf(q.n, q.kind);
    const centre = q.pos[6];
    const cp = flags & FLAG_GROUND ? nodeOf(q, centre) : 0xff;
    for (const p of q.pos) minY = Math.min(minY, p[1]);
    quads.push({ pos: q.pos, faces: L.faces, low: L.low, color: new Array(9).fill([c, c, c]), flags, terrain, checkpoint: cp,
      doubleSided: q.double, src: q });
  }
  // round to whole units, by tile (each in coordinates from its centre)
  const tiles = new Map();
  for (const q of quads) {
    const c = q.pos[6];
    const i = Math.max(-1, Math.min(1, Math.floor((c[0] + TILE / 2) / TILE)));
    const j = Math.max(-1, Math.min(1, Math.floor((c[2] + TILE / 2) / TILE)));
    const key = `${i},${j}`;
    if (!tiles.has(key)) tiles.set(key, { i, j, quads: [] });
    const ox = i * TILE, oz = j * TILE;
    tiles.get(key).quads.push({ ...q, pos: q.pos.map((p) => [Math.round(p[0] - ox), Math.round(p[1]), Math.round(p[2] - oz)]) });
  }
  // a kill plane under every tile (a kart that falls off is put back)
  const killY = Math.min(KILL_Y, Math.round(minY) - 1600);
  for (let i = -1; i <= 1; i++) {
    for (let j = -1; j <= 1; j++) {
      const key = `${i},${j}`;
      if (!tiles.has(key)) tiles.set(key, { i, j, quads: [] });
      const half = TILE / 2, step = 4096;
      for (let x = -half; x < half; x += step) {
        for (let z = -half; z < half; z += step) {
          const pos = new Array(9);
          for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) pos[SLOT[a][b]] = [x + (a * step) / 2, killY, z + (b * step) / 2];
          tiles.get(key).quads.push({ pos, faces: [INVISIBLE, INVISIBLE, INVISIBLE, INVISIBLE], low: INVISIBLE, color: null,
            flags: FLAG_COLLISION_SURFACE | FLAG_KILL_PLANE, terrain: 0, checkpoint: 0xff });
        }
      }
    }
  }
  const files = {};
  const sizes = [];
  let total = 0;
  for (const t of tiles.values()) {
    const out = writeTile(t.quads);
    files[`T_${t.i}_${t.j}.lev`] = out.data;
    sizes.push([t.i, t.j, out.data.length]);
    total += out.quads;
  }
  sizes.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  const index = new Uint8Array(12 + 8 * sizes.length);
  const iv = new DataView(index.buffer);
  index.set([0x57, 0x52, 0x4c, 0x44]);   // WRLD
  iv.setInt32(4, TILE, true);
  iv.setInt32(8, sizes.length, true);
  sizes.forEach(([i, j, n], k) => { iv.setInt16(12 + 8 * k, i, true); iv.setInt16(14 + 8 * k, j, true); iv.setUint32(16 + 8 * k, n, true); });
  files['index.bin'] = index;
  files['map.bin'] = minimap(quads, route);
  files['route.bin'] = routeFile(nodes, spawn);
  return { files, quads: total, nodes: nodes.length, route, spawn, ms: performance.now() - t0, preview: E.quads };
}

function routeFile(nodes, spawn) {
  const out = new Uint8Array(16 + 12 * nodes.length);
  const v = new DataView(out.buffer);
  out.set([0x57, 0x52, 0x54, 0x45]);   // WRTE
  v.setInt32(4, nodes.length, true);
  const f = spawn.f;
  // the kart's heading: race_setup's (yaw of the forward, less a quarter turn)
  const yaw = Math.round((Math.atan2(f[0], f[2]) / (2 * Math.PI)) * 4096);
  const rot = (((yaw - 0x400) % 4096) + 4096) % 4096;
  v.setInt16(8, Math.round(spawn.p[0]), true);
  v.setInt16(10, Math.round(spawn.p[1]), true);
  v.setInt16(12, Math.round(spawn.p[2]), true);
  v.setInt16(14, rot, true);
  nodes.forEach((n, i) => {
    const o = 16 + 12 * i;
    v.setInt16(o, n.p[0], true); v.setInt16(o + 2, n.p[1], true); v.setInt16(o + 4, n.p[2], true);
    v.setUint16(o + 6, Math.max(0, Math.min(65535, n.dist)), true);
    v.setUint8(o + 8, n.fwd); v.setUint8(o + 9, 0xff); v.setUint8(o + 10, n.back); v.setUint8(o + 11, 0xff);
  });
  return out;
}

// the minimap (map.bin, native_world.c): the route's roads in the floor shade, other floors as
// edges, the rest clear; MAP_UNIT units a texel over the field
function minimap(quads, route) {
  const n = (2 * FIELD) / MAP_UNIT;
  const grid = new Uint8Array(n * n);
  const onRoute = route && route.closed ? new Set(route.samples.map((s) => s.piece)) : null;
  for (const q of quads) {
    if (!(q.flags & FLAG_GROUND) || q.kindTag === 'ground') continue;
    const value = onRoute && q.src && onRoute.has(q.src.piece) ? 3 : 2;
    for (const k of [0, 1, 2, 3, 4, 5, 6, 7, 8]) {
      const p = q.pos[k];
      const x = Math.floor((p[0] + FIELD) / MAP_UNIT), z = Math.floor((p[2] + FIELD) / MAP_UNIT);
      if (x >= 0 && z >= 0 && x < n && z < n && grid[z * n + x] < value) grid[z * n + x] = value;
    }
  }
  const out = new Uint8Array(24 + n * n);
  const v = new DataView(out.buffer);
  out.set([0x57, 0x4d, 0x41, 0x50]);   // WMAP
  v.setInt32(4, MAP_UNIT, true);
  v.setInt32(8, -FIELD, true);
  v.setInt32(12, -FIELD, true);
  v.setInt32(16, n, true);
  v.setInt32(20, n, true);
  out.set(grid, 24);
  return out;
}

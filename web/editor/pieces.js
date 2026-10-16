// The editor's pieces: what each makes (surfaces, in the piece's own coordinates: entry at the
// origin, forward -z, right +x, up +y; CTR units) and, for the ones you drive along, the line
// through their middle (the route the laps follow, and where the next piece snaps on).
//
// A piece in a track: { id, type, x, y, z, yaw, pitch, roll, ...its params }.
// The surfaces go to an emitter (compile.js): E.surface(nu, nv, fn, opts), fn(u, v) -> { p, uv }
// over u, v in 0..1 (nu x nv quadblocks), opts { tex, kind: 'floor' | 'wall' | 'deco' | 'boost',
// out: the side that's the front (a vector, or a function of the point), double }.

import { add, sub, scale, cross, norm, madd, lerp, DEG, dot } from './geom.js';

export const BLOCK = 1024;      // the grid: a road's width, a block
export const LEVEL = 256;       // a height step
const QB = 512;                 // a quadblock's side at most (its four faces 256)
const TEXEL = 4;                // units a texel, for textures laid by size (not stretched)

// textures stretched across a road's width (their lines on the edges); the rest are laid 4 units
// a texel
export const SPANNED = new Set(['road', 'road-red', 'road-blue', 'kerb', 'rainbow']);

const smooth = (s) => s * s * (3 - 2 * s);
const PROFILES = {
  flat: () => 0,
  smooth: (s) => smooth(s),
  linear: (s) => s,
  kicker: (s) => s * s,                 // flat in, steep out: a jump
  easeOut: (s) => 1 - (1 - s) * (1 - s),  // steep in, flat out: a landing
  hump: (s) => Math.sin(Math.PI * s) ** 2,        // up and back down (rise is its height)
  bumps: (s) => Math.sin(2 * Math.PI * s) ** 2,   // two of them
};
const dProfile = (name, s) => {
  const h = 1e-4;
  const f = PROFILES[name] || PROFILES.smooth;
  return (f(Math.min(1, s + h)) - f(Math.max(0, s - h))) / (Math.min(1, s + h) - Math.max(0, s - h));
};
const BANKS = {
  none: () => 0,
  const: (s) => 1,
  in: (s) => smooth(s),
  out: (s) => 1 - smooth(s),
  arc: (s) => Math.sin(Math.PI * s) ** 2,      // in and back out, easing at both ends
  hold: (s) => smooth(Math.min(1, s / 0.3)) * smooth(Math.min(1, (1 - s) / 0.3)),   // in, held, out
};
const bankOf = (pc, s) => (pc.bank || 0) * (BANKS[pc.bankMode || 'const'] || BANKS.const)(s) * DEG;
// a bank turns the road about its low edge (the outside of the turn rises, the inside stays where
// it was, on whatever it's laid on): the middle line goes up half the width's rise. The ends'
// connectors stay on the unbanked line (`base`), so pieces still meet
const bankLift = (pc, bank) => (pc.width || BLOCK) / 2 * Math.abs(Math.sin(bank));

// ---- sweeps: roads, curves, slopes, banks, half pipes, kickers ----

// The middle line of a sweep at s (0..1): position, forward (with the slope), right (level)
// and up, before the bank. Curves turn left for a positive angle.
// a bridge's line: a cubic from the origin, leaving forward (its fromPitch up), to `to`,
// arriving along (toYaw, toPitch); the handles as long as the gap times its tension
function bezierAt(pc, s) {
  const P1 = pc.to || [0, 0, -BLOCK];
  const k = Math.hypot(P1[0], P1[1], P1[2]) * (pc.tension ?? 1);
  const fp = (pc.fromPitch || 0) * DEG, ty = (pc.toYaw || 0) * DEG, tp = (pc.toPitch || 0) * DEG;
  const t0 = [0, Math.sin(fp) * k, -Math.cos(fp) * k];
  const t1 = [-Math.sin(ty) * Math.cos(tp) * k, Math.sin(tp) * k, -Math.cos(ty) * Math.cos(tp) * k];
  const s2 = s * s, s3 = s2 * s;
  const h10 = s3 - 2 * s2 + s, h01 = -2 * s3 + 3 * s2, h11 = s3 - s2;
  const d10 = 3 * s2 - 4 * s + 1, d01 = -6 * s2 + 6 * s, d11 = 3 * s2 - 2 * s;
  const p = [0, 1, 2].map((i) => h10 * t0[i] + h01 * P1[i] + h11 * t1[i]);
  const d = [0, 1, 2].map((i) => d10 * t0[i] + d01 * P1[i] + d11 * t1[i]);
  return { p, d };
}

export function sweepFrame(pc, s) {
  if (pc.path === 'bezier') {
    const { p, d } = bezierAt(pc, s);
    const f = norm(d);
    const h = Math.hypot(f[0], f[2]) > 1e-6 ? norm([-f[2], 0, f[0]]) : [1, 0, 0];
    const up = norm(cross(h, f));
    const bank = bankOf(pc, s);
    const rb = norm(add(scale(h, Math.cos(bank)), scale(up, Math.sin(bank))));
    return { p: madd(p, up, bankLift(pc, bank)), base: p, f, r: rb, u: norm(cross(rb, f)), along: sweepLength(pc) };
  }
  const angle = (pc.angle || 0) * DEG;
  const rise = pc.rise || 0;
  const prof = PROFILES[pc.profile || 'smooth'] || PROFILES.smooth;
  let x, z, fx, fz, along;
  if (Math.abs(angle) < 1e-6) {
    const L = pc.length || BLOCK;
    x = 0; z = -L * s; fx = 0; fz = -1; along = L;
  } else {
    const R = pc.radius || BLOCK;
    const sg = Math.sign(angle), th = Math.abs(angle) * s;
    x = -sg * R * (1 - Math.cos(th));
    z = -R * Math.sin(th);
    fx = -sg * Math.sin(th);
    fz = -Math.cos(th);
    along = R * Math.abs(angle);
  }
  const y = rise * prof(s);
  const dy = rise * dProfile(pc.profile || 'smooth', s) / along;
  const f = norm([fx, dy, fz]);
  const right = norm([-fz, 0, fx]);
  const up = norm(cross(right, f));
  const bank = bankOf(pc, s);
  const rb = norm(add(scale(right, Math.cos(bank)), scale(up, Math.sin(bank))));
  const ub = norm(cross(rb, f));
  return { p: madd([x, y, z], up, bankLift(pc, bank)), base: [x, y, z], f, r: rb, u: ub, along };
}

export function sweepLength(pc) {
  if (pc.path === 'bezier') {
    let L = 0, prev = bezierAt(pc, 0).p;
    for (let i = 1; i <= 48; i++) {
      const cur = bezierAt(pc, i / 48).p;
      L += Math.hypot(cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2]);
      prev = cur;
    }
    return L;
  }
  const angle = (pc.angle || 0) * DEG;
  const flat = Math.abs(angle) < 1e-6 ? (pc.length || BLOCK) : (pc.radius || BLOCK) * Math.abs(angle);
  return Math.hypot(flat, pc.rise || 0);
}

// the cross section at t (-1 left .. 1 right): offsets along the banked right and up
function section(pc, t) {
  const W = (pc.width || BLOCK) / 2;
  const shape = pc.shape || 'flat';
  if (shape === 'flat') return [t * W, 0];
  // a half pipe (both sides) or a quarter pipe on one side: flat to `flatPart`, then a quarter
  // circle up of the rest's width
  const flatPart = pc.flatPart ?? 0.5;
  const side = shape === 'pipe' || (shape === 'pipeL' && t < 0) || (shape === 'pipeR' && t > 0);
  const a = Math.abs(t);
  if (!side || a <= flatPart) return [t * W, 0];
  const R = (1 - flatPart) * W;
  const k = (a - flatPart) / (1 - flatPart);       // 0..1 round the quarter
  const phi = k * (pc.pipeAngle ?? 80) * DEG;
  return [Math.sign(t) * (flatPart * W + R * Math.sin(phi)), R * (1 - Math.cos(phi))];
}

function sectionLen(pc) {
  // the cross section's length (for texture spans and quadblock counts)
  let L = 0, prev = section(pc, -1);
  for (let i = 1; i <= 32; i++) {
    const cur = section(pc, -1 + i / 16);
    L += Math.hypot(cur[0] - prev[0], cur[1] - prev[1]);
    prev = cur;
  }
  return L;
}

function emitSweep(pc, E) {
  const W = pc.width || BLOCK;
  const L = sweepLength(pc);
  // the longer edge (a curve's outer one) sets how many quadblocks along
  let outer = L;
  for (const side of [-1, 1]) {
    let e = 0, prev = null;
    for (let i = 0; i <= 32; i++) {
      const fr = sweepFrame(pc, i / 32);
      const q = add(fr.p, scale(fr.r, side * W / 2));
      if (prev) e += Math.hypot(q[0] - prev[0], q[1] - prev[1], q[2] - prev[2]);
      prev = q;
    }
    outer = Math.max(outer, e);
  }
  const nu = Math.max(1, Math.ceil(outer / QB));
  const sl = sectionLen(pc);
  const nv = Math.max(1, Math.ceil(sl / QB));
  const tex = pc.tex || 'road';
  const spanned = SPANNED.has(tex);
  // arc length along the middle, for the texture along the road
  const arc = [0];
  const N = 4 * nu;
  for (let i = 1; i <= N; i++) {
    const a = sweepFrame(pc, (i - 1) / N).p, b = sweepFrame(pc, i / N).p;
    arc.push(arc[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
  }
  const arcAt = (s) => {
    const x = s * N, i = Math.min(N - 1, Math.floor(x));
    return arc[i] + (arc[i + 1] - arc[i]) * (x - i);
  };
  const at = (s, t) => {
    const fr = sweepFrame(pc, s);
    const [dx, dy] = section(pc, t);
    return add(add(fr.p, scale(fr.r, dx)), scale(fr.u, dy));
  };
  const texSize = 256;
  const vScale = spanned ? texSize / W : 1 / TEXEL;
  // the road's top (u along, v across: front faces up)
  E.surface(nu, nv, (u, v) => {
    const t = -1 + 2 * v;
    const [dx] = section(pc, t);
    return {
      p: at(u, t),
      uv: [spanned ? v * texSize : (dx + W / 2) / TEXEL, arcAt(u) * vScale],
    };
  }, { tex, kind: 'floor', out: (p, u, v) => sweepFrame(pc, u).u, piece: pc, along: (u) => u });

  // walls along the edges (kerbs, barriers): inner face, top, outer face
  const wallTex = pc.wallTex || 'kerb';
  const thick = pc.thick ?? 96;
  for (const side of [-1, 1]) {
    const h = side < 0 ? (pc.wallL || 0) : (pc.wallR || 0);
    const edge = (s) => at(s, side);
    const upAt = (s) => {
      // up along the wall: the section's tangent at the edge turned up, or the bank's up
      const fr = sweepFrame(pc, s);
      return fr.u;
    };
    const outAt = (s) => scale(sweepFrame(pc, s).r, side);
    const nvW = Math.max(1, Math.ceil(Math.max(h, 1) / QB));
    if (h > 0) {
      const wt = 48;
      // inner face
      E.surface(nu, nvW, (u, v) => ({
        p: madd(edge(u), upAt(u), v * h),
        uv: [arcAt(u) / TEXEL, v * h / TEXEL],
      }), { tex: wallTex, kind: 'wall', out: (p, u) => scale(outAt(u), -1) });
      // top
      E.surface(nu, 1, (u, v) => ({
        p: madd(madd(edge(u), upAt(u), h), outAt(u), v * wt),
        uv: [arcAt(u) / TEXEL, v * wt / TEXEL],
      }), { tex: wallTex, kind: 'wall', out: (p, u) => upAt(u) });
      // outer face, down to the slab's bottom
      E.surface(nu, nvW, (u, v) => ({
        p: madd(madd(edge(u), outAt(u), wt), upAt(u), h - v * (h + thick)),
        uv: [arcAt(u) / TEXEL, v * (h + thick) / TEXEL],
      }), { tex: wallTex, kind: 'wall', out: (p, u) => outAt(u) });
    } else if (thick > 0) {
      // the slab's side
      E.surface(nu, 1, (u, v) => ({
        p: madd(edge(u), upAt(u), -v * thick),
        uv: [arcAt(u) / TEXEL, v * thick / TEXEL],
      }), { tex: pc.sideTex || 'concrete', kind: 'wall', out: (p, u) => outAt(u) });
    }
  }
  // the underside, when it's off the ground
  if (thick > 0 && !pc.noBottom) {
    E.surface(nu, nv, (u, v) => {
      const t = -1 + 2 * v;
      const fr = sweepFrame(pc, u);
      return { p: madd(at(u, t), fr.u, -thick), uv: [(t + 1) * W / 2 / TEXEL, arcAt(u) / TEXEL] };
    }, { tex: pc.sideTex || 'concrete', kind: 'wall', out: (p, u) => scale(sweepFrame(pc, u).u, -1), underside: true });
  }
  // pillars down to the ground under a raised road (the piece's place, E.world, says how far)
  if (pc.supports !== false && E.world && E.ground !== false) emitSupports(pc, E, at, thick);
  // a start line: a checker band across the road at the middle
  if (pc.type === 'start') {
    const s0 = 0.5 - 96 / L, s1 = 0.5 + 96 / L;
    E.surface(1, nv, (u, v) => {
      const s = s0 + (s1 - s0) * u, t = -1 + 2 * v;
      const fr = sweepFrame(pc, s);
      return { p: madd(at(s, t), fr.u, 3), uv: [v * W / TEXEL, u * 192 / TEXEL] };
    }, { tex: 'checker', kind: 'deco', out: (p, u) => sweepFrame(pc, s0 + (s1 - s0) * u).u });
  }
  // boost pads: across the middle of the road, over its first half (a trigger, as the game's)
  if (pc.boost) {
    const bw = Math.min(W * 0.5, 512) / W, s0 = 0.25, s1 = Math.min(0.75, 0.25 + 768 / L);
    E.surface(1, 1, (u, v) => {
      const s = s0 + (s1 - s0) * u, t = (-1 + 2 * v) * bw;
      const fr = sweepFrame(pc, s);
      return { p: madd(at(s, t), fr.u, 4), uv: [v * 256, u * 256] };
    }, { tex: 'boost', kind: 'boost', out: (p, u) => sweepFrame(pc, s0 + (s1 - s0) * u).u, super: pc.boost === 'super' });
  }
}

// pillars every couple of blocks under a sweep that's off the ground: from its underside straight
// down (in the world) to the ground, drawn in the piece's own coordinates
function emitSupports(pc, E, at, thick) {
  const W = E.world;
  const L = sweepLength(pc);
  const n = Math.max(1, Math.round(L / (2.5 * BLOCK)));
  const r = Math.min(160, (pc.width || BLOCK) * 0.09);
  for (let k = 0; k < n; k++) {
    const s = (k + 0.5) / n;
    const fr = sweepFrame(pc, s);
    const top = madd(fr.p, fr.u, -thick);
    const wtop = W.point(top);
    const h = wtop[1] - E.groundY;
    if (h < 300) continue;
    // straight down in the world, in the piece's terms
    const down = W.invDir([0, -h, 0]);
    const seg = 8;
    E.surface(seg, Math.max(1, Math.ceil(h / 1024)), (u, v) => {
      const a = u * 2 * Math.PI;
      const ring = W.invDir([Math.cos(a) * r, 0, -Math.sin(a) * r]);
      return { p: add(add(top, ring), scale(down, v)), uv: [u * 2 * Math.PI * r / TEXEL, v * h / TEXEL] };
    }, { tex: pc.supportTex || 'concrete', kind: 'wall', out: (p, u) => W.invDir([Math.cos(u * 2 * Math.PI), 0, -Math.sin(u * 2 * Math.PI)]) });
  }
}

// ---- boxes, ramps, pipes, decorations ----

// a box from its corners' function: faces with outward fronts
function emitBox(E, corner, size, texTop, texSide, kindTop, kindSide, opts = {}) {
  const [sx, sy, sz] = size;
  const P = (x, y, z) => corner(x, y, z);
  const n = (a) => Math.max(1, Math.ceil(a / QB));
  if (opts.sidesOnly) {
    E.surface(n(sx), 1, (u, v) => ({ p: P(u, 1, v), uv: [u * sx / TEXEL, v * sz / TEXEL] }), { tex: texTop, kind: kindTop, out: [0, 1, 0], frame: true });
    E.surface(n(sx), 1, (u, v) => ({ p: P(u, 0, v), uv: [u * sx / TEXEL, v * sz / TEXEL] }), { tex: texSide, kind: kindSide, out: [0, -1, 0], frame: true });
    E.surface(1, n(sy), (u, v) => ({ p: P(0, v, u), uv: [u * sz / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [-1, 0, 0], frame: true });
    E.surface(1, n(sy), (u, v) => ({ p: P(1, v, u), uv: [u * sz / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [1, 0, 0], frame: true });
    return;
  }
  // top (y = 1)
  if (!opts.noTop) E.surface(n(sx), n(sz), (u, v) => ({ p: P(u, 1, v), uv: [u * sx / TEXEL, v * sz / TEXEL] }), { tex: texTop, kind: kindTop, out: [0, 1, 0], frame: true });
  if (!opts.noBottom) E.surface(n(sx), n(sz), (u, v) => ({ p: P(u, 0, v), uv: [u * sx / TEXEL, v * sz / TEXEL] }), { tex: texSide, kind: kindSide, out: [0, -1, 0], frame: true });
  E.surface(n(sx), n(sy), (u, v) => ({ p: P(u, v, 0), uv: [u * sx / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [0, 0, -1], frame: true });
  E.surface(n(sx), n(sy), (u, v) => ({ p: P(u, v, 1), uv: [u * sx / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [0, 0, 1], frame: true });
  E.surface(n(sz), n(sy), (u, v) => ({ p: P(0, v, u), uv: [u * sz / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [-1, 0, 0], frame: true });
  E.surface(n(sz), n(sy), (u, v) => ({ p: P(1, v, u), uv: [u * sz / TEXEL, v * sy / TEXEL] }), { tex: texSide, kind: kindSide, out: [1, 0, 0], frame: true });
}

function emitPlatform(pc, E) {
  const w = pc.width || BLOCK, d = pc.length || BLOCK, h = pc.height ?? 128;
  // the top at y = 0, entry edge at z = 0, going forward (-z)
  emitBox(E, (x, y, z) => [(x - 0.5) * w, (y - 1) * h, -z * d], [w, h, d], pc.tex || 'concrete', pc.sideTex || 'concrete', 'floor', 'wall');
}

// a wedge: a ramp up from the ground to `rise` over its length, solid under
function emitWedge(pc, E) {
  const w = pc.width || BLOCK, d = pc.length || BLOCK, h = pc.rise ?? LEVEL;
  const nx = Math.max(1, Math.ceil(w / QB)), nz = Math.max(1, Math.ceil(Math.hypot(d, h) / QB));
  const top = (u, v) => [(u - 0.5) * w, v * h, -v * d];
  E.surface(nx, nz, (u, v) => ({ p: top(u, v), uv: [u * w / TEXEL, v * Math.hypot(d, h) / TEXEL] }), { tex: pc.tex || 'road-plain', kind: 'floor', out: [0, 1, 0] });
  // sides (triangles as quads with a collapsed edge) and the back
  for (const side of [0, 1]) {
    E.surface(nz, 1, (u, v) => ({ p: [(side - 0.5) * w, u * h * (1 - v), -u * d], uv: [u * d / TEXEL, (1 - v) * u * h / TEXEL] }), { tex: pc.sideTex || 'concrete', kind: 'wall', out: [side ? 1 : -1, 0, 0] });
  }
  E.surface(nx, Math.max(1, Math.ceil(h / QB)), (u, v) => ({ p: [(u - 0.5) * w, v * h, -d], uv: [u * w / TEXEL, v * h / TEXEL] }), { tex: pc.sideTex || 'concrete', kind: 'wall', out: [0, 0, -1] });
}

// a quarter pipe: flat in, then a quarter circle up (radius), across its width
function emitQuarter(pc, E) {
  const w = pc.width || BLOCK, R = pc.radius ?? BLOCK, flat = pc.length ?? 0;
  const phiMax = (pc.pipeAngle ?? 85) * DEG;
  const arcLen = R * phiMax;
  const nx = Math.max(1, Math.ceil(w / QB)), nz = Math.max(1, Math.ceil((arcLen + flat) / QB) * 2);
  const total = flat + arcLen;
  const at = (u, v) => {
    const d = v * total;
    if (d <= flat) return [(u - 0.5) * w, 0, -d];
    const phi = (d - flat) / R;
    return [(u - 0.5) * w, R * (1 - Math.cos(phi)), -flat - R * Math.sin(phi)];
  };
  E.surface(nx, nz, (u, v) => ({ p: at(u, v), uv: [u * w / TEXEL, v * total / TEXEL] }), {
    tex: pc.tex || 'concrete', kind: 'floor',
    out: (p) => { const d = Math.max(0, -p[2] - flat); const phi = Math.min(phiMax, d / R); return [0, Math.cos(phi), Math.sin(phi)]; },
  });
  // the back, and the sides
  const top = at(0, 1)[1];
  const back = -flat - R * Math.sin(phiMax);
  E.surface(nx, Math.max(1, Math.ceil(top / QB)), (u, v) => ({ p: [(u - 0.5) * w, v * top, back - 32], uv: [u * w / TEXEL, v * top / TEXEL] }), { tex: pc.sideTex || 'concrete', kind: 'wall', out: [0, 0, -1] });
  for (const side of [0, 1]) {
    E.surface(nz, 1, (u, v) => { const p = at(side, u); return { p: [p[0], p[1] * (1 - v), Math.min(p[2], back) ], uv: [u * total / TEXEL, (1 - v) * p[1] / TEXEL] }; }, { tex: pc.sideTex || 'concrete', kind: 'wall', out: [side ? 1 : -1, 0, 0] });
  }
}

// terrain: a hill over a width x length footprint, its middle at the origin: round (a
// smooth mound), ridge (long, round across), mesa (a flat top, slopes round the edge), peak (a
// mountain: steeper towards its top)
function emitHill(pc, E) {
  const w = pc.width || 4 * BLOCK, d = pc.length || 4 * BLOCK, h = pc.height ?? 2 * LEVEL;
  const shape = pc.shape || 'round';
  const nu = Math.max(1, Math.ceil(w / QB)), nv = Math.max(1, Math.ceil(d / QB));
  const bump = (u, v) => {
    const x = 2 * u - 1, z = 2 * v - 1;
    if (shape === 'ridge') return Math.pow(Math.cos(x * Math.PI / 2), 2);
    if (shape === 'mesa') {
      const r = Math.max(Math.abs(x), Math.abs(z));
      const k = Math.min(1, Math.max(0, (1 - r) / (pc.slope ?? 0.35)));
      return k * k * (3 - 2 * k);
    }
    const r = Math.min(1, Math.hypot(x, z));
    if (shape === 'peak') return peakAt(r);
    return Math.pow(Math.cos(r * Math.PI / 2), 2);
  };
  const at = (u, v) => ({ p: [(u - 0.5) * w, h * bump(u, v), (v - 0.5) * d], uv: [u * w / TEXEL, v * d / TEXEL] });
  if (!pc.capTex) {
    E.surface(nu, nv, at, { tex: pc.tex || 'grass', kind: 'floor', out: [0, 1, 0] });
    return;
  }
  // a snow cap: the quadblocks above the snow line in its texture
  const line = pc.capAt ?? 0.6;
  for (let a = 0; a < nu; a++) {
    for (let b = 0; b < nv; b++) {
      const top = bump((a + 0.5) / nu, (b + 0.5) / nv) > line;
      E.surface(1, 1, (u, v) => at((a + u) / nu, (b + v) / nv), { tex: top ? pc.capTex : pc.tex || 'grass', kind: 'floor', out: [0, 1, 0] });
    }
  }
}

// a mountain's height (0..1) at r (0 the top, 1 the foot): concave, a rounded tip
export const peakAt = (r) => Math.pow(1 - r, 1.6) * (1 - 0.15 * Math.exp(-r * r * 60));

// a cylinder (pillar, post), base at the origin
function emitCylinder(pc, E) {
  const r = pc.radius ?? 128, h = pc.height ?? 1024, seg = Math.max(8, Math.round(r / 32));
  const tex = pc.tex || 'concrete';
  E.surface(seg, Math.max(1, Math.ceil(h / QB)), (u, v) => {
    const a = u * 2 * Math.PI;
    return { p: [Math.cos(a) * r, v * h, -Math.sin(a) * r], uv: [u * 2 * Math.PI * r / TEXEL, v * h / TEXEL] };
  }, { tex, kind: pc.solid === false ? 'deco' : 'wall', out: (p) => norm([p[0], 0, p[2]]) });
  E.surface(seg, 1, (u, v) => {
    const a = u * 2 * Math.PI;
    return { p: [Math.cos(a) * r * (1 - v), h, -Math.sin(a) * r * (1 - v)], uv: [128 + Math.cos(a) * r * (1 - v) / TEXEL, 128 + Math.sin(a) * r * (1 - v) / TEXEL] };
  }, { tex, kind: pc.solid === false ? 'deco' : 'floor', out: [0, 1, 0] });
}

// a gate over the road: two posts and a banner (the start's checker, a checkpoint's colour)
function emitGate(pc, E, banner) {
  const w = (pc.width || BLOCK) + 128, h = pc.height ?? 640, post = 48;
  for (const side of [-1, 1]) {
    emitBox(E, (x, y, z) => [side * w / 2 + (x - 0.5) * post * 2, y * h, (z - 0.5) * post * 2], [post * 2, h, post * 2], 'white', pc.postTex || 'black', 'wall', 'wall', { noBottom: true });
  }
  const bh = 160;
  emitBox(E, (x, y, z) => [(x - 0.5) * (w + post * 2), h - bh + y * bh, (z - 0.5) * 48], [w + post * 2, bh, 48], banner, banner, 'deco', 'deco');
}

// a sign: a board on two posts, its face the sign's text (pc.signTex: a slot of the atlas the
// track's signs are drawn in, compile.signSlotsOf)
function emitSign(pc, E) {
  const w = pc.width || BLOCK, h = pc.height ?? w / 2, lift = pc.lift ?? 384, d = 48;
  for (const side of [-1, 1]) {
    emitBox(E, (x, y, z) => [side * (w / 2 - 40) + (x - 0.5) * 48, y * (lift + h), (z - 0.5) * 48], [48, lift + h, 48], 'black', 'black', 'wall', 'wall', { noBottom: true });
  }
  const tex = pc.signTex || 'white';
  // the face (towards -z, the way the sign faces) and the back
  // (read from in front: its left is the piece's +x on the face, -x on the back)
  E.surface(1, 1, (u, v) => ({ p: [(0.5 - u) * w, lift + v * h, -d / 2], uv: [u * 256, (1 - v) * 256] }), { tex, kind: 'wall', out: [0, 0, -1] });
  E.surface(1, 1, (u, v) => ({ p: [(u - 0.5) * w, lift + v * h, d / 2], uv: [u * 256, (1 - v) * 256] }), { tex: pc.twoSided === false ? 'black' : tex, kind: 'wall', out: [0, 0, 1] });
  emitBox(E, (x, y, z) => [(x - 0.5) * w, lift + y * h, (z - 0.5) * d], [w, h, d], 'black', 'black', 'wall', 'wall', { noTop: false, sidesOnly: true });
}

function emitTree(pc, E) {
  const h = pc.height ?? 1024, r = pc.radius ?? 384;
  emitCylinder({ radius: 48, height: h * 0.45, tex: 'wood' }, E);
  // the crown: a cone
  const seg = 12;
  E.surface(seg, 2, (u, v) => {
    const a = u * 2 * Math.PI, rr = r * (1 - v);
    return { p: [Math.cos(a) * rr, h * 0.3 + v * h * 0.7, -Math.sin(a) * rr], uv: [u * 2 * Math.PI * r / TEXEL, v * h / TEXEL] };
  }, { tex: pc.tex || 'green', kind: 'deco', out: (p) => norm([p[0], r * 0.6, p[2]]) });
  E.surface(seg, 1, (u, v) => {
    const a = u * 2 * Math.PI, rr = r * (1 - v);
    return { p: [Math.cos(a) * rr, h * 0.3, -Math.sin(a) * rr], uv: [u * 64, v * 64] };
  }, { tex: pc.tex || 'green', kind: 'deco', out: [0, -1, 0] });
}

// ---- the catalogue ----
// group (the toolbar's), label, type defaults; sweeps have a middle line (connectors)

const road = (extra) => ({ kind: 'sweep', width: BLOCK, length: BLOCK, tex: 'road', wallL: 0, wallR: 0, wallTex: 'kerb', thick: 96, ...extra });

export const CATALOGUE = {
  straight: { group: 'Road', label: 'Straight', ...road({}) },
  straight2: { group: 'Road', label: 'Long straight', ...road({ length: 4 * BLOCK }) },
  curve1: { group: 'Road', label: 'Tight curve', ...road({ angle: 90, radius: BLOCK }) },
  curve2: { group: 'Road', label: 'Curve', ...road({ angle: 90, radius: 2 * BLOCK }) },
  curve4: { group: 'Road', label: 'Wide curve', ...road({ angle: 90, radius: 4 * BLOCK }) },
  bend: { group: 'Road', label: 'Gentle bend', ...road({ angle: 30, radius: 4 * BLOCK }) },
  slopeUp: { group: 'Road', label: 'Slope up', ...road({ length: 2 * BLOCK, rise: 2 * LEVEL, profile: 'smooth' }) },
  slopeDown: { group: 'Road', label: 'Slope down', ...road({ length: 2 * BLOCK, rise: -2 * LEVEL, profile: 'smooth' }) },
  climb: { group: 'Road', label: 'Steep climb', ...road({ length: 3 * BLOCK, rise: 6 * LEVEL, profile: 'smooth' }) },
  bankedCurve: { group: 'Road', label: 'Banked curve', ...road({ angle: 90, radius: 3 * BLOCK, bank: 25, bankMode: 'arc', wallR: 0 }) },
  walled: { group: 'Road', label: 'Walled straight', ...road({ wallL: 160, wallR: 160 }) },
  walledCurve: { group: 'Road', label: 'Walled curve', ...road({ angle: 90, radius: 2 * BLOCK, wallL: 160, wallR: 160 }) },
  wide: { group: 'Road', label: 'Wide road', ...road({ width: 2 * BLOCK }) },
  narrow: { group: 'Road', label: 'Narrow road', ...road({ width: BLOCK / 2, tex: 'road-plain' }) },
  dirt: { group: 'Road', label: 'Dirt road', ...road({ tex: 'dirt', thick: 64 }) },
  ice: { group: 'Road', label: 'Ice road', ...road({ tex: 'ice' }) },

  halfpipe: { group: 'Stunt', label: 'Half pipe', ...road({ length: 2 * BLOCK, width: 2 * BLOCK, shape: 'pipe', flatPart: 0.45, tex: 'concrete' }) },
  pipeCurve: { group: 'Stunt', label: 'Half pipe curve', ...road({ angle: 90, radius: 3 * BLOCK, width: 2 * BLOCK, shape: 'pipe', flatPart: 0.45, tex: 'concrete' }) },
  kicker: { group: 'Stunt', label: 'Jump', ...road({ length: BLOCK, rise: LEVEL, profile: 'kicker', tex: 'hazard' }) },
  bigKicker: { group: 'Stunt', label: 'Big jump', ...road({ length: 2 * BLOCK, rise: 3 * LEVEL, profile: 'kicker', tex: 'hazard' }) },
  landing: { group: 'Stunt', label: 'Landing', ...road({ length: 2 * BLOCK, rise: -2 * LEVEL, profile: 'easeOut', tex: 'road' }) },
  hump: { group: 'Stunt', label: 'Hump', ...road({ length: 2 * BLOCK, rise: 384, profile: 'hump' }) },
  dip: { group: 'Stunt', label: 'Dip', ...road({ length: 2 * BLOCK, rise: -384, profile: 'hump' }) },
  bumps: { group: 'Stunt', label: 'Bumpy road', ...road({ length: 3 * BLOCK, rise: 128, profile: 'bumps', tex: 'dirt', thick: 64 }) },
  boost: { group: 'Stunt', label: 'Boost pad', ...road({ boost: 'normal' }) },
  superBoost: { group: 'Stunt', label: 'Super boost', ...road({ boost: 'super', tex: 'road-red' }) },
  quarter: { group: 'Stunt', label: 'Quarter pipe', kind: 'quarter', width: 2 * BLOCK, radius: BLOCK, length: 0, tex: 'concrete' },
  wedge: { group: 'Stunt', label: 'Ramp', kind: 'wedge', width: BLOCK, length: 2 * BLOCK, rise: LEVEL * 2, tex: 'hazard' },

  bridge: { group: 'Road', label: 'Bridge: join ends', ...road({ path: 'bezier', to: [0, 0, -2 * BLOCK], tension: 1 }) },
  start: { group: 'Race', label: 'Start / finish', ...road({ length: 2 * BLOCK, tex: 'road', wallL: 0, wallR: 0 }), gate: 'checker' },
  checkpoint: { group: 'Race', label: 'Checkpoint', ...road({ tex: 'road' }), gate: 'blue' },

  platform: { group: 'Blocks', label: 'Platform', kind: 'platform', width: BLOCK, length: BLOCK, height: 128, tex: 'concrete' },
  bigPlatform: { group: 'Blocks', label: 'Big platform', kind: 'platform', width: 4 * BLOCK, length: 4 * BLOCK, height: 128, tex: 'road-plain' },
  wall: { group: 'Blocks', label: 'Wall', kind: 'box', width: BLOCK, height: 384, length: 96, tex: 'brick' },
  block: { group: 'Blocks', label: 'Block', kind: 'box', width: BLOCK, height: BLOCK, length: BLOCK, tex: 'stone' },
  pillar: { group: 'Blocks', label: 'Pillar', kind: 'cylinder', radius: 128, height: 1024, tex: 'concrete' },

  hill: { group: 'Terrain', label: 'Hill', kind: 'hill', width: 4 * BLOCK, length: 4 * BLOCK, height: 2 * LEVEL, shape: 'round', tex: 'grass' },
  bigHill: { group: 'Terrain', label: 'Big hill', kind: 'hill', width: 8 * BLOCK, length: 8 * BLOCK, height: 6 * LEVEL, shape: 'round', tex: 'grass' },
  ridge: { group: 'Terrain', label: 'Ridge', kind: 'hill', width: 3 * BLOCK, length: 8 * BLOCK, height: 3 * LEVEL, shape: 'ridge', tex: 'grass' },
  mesa: { group: 'Terrain', label: 'Mesa', kind: 'hill', width: 6 * BLOCK, length: 6 * BLOCK, height: 4 * LEVEL, shape: 'mesa', slope: 0.4, tex: 'sand' },
  dune: { group: 'Terrain', label: 'Dune', kind: 'hill', width: 4 * BLOCK, length: 2 * BLOCK, height: LEVEL, shape: 'ridge', tex: 'sand' },
  mountain: { group: 'Terrain', label: 'Mountain', kind: 'hill', width: 12 * BLOCK, length: 12 * BLOCK, height: 16 * LEVEL, shape: 'peak', tex: 'stone' },
  snowHill: { group: 'Terrain', label: 'Snow hill', kind: 'hill', width: 6 * BLOCK, length: 6 * BLOCK, height: 4 * LEVEL, shape: 'round', tex: 'snow' },
  pond: { group: 'Terrain', label: 'Pond', kind: 'platform', width: 4 * BLOCK, length: 4 * BLOCK, height: 8, tex: 'water' },
  mudPit: { group: 'Terrain', label: 'Mud pit', kind: 'platform', width: 3 * BLOCK, length: 3 * BLOCK, height: 8, tex: 'mud' },
  tree: { group: 'Decor', label: 'Tree', kind: 'tree', height: 1400, radius: 420, tex: 'green' },
  post: { group: 'Decor', label: 'Post', kind: 'cylinder', radius: 40, height: 512, tex: 'white' },
  arch: { group: 'Decor', label: 'Arch', kind: 'gate', width: BLOCK, height: 768, banner: 'yellow' },
  crate: { group: 'Decor', label: 'Crate', kind: 'box', width: 256, height: 256, length: 256, tex: 'wood' },
  sign: { group: 'Decor', label: 'Sign', kind: 'sign', width: BLOCK, height: 512, lift: 384, text: 'CTR 1.6', bg: '#1d4fd8', fg: '#ffffff' },
  bigSign: { group: 'Decor', label: 'Big sign', kind: 'sign', width: 3 * BLOCK, height: 768, lift: 640, text: 'GO!', bg: '#d0381a', fg: '#ffd34d' },
};

export function makePiece(type, at = {}) {
  const def = CATALOGUE[type];
  const { group, label, ...params } = def;
  return { id: Math.random().toString(36).slice(2, 10), type, x: 0, y: 0, z: 0, yaw: 0, pitch: 0, roll: 0, ...params, ...at };
}

export const isSweep = (pc) => (pc.kind || CATALOGUE[pc.type]?.kind) === 'sweep';

// what a piece makes, in its own coordinates
export function emitPiece(pc, E) {
  switch (pc.kind) {
    case 'sweep':
      emitSweep(pc, E);
      if (pc.gate) {
        const s = pc.type === 'start' ? 0.5 : 0.5;
        const fr = sweepFrame(pc, s);
        E.withLocal(fr, () => emitGate({ width: pc.width }, E, pc.gate));
      }
      break;
    case 'platform': emitPlatform(pc, E); break;
    case 'hill': emitHill(pc, E); break;
    case 'wedge': emitWedge(pc, E); break;
    case 'quarter': emitQuarter(pc, E); break;
    case 'cylinder': emitCylinder(pc, E); break;
    case 'tree': emitTree(pc, E); break;
    case 'gate': emitGate(pc, E, pc.banner || 'yellow'); break;
    case 'sign': emitSign(pc, E); break;
    case 'box': {
      const w = pc.width || BLOCK, h = pc.height || BLOCK, d = pc.length || BLOCK;
      // standing on the ground: no bottom (it'd never be seen)
      const onGround = E.ground !== false && Math.abs(pc.y || 0) < 8 && !pc.pitch && !pc.roll;
      emitBox(E, (x, y, z) => [(x - 0.5) * w, y * h, -z * d], [w, h, d], pc.tex || 'stone', pc.sideTex || pc.tex || 'stone', 'floor', 'wall', { noBottom: onGround });
      break;
    }
    default: break;
  }
}

// a piece's connectors (sweeps): its entry and exit, in its own coordinates
export function connectors(pc) {
  if (pc.kind !== 'sweep') return [];
  const a = sweepFrame(pc, 0), b = sweepFrame(pc, 1);
  return [
    { p: a.base, f: scale(a.f, -1), end: 0 },   // facing out of the piece, back the way in
    { p: b.base, f: b.f, end: 1 },
  ];
}

// the track's signs' faces: each different text (and colours) a slot of the atlas, in order
export const signKey = (pc) => JSON.stringify([pc.text || '', pc.bg || '', pc.fg || '']);
export function signSlotsOf(pieces, slots = 16) {
  const out = new Map();
  for (const pc of pieces) {
    if (pc.kind !== 'sign') continue;
    const k = signKey(pc);
    if (!out.has(k) && out.size < slots) out.set(k, `sign-${out.size}`);
  }
  return out;
}

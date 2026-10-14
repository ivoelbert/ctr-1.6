// Tracks: the pieces, where one ends (and the next snaps on), saving and loading.

import { makePiece, connectors, sweepFrame } from './pieces.js';
import { transformOf, yawOf, DEG, norm } from './geom.js';

export const newTrack = (name = 'My track') => ({ version: 1, name, ground: true, groundTex: 'grass', pieces: [] });

// a piece's connectors in the world: { p, f (out of the piece), end }
export function worldConnectors(pc) {
  const T = transformOf(pc);
  return connectors(pc).map((c) => ({ p: T.point(c.p), f: T.dir(c.f), end: c.end, piece: pc }));
}

// a new piece of `type` whose entry sits on connector c (facing out of its piece)
export function attachTo(c, type, extra = {}) {
  const f = c.f;
  const yaw = yawOf(f);
  const pitch = Math.asin(Math.max(-1, Math.min(1, f[1]))) / DEG;
  return makePiece(type, { x: c.p[0], y: c.p[1], z: c.p[2], yaw, pitch: Math.abs(pitch) < 0.01 ? 0 : pitch, ...extra });
}

// a bridge from connector a (out of its piece) to b: a road along a cubic that leaves a's
// piece the way it faces and arrives into b's (b: a connector, or { p, f } a free end facing f)
export function bridge(a, b, extra = {}) {
  const yaw = yawOf(a.f);
  const fromPitch = Math.asin(Math.max(-1, Math.min(1, a.f[1]))) / DEG;
  const pc = makePiece('bridge', { x: a.p[0], y: a.p[1], z: a.p[2], yaw, pitch: 0, ...extra });
  const T = transformOf(pc);
  const inv = (v) => {
    // R is a turn about y: its inverse, its transpose
    const R = T.R;
    return [R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2], R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2], R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2]];
  };
  const to = inv([b.p[0] - a.p[0], b.p[1] - a.p[1], b.p[2] - a.p[2]]);
  const arrive = inv(b.end === undefined ? b.f : [-b.f[0], -b.f[1], -b.f[2]]);
  const toYaw = yawOf(arrive);
  const toPitch = Math.asin(Math.max(-1, Math.min(1, arrive[1] / (Math.hypot(...arrive) || 1)))) / DEG;
  return Object.assign(pc, { to: to.map((v) => Math.round(v * 100) / 100), fromPitch, toYaw, toPitch });
}

// the connectors no other piece's connector meets: where the track goes on
export function openEnds(track) {
  const all = track.pieces.flatMap(worldConnectors);
  return all.filter((c) => !all.some((d) => d !== c && d.piece !== c.piece &&
    Math.hypot(d.p[0] - c.p[0], d.p[1] - c.p[1], d.p[2] - c.p[2]) < 96 &&
    d.f[0] * c.f[0] + d.f[1] * c.f[1] + d.f[2] * c.f[2] < -0.9));
}

// a loop to start from: up onto pillars, a banked curve, a jump over a gap, a half pipe, a boost,
// and a bridge back round to the start
export function demoTrack() {
  const t = newTrack('Demo loop');
  const add = (pc) => { t.pieces.push(pc); return pc; };
  const exit = (pc) => worldConnectors(pc).find((c) => c.end === 1);
  const start = add(makePiece('start', { x: 0, y: 0, z: 6144, yaw: 0 }));
  let pc = start;
  const next = (type, extra) => { pc = add(attachTo(exit(pc), type, extra)); return pc; };
  next('straight2');
  next('curve2');
  next('slopeUp');
  next('straight2');
  next('bankedCurve');
  next('straight');
  next('kicker');
  // the jump: a kart at full speed clears a block's gap off it, landing two levels down
  const e = exit(pc);
  const fh = norm([e.f[0], 0, e.f[2]]);
  pc = add(makePiece('straight2', { x: e.p[0] + fh[0] * 1024, y: e.p[1] - 2 * 256, z: e.p[2] + fh[2] * 1024, yaw: yawOf(fh) }));
  next('slopeDown', { rise: -256 });
  next('curve2');
  next('halfpipe');
  next('straight');
  next('boost');
  next('curve4');
  // and back to the start's line
  const startIn = worldConnectors(start).find((c) => c.end === 0);
  add(bridge(exit(pc), startIn));
  return t;
}

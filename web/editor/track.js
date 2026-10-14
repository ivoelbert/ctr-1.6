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

// the connectors no other piece's connector meets: where the track goes on
export function openEnds(track) {
  const all = track.pieces.flatMap(worldConnectors);
  return all.filter((c) => !all.some((d) => d !== c && d.piece !== c.piece &&
    Math.hypot(d.p[0] - c.p[0], d.p[1] - c.p[1], d.p[2] - c.p[2]) < 96 &&
    d.f[0] * c.f[0] + d.f[1] * c.f[1] + d.f[2] * c.f[2] < -0.9));
}

// a loop to start from: the start, and round
export function demoTrack() {
  const t = newTrack('Demo loop');
  const add = (pc) => { t.pieces.push(pc); return pc; };
  let pc = add(makePiece('start', { x: 0, y: 0, z: 2048, yaw: 0 }));
  const next = (type, extra) => {
    const ends = worldConnectors(pc).filter((c) => c.end === 1);
    pc = add(attachTo(ends[0], type, extra));
    return pc;
  };
  // a rectangle of curves (radius 2048) and sides of 6144 and 4096: it closes on the start
  next('slopeUp');
  next('straight');
  next('straight');
  next('curve2');
  next('straight2');
  next('curve2', { bank: 20, bankMode: 'arc' });
  next('slopeDown');
  next('boost');
  next('straight');
  next('straight');
  next('straight');
  next('curve2');
  next('straight2');
  next('curve2');
  return t;
}

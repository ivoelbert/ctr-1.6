// Tracks to start from (the Open dialog's): each built piece by piece, as you would, and joined
// back to the start with a bridge.

import { makePiece } from './pieces.js';
import { newTrack, worldConnectors, attachTo, bridge, demoTrack } from './track.js';

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
  t.pieces.push(bridge(exit(pc), worldConnectors(first).find((c) => c.end === 0)));
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
  ];
}

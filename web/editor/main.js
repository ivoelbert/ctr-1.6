// The track editor (index.html loads it for ?editor): prepare() before the game starts,
// start() once it runs.
import { Game } from './game.js';
import { demoTrack } from './track.js';

let game = null;

export async function prepare(Module) {
  game = new Game(Module);
  const track = demoTrack();
  const out = game.prepare(track);
  window.ctrEditor = { game, track, last: out };
  console.log(`[editor] ${out.quads} quadblocks, ${out.nodes} checkpoints, route ${out.route ? (out.route.closed ? 'closed' : 'open') : 'none'} (${out.ms.toFixed(1)} ms)`);
}

export function start() {}

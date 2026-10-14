// The editor's side of the game: its textures in the atlas the game samples, a track compiled
// into the files the engine reads (assets/world/), and the restart that drives it.

import { makeTextures, buildAtlas } from './textures.js';
import { compileTrack } from './compile.js';

export class Game {
  constructor(Module) {
    this.M = Module;
    this.textures = makeTextures();
    this.atlas = buildAtlas(this.textures);
    this.files = {};
  }

  // before the game starts: the atlas and the first track's files
  prepare(track) {
    const FS = this.M.FS;
    FS.mkdirTree('/assets/dust2');
    FS.writeFile('/assets/dust2/atlas.rgba', this.atlas.file);
    FS.mkdirTree('/assets/world');
    // the engine asks for a tile when it needs one: it's always here, the last compile's
    this.M.ctrFetchTile = (i, j) => {
      const name = `T_${i}_${j}.lev`;
      if (this.files[name]) FS.writeFile(`/assets/world/${name}`, this.files[name]);
    };
    return this.write(track);
  }

  compile(track, test = null) {
    return compileTrack(track, this.atlas, this.textures, test);
  }

  write(track, test = null) {
    const out = this.compile(track, test);
    const FS = this.M.FS;
    // the old tiles go (the engine reads and removes each as it loads it)
    for (const name of Object.keys(this.files)) {
      try { FS.unlink(`/assets/world/${name}`); } catch { /* read already */ }
    }
    this.files = out.files;
    for (const [name, data] of Object.entries(out.files)) {
      if (name.startsWith('T_')) continue;   // tiles go when asked for (ctrFetchTile)
      FS.writeFile(`/assets/world/${name}`, data);
    }
    return out;
  }

  // drive the track now: compiled, swapped in, the race started over (no countdown)
  drive(track, test = null) {
    const out = this.write(track, test);
    this.M._NativeWeb_EditorRestart(1);
    this.M.ctrPaused = false;
    return out;
  }

  pause(on) {
    this.M.ctrPaused = !!on;
  }
}

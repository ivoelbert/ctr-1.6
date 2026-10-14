// The editor's side of the game: its textures in the atlas the game samples, a track compiled
// into the files the engine reads (assets/world/), and the restart that drives it.

import { makeTextures, buildAtlas, loadCtrTextures, signSlots, drawSign, SIGN_SLOTS } from './textures.js';
import { compileTrack } from './compile.js';
import { signSlotsOf } from './pieces.js';

export class Game {
  constructor(Module, extra = []) {
    this.M = Module;
    this.textures = makeTextures().concat(signSlots(), extra);
    this.atlas = buildAtlas(this.textures);
    this.files = {};
    this.signsDrawn = '';
    this.atlasDirty = false;
  }

  // the track's signs drawn in their slots (the canvases, and the atlas the game has); returns
  // the slots redrawn (the editor's view updates those)
  updateSigns(track) {
    const slots = signSlotsOf(track.pieces, SIGN_SLOTS);
    const want = JSON.stringify([...slots]);
    if (want === this.signsDrawn) return [];
    this.signsDrawn = want;
    const changed = [];
    const specs = new Map([...slots].map(([key, id]) => [id, JSON.parse(key)]));
    for (let k = 0; k < SIGN_SLOTS; k++) {
      const id = `sign-${k}`;
      const t = this.textures.find((x) => x.id === id);
      const [text, bg, fg] = specs.get(id) || ['', undefined, undefined];
      drawSign(t.canvas, text, bg || undefined, fg || undefined);
      // into the game's atlas
      const r = this.atlas.rects[id];
      const px = t.canvas.getContext('2d').getImageData(0, 0, t.size, t.size).data;
      const ox = (r.layer % 4) * 1024 + r.x, oy = Math.floor(r.layer / 4) * 1024 + r.y;
      for (let row = 0; row < t.size; row++) this.atlas.file.set(px.subarray(row * t.size * 4, (row + 1) * t.size * 4), 12 + ((oy + row) * this.atlas.width + ox) * 4);
      changed.push(id);
    }
    this.atlasDirty = true;
    return changed;
  }

  // with CTR's own textures, when they're there
  static async create(Module) {
    return new Game(Module, await loadCtrTextures());
  }

  // before the game starts: the atlas and the first track's files
  prepare(track) {
    const FS = this.M.FS;
    this.updateSigns(track);
    this.atlasDirty = false;
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
  // the atlas again in the game, when its signs changed
  syncAtlas() {
    if (!this.atlasDirty) return;
    this.atlasDirty = false;
    this.M.FS.writeFile('/assets/dust2/atlas.rgba', this.atlas.file);
    if (this.started && this.M._NativeWeb_ReloadAtlas) this.M._NativeWeb_ReloadAtlas();
  }

  drive(track, test = null) {
    // the game left the editor's level (its pause menu's Quit): back in with a reload, the
    // track autosaved
    const s = window.ctr && window.ctr.state();
    if (s && s.level !== 0) {
      const q = new URLSearchParams(location.search);
      q.set('drive', '');
      location.search = q.toString();
      return null;
    }
    this.updateSigns(track);
    this.syncAtlas();
    const out = this.write(track, test);
    this.M._NativeWeb_EditorRestart(1);
    this.pause(false);
    return out;
  }

  pause(on) {
    this.M.ctrPaused = !!on;
    // the sound stops with it (it plays on in SDL's callback otherwise)
    if (this.M._NativeWeb_PauseAudio) this.M._NativeWeb_PauseAudio(on ? 1 : 0);
  }
}

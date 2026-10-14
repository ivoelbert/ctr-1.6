// The track editor (index.html loads it for ?editor). prepare() runs before the game starts
// (the atlas and the first track's tiles); start() once it runs: the game boots into the
// track, is held there, and the editor takes the screen. Tab drives the track at once (the
// tiles compiled in the page and swapped into the race: game.js); Tab or Esc comes back.

import * as THREE from 'three';
import { Game } from './game.js';
import { View } from './view.js';
import { CATALOGUE, makePiece, BLOCK, LEVEL, isSweep, sweepFrame, SPANNED } from './pieces.js';
import { newTrack, demoTrack, worldConnectors, attachTo, openEnds, bridge } from './track.js';
import { findRoute, FIELD } from './compile.js';
import { DEG, transformOf, yawOf } from './geom.js';
import { examples } from './examples.js';

const AUTOSAVE = 'ctr-editor-track';
const PREFS = 'ctr-editor-prefs';

let game = null;
let M = null;

export async function prepare(Module, params) {
  M = Module;
  game = await Game.create(Module);
  // the stylesheet as text (an older server sends .css without its type, and the page would
  // ignore a <link> to it)
  const css = document.createElement('style');
  css.textContent = await (await fetch('editor/editor.css', { cache: 'no-store' })).text();
  document.head.appendChild(css);
  const track = await initialTrack(params);
  const out = game.prepare(track);
  editor.track = track;
  window.ctrEditor = { game, get track() { return editor.track; }, last: out, editor };
  console.log(`[editor] ${out.quads} quadblocks, ${out.nodes} checkpoints, route ${out.route ? (out.route.closed ? 'closed' : 'open') : 'none'} (${out.ms.toFixed(1)} ms)`);
}

export function start() {
  editor.init();
}

async function initialTrack(params) {
  const name = params && params.get('track');
  if (name) {
    try {
      const r = await fetch(`tracks/${encodeURIComponent(name)}.json`, { cache: 'no-store' });
      if (r.ok) return normalise(await r.json());
    } catch { /* fall through */ }
    const kept = library.get(name);
    if (kept) return normalise(kept);
  }
  try {
    const saved = localStorage.getItem(AUTOSAVE);
    if (saved) return normalise(JSON.parse(saved));
  } catch { /* none */ }
  return demoTrack();
}

// a loaded track with today's defaults under it (pieces keep their own values)
function normalise(t) {
  const out = { ...newTrack(t.name || 'My track'), ...t };
  out.pieces = (t.pieces || []).filter((p) => CATALOGUE[p.type]).map((p) => {
    const { group, label, ...defs } = CATALOGUE[p.type];
    return { ...defs, ...p, id: p.id || Math.random().toString(36).slice(2, 10) };
  });
  return out;
}

// the tracks saved in this browser (as well as to the server's tracks/, when it has them)
const LIBRARY = 'ctr-editor-library';
const library = {
  all() { try { return JSON.parse(localStorage.getItem(LIBRARY) || '{}'); } catch { return {}; } },
  get(name) { const t = this.all()[name]; return t ? t.track : null; },
  put(name, track) {
    const all = this.all();
    all[name] = { mtime: Date.now(), track };
    try { localStorage.setItem(LIBRARY, JSON.stringify(all)); } catch { /* full */ }
  },
  remove(name) {
    const all = this.all();
    delete all[name];
    try { localStorage.setItem(LIBRARY, JSON.stringify(all)); } catch { /* fine */ }
  },
};

const clone = (o) => JSON.parse(JSON.stringify(o));
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
};

// the property editors: [key, label, kind, min, max, step]
const SWEEP_FIELDS = [
  ['length', 'Length', 'range', 256, 16384, 256, (p) => !p.angle],
  ['angle', 'Turn', 'range', -180, 180, 5],
  ['radius', 'Radius', 'range', 512, 16384, 256, (p) => !!p.angle],
  ['rise', 'Rise', 'range', -4096, 4096, 64],
  ['profile', 'Slope shape', 'select', ['smooth', 'linear', 'kicker', 'easeOut', 'hump', 'bumps']],
  ['width', 'Width', 'range', 256, 8192, 128],
  ['bank', 'Bank', 'range', -80, 80, 1],
  ['bankMode', 'Bank shape', 'select', ['const', 'arc', 'in', 'out']],
  ['shape', 'Cross section', 'select', ['flat', 'pipe', 'pipeL', 'pipeR']],
  ['flatPart', 'Pipe floor', 'range', 0, 0.95, 0.05, (p) => p.shape && p.shape !== 'flat'],
  ['pipeAngle', 'Pipe height', 'range', 20, 89, 1, (p) => p.shape && p.shape !== 'flat'],
  ['wallL', 'Left wall', 'range', 0, 2048, 32],
  ['wallR', 'Right wall', 'range', 0, 2048, 32],
  ['thick', 'Thickness', 'range', 0, 1024, 16],
  ['boost', 'Boost pad', 'select', ['', 'normal', 'super']],
];
const FIELDS = {
  sweep: SWEEP_FIELDS,
  bridge: [['tension', 'Roundness', 'range', 0.2, 2.5, 0.05], ...SWEEP_FIELDS.filter(([k]) => !['length', 'angle', 'radius', 'rise', 'profile'].includes(k))],
  platform: [['width', 'Width', 'range', 256, 16384, 256], ['length', 'Length', 'range', 256, 16384, 256], ['height', 'Height', 'range', 16, 4096, 16]],
  box: [['width', 'Width', 'range', 32, 16384, 32], ['length', 'Depth', 'range', 32, 16384, 32], ['height', 'Height', 'range', 32, 8192, 32]],
  wedge: [['width', 'Width', 'range', 256, 8192, 128], ['length', 'Length', 'range', 256, 8192, 128], ['rise', 'Rise', 'range', 64, 4096, 64]],
  quarter: [['width', 'Width', 'range', 256, 8192, 128], ['radius', 'Radius', 'range', 256, 4096, 64], ['length', 'Flat run', 'range', 0, 4096, 64], ['pipeAngle', 'Steepness', 'range', 30, 89, 1]],
  cylinder: [['radius', 'Radius', 'range', 16, 2048, 16], ['height', 'Height', 'range', 32, 8192, 32]],
  tree: [['height', 'Height', 'range', 256, 6000, 64], ['radius', 'Crown', 'range', 64, 2048, 32]],
  hill: [['width', 'Width', 'range', 512, 16384, 256], ['length', 'Length', 'range', 512, 16384, 256], ['height', 'Height', 'range', 64, 6144, 64],
    ['shape', 'Shape', 'select', ['round', 'ridge', 'mesa']], ['slope', 'Mesa slope', 'range', 0.1, 1, 0.05, (p) => p.shape === 'mesa']],
  gate: [['width', 'Width', 'range', 256, 8192, 128], ['height', 'Height', 'range', 256, 4096, 64]],
  sign: [['text', 'Text', 'text'], ['bg', 'Colour', 'color'], ['fg', 'Letters', 'color'], ['width', 'Width', 'range', 256, 8192, 128], ['height', 'Height', 'range', 128, 4096, 64], ['lift', 'Lift', 'range', 0, 4096, 64]],
};
const TEX_FIELDS = {
  sweep: [['tex', 'Surface'], ['wallTex', 'Walls'], ['sideTex', 'Sides']],
  platform: [['tex', 'Top'], ['sideTex', 'Sides']],
  box: [['tex', 'Surface'], ['sideTex', 'Sides']],
  wedge: [['tex', 'Surface'], ['sideTex', 'Sides']],
  quarter: [['tex', 'Surface'], ['sideTex', 'Sides']],
  cylinder: [['tex', 'Surface']],
  tree: [['tex', 'Leaves']],
  gate: [['banner', 'Banner']],
  hill: [['tex', 'Surface']],
};

const editor = {
  track: null,
  selection: new Set(),
  tool: null,             // a catalogue type being placed
  mirror: false,          // the tool mirrored (curves the other way)
  rot: 0,                 // the tool's yaw (degrees)
  level: 0,               // the build height, in LEVEL steps
  snap: { grid: true, size: BLOCK, rot: 90 },
  mode: 'edit',
  undo: [],
  redo: [],
  clipboard: null,
  trail: [],
  lastPick: null,
  ready: false,

  init() {
    this.loadPrefs();
    const root = el('div', { id: 'ed' });
    document.body.appendChild(root);
    this.root = root;
    this.view = new View(root, game.textures);
    this.view.tick = (dt) => this.tick(dt);
    this.buildUI();
    this.view.setGround(this.track.ground !== false, this.track.groundTex);
    this.view.sync(this.track);
    this.frameTrack();
    this.refresh();
    this.bindInput();
    try {
      if (!localStorage.getItem('ctr-editor-seen-help')) {
        this.toggleHelp(true);
        localStorage.setItem('ctr-editor-seen-help', '1');
      }
    } catch { /* fine */ }
    // the game boots into the track behind the editor; it's held once it's racing
    const wait = () => {
      const s = window.ctr && window.ctr.state ? window.ctr.state() : null;
      if (s && s.kart && s.eventTime > 0 && (s.gameMode1 & 0x40) === 0) {
        this.ready = true;
        game.started = true;
        // ?drive (the launcher's Drive): straight into the race
        if (new URLSearchParams(location.search).has('drive')) this.drive();
        else game.pause(true);
        this.status();
        return;
      }
      setTimeout(wait, 100);
    };
    wait();
  },

  loadPrefs() {
    try { Object.assign(this.snap, JSON.parse(localStorage.getItem(PREFS) || '{}').snap || {}); } catch { /* defaults */ }
  },
  savePrefs() {
    try { localStorage.setItem(PREFS, JSON.stringify({ snap: this.snap })); } catch { /* fine */ }
  },

  // ---------------------------------------------------------------- the panels
  buildUI() {
    const R = this.root;
    this.nameInput = el('input', { type: 'text', class: 'name', value: this.track.name, title: 'Track name',
      onchange: () => { this.commit(() => { this.track.name = this.nameInput.value.trim() || 'My track'; }); } });
    this.groundBtn = el('button', { title: 'The grass under everything (off: the track floats over nothing)', onclick: () => this.commit(() => { this.track.ground = this.track.ground === false; }) }, 'Ground');
    this.groundTex = el('select', { title: 'The ground', onchange: () => this.commit(() => { this.track.groundTex = this.groundTex.value; }) },
      ...['grass', 'sand', 'dirt', 'snow', 'water', 'lava', 'concrete', 'road-plain', 'checker', 'ice', 'mud'].map((t) => el('option', { value: t }, game.textures.find((x) => x.id === t)?.label || t)));
    this.skyInput = el('input', { type: 'color', class: 'sky', title: 'The sky', onchange: () => this.commit(() => { this.track.sky = this.skyInput.value; }) });
    this.lightSel = el('select', { title: 'The light: day to night', onchange: () => this.commit(() => { this.track.light = Number(this.lightSel.value); }) },
      el('option', { value: 1 }, 'Day'), el('option', { value: 0.85 }, 'Afternoon'), el('option', { value: 0.65 }, 'Evening'), el('option', { value: 0.42 }, 'Night'));
    this.weatherSel = el('select', { title: 'The weather', onchange: () => this.commit(() => { this.track.weather = this.weatherSel.value || undefined; if (!this.weatherSel.value) delete this.track.weather; }) },
      el('option', { value: '' }, 'Clear'), el('option', { value: 'rain' }, 'Rain'), el('option', { value: 'snow' }, 'Snow'));
    this.undoBtn = el('button', { title: 'Undo (Ctrl+Z)', onclick: () => this.doUndo() }, '↶');
    this.redoBtn = el('button', { title: 'Redo (Ctrl+Shift+Z)', onclick: () => this.doRedo() }, '↷');
    this.snapBtn = el('button', { title: 'Grid snap (G): pieces on the block grid; off, anywhere', onclick: () => this.toggleSnap() }, 'Grid');
    this.snapSize = el('select', { title: 'Grid size', onchange: () => { this.snap.size = Number(this.snapSize.value); this.savePrefs(); } },
      el('option', { value: BLOCK }, '1'), el('option', { value: BLOCK / 2 }, '½'), el('option', { value: BLOCK / 4 }, '¼'), el('option', { value: BLOCK / 16 }, '1/16'));
    this.rotStep = el('select', { title: 'Rotation step (R)', onchange: () => { this.snap.rot = Number(this.rotStep.value); this.savePrefs(); } },
      el('option', { value: 90 }, '90°'), el('option', { value: 45 }, '45°'), el('option', { value: 15 }, '15°'), el('option', { value: 5 }, '5°'), el('option', { value: 1 }, '1°'));
    this.levelLabel = el('span', { class: 'muted', title: 'Build height (PgUp / PgDn, or Q / E)' });
    const top = el('div', { class: 'bar top' },
      el('span', { class: 'title' }, 'EDITOR'),
      this.nameInput,
      el('button', { title: 'A new, empty track', onclick: () => this.newTrack() }, 'New'),
      el('button', { title: 'Open a saved track', onclick: () => this.openDialog() }, 'Open'),
      el('button', { title: 'Save (Ctrl+S)', onclick: () => this.save() }, 'Save'),
      el('span', { class: 'sep' }),
      this.undoBtn, this.redoBtn,
      el('span', { class: 'sep' }),
      this.snapBtn, this.snapSize, this.rotStep, this.levelLabel,
      el('span', { class: 'sep' }),
      this.groundBtn, this.groundTex, this.skyInput, this.lightSel, this.weatherSel,
      el('span', { class: 'grow' }),
      el('button', { title: 'Help (H)', onclick: () => this.toggleHelp() }, '?'),
      el('button', { title: 'Drive from where the mouse points (Shift+Tab)', onclick: () => this.drive(true) }, '▶ Here'),
      el('button', { class: 'go', title: 'Drive the track from the start (Tab)', onclick: () => this.drive() }, '▶ DRIVE'));
    R.appendChild(top);

    // the palette
    const groups = [...new Set(Object.values(CATALOGUE).map((d) => d.group))];
    this.thumbs = this.view.thumbnails(Object.fromEntries(Object.entries(CATALOGUE).map(([type, d]) => [type, makePiece(type)])));
    this.tabs = el('div', { class: 'tabs' });
    this.palette = el('div', { class: 'palette' });
    this.group = groups[0];
    for (const g of groups) {
      this.tabs.appendChild(el('button', { 'data-group': g, onclick: () => { this.group = g; this.renderPalette(); } }, g));
    }
    this.tabs.appendChild(el('span', { class: 'grow' }));
    this.statusEl = el('div', { class: 'status' });
    R.appendChild(el('div', { class: 'bar bottom' }, this.tabs, this.palette, this.statusEl));
    this.renderPalette();
    // the view's middle in the middle of what the bars leave
    const insets = () => this.view.setInsets(top.offsetHeight, this.statusEl.parentElement.offsetHeight);
    insets();
    window.addEventListener('resize', insets);

    this.props = el('div', { class: 'props', hidden: true });
    R.appendChild(this.props);
    this.help = el('div', { class: 'help', hidden: true, onclick: () => this.toggleHelp(false) });
    R.appendChild(this.help);
    this.renderHelp();
    this.dialog = el('div', { class: 'dialog', hidden: true });
    R.appendChild(this.dialog);
    this.toastEl = el('div', { class: 'toast' });
    R.appendChild(this.toastEl);
    this.driveHint = el('div', { id: 'drivehint', class: 'fade' }, 'Tab or Esc: back to the editor · Backspace: start over');
    document.body.appendChild(this.driveHint);
  },

  renderPalette() {
    this.tabs.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.group === this.group));
    this.palette.replaceChildren(...Object.entries(CATALOGUE).filter(([, d]) => d.group === this.group).map(([type, d]) =>
      el('div', { class: 'tile' + (this.tool === type ? ' on' : ''), title: d.label, onclick: () => this.pickTool(type) },
        el('img', { src: this.thumbs[type], alt: '' }), el('span', {}, d.label))));
  },

  renderHelp() {
    const rows = [
      ['Left click', 'Place the piece you picked; with none, select (Shift: add to the selection)'],
      ['Right drag · Middle drag', 'Turn the camera · move it (Shift + right drag too)'],
      ['Alt + drag · Space + drag', 'The same on a trackpad: turn the camera · move it'],
      ['Drag over empty ground', 'Select everything in the box (Shift: add to it)'],
      ['Wheel · W A S D', 'Zoom · move the camera along the ground'],
      ['R / Shift+R', 'Turn the piece you place, or the selection, by the rotation step'],
      ['T', 'Mirror the piece you place (curves the other way)'],
      ['PgUp / PgDn  ·  E / Q', 'Build higher / lower (a step is a quarter block)'],
      ['G', 'Grid snap on / off: off, pieces go anywhere, at any angle'],
      ['M', 'The selection\'s gizmo: move or turn (drag its arrows or rings)'],
      ['Near a green arrow', 'A road piece snaps onto the end of the track'],
      ['Alt + click', 'Pick up a piece\'s type and settings (eyedropper)'],
      ['Right click (no drag)', 'Delete the piece under the mouse'],
      ['Delete · Ctrl+D', 'Delete · duplicate the selection'],
      ['1 – 9 · , and .', 'Pick the palette\'s pieces by number · the previous / next tab'],
      ['Ctrl+C / Ctrl+V', 'Copy / paste the selection (pasted where the mouse is)'],
      ['Ctrl+Z / Ctrl+Shift+Z', 'Undo / redo'],
      ['Ctrl+S', 'Save the track (tracks/ by the game)'],
      ['F · V', 'Look at the selection (or the whole track) · straight down on it, and back'],
      ['Tab', 'Drive it from the start, at once · Tab or Esc again: back here · Backspace while driving: start over'],
      ['Shift+Tab', 'Drive from where the mouse points'],
      ['Esc', 'Put the piece down / clear the selection'],
    ];
    this.help.replaceChildren(
      el('h2', {}, 'Track editor'),
      el('p', { class: 'muted' }, 'Lay a loop from the Start / finish round back to it: laps count once it closes (the line along the track turns green). Every piece can be moved and turned freely, and its shape changed on the right: lengths, curves, slopes, banks, walls, pipes, textures.'),
      el('table', {}, ...rows.map(([k, v]) => el('tr', {}, el('td', {}, k), el('td', {}, v)))),
      el('p', { class: 'muted' }, 'H or ? closes this.'));
  },

  toggleHelp(on) {
    this.help.hidden = on === undefined ? !this.help.hidden : !on;
  },

  toast(msg) {
    this.toastEl.textContent = msg;
    this.toastEl.classList.add('show');
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toastEl.classList.remove('show'), 2200);
  },

  // ---------------------------------------------------------------- state
  snapshot() { return JSON.stringify(this.track); },

  // a change: fn edits this.track; the step before it goes on the undo list
  commit(fn, { quiet = false } = {}) {
    const before = this.snapshot();
    fn();
    const after = this.snapshot();
    if (after === before) return;
    this.undo.push(before);
    if (this.undo.length > 300) this.undo.shift();
    this.redo = [];
    this.changed(quiet);
  },

  changed(quiet = false) {
    // the pieces stay on the field (its edges are the engine's 16-bit reach)
    for (const pc of this.track.pieces) {
      pc.x = Math.max(-FIELD, Math.min(FIELD, pc.x || 0));
      pc.z = Math.max(-FIELD, Math.min(FIELD, pc.z || 0));
      pc.y = Math.max(-2048, Math.min(24576, pc.y || 0));
    }
    if (document.activeElement !== this.nameInput) this.nameInput.value = this.track.name;
    for (const id of game.updateSigns(this.track)) this.view.refreshTexture(id);
    this.view.setGround(this.track.ground !== false, this.track.groundTex);
    this.view.sync(this.track);
    for (const id of [...this.selection]) if (!this.track.pieces.some((p) => p.id === id)) this.selection.delete(id);
    this.refresh(quiet);
    clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => { try { localStorage.setItem(AUTOSAVE, this.snapshot()); } catch { /* full */ } }, 300);
  },

  doUndo() {
    if (!this.undo.length) return;
    this.redo.push(this.snapshot());
    this.track = JSON.parse(this.undo.pop());
    this.nameInput.value = this.track.name;
    this.changed();
  },
  doRedo() {
    if (!this.redo.length) return;
    this.undo.push(this.snapshot());
    this.track = JSON.parse(this.redo.pop());
    this.nameInput.value = this.track.name;
    this.changed();
  },

  refresh(quiet = false) {
    this.route = findRoute(this.track.pieces);
    this.ends = openEnds(this.track);
    this.view.showOverlay({ ends: this.ends, route: this.route, selected: [...this.selection], trail: this.trail });
    this.undoBtn.disabled = !this.undo.length;
    this.redoBtn.disabled = !this.redo.length;
    this.snapBtn.classList.toggle('on', this.snap.grid);
    this.snapSize.value = String(this.snap.size);
    this.rotStep.value = String(this.snap.rot);
    this.groundBtn.classList.toggle('on', this.track.ground !== false);
    this.groundTex.value = this.track.groundTex || 'grass';
    this.skyInput.value = this.track.sky || '#6eaae6';
    this.lightSel.value = String(this.track.light ?? 1);
    this.weatherSel.value = this.track.weather || '';
    this.view.setEnvironment(this.track.sky || '#6eaae6', this.track.light ?? 1);
    this.levelLabel.textContent = `▲${this.level}`;
    this.view.buildGrid(this.level * LEVEL);
    if (!quiet) this.renderProps();
    this.status();
  },

  status() {
    const n = this.track.pieces.length;
    const r = this.route;
    let route;
    if (!this.track.pieces.some((p) => p.type === 'start')) route = el('span', { class: 'warn' }, 'No Start / finish yet: free drive (Race tab)');
    else if (r && r.closed) route = el('span', { class: 'ok' }, `Loop closed ✓ ${(r.length / BLOCK).toFixed(1)} blocks a lap`);
    else route = el('span', { class: 'warn' }, `Loop open: ${r ? (r.length / BLOCK).toFixed(1) : 0} blocks from the start `,
      el('button', { onclick: () => this.closeLoop(), title: 'Join the end of the track back to the start with a bridge' }, 'Close the loop'));
    const tool = this.tool === 'bridge' ? el('span', {}, el('b', {}, 'Bridge: '), this.bridgeFrom ? 'click another open end, or anywhere (draws on) · Esc stop' : 'click an open end (green arrow) to start from') :
      this.tool ? el('span', {}, 'Placing ', el('b', {}, CATALOGUE[this.tool].label), ' · R turn · T mirror · Esc done') :
      this.selection.size ? el('span', {}, el('b', {}, `${this.selection.size} selected`), ' · M move/turn · R turn · Del delete · Ctrl+D duplicate') :
        el('span', { class: 'muted' }, 'Pick a piece below, or click one to select it · H: help');
    // the last drive's laps, and the best of them
    const time = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}.${String(Math.floor((ms % 1000) / 10)).padStart(2, '0')}`;
    const laps = this.laps && this.laps.length ? el('span', {}, 'Laps ', ...this.laps.slice(-3).map((t, i, a) => el('b', {}, time(t) + (i < a.length - 1 ? ' · ' : ''))),
      this.laps.length > 1 ? el('span', { class: 'muted' }, `  best ${time(Math.min(...this.laps))}`) : null) : null;
    this.statusEl.replaceChildren(...[route, el('span', { class: 'muted' }, `${n} pieces`), laps, tool].filter(Boolean),
      el('span', { class: 'grow' }), el('span', { class: 'muted' }, this.ready ? 'Game ready: Tab drives' : 'Game loading…'));
  },

  // ---------------------------------------------------------------- tools and placement
  pickTool(type) {
    this.tool = this.tool === type ? null : type;
    this.mirror = false;
    this.toolExtra = null;
    this.bridgeFrom = null;
    if (this.tool) this.selection.clear();
    this.detachGizmo();
    this.renderPalette();
    this.refresh();
    this.updateGhost();
  },

  toggleSnap() {
    this.snap.grid = !this.snap.grid;
    this.savePrefs();
    this.toast(this.snap.grid ? 'Grid snap on' : 'Grid snap off: free placement');
    this.refresh(true);
    this.updateGhost();
    this.attachGizmo();
  },

  // the ghost for the tool at the mouse: snapped onto an open end when one is near, else on
  // the grid (or anywhere, snap off) at the build height
  // the open end nearest the mouse (within reach), but not `not`
  nearestEnd(at, not = null, reach = 1600) {
    let best = null, bd = reach;
    for (const c of this.ends) {
      if (not && (c === not || (c.piece === not.piece && c.end === not.end))) continue;
      const d = Math.hypot(c.p[0] - at[0], c.p[2] - at[2]) + Math.abs(c.p[1] - at[1]) * 0.5;
      if (d < bd) { bd = d; best = c; }
    }
    return best;
  },

  // the bridge tool: from an open end to another, or to the mouse (a free curve)
  bridgeCandidate(at) {
    if (!this.bridgeFrom) return null;
    const a = this.bridgeFrom;
    const target = this.nearestEnd(at, a);
    if (target) return { piece: bridge(a, target, this.toolExtra || {}), snapped: true, joins: true };
    const p = this.lastPick.plane || at;
    const d = [p[0] - a.p[0], 0, p[2] - a.p[2]];
    const L = Math.hypot(d[0], d[2]);
    if (L < 256) return null;
    // a free end: on the build height, arriving along the way from the start to it, turned
    // as much again as the start's heading is off that way (a smooth arc, not an S)
    const chord = Math.atan2(d[0], d[2]);
    const head = Math.atan2(a.f[0], a.f[2]);
    let off = chord - head;
    while (off > Math.PI) off -= 2 * Math.PI;
    while (off < -Math.PI) off += 2 * Math.PI;
    const arrive = chord + off;
    return { piece: bridge(a, { p: [p[0], this.level * LEVEL, p[2]], f: [Math.sin(arrive), 0, Math.cos(arrive)] }, this.toolExtra || {}), snapped: false };
  },

  candidate() {
    if (!this.tool || !this.lastPick) return null;
    if (this.tool === 'bridge') {
      const at = this.lastPick.point || this.lastPick.plane;
      return at ? this.bridgeCandidate(at) : null;
    }
    const def = CATALOGUE[this.tool];
    // the eyedropper's settings, or the catalogue's; mirrored, curves and banks the other way
    const extra = { ...(this.toolExtra || {}) };
    const angle = extra.angle ?? def.angle, bank = extra.bank ?? def.bank;
    if (this.mirror && angle) extra.angle = -angle;
    if (this.mirror && bank) extra.bank = -bank;
    const at = this.lastPick.point || this.lastPick.plane;
    if (!at) return null;
    if (def.kind === 'sweep') {
      let best = null, bd = 1600;
      for (const c of this.ends) {
        const d = Math.hypot(c.p[0] - at[0], c.p[2] - at[2]) + Math.abs(c.p[1] - at[1]) * 0.5;
        if (d < bd) { bd = d; best = c; }
      }
      if (best) return { piece: attachTo(best, this.tool, extra), snapped: true };
    }
    // blocks and decorations go on what's under the mouse (stacked), roads on the build height
    const onSurface = def.kind !== 'sweep' && this.lastPick.point && !['hill'].includes(def.kind);
    const p = onSurface ? this.lastPick.point : (this.lastPick.plane || at);
    const y = onSurface ? Math.round(this.lastPick.point[1]) : this.level * LEVEL;
    let x = p[0], z = p[2];
    let yaw = this.rot;
    if (this.snap.grid) {
      yaw = Math.round(yaw / this.snap.rot) * this.snap.rot;
      const g = this.snap.size;
      const centred = ['cylinder', 'tree', 'hill'].includes(def.kind);
      if (centred || Math.abs(((yaw % 90) + 90) % 90) > 1e-6) {
        x = Math.round(x / g) * g + (centred && g === BLOCK ? g / 2 : 0);
        z = Math.round(z / g) * g + (centred && g === BLOCK ? g / 2 : 0);
      } else {
        // the entry edge on a grid line, the piece's middle on a cell's middle (or a line, for
        // an even number of blocks across)
        const f = [-Math.sin(yaw * DEG), -Math.cos(yaw * DEG)];
        const along = Math.abs(f[0]) > 0.5 ? 'x' : 'z';
        const w = def.width || BLOCK;
        const odd = g === BLOCK && Math.round(w / BLOCK) % 2 === 1 ? g / 2 : 0;
        if (along === 'x') {
          x = Math.round(x / g) * g;
          z = Math.round((z - odd) / g) * g + odd;
        } else {
          z = Math.round(z / g) * g;
          x = Math.round((x - odd) / g) * g + odd;
        }
      }
    }
    x = Math.max(-FIELD, Math.min(FIELD, x));
    z = Math.max(-FIELD, Math.min(FIELD, z));
    return { piece: makePiece(this.tool, { x, y, z, yaw, ...extra }), snapped: false };
  },

  updateGhost() {
    const c = this.candidate();
    this.view.setGhost(c ? c.piece : null, c ? (c.snapped ? '#9cffc4' : '#ffffff') : null);
    this.ghostCandidate = c;
  },

  place() {
    if (this.tool === 'bridge' && !this.bridgeFrom) {
      const at = this.lastPick && (this.lastPick.point || this.lastPick.plane);
      const end = at && this.nearestEnd(at);
      if (!end) { this.toast('Click near a green arrow: an open end of the track'); return; }
      this.bridgeFrom = end;
      this.toast('Now click another open end, or anywhere to draw a curve there');
      this.refresh(true);
      return;
    }
    const c = this.ghostCandidate || this.candidate();
    if (!c) return;
    const pc = c.piece;
    pc.id = Math.random().toString(36).slice(2, 10);
    this.commit(() => { this.track.pieces.push(pc); });
    if (this.tool === 'bridge') {
      // drawing on: the next curve starts where this one ended (unless it joined an end)
      this.bridgeFrom = c.joins ? null : worldConnectors(pc).find((e) => e.end === 1);
      this.refresh(true);
    }
    this.updateGhost();
  },

  // the open route's end joined back to the start's line with a bridge
  closeLoop() {
    const r = this.route;
    if (!r || r.closed) return;
    const startIn = this.ends.find((c) => c.piece.id === r.start.id && c.end === 0);
    const last = this.ends.find((c) => Math.hypot(c.p[0] - r.end.p[0], c.p[1] - r.end.p[1], c.p[2] - r.end.p[2]) < 2 && c.piece.id !== r.start.id) ||
      this.ends.find((c) => c.piece.id === r.start.id && c.end === 1);
    if (!startIn || !last) { this.toast('No open end to join to the start'); return; }
    const pc = bridge(last, startIn);
    this.commit(() => { this.track.pieces.push(pc); });
    this.toast('Loop closed with a bridge: tweak it on the right');
  },

  // ---------------------------------------------------------------- selection and the gizmo
  select(id, add = false) {
    if (!add) this.selection.clear();
    if (id) {
      if (add && this.selection.has(id)) this.selection.delete(id);
      else this.selection.add(id);
    }
    this.attachGizmo();
    this.refresh();
  },

  selectedPieces() { return this.track.pieces.filter((p) => this.selection.has(p.id)); },

  attachGizmo() {
    const sel = this.selectedPieces();
    const g = this.view.gizmo;
    if (!sel.length || this.tool) { this.detachGizmo(); return; }
    const first = sel[0];
    this.view.pivot.position.set(first.x || 0, first.y || 0, first.z || 0);
    this.view.pivot.rotation.set(0, 0, 0);
    this.view.pivot.updateMatrixWorld();
    g.attach(this.view.pivot);
    g.setMode(this.gizmoMode || 'translate');
    g.setTranslationSnap(this.snap.grid ? Math.min(this.snap.size, LEVEL) : null);
    g.setRotationSnap(this.snap.grid ? this.snap.rot * DEG : null);
    g.setSpace('world');
    if (!this.gizmoBound) {
      this.gizmoBound = true;
      g.addEventListener('mouseDown', () => {
        this.dragStart = { pivot: this.view.pivot.position.clone(), pieces: clone(this.selectedPieces()), before: this.snapshot() };
      });
      g.addEventListener('objectChange', () => this.gizmoMoved(false));
      g.addEventListener('mouseUp', () => this.gizmoMoved(true));
    }
  },

  detachGizmo() { this.view.gizmo.detach(); },

  // the selection follows the pivot: moved by its move, turned round it by its turn
  gizmoMoved(done) {
    if (!this.dragStart) return;
    const P0 = this.dragStart.pivot;
    const piv = this.view.pivot;
    const dq = piv.quaternion.clone();
    const dt = piv.position.clone().sub(P0);
    for (const orig of this.dragStart.pieces) {
      const pc = this.track.pieces.find((p) => p.id === orig.id);
      if (!pc) continue;
      const rel = new THREE.Vector3(orig.x || 0, orig.y || 0, orig.z || 0).sub(P0).applyQuaternion(dq);
      const pos = P0.clone().add(rel).add(dt);
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler((orig.pitch || 0) * DEG, (orig.yaw || 0) * DEG, (orig.roll || 0) * DEG, 'YXZ'));
      const e = new THREE.Euler().setFromQuaternion(dq.clone().multiply(q), 'YXZ');
      pc.x = round2(pos.x); pc.y = round2(pos.y); pc.z = round2(pos.z);
      pc.pitch = round2(e.x / DEG); pc.yaw = round2(e.y / DEG); pc.roll = round2(e.z / DEG);
      const obj = this.view.pieces.get(pc.id);
      if (obj) this.view.place(obj, pc);
    }
    if (done) {
      const before = this.dragStart.before;
      // a road piece dropped with its start by an open end locks onto it (a magnet)
      if (this.dragStart.pieces.length === 1) this.magnet(this.dragStart.pieces[0].id);
      this.dragStart = null;
      if (this.snapshot() !== before) {
        this.undo.push(before);
        this.redo = [];
        this.changed();
      }
      this.attachGizmo();
    }
  },

  magnet(id) {
    const pc = this.track.pieces.find((p) => p.id === id);
    if (!pc || pc.kind !== 'sweep') return;
    const mine = worldConnectors(pc).find((c) => c.end === 0);
    let best = null, bd = 320;
    for (const c of openEnds({ pieces: this.track.pieces.filter((p) => p.id !== id) })) {
      const d = Math.hypot(c.p[0] - mine.p[0], c.p[1] - mine.p[1], c.p[2] - mine.p[2]);
      // facing each other: the end out of its piece, ours back out of ours
      if (d < bd && c.f[0] * mine.f[0] + c.f[1] * mine.f[1] + c.f[2] * mine.f[2] < -0.85) { bd = d; best = c; }
    }
    if (!best) return;
    const { id: _, x, y, z, yaw, pitch, roll, ...shape } = pc;
    const at = attachTo(best, pc.type, shape);
    Object.assign(pc, { x: at.x, y: at.y, z: at.z, yaw: at.yaw, pitch: at.pitch, roll: 0 });
    const obj = this.view.pieces.get(pc.id);
    if (obj) this.view.place(obj, pc);
    this.toast('Snapped onto the end');
  },

  rotateSelection(sign) {
    const sel = this.selectedPieces();
    if (!sel.length) return;
    const step = this.snap.grid ? this.snap.rot : 15;
    const piv = [sel[0].x, sel[0].y, sel[0].z];
    this.commit(() => {
      const a = sign * step * DEG;
      for (const pc of sel) {
        const dx = pc.x - piv[0], dz = pc.z - piv[2];
        pc.x = round2(piv[0] + dx * Math.cos(a) + dz * Math.sin(a));
        pc.z = round2(piv[2] - dx * Math.sin(a) + dz * Math.cos(a));
        pc.yaw = round2(((pc.yaw || 0) + sign * step + 540) % 360 - 180);
      }
    });
    this.attachGizmo();
  },

  deleteSelection() {
    if (!this.selection.size) return;
    this.commit(() => { this.track.pieces = this.track.pieces.filter((p) => !this.selection.has(p.id)); });
    this.selection.clear();
    this.detachGizmo();
    this.refresh();
  },

  duplicate() {
    const sel = this.selectedPieces();
    if (!sel.length) return;
    // a road piece goes on after itself; the rest a block to the side
    const copies = sel.map((p) => ({ ...clone(p), id: Math.random().toString(36).slice(2, 10) }));
    if (sel.length === 1 && isSweep(sel[0])) {
      const end = worldConnectors(sel[0]).find((c) => c.end === 1);
      const { id, x, y, z, yaw, pitch, roll, ...shape } = copies[0];
      Object.assign(copies[0], attachTo(end, sel[0].type, shape), { id: copies[0].id });
    } else {
      for (const c of copies) c.x += BLOCK;
    }
    this.commit(() => { this.track.pieces.push(...copies); });
    this.selection = new Set(copies.map((c) => c.id));
    this.attachGizmo();
    this.refresh();
  },

  copy() {
    const sel = this.selectedPieces();
    if (sel.length) { this.clipboard = clone(sel); this.toast(`Copied ${sel.length}`); }
  },
  paste() {
    if (!this.clipboard || !this.lastPick) return;
    const at = this.lastPick.plane || this.lastPick.point;
    if (!at) return;
    const ox = this.clipboard[0].x, oz = this.clipboard[0].z;
    let dx = at[0] - ox, dz = at[2] - oz;
    if (this.snap.grid) { dx = Math.round(dx / this.snap.size) * this.snap.size; dz = Math.round(dz / this.snap.size) * this.snap.size; }
    const copies = this.clipboard.map((p) => ({ ...clone(p), id: Math.random().toString(36).slice(2, 10), x: p.x + dx, z: p.z + dz }));
    this.commit(() => { this.track.pieces.push(...copies); });
    this.selection = new Set(copies.map((c) => c.id));
    this.attachGizmo();
    this.refresh();
  },

  // ---------------------------------------------------------------- the properties panel
  renderProps() {
    const sel = this.selectedPieces();
    if (!sel.length) { this.props.hidden = true; return; }
    this.props.hidden = false;
    const pc = sel[0];
    const kids = [];
    if (sel.length > 1) {
      kids.push(el('h3', {}, `${sel.length} pieces`));
    } else {
      kids.push(el('h3', {}, CATALOGUE[pc.type]?.label || pc.type));
      for (const f of FIELDS[pc.path === 'bezier' ? 'bridge' : pc.kind] || []) {
        const [key, label, kind, a, b, step, show] = f;
        if (show && !show(pc)) continue;
        kids.push(this.fieldRow(pc, key, label, kind, a, b, step));
      }
    }
    // textures (for every selected piece)
    const texFields = TEX_FIELDS[pc.kind] || [];
    const groups = [...new Set(game.textures.map((t) => t.group))].filter((g) => g !== 'Signs');
    for (const [key, label] of texFields) {
      if (key === 'wallTex' && !(pc.wallL || pc.wallR)) continue;
      // the textures by where they're from: the editor's, or one of CTR's tracks
      const current = game.textures.find((t) => t.id === pc[key]);
      const shown = (this.texGroup && this.texGroup[key]) || (current ? current.group : 'Editor');
      const pick = el('select', { class: 'texgroup', onchange: () => { this.texGroup = { ...(this.texGroup || {}), [key]: pick.value }; this.renderProps(); } },
        ...groups.map((g) => el('option', { value: g }, g === 'Editor' ? 'Editor\'s' : `CTR: ${g}`)));
      pick.value = shown;
      kids.push(el('h3', {}, label, groups.length > 1 ? pick : null));
      kids.push(el('div', { class: 'swatches' }, ...game.textures.filter((t) => t.group === shown).map((t) => {
        const sw = el('div', { class: 'swatch' + ((pc[key] || '') === t.id ? ' on' : ''), title: t.label,
          onclick: () => this.commit(() => { for (const p of sel) if ((TEX_FIELDS[p.kind] || []).some(([k]) => k === key)) p[key] = t.id; }) });
        sw.style.backgroundImage = `url(${this.texThumb(t)})`;
        return sw;
      })));
    }
    if (sel.length === 1) {
      kids.push(el('h3', {}, 'Place'));
      for (const [key, label, step] of [['x', 'X', 64], ['y', 'Height', 64], ['z', 'Z', 64], ['yaw', 'Turn', 1], ['pitch', 'Pitch', 1], ['roll', 'Roll', 1]]) {
        const inp = el('input', { type: 'number', step, value: round2(pc[key] || 0),
          onchange: () => this.commit(() => { pc[key] = Number(inp.value) || 0; }) });
        kids.push(el('div', { class: 'row' }, el('label', {}, label), el('div', { class: 'ctl' }, inp)));
      }
    }
    kids.push(el('div', { class: 'buttons' },
      el('button', { onclick: () => this.duplicate(), title: 'Ctrl+D' }, 'Duplicate'),
      el('button', { onclick: () => this.rotateSelection(1), title: 'R' }, '⟲ Turn'),
      el('button', { onclick: () => this.setGizmo(this.gizmoMode === 'rotate' ? 'translate' : 'rotate'), title: 'M' }, this.gizmoMode === 'rotate' ? 'Gizmo: turn' : 'Gizmo: move'),
      el('button', { onclick: () => this.deleteSelection(), title: 'Delete' }, 'Delete')));
    this.props.replaceChildren(...kids);
  },

  fieldRow(pc, key, label, kind, a, b, step) {
    const def = CATALOGUE[pc.type] || {};
    // what the pieces take when a value isn't set (pieces.js)
    const builtIn = { pipeAngle: pc.kind === 'quarter' ? 85 : 80, flatPart: 0.5, profile: 'smooth', bankMode: 'const', shape: pc.kind === 'hill' ? 'round' : 'flat', tension: 1, slope: 0.35 };
    const value = pc[key] ?? def[key] ?? builtIn[key] ?? (kind === 'select' ? a[0] : 0);
    if (kind === 'text' || kind === 'color') {
      const inp = el('input', { type: kind, value: value || (kind === 'color' ? '#ffffff' : ''), class: kind === 'color' ? 'sky' : '',
        onchange: () => this.commit(() => { pc[key] = inp.value; }) });
      if (kind === 'text') inp.style.width = '150px';
      return el('div', { class: 'row' }, el('label', {}, label), el('div', { class: 'ctl' }, inp));
    }
    if (kind === 'select') {
      const s = el('select', { onchange: () => this.commit(() => { pc[key] = s.value || undefined; if (!s.value) delete pc[key]; }) },
        ...a.map((o) => el('option', { value: o }, o === '' ? 'none' : o)));
      s.value = value ?? '';
      return el('div', { class: 'row' }, el('label', {}, label), el('div', { class: 'ctl' }, s));
    }
    const range = el('input', { type: 'range', min: a, max: b, step, value });
    const num = el('input', { type: 'number', min: a, max: b, step, value });
    let before = null;
    const live = (v) => {
      if (before === null) before = this.snapshot();
      pc[key] = v;
      num.value = v;
      range.value = v;
      this.view.sync(this.track);
      this.refresh(true);
    };
    const done = () => {
      if (before !== null && before !== this.snapshot()) { this.undo.push(before); this.redo = []; this.changed(true); }
      before = null;
    };
    range.addEventListener('input', () => live(Number(range.value)));
    range.addEventListener('change', done);
    num.addEventListener('change', () => { live(Number(num.value) || 0); done(); });
    return el('div', { class: 'row' }, el('label', {}, label), el('div', { class: 'ctl' }, range, num));
  },

  texThumb(t) {
    if (!this.texThumbs) this.texThumbs = {};
    if (!this.texThumbs[t.id]) {
      const c = document.createElement('canvas');
      c.width = c.height = 48;
      c.getContext('2d').drawImage(t.canvas, 0, 0, 48, 48);
      this.texThumbs[t.id] = c.toDataURL();
    }
    return this.texThumbs[t.id];
  },

  setGizmo(mode) {
    this.gizmoMode = mode;
    this.view.gizmo.setMode(mode);
    this.renderProps();
  },

  // ---------------------------------------------------------------- tracks
  newTrack() {
    if (this.track.pieces.length && !confirm('Start a new, empty track? (This one stays in the undo list.)')) return;
    this.commit(() => { this.track = newTrack('New track'); });
    this.nameInput.value = this.track.name;
    this.selection.clear();
    this.detachGizmo();
    this.refresh();
  },

  fileName() { return (this.track.name || 'My track').replace(/[^A-Za-z0-9 _.-]/g, '').trim().slice(0, 64) || 'track'; },

  async save() {
    const name = this.fileName();
    library.put(name, this.track);
    try {
      const r = await fetch(`tracks/${encodeURIComponent(name)}.json`, { method: 'PUT', body: JSON.stringify(this.track, null, 1) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      this.toast(`Saved "${name}" (tracks/${name}.json)`);
    } catch (e) {
      // an older server (play.sh says so): the browser keeps it
      this.toast(`Saved "${name}" in this browser (restart ./play.sh to save it to tracks/ too)`);
    }
  },

  async openDialog() {
    let list = [];
    try {
      const r = await fetch('tracks/', { cache: 'no-store' });
      if (r.ok) list = await r.json();
    } catch { /* none */ }
    // and the browser's own, the ones the server hasn't
    for (const [name, t] of Object.entries(library.all())) {
      if (!list.some((x) => x.name === name)) list.push({ name, mtime: t.mtime, local: true });
    }
    const close = () => { this.dialog.hidden = true; };
    const items = list.map((t) => el('div', { class: 'item' },
      el('span', { class: 'n', onclick: async () => {
        let data = null;
        if (t.local) data = library.get(t.name);
        else {
          const r = await fetch(`tracks/${encodeURIComponent(t.name)}.json`, { cache: 'no-store' });
          if (r.ok) data = await r.json();
        }
        if (!data) return;
        const loaded = normalise(data);
        this.commit(() => { this.track = loaded; });
        this.nameInput.value = this.track.name;
        this.selection.clear();
        this.detachGizmo();
        this.frameTrack();
        this.refresh();
        close();
      } }, t.name),
      el('span', { class: 'muted' }, new Date(t.mtime).toLocaleString()),
      el('button', { onclick: async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${t.name}"?`)) return;
        library.remove(t.name);
        if (!t.local) await fetch(`tracks/${encodeURIComponent(t.name)}.json`, { method: 'DELETE' }).catch(() => {});
        this.openDialog();
      } }, '✕')));
    this.dialog.replaceChildren(
      el('h3', {}, 'Open a track'),
      ...(items.length ? items : [el('p', { class: 'muted' }, 'No saved tracks yet: Save (Ctrl+S) puts one here.')]),
      el('h3', { style: 'margin-top:12px' }, 'Examples'),
      ...examples(game.textures).map(([name, make]) => el('div', { class: 'item' },
        el('span', { class: 'n', onclick: () => {
          const t = normalise(make());
          this.commit(() => { this.track = t; });
          this.selection.clear();
          this.detachGizmo();
          this.frameTrack();
          this.refresh();
          close();
        } }, name), el('span', { class: 'muted' }, 'built in'))),
      el('div', { class: 'buttons', style: 'margin-top:10px; display:flex; gap:6px' },
        el('button', { onclick: () => this.exportTrack(), title: 'Download this track as a file' }, 'Export file'),
        el('button', { onclick: () => this.importTrack(close), title: 'Open a track file' }, 'Import file'),
        el('span', { class: 'grow' }),
        el('button', { onclick: close }, 'Close')));
    this.dialog.hidden = false;
  },

  exportTrack() {
    const blob = new Blob([JSON.stringify(this.track, null, 1)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: `${this.fileName()}.ctrtrack.json` });
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  importTrack(done) {
    const input = el('input', { type: 'file', accept: '.json,application/json' });
    input.addEventListener('change', async () => {
      const f = input.files[0];
      if (!f) return;
      try {
        const loaded = normalise(JSON.parse(await f.text()));
        this.commit(() => { this.track = loaded; });
        this.selection.clear();
        this.detachGizmo();
        this.frameTrack();
        this.refresh();
        this.toast(`Imported "${loaded.name}"`);
        done();
      } catch (e) {
        this.toast(`Not a track file: ${e.message}`);
      }
    });
    input.click();
  },

  frameTrack() {
    const pts = this.track.pieces.map((p) => [p.x, p.y, p.z]);
    if (pts.length) this.view.focus(pts);
  },

  // ---------------------------------------------------------------- driving
  drive(fromHere = false) {
    if (this.mode === 'drive') return;
    let test = null;
    if (fromHere) {
      const at = this.lastPick && (this.lastPick.point || this.lastPick.plane);
      const f = new THREE.Vector3();
      this.view.camera.getWorldDirection(f);
      const p = at || [this.view.controls.target.x, this.view.controls.target.y, this.view.controls.target.z];
      test = { p: [p[0], p[1] + 80, p[2]], yaw: Math.atan2(-f.x, -f.z) };
    }
    if (!this.ready) { this.toast('The game is still loading…'); return; }
    this.lastTest = test;
    try { localStorage.setItem(AUTOSAVE, this.snapshot()); } catch { /* full */ }
    const out = game.drive(this.track, test);
    if (!out) return;
    window.ctrEditor.last = out;
    this.mode = 'drive';
    this.view.visible = false;
    this.root.hidden = true;
    this.trail = [];
    const canvas = document.getElementById('canvas');
    canvas.focus();
    this.driveHint.classList.remove('fade');
    clearTimeout(this.hintTimer);
    this.hintTimer = setTimeout(() => this.driveHint.classList.add('fade'), 2500);
    clearInterval(this.trailTimer);
    // the drive's line (shown when you're back) and its laps' times
    this.laps = [];
    let lap = 0, lapStart = 0, tick = 0;
    this.trailTimer = setInterval(() => {
      const s = window.ctr.state();
      if (!s.kart) return;
      if (s.kart.lap > lap) {
        if (lap === 0 || this.laps.length || s.kart.lap - lap === 1) this.laps.push(s.eventTime - lapStart);
        lap = s.kart.lap;
        lapStart = s.eventTime;
      } else if (s.kart.lap < lap || s.eventTime < lapStart) {
        lap = s.kart.lap;     // started over (Backspace)
        lapStart = s.eventTime;
        this.laps = [];
      }
      if (++tick % 3 === 0) this.trail.push([s.kart.x, s.kart.y, s.kart.z]);
      if (this.trail.length > 6000) this.trail.shift();
    }, 40);
  },

  restart() {
    const out = game.drive(this.track, this.lastTest || null);
    if (out) window.ctrEditor.last = out;
    this.trail = [];
  },

  back() {
    if (this.mode !== 'drive') return;
    game.pause(true);
    window.ctr.release();
    clearInterval(this.trailTimer);
    this.mode = 'edit';
    this.root.hidden = false;
    this.view.visible = true;
    this.driveHint.classList.add('fade');
    this.refresh(true);
  },

  // ---------------------------------------------------------------- input
  bindInput() {
    const cv = this.view.renderer.domElement;
    let down = null;
    // a trackpad's camera: Alt + drag turns it, Space + drag moves it (the left button's, while held)
    let spaceHeld = false;
    const leftButton = (alt) => {
      this.view.controls.mouseButtons.LEFT = spaceHeld ? THREE.MOUSE.PAN : alt ? THREE.MOUSE.ROTATE : -1;
    };
    // a box drawn over empty ground selects what's in it
    const box = el('div', { class: 'boxsel', hidden: true });
    this.root.appendChild(box);
    cv.addEventListener('pointermove', (ev) => {
      this.lastPick = this.view.pick(ev, this.level * LEVEL);
      if (this.tool) this.updateGhost();
      if (down && down.box) {
        const x0 = Math.min(down.x, ev.clientX), y0 = Math.min(down.y, ev.clientY);
        Object.assign(box.style, { left: `${x0}px`, top: `${y0}px`, width: `${Math.abs(ev.clientX - down.x)}px`, height: `${Math.abs(ev.clientY - down.y)}px` });
        box.hidden = Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 6;
      }
    });
    cv.addEventListener('pointerdown', (ev) => {
      leftButton(ev.altKey);
      down = { x: ev.clientX, y: ev.clientY, button: ev.button, t: performance.now() };
      // a box: the left button on nothing, no tool, no gizmo handle, no camera key
      if (ev.button === 0 && !this.tool && !ev.altKey && !spaceHeld && !this.view.gizmo.axis) {
        const pick = this.view.pick(ev, this.level * LEVEL);
        if (!pick.piece) down.box = true;
      }
    });
    cv.addEventListener('pointerup', (ev) => {
      if (!down) return;
      const moved = Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5;
      const b = down.button;
      const wasBox = down.box;
      const start = down;
      down = null;
      box.hidden = true;
      if (wasBox && moved) { this.boxSelect(start, ev); return; }
      if (moved || this.view.gizmo.dragging) return;
      const pick = this.view.pick(ev, this.level * LEVEL);
      this.lastPick = pick;
      if (b === 0) {
        if (ev.altKey && pick.piece) { this.eyedropper(pick.piece); return; }
        if (this.tool) { this.place(); return; }
        if (this.view.gizmo.axis) return;   // a click on the gizmo
        this.select(pick.piece, ev.shiftKey);
      } else if (b === 2 && pick.piece && !this.tool) {
        this.commit(() => { this.track.pieces = this.track.pieces.filter((p) => p.id !== pick.piece); });
        this.selection.delete(pick.piece);
        this.attachGizmo();
        this.refresh();
      } else if (b === 2 && this.tool) {
        this.pickTool(this.tool);   // right click puts the tool down
      }
    });
    cv.addEventListener('contextmenu', (e) => e.preventDefault());

    // the editor's keys go no further (the game, held, would see them when it's back)
    const keys = new Set();
    window.addEventListener('keydown', (ev) => {
      if (this.mode === 'drive') {
        if (ev.code === 'Tab' || ev.code === 'Escape') {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          this.back();
        } else if (ev.code === 'Backspace') {
          // start over at the line, at once (the same track)
          ev.preventDefault();
          ev.stopImmediatePropagation();
          this.restart();
        }
        return;
      }
      const typing = ev.target && (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT' || ev.target.tagName === 'TEXTAREA');
      ev.stopImmediatePropagation();
      if (typing && ev.code !== 'Tab' && ev.code !== 'Escape') return;
      const ctrl = ev.ctrlKey || ev.metaKey;
      const k = ev.code;
      let handled = true;
      if (k === 'Tab') this.drive(ev.shiftKey);
      else if (k === 'Escape') {
        if (!this.help.hidden || !this.dialog.hidden) { this.help.hidden = true; this.dialog.hidden = true; }
        else if (this.tool === 'bridge' && this.bridgeFrom) { this.bridgeFrom = null; this.updateGhost(); this.refresh(true); }
        else if (this.tool) this.pickTool(this.tool);
        else { this.selection.clear(); this.detachGizmo(); this.refresh(); }
        if (typing) ev.target.blur();
      } else if (ctrl && k === 'KeyZ') ev.shiftKey ? this.doRedo() : this.doUndo();
      else if (ctrl && k === 'KeyY') this.doRedo();
      else if (ctrl && k === 'KeyS') this.save();
      else if (ctrl && k === 'KeyD') this.duplicate();
      else if (ctrl && k === 'KeyC') this.copy();
      else if (ctrl && k === 'KeyV') this.paste();
      else if (ctrl) handled = false;
      else if (k === 'KeyR') {
        // on an open end a piece can only face on: R flips it, as T does
        if (this.tool && this.ghostCandidate && this.ghostCandidate.snapped) { this.mirror = !this.mirror; this.updateGhost(); }
        else if (this.tool) { this.rot = (this.rot + (ev.shiftKey ? -1 : 1) * (this.snap.grid ? this.snap.rot : 15) + 360) % 360; this.updateGhost(); }
        else this.rotateSelection(ev.shiftKey ? -1 : 1);
      } else if (k === 'KeyT') { this.mirror = !this.mirror; this.updateGhost(); }
      else if (k === 'Space') { spaceHeld = true; leftButton(false); }
      else if (k === 'KeyG') this.toggleSnap();
      else if (k === 'KeyM') this.setGizmo(this.gizmoMode === 'rotate' ? 'translate' : 'rotate');
      else if (k === 'KeyH' || ev.key === '?') this.toggleHelp();
      else if (k === 'KeyF') this.focusSelection();
      else if (k === 'KeyV') this.topView();
      else if (k === 'PageUp' || k === 'KeyE') { this.level = Math.min(100, this.level + 1); this.refresh(true); this.updateGhost(); }
      else if (k === 'PageDown' || k === 'KeyQ') { this.level = Math.max(-4, this.level - 1); this.refresh(true); this.updateGhost(); }
      else if (k === 'Delete' || k === 'Backspace') this.deleteSelection();
      else if (/^Digit[1-9]$/.test(k)) {
        // the palette's tab, by number
        const types = Object.entries(CATALOGUE).filter(([, d]) => d.group === this.group).map(([t]) => t);
        const t = types[Number(k.slice(5)) - 1];
        if (t) this.pickTool(t);
      } else if (k === 'Comma' || k === 'Period') {
        const groups = [...new Set(Object.values(CATALOGUE).map((d) => d.group))];
        this.group = groups[(groups.indexOf(this.group) + (k === 'Period' ? 1 : groups.length - 1)) % groups.length];
        this.renderPalette();
      }
      else if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(k)) keys.add(k);
      else handled = false;
      if (handled) ev.preventDefault();
    }, true);
    // key-ups go on to the game, held or not: a key let go while you build (the gas held through
    // Tab) would stay down in it otherwise
    window.addEventListener('keyup', (ev) => {
      keys.delete(ev.code);
      if (ev.code === 'Space') { spaceHeld = false; leftButton(false); }
    }, true);

    window.addEventListener('blur', () => keys.clear());
    this.keys = keys;
  },

  // the pieces whose middles are in the box (screen coordinates), added with Shift
  boxSelect(a, ev) {
    const r = this.view.renderer.domElement.getBoundingClientRect();
    const x0 = Math.min(a.x, ev.clientX), x1 = Math.max(a.x, ev.clientX), y0 = Math.min(a.y, ev.clientY), y1 = Math.max(a.y, ev.clientY);
    if (!ev.shiftKey) this.selection.clear();
    const v = new THREE.Vector3();
    for (const pc of this.track.pieces) {
      const obj = this.view.pieces.get(pc.id);
      if (!obj) continue;
      new THREE.Box3().setFromObject(obj).getCenter(v).project(this.view.camera);
      const sx = r.left + ((v.x + 1) / 2) * r.width, sy = r.top + ((1 - v.y) / 2) * r.height;
      if (v.z < 1 && sx >= x0 && sx <= x1 && sy >= y0 && sy <= y1) this.selection.add(pc.id);
    }
    this.attachGizmo();
    this.refresh();
  },

  tick(dt) {
    if (!this.keys || !this.keys.size) return;
    const dist = this.view.camera.position.distanceTo(this.view.controls.target);
    const speed = Math.max(1500, dist * 1.2) * dt;
    let dx = 0, dz = 0;
    if (this.keys.has('KeyW') || this.keys.has('ArrowUp')) dz += speed;
    if (this.keys.has('KeyS') || this.keys.has('ArrowDown')) dz -= speed;
    if (this.keys.has('KeyD') || this.keys.has('ArrowRight')) dx += speed;
    if (this.keys.has('KeyA') || this.keys.has('ArrowLeft')) dx -= speed;
    if (dx || dz) this.view.pan(dx, dz);
  },

  // straight down on the track (V), and back to where the camera was
  topView() {
    const v = this.view, t = v.controls.target;
    if (this.savedCamera) {
      v.camera.position.copy(this.savedCamera);
      this.savedCamera = null;
      return;
    }
    this.savedCamera = v.camera.position.clone();
    const d = Math.max(6000, v.camera.position.distanceTo(t));
    v.camera.position.set(t.x, t.y + d, t.z + 1);
  },

  focusSelection() {
    const sel = this.selectedPieces();
    const pts = (sel.length ? sel : this.track.pieces).map((p) => [p.x, p.y, p.z]);
    this.view.focus(pts);
  },

  eyedropper(id) {
    const pc = this.track.pieces.find((p) => p.id === id);
    if (!pc) return;
    this.tool = pc.type;
    this.rot = pc.yaw || 0;
    this.mirror = false;
    const { id: _, x, y, z, yaw, pitch, roll, ...shape } = pc;
    this.toolExtra = shape;
    this.selection.clear();
    this.detachGizmo();
    this.renderPalette();
    this.refresh();
    this.toast(`Picked ${CATALOGUE[pc.type].label}`);
  },
};

const round2 = (v) => Math.round(v * 100) / 100;

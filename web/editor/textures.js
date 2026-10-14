// The editor's textures, drawn here (nothing from a disc): roads, ground, walls, trims, and a
// few plain colours. Each is a power-of-two square that repeats; the game samples them from a
// borderless "CTRW" atlas (engine/platform/native_renderer.c) and the editor's view from the
// same canvases.

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5; s >>>= 0;
    return s / 4294967296;
  };
}

// value noise that tiles over n cells
function tilingNoise(size, cells, seed) {
  const r = rng(seed);
  const g = Array.from({ length: cells * cells }, () => r());
  const at = (x, y) => g[((y % cells + cells) % cells) * cells + ((x % cells + cells) % cells)];
  const out = new Float32Array(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const fx = (x / size) * cells, fy = (y / size) * cells;
      const ix = Math.floor(fx), iy = Math.floor(fy);
      let tx = fx - ix, ty = fy - iy;
      tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty);
      const a = at(ix, iy), b = at(ix + 1, iy), c = at(ix, iy + 1), d = at(ix + 1, iy + 1);
      out[y * size + x] = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
    }
  }
  return out;
}

function fractal(size, seed, octaves = [[4, 0.5], [8, 0.25], [16, 0.15], [32, 0.1]]) {
  const out = new Float32Array(size * size);
  octaves.forEach(([cells, w], k) => {
    const n = tilingNoise(size, cells, seed * 31 + k);
    for (let i = 0; i < out.length; i++) out[i] += n[i] * w;
  });
  let total = 0;
  for (const [, w] of octaves) total += w;
  for (let i = 0; i < out.length; i++) out[i] /= total;
  return out;
}

function canvas(size) {
  const c = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(size, size) : Object.assign(document.createElement('canvas'), { width: size, height: size });
  return c;
}

// fill from a per-texel function (x, y, noise) -> [r, g, b, a?]
function painted(size, seed, fn) {
  const c = canvas(size);
  const cx = c.getContext('2d');
  const img = cx.createImageData(size, size);
  const n = fractal(size, seed);
  const r = rng(seed + 99);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const v = fn(x, y, n[y * size + x], r);
      const o = 4 * (y * size + x);
      img.data[o] = v[0]; img.data[o + 1] = v[1]; img.data[o + 2] = v[2]; img.data[o + 3] = v[3] ?? 255;
    }
  }
  cx.putImageData(img, 0, 0);
  return c;
}

const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const shade = (c, k) => c.map((v) => Math.max(0, Math.min(255, Math.round(v * k))));

function asphalt(size, seed, base = [78, 80, 86]) {
  return painted(size, seed, (x, y, n, r) => shade(base, 0.8 + n * 0.35 + (r() - 0.5) * 0.18));
}

// a road: asphalt, white edge lines and a dashed middle line, across u (the road's width)
function road(size, seed, base, line = [235, 235, 225], dash = [250, 205, 60], edges = true) {
  const a = asphalt(size, seed, base);
  const cx = a.getContext('2d');
  if (edges) {
    cx.fillStyle = `rgb(${line})`;
    cx.fillRect(size * 0.04, 0, size * 0.03, size);
    cx.fillRect(size * 0.93, 0, size * 0.03, size);
  }
  if (dash) {
    cx.fillStyle = `rgb(${dash})`;
    cx.fillRect(size * 0.49, 0, size * 0.02, size * 0.5);
  }
  return a;
}

function stripes(size, colors, count, vertical = false) {
  const c = canvas(size);
  const cx = c.getContext('2d');
  const w = size / count;
  for (let i = 0; i < count; i++) {
    cx.fillStyle = colors[i % colors.length];
    if (vertical) cx.fillRect(0, i * w, size, w); else cx.fillRect(i * w, 0, w, size);
  }
  return c;
}

function checker(size, n, a, b) {
  const c = canvas(size);
  const cx = c.getContext('2d');
  const w = size / n;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      cx.fillStyle = (i + j) % 2 ? a : b;
      cx.fillRect(i * w, j * w, w, w);
    }
  }
  return c;
}

function boost(size) {
  const c = canvas(size);
  const cx = c.getContext('2d');
  cx.fillStyle = '#d0381a';
  cx.fillRect(0, 0, size, size);
  // two chevrons pointing along v (forward), yellow on orange
  cx.fillStyle = '#ffd34d';
  for (const y0 of [size * 0.08, size * 0.58]) {
    cx.beginPath();
    cx.moveTo(size * 0.12, y0 + size * 0.34);
    cx.lineTo(size * 0.5, y0);
    cx.lineTo(size * 0.88, y0 + size * 0.34);
    cx.lineTo(size * 0.88, y0 + size * 0.46);
    cx.lineTo(size * 0.5, y0 + size * 0.12);
    cx.lineTo(size * 0.12, y0 + size * 0.46);
    cx.closePath();
    cx.fill();
  }
  return c;
}

function bricks(size, seed, mortar = [190, 180, 160], brick = [150, 70, 50]) {
  const rows = 8, cols = 4;
  const r = rng(seed);
  const tint = Array.from({ length: rows * cols * 2 }, () => 0.8 + r() * 0.35);
  return painted(size, seed, (x, y, n) => {
    const row = Math.floor((y / size) * rows);
    const off = row % 2 ? 0.5 : 0;
    const fx = (x / size) * cols + off;
    const col = Math.floor(fx) % cols;
    const fy = (y / size) * rows - row;
    const ex = fx - Math.floor(fx);
    if (fy < 0.1 || ex < 0.05) return shade(mortar, 0.85 + n * 0.3);
    return shade(brick, tint[row * cols + col] * (0.85 + n * 0.3));
  });
}

function planks(size, seed) {
  const n = 6;
  const r = rng(seed);
  const tint = Array.from({ length: n }, () => 0.8 + r() * 0.3);
  const grain = fractal(size, seed + 5, [[2, 0.5], [64, 0.5]]);
  return painted(size, seed, (x, y) => {
    const k = Math.floor((x / size) * n);
    const fx = (x / size) * n - k;
    if (fx < 0.06) return [70, 45, 25];
    const g = grain[y * size + Math.floor(x / 4) * 4];
    return shade([170, 120, 70], tint[k] * (0.75 + g * 0.5));
  });
}

function plate(size, seed) {
  const c = painted(size, seed, (x, y, n) => shade([150, 155, 165], 0.85 + n * 0.25));
  const cx = c.getContext('2d');
  cx.strokeStyle = 'rgba(40,40,50,0.8)';
  cx.lineWidth = 3;
  cx.strokeRect(2, 2, size - 4, size - 4);
  cx.fillStyle = 'rgba(60,60,70,0.9)';
  for (const [x, y] of [[12, 12], [size - 12, 12], [12, size - 12], [size - 12, size - 12]]) {
    cx.beginPath(); cx.arc(x, y, 5, 0, 7); cx.fill();
  }
  return c;
}

function plain(size, color, seed) {
  return painted(size, seed, (x, y, n) => shade(color, 0.92 + n * 0.12));
}

function water(size, seed) {
  const n2 = fractal(size, seed + 3, [[4, 0.6], [8, 0.4]]);
  return painted(size, seed, (x, y, n) => mix([40, 110, 190], [120, 200, 240], Math.max(0, n2[y * size + x] * 1.6 - 0.5)));
}

function lava(size, seed) {
  return painted(size, seed, (x, y, n) => mix([120, 20, 10], [255, 190, 40], Math.pow(n, 1.6)));
}

function rainbow(size) {
  const c = canvas(size);
  const cx = c.getContext('2d');
  const colors = ['#ff4b4b', '#ff9f2e', '#ffe14a', '#5ce65c', '#4bc1ff', '#7a6bff', '#d65cff'];
  const w = size / colors.length;
  colors.forEach((col, i) => { cx.fillStyle = col; cx.fillRect(i * w, 0, w + 1, size); });
  return c;
}

// The catalogue: id (a quad's texture), label, the terrain it drives like (namespace_Level.h
// TerrainType: 0 asphalt, 1 dirt, 2 grass, 3 wood, 5 stone, 6 ice, 9 snow, 12 metal, 13 fast
// water, 14 mud), and its canvas.
export function makeTextures() {
  const S = 256;
  const list = [
    ['road', 'Road', 0, () => road(S, 1, [76, 78, 84])],
    ['road-plain', 'Asphalt', 0, () => asphalt(S, 2)],
    ['road-red', 'Red road', 0, () => road(S, 3, [150, 60, 50], [240, 230, 220], null)],
    ['road-blue', 'Blue road', 0, () => road(S, 4, [50, 80, 150], [240, 240, 255], null)],
    ['dirt', 'Dirt', 1, () => painted(S, 5, (x, y, n) => shade([150, 105, 65], 0.75 + n * 0.5))],
    ['grass', 'Grass', 2, () => painted(S, 6, (x, y, n, r) => shade([78, 150, 60], 0.75 + n * 0.45 + (r() - 0.5) * 0.15))],
    ['sand', 'Sand', 1, () => painted(S, 7, (x, y, n) => shade([225, 195, 130], 0.85 + n * 0.25))],
    ['snow', 'Snow', 9, () => painted(S, 8, (x, y, n) => shade([235, 240, 250], 0.88 + n * 0.14))],
    ['ice', 'Ice', 6, () => painted(S, 9, (x, y, n) => mix([150, 200, 235], [235, 250, 255], n))],
    ['wood', 'Wood', 3, () => planks(S, 10)],
    ['metal', 'Metal', 12, () => plate(S, 11)],
    ['stone', 'Stone', 5, () => painted(S, 12, (x, y, n) => shade([140, 135, 125], 0.7 + n * 0.55))],
    ['brick', 'Brick', 5, () => bricks(S, 13)],
    ['concrete', 'Concrete', 0, () => painted(S, 14, (x, y, n, r) => shade([175, 172, 165], 0.85 + n * 0.2 + (r() - 0.5) * 0.08))],
    ['kerb', 'Kerb', 0, () => stripes(S, ['#e23b2e', '#f4f1ea'], 4, true)],
    ['hazard', 'Hazard', 12, () => {
      const c = canvas(S); const cx = c.getContext('2d');
      cx.fillStyle = '#1c1c1c'; cx.fillRect(0, 0, S, S);
      cx.fillStyle = '#f5c518';
      for (let i = -2; i < 4; i++) { cx.beginPath(); cx.moveTo(i * S / 2, 0); cx.lineTo(i * S / 2 + S / 4, 0); cx.lineTo(i * S / 2 + S / 4 + S, S); cx.lineTo(i * S / 2 + S, S); cx.fill(); }
      return c;
    }],
    ['checker', 'Checker', 0, () => checker(S, 8, '#111', '#f2f2f2')],
    ['boost', 'Boost pad', 0, () => boost(S)],
    ['water', 'Water', 13, () => water(S, 15)],
    ['lava', 'Lava', 14, () => lava(S, 16)],
    ['mud', 'Mud', 14, () => painted(S, 17, (x, y, n) => shade([95, 70, 45], 0.7 + n * 0.5))],
    ['rainbow', 'Rainbow', 0, () => rainbow(S)],
    ['white', 'White', 0, () => plain(S, [235, 235, 235], 20)],
    ['red', 'Red', 0, () => plain(S, [210, 50, 40], 21)],
    ['orange', 'Orange', 0, () => plain(S, [240, 140, 30], 22)],
    ['yellow', 'Yellow', 0, () => plain(S, [245, 210, 50], 23)],
    ['green', 'Green', 0, () => plain(S, [60, 170, 70], 24)],
    ['blue', 'Blue', 0, () => plain(S, [50, 110, 210], 25)],
    ['purple', 'Purple', 0, () => plain(S, [140, 70, 190], 26)],
    ['black', 'Black', 0, () => plain(S, [35, 35, 38], 27)],
  ];
  return list.map(([id, label, terrain, draw]) => withAverage({ id, label, terrain, size: S, canvas: draw(), group: 'Editor' }));
}

function withAverage(t) {
  const px = t.canvas.getContext('2d').getImageData(0, 0, t.size, t.size).data;
  const average = [0, 0, 0];
  for (let i = 0; i < px.length; i += 4) { average[0] += px[i]; average[1] += px[i + 1]; average[2] += px[i + 2]; }
  return { ...t, average: average.map((v) => v / (t.size * t.size)) };
}

// CTR's own track textures, when play.sh has taken them from your disc (tools/editor/ctrtex.py:
// lev/editor_ctrtex.png and .json): grouped by track
export async function loadCtrTextures() {
  try {
    const list = await (await fetch('lev/editor_ctrtex.json', { cache: 'no-store' })).json();
    const img = await createImageBitmap(await (await fetch('lev/editor_ctrtex.png', { cache: 'no-store' })).blob());
    return list.textures.map((t) => {
      const c = canvas(list.cell);
      const cx = c.getContext('2d');
      cx.drawImage(img, (t.cell % list.row) * list.cell, Math.floor(t.cell / list.row) * list.cell, list.cell, list.cell, 0, 0, list.cell, list.cell);
      return withAverage({ id: t.id, label: t.label, terrain: t.terrain, size: list.cell, canvas: c, group: t.track });
    });
  } catch {
    return [];
  }
}

// a sign's face: its text, fitted, on its colour (drawn 2:1 and squeezed into the square cell:
// the board it goes on is twice as wide as it's tall)
export const SIGN_SLOTS = 16;
export function drawSign(c, text, bg = '#1d4fd8', fg = '#ffffff') {
  const W = 512, H = 256;
  const wide = canvas(W);
  wide.width = W; wide.height = H;
  const cx = wide.getContext('2d');
  cx.fillStyle = bg;
  cx.fillRect(0, 0, W, H);
  cx.strokeStyle = fg;
  cx.lineWidth = 10;
  cx.strokeRect(10, 10, W - 20, H - 20);
  const lines = String(text || '').split(/\n|\\n/).slice(0, 3);
  let size = 120;
  cx.font = `900 ${size}px system-ui, sans-serif`;
  while (size > 20 && (lines.some((l) => cx.measureText(l).width > W - 60) || size * lines.length * 1.1 > H - 50)) {
    size -= 4;
    cx.font = `900 ${size}px system-ui, sans-serif`;
  }
  cx.fillStyle = fg;
  cx.textAlign = 'center';
  cx.textBaseline = 'middle';
  lines.forEach((l, i) => cx.fillText(l, W / 2, H / 2 + (i - (lines.length - 1) / 2) * size * 1.08));
  const out = c.getContext('2d');
  out.clearRect(0, 0, c.width, c.height);
  out.drawImage(wide, 0, 0, c.width, c.height);
}

export function signSlots() {
  return Array.from({ length: SIGN_SLOTS }, (_, k) => {
    const c = canvas(256);
    drawSign(c, '');
    return { id: `sign-${k}`, label: `Sign ${k + 1}`, terrain: 0, size: 256, canvas: c, group: 'Signs', average: [40, 80, 200] };
  });
}

// A borderless "CTRW" atlas (4 layers of 1024 a row, textures at 64-aligned origins): the
// file the game loads (assets/dust2/atlas.rgba) and where each texture went.
export function buildAtlas(textures) {
  const LAYER = 1024;
  const rects = {};
  // shelf-pack each layer: textures are squares of 64-multiples, biggest first
  const sorted = [...textures].sort((a, b) => b.size - a.size);
  let layer = 0, x = 0, y = 0, rowH = 0;
  for (const t of sorted) {
    if (x + t.size > LAYER) { x = 0; y += rowH; rowH = 0; }
    if (y + t.size > LAYER) { layer++; x = 0; y = 0; rowH = 0; }
    if (layer === 15) layer++;   // layer 15's CLUT is the never-drawn one (track.INVISIBLE)
    rects[t.id] = { layer, x, y, size: t.size };
    x += t.size;
    rowH = Math.max(rowH, t.size);
  }
  const layers = layer + 1;
  const width = 4 * LAYER, height = Math.ceil(layers / 4) * LAYER;
  const file = new Uint8Array(12 + width * height * 4);
  const dv = new DataView(file.buffer);
  dv.setUint32(0, 0x57525443, true);   // "CTRW"
  dv.setUint32(4, width, true);
  dv.setUint32(8, height, true);
  for (const t of textures) {
    const r = rects[t.id];
    const px = t.canvas.getContext('2d').getImageData(0, 0, t.size, t.size).data;
    const ox = (r.layer % 4) * LAYER + r.x, oy = Math.floor(r.layer / 4) * LAYER + r.y;
    for (let row = 0; row < t.size; row++) {
      file.set(px.subarray(row * t.size * 4, (row + 1) * t.size * 4), 12 + ((oy + row) * width + ox) * 4);
    }
  }
  return { file, rects, width, height };
}

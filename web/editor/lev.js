// CTR level files (LEV) in the page: tools/levwriter.py's mesh-only level (a world's tile:
// quadblocks, vertices, a BSP over them and their texture layouts), for the editor's tiles.
// The layout is the game's (engine/include/namespace_Level.h); NOTES.md has the details.
//
// A quad (what the editor's pieces make, compile.js) is
//   { pos: 9 [x, y, z] in slot order 0 4 1 / 5 6 7 / 2 8 3 (CTR ints, y up),
//     faces: 4 layouts (or null), low: a layout, color: 9 [r, g, b] (0x80 = 1),
//     flags, terrain, checkpoint (255: none), doubleSided, triangle }
// and its front, the side collision sees, is (p2 - p0) x (p1 - p0).
// A layout is { uv: 4 [u, v] (0-255), clut, tpage }.

export const FLAG_TRIGGER = 0x0040;
export const FLAG_KILL_PLANE = 0x0200;
export const FLAG_CAMERA_SEARCH = 0x0800;
export const FLAG_GROUND = 0x1000;
export const FLAG_COLLISION_SURFACE = 0x2000;
export const FLAG_SKIP_WATER_LIST = 0x8000;

const QUAD_SIZE = 0x5c;
const VERT_SIZE = 0x10;
const BSP_SIZE = 0x20;
const LEVEL_SIZE = 0x1f4;
const BSP_NEAR_FIRST = 0x0d02;

// Hi-LOD triangles as COLL tests them, then low LOD (levwriter.HI_TRIS, LO_TRIS)
const HI_TRIS = [[0, 4, 5], [4, 6, 5], [6, 4, 1], [5, 6, 2], [8, 6, 7], [7, 3, 8], [1, 7, 6], [2, 6, 8]];
const LO_TRIS = [[0, 1, 2], [1, 3, 2]];
const ALL_TRIS = HI_TRIS.concat(LO_TRIS);

class Blob {
  constructor(size = 1 << 16) {
    this.buf = new Uint8Array(size);
    this.view = new DataView(this.buf.buffer);
    this.len = 0;
    this.ptrs = [];
  }
  alloc(size, align = 4) {
    this.len = (this.len + align - 1) & ~(align - 1);
    const off = this.len;
    this.len += size;
    if (this.len > this.buf.length) {
      let n = this.buf.length;
      while (n < this.len) n *= 2;
      const b = new Uint8Array(n);
      b.set(this.buf);
      this.buf = b;
      this.view = new DataView(b.buffer);
    }
    return off;
  }
  u8(o, v) { this.view.setUint8(o, v); }
  s8(o, v) { this.view.setInt8(o, v); }
  u16(o, v) { this.view.setUint16(o, v, true); }
  s16(o, v) { this.view.setInt16(o, v, true); }
  u32(o, v) { this.view.setUint32(o, v >>> 0, true); }
  // a pointer at slot to data offset target (null: 0, and out of the map)
  ptr(slot, target) {
    if (target === null || target === undefined) { this.u32(slot, 0); return; }
    this.u32(slot, target);
    this.ptrs.push(slot);
  }
  finish() {
    const len = (this.len + 3) & ~3;
    const slots = [...new Set(this.ptrs)].sort((a, b) => a - b);
    const out = new Uint8Array(4 + len + 4 + 4 * slots.length);
    const v = new DataView(out.buffer);
    v.setUint32(0, len, true);
    out.set(this.buf.subarray(0, len), 4);
    v.setUint32(4 + len, 4 * slots.length, true);
    slots.forEach((s, i) => v.setUint32(8 + len + 4 * i, s, true));
    return out;
  }
}

// a quadblock's blockID from its index: runs of 32 numbered backwards (levwriter.block_id)
const blockId = (qi) => ((qi & ~31) | (31 - (qi & 31))) & 0x7fff;

// triNormalVecBitShift and the 10 dividends (levwriter.normal_dividends)
function normalDividends(pos, triangle) {
  const lens = [];
  for (let i = 0; i < ALL_TRIS.length; i++) {
    if (triangle && (i === 4 || i === 5 || i === 6 || i === 7 || i === 9)) { lens.push(null); continue; }
    const [a, b, c] = ALL_TRIS[i];
    const e1 = [pos[c][0] - pos[a][0], pos[c][1] - pos[a][1], pos[c][2] - pos[a][2]];
    const e2 = [pos[b][0] - pos[a][0], pos[b][1] - pos[a][1], pos[b][2] - pos[a][2]];
    let n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    if (i >= 8) n = n.map((x) => x >> 2);   // low LOD: an arithmetic shift, as CTR_MipsSra
    lens.push(Math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]));
  }
  for (let shift = 18; shift >= 0; shift--) {
    const divs = [];
    let ok = true;
    for (const L of lens) {
      if (L === null || L === 0) { divs.push(0); continue; }
      const d = Math.trunc((4096 * 2 ** shift) / L);
      if (d > 0x7fff) { ok = false; break; }
      divs.push(d);
    }
    if (ok) return [shift, divs];
  }
  return [0, new Array(10).fill(0)];
}

function bbox(pos) {
  const b = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const p of pos) {
    for (let k = 0; k < 3; k++) {
      if (p[k] < b[k]) b[k] = p[k];
      if (p[k] > b[k + 3]) b[k + 3] = p[k];
    }
  }
  return b;
}

// kd-tree over the quadblocks' box centres: nodes and the quadblock order (levwriter.build_bsp)
function buildBsp(boxes, maxLeaf) {
  const centres = boxes.map((b) => [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2]);
  const nodes = [];
  const order = [];
  const make = (idx) => {
    const me = nodes.length;
    nodes.push(null);
    const box = boxes[idx[0]].slice();
    for (const i of idx) {
      const b = boxes[i];
      for (let k = 0; k < 3; k++) {
        if (b[k] < box[k]) box[k] = b[k];
        if (b[k + 3] > box[k + 3]) box[k + 3] = b[k + 3];
      }
    }
    if (idx.length <= maxLeaf) {
      nodes[me] = { leaf: true, box, first: order.length, count: idx.length };
      for (const i of idx) order.push(i);
      return me;
    }
    let ax = 0, best = -1;
    for (let a = 0; a < 3; a++) {
      let lo = Infinity, hi = -Infinity;
      for (const i of idx) { const v = centres[i][a]; if (v < lo) lo = v; if (v > hi) hi = v; }
      const span = (hi - lo) * (a === 1 ? 0.5 : 1);
      if (span > best) { best = span; ax = a; }
    }
    idx.sort((p, q) => centres[p][ax] - centres[q][ax]);
    const mid = idx.length >> 1;
    const split = Math.trunc(centres[idx[mid]][ax]);
    const left = make(idx.slice(0, mid));
    const right = make(idx.slice(mid));
    const axis = [0, 0, 0];
    axis[ax] = 0x1000;
    nodes[me] = { leaf: false, box, children: [left, right], axis: [axis[0], axis[1], axis[2], split] };
    return me;
  };
  make(boxes.map((_, i) => i));
  return { nodes, order };
}

const clampS16 = (v) => Math.max(-32768, Math.min(32767, Math.round(v)));

// A mesh-only level (a tile): the header points at mesh_info, and nothing else is read.
// maxLeaf: quadblocks a BSP leaf holds (a window's BSP has room for 9 tiles' nodes).
export function writeTile(quads, maxLeaf = 24) {
  const b = new Blob(QUAD_SIZE * quads.length * 2 + 4096);
  const hdr = b.alloc(LEVEL_SIZE);
  const leaf = Math.max(maxLeaf, Math.ceil(quads.length / 512));
  const boxes = quads.map((q) => bbox(q.pos));
  const { nodes, order } = buildBsp(boxes, leaf);
  const nq = quads.length;
  const nn = nodes.length;
  if (nn >= 0x4000) throw new Error('too many BSP nodes');

  // vertices, shared when position and colour match; banks of 65536 past that many
  const verts = [];       // [x, y, z, r, g, b]
  let vindex = new Map();
  let bankStart = 0;
  const quadVidx = new Array(nq);
  const quadBank = new Array(nq);
  // a vertex's key: its 16-bit position and its colour, packed as characters
  const keyOf = (p, c) => String.fromCharCode(p[0] & 0xffff, p[1] & 0xffff, p[2] & 0xffff, c[0] | (c[1] << 8), c[2]);
  let banked = false;
  for (let k = 0; k < nq; k++) {
    const q = quads[order[k]];
    const keys = [];
    for (let s = 0; s < 9; s++) keys.push(keyOf(q.pos[s], q.color ? q.color[s] : [128, 128, 128]));
    let fresh = 0;
    for (const key of new Set(keys)) if (!vindex.has(key)) fresh++;
    if (verts.length - bankStart + fresh > 0x10000) {
      banked = true;
      while (verts.length < bankStart + 0x10000) verts.push(verts[verts.length - 1]);
      bankStart = verts.length;
      vindex = new Map();
    }
    const ids = [];
    for (let s = 0; s < 9; s++) {
      let id = vindex.get(keys[s]);
      if (id === undefined) {
        id = verts.length - bankStart;
        vindex.set(keys[s], id);
        const c = q.color ? q.color[s] : [128, 128, 128];
        verts.push([q.pos[s][0], q.pos[s][1], q.pos[s][2], c[0], c[1], c[2]]);
      }
      ids.push(id);
    }
    quadVidx[k] = ids;
    quadBank[k] = bankStart >> 16;
  }

  const mesh = b.alloc(0x20);
  const quadOff = b.alloc(QUAD_SIZE * nq);
  const vertOff = b.alloc(VERT_SIZE * verts.length);
  const bspOff = b.alloc(BSP_SIZE * nn);

  // texture layouts (far, middle, near and mosaic copies of one), shared when identical
  const layouts = new Map();
  const layoutOff = (tl) => {
    if (!tl) return null;
    const u = tl.uv;
    const key = String.fromCharCode(u[0][0] | (u[0][1] << 8), u[1][0] | (u[1][1] << 8), u[2][0] | (u[2][1] << 8), u[3][0] | (u[3][1] << 8), tl.clut, tl.tpage);
    let off = layouts.get(key);
    if (off === undefined) {
      off = b.alloc(0x30);
      for (let c = 0; c < 4; c++) {
        const o = off + 12 * c;
        b.u8(o, tl.uv[0][0]); b.u8(o + 1, tl.uv[0][1]); b.u16(o + 2, tl.clut);
        b.u8(o + 4, tl.uv[1][0]); b.u8(o + 5, tl.uv[1][1]); b.u16(o + 6, tl.tpage);
        b.u8(o + 8, tl.uv[2][0]); b.u8(o + 9, tl.uv[2][1]);
        b.u8(o + 10, tl.uv[3][0]); b.u8(o + 11, tl.uv[3][1]);
      }
      layouts.set(key, off);
    }
    return off;
  };

  for (let i = 0; i < verts.length; i++) {
    const o = vertOff + VERT_SIZE * i;
    const v = verts[i];
    b.s16(o, v[0]); b.s16(o + 2, v[1]); b.s16(o + 4, v[2]); b.u16(o + 6, 0);
    b.u8(o + 8, v[3]); b.u8(o + 9, v[4]); b.u8(o + 10, v[5]); b.u8(o + 11, 0);
    b.u8(o + 12, v[3]); b.u8(o + 13, v[4]); b.u8(o + 14, v[5]); b.u8(o + 15, 0);
  }

  for (let k = 0; k < nq; k++) {
    const q = quads[order[k]];
    const o = quadOff + QUAD_SIZE * k;
    for (let s = 0; s < 9; s++) b.u16(o + 2 * s, quadVidx[k][s]);
    b.u16(o + 0x12, q.flags);
    b.u32(o + 0x14, q.doubleSided ? 0x80000000 : 0);
    b.u32(o + 0x18, 0);
    for (let f = 0; f < 4; f++) b.ptr(o + 0x1c + 4 * f, layoutOff(q.faces[f]));
    const bx = boxes[order[k]];
    for (let c = 0; c < 6; c++) b.s16(o + 0x2c + 2 * c, bx[c]);
    b.u8(o + 0x38, q.terrain || 0); b.u8(o + 0x39, q.weather || 0); b.u8(o + 0x3a, quadBank[k]); b.s8(o + 0x3b, 0);
    b.s16(o + 0x3c, blockId(k)); b.u8(o + 0x3e, q.checkpoint ?? 0xff);
    b.ptr(o + 0x40, layoutOff(q.low));
    b.ptr(o + 0x44, null);   // the world's PVS (native_world.c sets it)
    const [shift, divs] = normalDividends(q.pos, q.triangle);
    b.s8(o + 0x3f, shift);
    for (let d = 0; d < 10; d++) b.s16(o + 0x48 + 2 * d, divs[d]);
  }

  for (let ni = 0; ni < nn; ni++) {
    const n = nodes[ni];
    const o = bspOff + BSP_SIZE * ni;
    b.u16(o, n.leaf ? 1 : 0); b.s16(o + 2, ni);
    for (let c = 0; c < 6; c++) b.s16(o + 4 + 2 * c, n.box[c]);
    if (n.leaf) {
      b.u32(o + 0x10, 0);
      b.ptr(o + 0x14, null);
      b.u32(o + 0x18, n.count);
      b.ptr(o + 0x1c, quadOff + QUAD_SIZE * n.first);
    } else {
      for (let c = 0; c < 4; c++) b.s16(o + 0x10 + 2 * c, clampS16(n.axis[c]));
      const ids = n.children.map((c) => c | (nodes[c].leaf ? 0x4000 : 0));
      b.u16(o + 0x18, ids[0]); b.u16(o + 0x1a, ids[1]); b.u16(o + 0x1c, BSP_NEAR_FIRST); b.u16(o + 0x1e, 0);
    }
  }

  b.u32(mesh, nq); b.u32(mesh + 4, verts.length); b.u32(mesh + 8, 0);
  b.ptr(mesh + 0x0c, quadOff);
  b.ptr(mesh + 0x10, vertOff);
  b.u32(mesh + 0x14, banked ? 0x4b4e4142 : 0);   // LEV_VERTEX_BANKS
  b.ptr(mesh + 0x18, bspOff);
  b.u32(mesh + 0x1c, nn);
  b.ptr(hdr, mesh);
  return { data: b.finish(), quads: nq, verts: verts.length, nodes: nn };
}

"""Tony Hawk's Pro Skater 4's levels, as the PC version (Aspyr's) keeps them: data/levels/LVL/
lvlscn.dat (the scene), lvltex.dat (its textures) and lvl.qb (its script: the nodes, restarts
among them). Neversoft's Xbox formats, little-endian:

tex.dat   version, count; per texture: checksum, width, height, mip levels, texel depth, palette
          depth, compression (1: DXT1, 2: DXT1 with alpha, 5: DXT5, 0: plain), palette size; the
          palette; per mip level: its size and data.
scn.dat   three version words, material count; per material: checksum, pass count, alpha
          cutoff, sorted (byte), draw order (float), single-sided (byte), grassify (byte; with it,
          grass height and layers), then per pass: texture checksum, flags, has-colour (byte),
          colour (3 floats, 0.5 = 1), blend mode (8 bytes), u and v addressing, envmap multiples,
          filtering, then UV wibble (flags & 1: 8 floats), VC wibble (flags & 2: sequences of keyed
          colours) and the mipmap settings (16 bytes).
          Then sector count; per sector: checksum, bone, flags, mesh count, bounding box (6 floats),
          sphere (4), vertex count and stride, positions (3 floats), normals (flags & 4), texture
          coordinate sets (flags & 1: a count, then 2 floats a vertex a set), colours (flags & 2:
          BGRA, 0x80 = 1), VC wibble indices (flags & 0x800: a byte each); per mesh: flags,
          material checksum, index count and 16-bit indices: a triangle strip, joined by repeats.
qb        compiled script: tokens, and a table of the names checksums stand for (0x2B: checksum,
          name). The NodeArray's structs (0x03 ... 0x04) hold each node's Position and Angles
          (0x1E: 3 floats), Class and Name (0x16: a checksum), Position first.

Positions are inches (0.0254 m), y up.
"""
import os
import re
import struct
from collections import namedtuple

import numpy as np

Texture = namedtuple('Texture', 'name rgba')
Sector = namedtuple('Sector', 'checksum flags positions uv colors meshes')    # meshes: [(material, flags, indices)]
Material = namedtuple('Material', 'checksum passes grass')                     # passes: [(texture checksum, flags, blend)]
Node = namedtuple('Node', 'cls name position angles refs checksum')    # refs: every name the node's struct uses; checksum: its name's

INCH = 0.0254


# textures

def _rgb565(c):
    c = c.astype(np.uint32)
    return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1)


def _dxt_colors(blocks, alpha1bit):
    """The 4x4 colour (RGBA) of DXT colour blocks (n, 8 bytes)."""
    c0 = blocks[:, 0].astype(np.uint32) | (blocks[:, 1].astype(np.uint32) << 8)
    c1 = blocks[:, 2].astype(np.uint32) | (blocks[:, 3].astype(np.uint32) << 8)
    a, b = _rgb565(c0).astype(np.int32), _rgb565(c1).astype(np.int32)
    four = c0 > c1
    p2 = np.where(four[:, None], (2 * a + b) // 3, (a + b) // 2)
    p3 = np.where(four[:, None], (a + 2 * b) // 3, 0)
    pal = np.stack([a, b, p2, p3], 1)                               # (n, 4, 3)
    alpha = np.full((len(blocks), 4), 255, np.int32)
    if alpha1bit:
        alpha[:, 3] = np.where(four, 255, 0)
    bits = blocks[:, 4:8].astype(np.uint32)
    idx = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
    sel = (idx[:, None] >> (2 * np.arange(16))) & 3                 # (n, 16)
    rgb = np.take_along_axis(pal, sel[:, :, None].repeat(3, 2), 1)
    al = np.take_along_axis(alpha, sel, 1)
    return np.concatenate([rgb, al[:, :, None]], 2).astype(np.uint8)  # (n, 16, 4)


def _dxt5_alpha(blocks):
    a0, a1 = blocks[:, 0].astype(np.int32), blocks[:, 1].astype(np.int32)
    lut = np.zeros((len(blocks), 8), np.int32)
    lut[:, 0], lut[:, 1] = a0, a1
    big = a0 > a1
    for i in range(2, 8):
        lut[:, i] = np.where(big, ((8 - i) * a0 + (i - 1) * a1) // 7, 0)
    for i in range(2, 6):
        lut[:, i] = np.where(big, lut[:, i], ((6 - i) * a0 + (i - 1) * a1) // 5)
    lut[:, 6] = np.where(big, lut[:, 6], 0)
    lut[:, 7] = np.where(big, lut[:, 7], 255)
    bits = np.zeros(len(blocks), np.uint64)
    for k in range(6):
        bits |= blocks[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    sel = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
    return np.take_along_axis(lut, sel, 1).astype(np.uint8)


def _dxt3_alpha(blocks):
    a = blocks[:, :8]
    lo, hi = a & 15, a >> 4
    return (np.stack([lo, hi], 2).reshape(len(blocks), 16) * 17).astype(np.uint8)


def decode_dxt(data, w, h, kind):
    """A w x h DXT image (kind 1: DXT1, 3, 5) as RGBA rows."""
    bw, bh = max(1, w // 4), max(1, h // 4)
    size = 8 if kind == 1 else 16
    blocks = np.frombuffer(data, np.uint8, bw * bh * size).reshape(-1, size)
    if kind == 1:
        px = _dxt_colors(blocks, True)
    else:
        px = _dxt_colors(blocks[:, 8:], False)
        px[:, :, 3] = _dxt5_alpha(blocks[:, :8]) if kind == 5 else _dxt3_alpha(blocks[:, :8])
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w]


def read_textures(path):
    """{checksum: Texture} of a tex.dat (the first, biggest mip level)."""
    d = open(path, 'rb').read()
    _, n = struct.unpack_from('<II', d, 0)
    o, out = 8, {}
    for _ in range(n):
        chk, w, h, levels, depth, pdepth, comp, psize = struct.unpack_from('<8I', d, o)
        o += 32
        pal = d[o:o + psize]
        o += psize
        first = None
        for lv in range(levels):
            size = struct.unpack_from('<I', d, o)[0]
            if lv == 0:
                first = d[o + 4:o + 4 + size]
            o += 4 + size
        rgba = None
        if size and first is not None:
            if len(first) == max(1, w // 4) * max(1, h // 4) * 8:
                rgba = decode_dxt(first, w, h, 1)
            elif len(first) == max(1, w // 4) * max(1, h // 4) * 16:
                rgba = decode_dxt(first, w, h, 3 if comp == 3 else 5)
            elif len(first) == w * h * 4:
                bgra = np.frombuffer(first, np.uint8).reshape(h, w, 4)
                rgba = bgra[..., [2, 1, 0, 3]].copy()
            elif len(first) == w * h and psize >= 1024:
                p = np.frombuffer(pal, np.uint8)[:1024].reshape(256, 4)[:, [2, 1, 0, 3]]
                rgba = p[np.frombuffer(first, np.uint8).reshape(h, w)]
        if rgba is not None:
            out[chk] = Texture(f'{chk:08x}', rgba)
    return out


# scene

def read_scene(path, textures=None):
    """(materials {checksum: Material}, sectors [Sector]) of a scn.dat."""
    s = open(path, 'rb').read()
    known = set(textures or ())
    nm = struct.unpack_from('<I', s, 12)[0]
    o, materials = 16, {}
    for _ in range(nm):
        chk, npass = struct.unpack_from('<II', s, o)
        grass = s[o + 18]
        p = o + 19 + (8 if grass else 0)
        passes = []
        for _ in range(npass):
            tex, fl = struct.unpack_from('<II', s, p)
            blend = struct.unpack_from('<I', s, p + 21)[0]
            q = p + 77 + (32 if fl & 1 else 0)
            if fl & 2:
                nseq = struct.unpack_from('<I', s, q)[0]
                q += 4
                for _ in range(nseq):
                    q += 8 + 8 * struct.unpack_from('<I', s, q)[0]
            passes.append((tex, fl, blend))
            p = q + 16
        materials[chk] = Material(chk, passes, bool(grass))
        o = p
    nsec = struct.unpack_from('<I', s, o)[0]
    o += 4
    sectors = []
    for _ in range(nsec):
        chk, _, flags, nmesh = struct.unpack_from('<IiII', s, o)
        o += 16 + 24 + 16
        nv, _ = struct.unpack_from('<II', s, o)
        o += 8
        pos = np.frombuffer(s, np.float32, nv * 3, o).reshape(nv, 3).astype(np.float64)
        o += nv * 12
        if flags & 4:
            o += nv * 12
        uv = np.zeros((nv, 2))
        if flags & 1:
            nt = struct.unpack_from('<I', s, o)[0]
            o += 4
            if nt:
                uv = np.frombuffer(s, np.float32, nv * nt * 2, o).reshape(nv, nt, 2)[:, 0].astype(np.float64)
            o += nv * nt * 8
            # a few sectors' coordinates are junk (NaN, 1e30): nothing to wrap
            uv[~np.isfinite(uv).all(axis=1) | (np.abs(uv) > 1e4).any(axis=1)] = 0.0
        col = np.full((nv, 4), 128.0)
        if flags & 2:
            bgra = np.frombuffer(s, np.uint8, nv * 4, o).reshape(nv, 4)
            col = bgra[:, [2, 1, 0, 3]].astype(np.float64)
            o += nv * 4
        if flags & 0x800:
            o += nv
        meshes = []
        for _ in range(nmesh):
            mf, mat, n = struct.unpack_from('<III', s, o)
            o += 12
            meshes.append((mat, mf, np.frombuffer(s, np.uint16, n, o).astype(np.int64)))
            o += 2 * n
        sectors.append(Sector(chk, flags, pos, uv, col, meshes))
    return materials, sectors


def strip_triangles(idx, pos):
    """A joined triangle strip's triangles (i, j, k), every other one turned round, those with
    two corners together (the joins) left out."""
    if len(idx) < 3:
        return np.zeros((0, 3), np.int64)
    i = np.arange(len(idx) - 2)
    tri = np.stack([idx[i], idx[i + 1], idx[i + 2]], 1)
    odd = i % 2 == 1
    tri[odd] = tri[odd][:, [1, 0, 2]]
    a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
    ok = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    ok &= np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-6
    return tri[ok]


# script

def read_nodes(path):
    """The NodeArray's nodes: [Node(class, name, position (3,), angles (3,))]."""
    d = open(path, 'rb').read()
    table = {struct.unpack('<I', m.group(1))[0]: m.group(2).decode('latin1')
             for m in re.finditer(rb'\x2b(.{4})([A-Za-z_][A-Za-z0-9_ ]{0,60})\x00', d, re.S)}
    inv = {v.lower(): k for k, v in table.items()}

    def name_token(n):
        return b'\x16' + struct.pack('<I', inv[n.lower()]) if n.lower() in inv else None

    want = {k: name_token(k) for k in ('Position', 'Angles', 'Class', 'Name')}
    if want['Position'] is None:
        return []
    # a node's struct starts with its Position: what follows it, up to the next node's, is its own
    starts = [m.start() for m in re.finditer(re.escape(want['Position'] + b'\x07\x1e'), d)]
    out = []
    for k, at in enumerate(starts):
        seg = d[at:starts[k + 1] if k + 1 < len(starts) else at + 400]
        pos = np.array(struct.unpack_from('<3f', seg, 7))
        ang = np.zeros(3)
        if want['Angles']:
            a = seg.find(want['Angles'] + b'\x07\x1e')
            if 0 <= a <= len(seg) - 19:
                ang = np.array(struct.unpack_from('<3f', seg, a + 7))

        def val(key):
            if want[key] is None:
                return ''
            a = seg.find(want[key] + b'\x07\x16')
            return table.get(struct.unpack_from('<I', seg, a + 7)[0], '') if 0 <= a <= len(seg) - 11 else ''
        refs = {table.get(struct.unpack_from('<I', seg, m.start() + 1)[0], '') for m in re.finditer(b'\x16', seg) if m.start() + 5 <= len(seg)}
        name = val('Name')
        out.append(Node(val('Class'), name, pos, ang, refs - {''}, inv.get(name.lower())))
    return out


def player_start(nodes):
    """The node one player starts at: a restart that lists Player1 (its restart types), else the
    first restart."""
    restarts = [n for n in nodes if n.cls.lower() == 'restart']
    for n in restarts:
        if any(r.lower() == 'player1' for r in n.refs):
            return n
    return restarts[0] if restarts else None


def level_files(data_dir, code):
    """The level's files (scn, tex, qb) in a THPS4 data folder (data/levels/Code/code*.dat), any
    letter case."""
    levels = os.path.join(data_dir, 'levels')
    folder = next((f for f in os.listdir(levels) if f.lower() == code.lower()), None)
    if folder is None:
        raise FileNotFoundError(f'{code} in {levels}')
    files = {f.lower(): os.path.join(levels, folder, f) for f in os.listdir(os.path.join(levels, folder))}
    c = code.lower()
    return files[f'{c}scn.dat'], files[f'{c}tex.dat'], files.get(f'{c}.qb')

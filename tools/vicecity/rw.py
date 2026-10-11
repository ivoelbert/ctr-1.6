"""RenderWare's files as Vice City's PS2 version has them: models (.dff) and texture
dictionaries (.txd), in their PS2-native form.

A file is a tree of chunks (type, size, version). A model (clump) has frames (a hierarchy of
3 x 4 matrices, named by an extension), geometries and atomics (a geometry on a frame). A PS2
geometry keeps its vertices as the packets the game sends the vector unit (the Native Data
extension, 0x510): per mesh (a material's triangle strip, or list: BinMesh's flag) a DMA chain
of VIF UNPACKs, in batches of up to 68 vertices, each the strip's next run with the last two of
the one before (a list's: 60, not overlapping):

  address 0  positions, V3_32 (floats, metres)
  address 1  texture coordinates, V2_32
  address 2  colours, V4_8 unsigned (the light baked in: RenderWare's prelight, 255 = 1.0)
  address 3  normals, V3_8

A texture (0x15) is a header (width, height, depth, TEX0, the pixels' and palette's sizes) and
the GS packets that upload it: GIF tags setting TRXPOS and TRXREG (the transfer's size; the
game sets BITBLTBUF, where it goes, when it uploads), then IMAGE data, the full-size level
first. A transfer half the texture's width and height is a swizzled one (ps2/gs.py).
"""
import struct
from collections import namedtuple

import numpy as np

from ps2 import gs

STRUCT, STRING, EXTENSION, TEXTURE, MATERIAL, MATLIST = 0x01, 0x02, 0x03, 0x06, 0x07, 0x08
FRAMELIST, GEOMETRY, CLUMP, ATOMIC, TEXNATIVE, TEXDICT, GEOMLIST = 0x0e, 0x0f, 0x10, 0x14, 0x15, 0x16, 0x1a
BINMESH, NATIVEDATA, FRAMENAME = 0x50e, 0x510, 0x253f2fe
NATIVE = 0x01000000

Texture = namedtuple('Texture', 'name rgba')


def chunks(d, o, end):
    while o + 12 <= end:
        t, s, _ = struct.unpack_from('<III', d, o)
        yield t, o + 12, s
        o += 12 + s


def child(d, o, end, kind):
    return next(((p, s) for t, p, s in chunks(d, o, end) if t == kind), (None, 0))


# models

def strip_batches(data):
    """A mesh's native packet: its batches as {VU address: values}."""
    o, out = 0, []
    while o + 16 <= len(data):
        tag = struct.unpack_from('<Q', data, o)[0]
        qwc, tid = tag & 0xffff, (tag >> 28) & 7
        p, end = o + 8, o + 16 + qwc * 16       # the tag's upper 8 bytes are VIF codes too
        batch = {}
        while p + 4 <= min(end, len(data)):
            code = struct.unpack_from('<I', data, p)[0]
            p += 4
            cmd, num, imm = code >> 24 & 0x7f, (code >> 16) & 0xff, code & 0xffff
            if cmd & 0x60 == 0x60:
                vn, vl = (cmd >> 2) & 3, cmd & 3
                n = num or 256
                size = (4, 2, 1, 2)[vl] * (vn + 1) * n
                unsigned = imm & 0x4000
                dt = ('<f4', '<u2' if unsigned else '<i2', 'u1' if unsigned else 'i1', '<u2')[vl]
                vals = np.frombuffer(data, dt, size // np.dtype(dt).itemsize, p).reshape(n, vn + 1)
                batch[imm & 0x3ff] = vals
                p += (size + 3) & ~3
            elif cmd in (0x14, 0x15, 0x17):     # MSCAL, MSCALF, MSCNT: the batch is sent
                if batch:
                    out.append(batch)
                batch = {}
            elif cmd in (0x30, 0x31):           # STROW, STCOL
                p += 16
            elif cmd == 0x20:                   # STMASK
                p += 4
            elif cmd in (0x50, 0x51):           # DIRECT, DIRECTHL
                p += (imm or 65536) * 16
        if batch:
            out.append(batch)
        o = end
        if tid in (6, 7):                       # ret, end
            break
    return out


def mesh_strip(data, strip=True):
    """A mesh's whole strip (or list): positions (n, 3), uv (n, 2), rgba (n, 4), the batches'
    overlaps taken out (a strip's batch starts with the last two of the one before; a list's
    batches, 60 vertices or fewer, don't overlap)."""
    parts = []
    for i, b in enumerate(strip_batches(data)):
        if 0 not in b:
            continue
        n = len(b[0])
        pos = b[0][:, :3].astype(np.float64)
        uv = b[1][:, :2].astype(np.float64) if 1 in b else np.zeros((n, 2))
        col = b[2][:, :4].astype(np.float64) if 2 in b else np.full((n, 4), 128.0)
        k = 2 if parts and strip else 0
        parts.append((pos[k:], uv[k:], col[k:]))
    if not parts:
        return np.zeros((0, 3)), np.zeros((0, 2)), np.zeros((0, 4))
    pos, uv, col = (np.concatenate([p[i] for p in parts]) for i in range(3))
    # a few meshes have junk in some vertices' texture coordinates (NaN, 1e21): they take
    # their neighbour's in the strip
    bad = ~np.isfinite(uv).all(axis=1) | (np.abs(uv) > 1e4).any(axis=1)
    if bad.any():
        good = np.nonzero(~bad)[0]
        if len(good) == 0:
            uv = np.zeros_like(uv)
        else:
            idx = np.nonzero(bad)[0]
            uv[idx] = uv[good[np.clip(np.searchsorted(good, idx), 0, len(good) - 1)]]
    return pos, uv, col


def list_triangles(pos):
    """A triangle list's triangles, those with two corners together left out."""
    n = len(pos) // 3
    tri = np.arange(3 * n).reshape(n, 3)
    a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
    return tri[np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-8]


def strip_triangles(pos):
    """A strip's triangles (i, j, k), those with two corners together (the joins between its
    runs) left out. Each run alternates its triangles' turn from its own first one."""
    n = len(pos)
    if n < 3:
        return np.zeros((0, 3), int)
    i = np.arange(n - 2)
    a, b, c = pos[i], pos[i + 1], pos[i + 2]
    ok = np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-8
    # the run each triangle is in starts after the last degenerate one before it
    start = np.maximum.accumulate(np.where(~ok, i + 1, 0))
    tri = np.stack([i, i + 1, i + 2], 1)
    odd = (i - start) % 2 == 1
    tri[odd] = tri[odd][:, [1, 0, 2]]
    return tri[ok]


def read_geometry(d, o, end):
    """[(positions (n, 3), uv (n, 2), rgba (n, 4), triangles (m, 3), texture name)] per mesh."""
    p, s = child(d, o, end, STRUCT)
    flags = struct.unpack_from('<I', d, p)[0]
    textures = []
    mp, ms = child(d, o, end, MATLIST)
    if mp is not None:
        for t, q, qs in chunks(d, mp, mp + ms):
            if t == MATERIAL:
                tp, ts = child(d, q, q + qs, TEXTURE)
                name = ''
                if tp is not None:
                    sp = [(sq, ss) for tt, sq, ss in chunks(d, tp, tp + ts) if tt == STRING]
                    if sp:
                        name = d[sp[0][0]:sp[0][0] + sp[0][1]].split(b'\0')[0].decode('latin1').lower()
                textures.append(name)
    out = []
    ep, es = child(d, o, end, EXTENSION)
    if not flags & NATIVE or ep is None:
        return out
    bp, bs = child(d, ep, ep + es, BINMESH)
    np_, ns = child(d, ep, ep + es, NATIVEDATA)
    if bp is None or np_ is None:
        return out
    strip, nmesh, _ = struct.unpack_from('<III', d, bp)       # strip: 1, a triangle list: 0
    mats = [struct.unpack_from('<II', d, bp + 12 + 8 * k)[1] for k in range(nmesh)]
    sp, ss = child(d, np_, np_ + ns, STRUCT)
    q = sp + 4                                   # the platform (4: PS2)
    for k in range(nmesh):
        size = struct.unpack_from('<I', d, q)[0]
        pos, uv, col = mesh_strip(d[q + 8:q + 8 + size], strip)
        q += 8 + size
        tex = textures[mats[k]] if mats[k] < len(textures) else ''
        out.append((pos, uv, col, strip_triangles(pos) if strip else list_triangles(pos), tex))
    return out


def read_clump(d):
    """A model's meshes in its own coordinates: [(positions, uv, rgba, triangles, texture,
    frame name)], each atomic's geometry put where its frame is."""
    end = struct.unpack_from('<I', d, 4)[0] + 12
    cp, cs = 12, end - 12
    fp, fs = child(d, cp, cp + cs, FRAMELIST)
    frames, names = [], []
    if fp is not None:
        sp, ss = child(d, fp, fp + fs, STRUCT)
        n = struct.unpack_from('<I', d, sp)[0]
        for k in range(n):
            v = struct.unpack_from('<12fiI', d, sp + 4 + 56 * k)
            frames.append((np.array(v[:9]).reshape(3, 3), np.array(v[9:12]), v[12]))
        for t, q, qs in chunks(d, sp + ss, fp + fs):
            if t == EXTENSION:
                np_, ns = child(d, q, q + qs, FRAMENAME)
                names.append(d[np_:np_ + ns].decode('latin1').lower() if np_ is not None else '')
    names += [''] * (len(frames) - len(names))

    def world(k):
        rot, pos, parent = frames[k]
        if 0 <= parent < len(frames) and parent != k:
            prot, ppos = world(parent)
            return rot @ prot, pos @ prot + ppos
        return rot, pos

    gp, gs_ = child(d, cp, cp + cs, GEOMLIST)
    geoms = [read_geometry(d, q, q + qs) for t, q, qs in chunks(d, gp, gp + gs_) if t == GEOMETRY] if gp is not None else []
    out = []
    for t, q, qs in chunks(d, cp, cp + cs):
        if t != ATOMIC:
            continue
        sp, _ = child(d, q, q + qs, STRUCT)
        frame, geom = struct.unpack_from('<II', d, sp)
        if geom >= len(geoms):
            continue
        rot, pos = world(frame) if frame < len(frames) else (np.eye(3), np.zeros(3))
        for P, uv, col, tris, tex in geoms[geom]:
            out.append((P @ rot + pos, uv, col, tris, tex, names[frame] if frame < len(names) else ''))
    return out


# textures

def transfers(data):
    """A texture's GIF packets: [(width, height, IMAGE bytes)] per transfer (TRXREG's size;
    the destination, BITBLTBUF, is the game's to choose when it uploads)."""
    o, regs, out = 0, {}, []
    while o + 16 <= len(data):
        lo = struct.unpack_from('<Q', data, o)[0]
        o += 16
        nloop, flg, nreg = lo & 0x7fff, (lo >> 58) & 3, (lo >> 60) & 15 or 16
        if flg == 0:        # PACKED: A+D register writes
            for _ in range(nloop * nreg):
                val, reg = struct.unpack_from('<QQ', data, o)
                regs[reg & 0xff] = val
                o += 16
        elif flg == 2:      # IMAGE
            reg = regs.get(0x52, 0)
            out.append((reg & 0xfff, (reg >> 32) & 0xfff, data[o:o + nloop * 16]))
            o += nloop * 16
        else:
            break
    return out



def read_texture(d, o, end):
    """A texture (0x15) as a Texture (RGBA, alpha 255 opaque), or None. Its first transfer
    is the full-size image: 32-bit pixels as they are; 8- and 4-bit indices either as they are
    or, sent as 32- or 16-bit pixels half as wide and high, swizzled by the GS (gs.write_read)."""
    parts = [(t, q, qs) for t, q, qs in chunks(d, o, end)]
    strings = [d[q:q + qs].split(b'\0')[0].decode('latin1').lower() for t, q, qs in parts if t == STRING]
    raster = [(q, qs) for t, q, qs in parts if t == STRUCT][1:]
    if not strings or not raster:
        return None
    q, qs = raster[0]
    inner = [(qq, ss) for t, qq, ss in chunks(d, q, q + qs) if t == STRUCT]
    if len(inner) < 2:
        return None
    (hp, _), (dp, ds) = inner[0], inner[1]
    w, h, depth = struct.unpack_from('<iii', d, hp)
    tex0 = struct.unpack_from('<Q', d, hp + 16)[0]
    pixel_size, palette_size = struct.unpack_from('<II', d, hp + 48)
    tbw = (tex0 >> 14) & 0x3f
    pix = transfers(d[dp:dp + pixel_size])
    if not pix:
        return None
    tw, th, raw = pix[0]
    if depth == 32:
        rgba = np.frombuffer(raw, np.uint8, w * h * 4).reshape(h, w, 4).copy()
    elif depth in (8, 4):
        if (tw, th) != (w, h):
            idx = gs.write_read(raw, 32 if depth == 8 else 16, tw, th, max(1, tw // 64), depth, w, h, max(2, tbw, w // 64))
        elif depth == 8:
            idx = np.frombuffer(raw, np.uint8, w * h).reshape(h, w)
        else:
            nib = np.frombuffer(raw, np.uint8, w * h // 2)
            idx = np.stack([nib & 15, nib >> 4], 1).reshape(h, w)
        pal = transfers(d[dp + pixel_size:dp + pixel_size + palette_size])
        if not pal:
            return None
        pw, ph, praw = pal[0]
        n = 256 if depth == 8 else 16
        pal = gs.csm1(np.frombuffer(praw, np.uint8, n * 4).reshape(n, 4).copy())
        rgba = pal[np.minimum(idx, n - 1)]
    else:
        return None
    rgba[..., 3] = np.minimum(255, rgba[..., 3].astype(int) * 2)
    return Texture(strings[0], rgba)


def read_txd(d):
    """{name: Texture} of a texture dictionary."""
    end = struct.unpack_from('<I', d, 4)[0] + 12
    out = {}
    for t, q, qs in chunks(d, 12, end):
        if t == TEXNATIVE:
            tex = read_texture(d, q, q + qs)
            if tex is not None:
                out[tex.name] = tex
    return out

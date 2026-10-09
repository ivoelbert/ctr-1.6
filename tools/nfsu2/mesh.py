"""NFSU2's PS2 meshes ("solids", chunk 0x80134010).

A solid has a header (0x134011: name hash, bounding box, name), the hashes of its textures
(0x134012) and its mesh (0x80134100): a table of batches (0x134a01, 16 bytes each: vertex and
triangle counts, which texture) and the batches themselves (0x134a02), each a VIF packet the
game sends to the vector unit as is. A batch is a run of UNPACKs into VU memory then MSCAL:

  address 0     4 bytes: vertex count n, group count L = (n - 1) / 4, type (1: float positions)
  address 1     the strip flags (words 0, 2, 3; see strip_skip) and the position scale, 1/256
  address 2     the batch's bounding box, min and max (metres)
  address 5     positions, in groups of 4 vertices: x0-3, y0-3, z0-3 (16-bit, in 1/256 m from
                an origin in whole metres; floats in big batches), then the leftover 1-3
  address 29    texture coordinates, 2 quadwords per group (1.0 = 4096)
  address 45    colours, RGBA8 (0x80 = 1.0): the night's baked light

The vertices are triangle strips, joined in a batch; a flag per vertex marks the two that
start each strip.
"""
import struct

import numpy as np

from . import bun

Batch = tuple   # (positions (n, 3), uv (n, 2), rgba (n, 4), triangles [(i, j, k)], texture index)


def unpacks(d, off, size):
    """Each batch's UNPACKs: {VU address: (command, values)}."""
    p, stop = bun.skip_padding(d, off), off + size
    batch = {}
    while p + 4 <= stop:
        code = struct.unpack_from('<I', d, p)[0]
        p += 4
        cmd, num, imm = code >> 24, (code >> 16) & 0xff, code & 0xffff
        if cmd & 0x60 == 0x60:
            vn, vl = (cmd >> 2) & 3, cmd & 3
            sz = (4, 2, 1)[vl] * (vn + 1) * (num or 256)
            dt = ('<f4' if vn == 2 else '<i4', '<i2', 'u1')[vl]
            batch[imm & 0x3ff] = (cmd, np.frombuffer(d[p:p + sz], dt).copy())
            p += (sz + 3) & ~3
        elif cmd == 0x14:      # MSCAL: the batch is complete
            yield batch
            batch = {}


def soa(b, a0, rows, n):
    """Per-vertex rows from groups of 4 at VU address a0 (rows quadwords each: one component of
    4 vertices per quadword), then the leftover vertices' unpack."""
    g = n // 4
    out = b[a0][1].reshape(-1, rows, 4)[:g] if g else np.zeros((0, rows, 4), b[a0][1].dtype)
    full = out.transpose(0, 2, 1).reshape(-1, rows)
    r = n - 4 * g
    if r:
        full = np.concatenate([full, b[a0 + rows * g][1].reshape(rows, -1)[:, :r].T])
    return full


def strip_skip(n, L, w):
    """1 for each vertex no triangle ends at (each strip's first two), from the batch's flag
    words. The microcode reads a bit per vertex: bit 14 - i of word 0 for the first vertices
    (word 3 when L = 3, word 2 when L = 7) and bit S + 1 - i of word 3 for the last 14 of the
    S = 4 (L + 1) slots. Checked against every batch's triangle count in the city."""
    S = 4 * (L + 1)
    first = {3: 3, 7: 2}.get(L, 0)
    k = 15 if L >= 7 else (S - 14 if L >= 4 else S)
    out = np.zeros(n, int)
    for i in range(n):
        if i < k:
            out[i] = (w[first] >> (14 - i)) & 1 if i <= 14 else 0
        else:
            out[i] = (w[3] >> (S + 1 - i)) & 1
    out[:2] = 1
    if L >= 7 and n > 16:
        # slot 15's flag isn't in the words: strips start in pairs, so it partners a lone
        # flag at 14 or 16
        out[15] = int((out[14] and not out[13]) or (out[16] and not (n > 17 and out[17])))
    return out


def batch_geometry(b):
    """(positions (n, 3) metres, uv (n, 2), rgba (n, 4), triangles) of one batch."""
    n, L = int(b[0][1][0]), int(b[0][1][1])
    bb = b[2][1].astype(np.float64)
    if b[5][0] & 3 == 0:
        pos = soa({k: (c, a.view('<f4')) for k, (c, a) in b.items()}, 5, 3, n).astype(np.float64)
    else:
        # 1/256 m from an origin in whole metres that the packet doesn't hold: at or one
        # below the box's corner, whichever keeps the vertices in the box
        v = (soa(b, 5, 3, n).astype(np.int64) & 0xffff) / 256.0
        o = np.floor(bb[:3])
        for ax in range(3):
            for cand in (o[ax], o[ax] - 1):
                p = cand + v[:, ax]
                if p.min() >= bb[ax] - 0.03 and p.max() <= bb[3 + ax] + 0.03:
                    o[ax] = cand
                    break
            else:
                o[ax] = np.round(bb[ax] + 0.01 - v[:, ax].min())
        pos = o + v
    uv = np.zeros((n, 2))
    g = n // 4
    if g:
        # per group of 4: (s0, t0, t1, s1), (s2, t2, t3, s3)
        q = b[29][1].astype(np.float64).reshape(-1, 2, 4)[:g]
        uv[:4 * g, 0] = np.stack([q[:, 0, 0], q[:, 0, 3], q[:, 1, 0], q[:, 1, 3]], 1).ravel()
        uv[:4 * g, 1] = np.stack([q[:, 0, 1], q[:, 0, 2], q[:, 1, 1], q[:, 1, 2]], 1).ravel()
    r = n - 4 * g
    if r and 29 + 2 * g in b:
        rem = np.zeros(8)
        vals = b[29 + 2 * g][1].astype(np.float64)[:8]
        rem[:len(vals)] = vals
        uv[4 * g:, 0] = [rem[0], rem[3], rem[4], rem[7]][:r]
        uv[4 * g:, 1] = [rem[1], rem[2], rem[5], rem[6]][:r]
    uv /= 4096.0
    col = b[45][1].reshape(-1, 4)[:n].astype(np.float64) if 45 in b else np.full((n, 4), 128.0)
    skip = strip_skip(n, L, [int(x) for x in b[1][1].view('<u4')])
    tris, start = [], 0
    for i in range(n):
        if skip[i] and (i == 0 or not skip[i - 1]):
            start = i
        if i >= 2 and not skip[i]:
            tris.append((i - 2, i - 1, i) if (i - start) % 2 == 0 else (i - 1, i - 2, i))
    return pos, uv, col, tris


def solids(d, off, end):
    """{hash: dict(name, bbox, tex [hashes], batches [(pos, uv, rgba, tris, texture index)])}."""
    out = {}
    for _, o, s in bun.walk(d, off, end, {0x80134010}):
        obj = {'tex': [], 'batches': []}
        for c2, o2, s2 in bun.chunks(d, o, o + s):
            if c2 == 0x134011:
                p = bun.skip_padding(d, o2)
                obj['hash'] = struct.unpack_from('<I', d, p + 0x10)[0]
                obj['bbox'] = struct.unpack_from('<8f', d, p + 0x20)
                obj['name'] = d[p + 0xa4:o2 + s2].split(b'\0')[0].decode('latin1')
            elif c2 == 0x134012:
                obj['tex'] = [struct.unpack_from('<I', d, o2 + 8 * k)[0] for k in range(s2 // 8)]
            elif c2 == 0x80134100:
                table = []
                for c3, o3, s3 in bun.chunks(d, o2, o2 + s2):
                    if c3 == 0x134a01:
                        q = bun.skip_padding(d, o3)
                        table = [d[q + k:q + k + 16] for k in range(0, o3 + s3 - q - 15, 16)]
                    elif c3 == 0x134a02:
                        for bi, b in enumerate(unpacks(d, o3, s3)):
                            if b[0][1][2] == 7:
                                continue    # 4-vertex glow sprites
                            pos, uv, col, tris = batch_geometry(b)
                            obj['batches'].append((pos, uv, col, tris, table[bi][14] if bi < len(table) else 0))
        if 'hash' in obj:
            out[obj['hash']] = obj
    return out

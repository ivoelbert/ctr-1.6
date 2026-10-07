"""Builds the Dust 2 track for CTR from the "De_Dust 2 with real light" model (Neo_minigan, CC-BY-4.0).

  python3 -I tools/build_dust2.py MODEL.glb OUTDIR

Writes
  OUTDIR/dust2.lev        the level (a CTR LEV file, see levwriter.py)
  OUTDIR/dust2_atlas.jpg  the model's textures in one image, sampled through tpage mode 3
  OUTDIR/dust2.json       numbers the page and the tests use (scale, spawn, atlas size)

The model is in Hammer units (x east, y north, z up). CTR is right-handed with y up (a kart
facing -z turns left toward -x), so a Hammer point (x, y, z) goes to SCALE * (x - cx, z, -(y - cy)).
Collision in CTR is one-sided: a quadblock's front is (p2 - p0) x (p1 - p0), so every face is
wound to face the side its model normal points to (into the playable space).
"""
import io
import json
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gltf import images, triangles  # noqa: E402
from levwriter import (FLAG_CAMERA_SEARCH, FLAG_COLLISION_SURFACE, FLAG_GROUND, Level, Node, Quad,  # noqa: E402
                       TexLayout, write_level)

SCALE = 4.0             # CTR units per Hammer unit
CENTER = (-320.0, 1120.0)  # Hammer x, y of the map's middle
MAX_EDGE = 800.0        # longest quadblock edge, CTR units
LAYER_SIZE = 1024       # each model texture is 1024 x 1024
ATLAS_COLS = 4
PAGE_ALIGN = 32         # texture page origins are 32-texel aligned (TF_VIRTUAL_ATLAS)
MAX_UV_SPAN = 255 - PAGE_ALIGN
TPAGE_ATLAS = 3 << 7    # color mode 3
DOUBLE_SIDED = os.environ.get('DOUBLE_SIDED') == '1'


def to_ctr(p):
    p = np.asarray(p, dtype=np.float64)
    return np.stack([(p[..., 0] - CENTER[0]) * SCALE, p[..., 2] * SCALE, -(p[..., 1] - CENTER[1]) * SCALE], axis=-1)


def dir_to_ctr(n):
    n = np.asarray(n, dtype=np.float64)
    return np.stack([n[..., 0], n[..., 2], -n[..., 1]], axis=-1)


class Tri:
    __slots__ = ('p', 'uv', 'layer', 'n')

    def __init__(self, p, uv, layer, n):
        self.p = p        # (3,3) CTR space
        self.uv = uv      # (3,2) texels in the layer
        self.layer = layer
        self.n = n        # unit normal, CTR space (the side that faces the player)


def load(glb):
    js, imgs = images(glb)
    layer_of_mat = {i: js['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source']
                    for i, m in enumerate(js['materials'])}
    tris = []
    flipped = 0
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        layer = layer_of_mat[mat]
        for k in range(len(P)):
            p = P[k].copy()
            uv = UV[k] * LAYER_SIZE
            geo = np.cross(p[1] - p[0], p[2] - p[0])
            area2 = np.linalg.norm(geo)
            if area2 < 1e-3:
                continue
            geo /= area2
            vn = N[k].sum(axis=0)
            if np.dot(geo, vn) < 0:  # wound against its normals: turn it around
                p = p[[0, 2, 1]]
                uv = uv[[0, 2, 1]]
                geo = -geo
                flipped += 1
            tris.append(Tri(to_ctr(p), uv.copy(), layer, dir_to_ctr(geo)))
    print(f'{len(tris)} triangles ({flipped} turned to face their normals)')
    return tris, imgs


def pair_quads(tris):
    """Merges coplanar triangle pairs with one affine texture mapping into quads.

    Returns (quads, singles): quads as (4 points, 4 uvs, layer, normal) in cyclic order."""
    def key(v):
        return tuple(np.round(v, 2))

    edges = {}
    for ti, t in enumerate(tris):
        for e in range(3):
            a, b = key(t.p[e]), key(t.p[(e + 1) % 3])
            edges.setdefault((a, b), []).append((ti, e))
    used = [False] * len(tris)
    quads = []
    order = sorted(range(len(tris)), key=lambda i: -np.linalg.norm(np.cross(tris[i].p[1] - tris[i].p[0], tris[i].p[2] - tris[i].p[0])))
    for ti in order:
        if used[ti]:
            continue
        t = tris[ti]
        best = None
        for e in range(3):
            a, b = key(t.p[e]), key(t.p[(e + 1) % 3])
            for (tj, f) in edges.get((b, a), []):
                if tj == ti or used[tj]:
                    continue
                u = tris[tj]
                if u.layer != t.layer or np.dot(u.n, t.n) < 0.9999:
                    continue
                # cyclic quad: t = (A, B, C) with shared edge A->B (index e), u has B->A
                A, B, C = t.p[e], t.p[(e + 1) % 3], t.p[(e + 2) % 3]
                D = u.p[(f + 2) % 3]
                uA, uB, uC = t.uv[e], t.uv[(e + 1) % 3], t.uv[(e + 2) % 3]
                uD = u.uv[(f + 2) % 3]
                if abs(np.dot(D - A, t.n)) > 0.5:
                    continue
                # same texture mapping on both sides of the edge
                if np.abs(u.uv[f] - uB).max() > 0.75 or np.abs(u.uv[(f + 1) % 3] - uA).max() > 0.75:
                    continue
                # predict D's uv from t's affine map
                M = np.array([B - A, C - A]).T  # 3x2
                coef, *_ = np.linalg.lstsq(M, D - A, rcond=None)
                pred = uA + coef[0] * (uB - uA) + coef[1] * (uC - uA)
                if np.abs(pred - uD).max() > 0.75:
                    continue
                poly = [A, D, B, C]
                convex = True
                for i in range(4):
                    e1 = poly[(i + 1) % 4] - poly[i]
                    e2 = poly[(i + 2) % 4] - poly[(i + 1) % 4]
                    if np.dot(np.cross(e1, e2), t.n) <= 1e-6:
                        convex = False
                        break
                if not convex:
                    continue
                area = np.linalg.norm(np.cross(u.p[1] - u.p[0], u.p[2] - u.p[0]))
                if best is None or area > best[0]:
                    best = (area, tj, (A, D, B, C), (uA, uD, uB, uC))
        if best:
            _, tj, pts, uvs = best
            used[ti] = used[tj] = True
            quads.append((np.array(pts), np.array(uvs), t.layer, t.n))
    singles = [t for i, t in enumerate(tris) if not used[i]]
    print(f'{len(quads)} quads from pairs, {len(singles)} triangles left')
    return quads, singles


def page_for(uvs):
    """32-aligned page origin holding all uvs, or None if they span too much."""
    lo = np.floor(uvs.min(axis=0) / PAGE_ALIGN) * PAGE_ALIGN
    lo = np.clip(lo, 0, LAYER_SIZE - PAGE_ALIGN)
    hi = uvs.max(axis=0)
    if (hi - lo).max() > 255:
        return None
    return lo


def layout(uv4, layer, origin):
    rel = np.clip(np.round(uv4 - origin), 0, 255).astype(int)
    clut = (layer << 10) | ((int(origin[1]) // PAGE_ALIGN) << 5) | (int(origin[0]) // PAGE_ALIGN)
    return TexLayout(uv=tuple((int(u), int(v)) for u, v in rel), clut=clut, tpage=TPAGE_ATLAS)


FACE_CORNERS = [(0, 4, 5, 6), (4, 1, 6, 7), (5, 6, 2, 8), (6, 7, 8, 3)]


def surface_flags(n):
    if n[1] > 0.7:
        return FLAG_GROUND | FLAG_CAMERA_SEARCH, 0
    return FLAG_COLLISION_SURFACE, 0


def quad_block(P9, UV9, layer, n, triangle):
    """A Quad from 9 slot positions/uvs (CTR space), wound so its front faces n."""
    P9 = [np.asarray(p) for p in P9]
    front = np.cross(P9[2] - P9[0], P9[1] - P9[0])
    if np.dot(front, n) < 0:
        raise ValueError('wrong winding')
    origin = page_for(np.array(UV9))
    if origin is None:
        return None
    faces = [layout(np.array([UV9[c] for c in fc]), layer, origin) for fc in FACE_CORNERS]
    low = layout(np.array([UV9[c] for c in (0, 1, 2, 3)]), layer, origin)
    flags, terrain = surface_flags(n)
    pos = [tuple(int(round(v)) for v in p) for p in P9]
    return Quad(pos=pos, faces=faces, low=low, flags=flags, terrain=terrain, triangle=triangle,
                double_sided=DOUBLE_SIDED)


def bilinear(c, s, t):
    # c: corners in slot order 0 (s=0,t=0), 1 (1,0), 2 (0,1), 3 (1,1)
    return (1 - s) * (1 - t) * c[0] + s * (1 - t) * c[1] + (1 - s) * t * c[2] + s * t * c[3]


def emit_quad(pts, uvs, layer, n, out, depth=0):
    """pts/uvs in cyclic order A, B, C, D (CCW about n). Tessellates into quadblocks."""
    A, B, C, D = pts
    uA, uB, uC, uD = uvs
    # slots 0, 1, 2, 3 = A, D, B, C makes (p2 - p0) x (p1 - p0) = (B - A) x (D - A) face n
    corners = [A, D, B, C]
    ucorners = [uA, uD, uB, uC]
    if np.dot(np.cross(corners[2] - corners[0], corners[1] - corners[0]), n) < 0:
        corners = [A, B, D, C]
        ucorners = [uA, uB, uD, uC]
    len_s = max(np.linalg.norm(corners[1] - corners[0]), np.linalg.norm(corners[3] - corners[2]))
    len_t = max(np.linalg.norm(corners[2] - corners[0]), np.linalg.norm(corners[3] - corners[1]))
    uv_s = max(np.abs(ucorners[1] - ucorners[0]).max(), np.abs(ucorners[3] - ucorners[2]).max())
    uv_t = max(np.abs(ucorners[2] - ucorners[0]).max(), np.abs(ucorners[3] - ucorners[1]).max())
    ns = max(1, math.ceil(len_s / MAX_EDGE), math.ceil(uv_s / MAX_UV_SPAN * 1.0001))
    nt = max(1, math.ceil(len_t / MAX_EDGE), math.ceil(uv_t / MAX_UV_SPAN * 1.0001))
    for i in range(ns):
        for j in range(nt):
            s0, s1 = i / ns, (i + 1) / ns
            t0, t1 = j / nt, (j + 1) / nt
            sm, tm = (s0 + s1) / 2, (t0 + t1) / 2
            grid = {0: (s0, t0), 4: (sm, t0), 1: (s1, t0), 5: (s0, tm), 6: (sm, tm), 7: (s1, tm),
                    2: (s0, t1), 8: (sm, t1), 3: (s1, t1)}
            P9 = [bilinear(corners, *grid[k]) for k in range(9)]
            U9 = [bilinear(ucorners, *grid[k]) for k in range(9)]
            q = quad_block(P9, U9, layer, n, False)
            if q is None:
                if depth > 3:
                    print('warning: dropped a quad whose texture spans too much')
                    continue
                sub = [bilinear(corners, s, t) for s, t in ((s0, t0), (s1, t0), (s1, t1), (s0, t1))]
                usub = [bilinear(ucorners, s, t) for s, t in ((s0, t0), (s1, t0), (s1, t1), (s0, t1))]
                # split in two along s
                mid_a, mid_b = (sub[0] + sub[1]) / 2, (sub[3] + sub[2]) / 2
                umid_a, umid_b = (usub[0] + usub[1]) / 2, (usub[3] + usub[2]) / 2
                for pp, uu in (([sub[0], mid_a, mid_b, sub[3]], [usub[0], umid_a, umid_b, usub[3]]),
                               ([mid_a, sub[1], sub[2], mid_b], [umid_a, usub[1], usub[2], umid_b])):
                    pp = np.array(pp)
                    if np.dot(np.cross(pp[1] - pp[0], pp[3] - pp[0]), n) < 0:
                        pp = pp[[0, 3, 2, 1]]
                        uu = [uu[0], uu[3], uu[2], uu[1]]
                    emit_quad(pp, np.array(uu), layer, n, out, depth + 1)
                continue
            out.append(q)


def emit_triangle(p, uv, layer, n, out):
    """Subdivides a triangle into a k x k grid: parallelogram cells become quadblocks, the
    diagonal row triangle quadblocks."""
    a, b, c = p
    ua, ub, uc = uv
    longest = max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
    uvlong = max(np.abs(ub - ua).max(), np.abs(uc - ua).max(), np.abs(uc - ub).max())
    k = max(1, math.ceil(longest / MAX_EDGE), math.ceil(uvlong / MAX_UV_SPAN * 1.0001))

    def P(i, j):
        return a + (b - a) * (i / k) + (c - a) * (j / k)

    def U(i, j):
        return ua + (ub - ua) * (i / k) + (uc - ua) * (j / k)

    for i in range(k):
        for j in range(k - i):
            if j < k - i - 1:
                pts = np.array([P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)])
                uvs = np.array([U(i, j), U(i + 1, j), U(i + 1, j + 1), U(i, j + 1)])
                if np.dot(np.cross(pts[1] - pts[0], pts[3] - pts[0]), n) < 0:
                    pts = pts[[0, 3, 2, 1]]
                    uvs = uvs[[0, 3, 2, 1]]
                emit_quad(pts, uvs, layer, n, out)
            else:
                t = [P(i, j), P(i + 1, j), P(i, j + 1)]
                tu = [U(i, j), U(i + 1, j), U(i, j + 1)]
                # slots 0, 1, 2 with (p2 - p0) x (p1 - p0) facing n
                if np.dot(np.cross(t[2] - t[0], t[1] - t[0]), n) < 0:
                    t = [t[0], t[2], t[1]]
                    tu = [tu[0], tu[2], tu[1]]
                A, B, Cc = t
                uA, uB, uC = tu
                P9 = [A, B, Cc, Cc, (A + B) / 2, (A + Cc) / 2, (B + Cc) / 2, (B + Cc) / 2, Cc]
                U9 = [uA, uB, uC, uC, (uA + uB) / 2, (uA + uC) / 2, (uB + uC) / 2, (uB + uC) / 2, uC]
                q = quad_block(P9, U9, layer, n, True)
                if q is None:
                    print('warning: dropped a triangle whose texture spans too much')
                    continue
                out.append(q)


def floor_height(tris, x, z, above):
    """Highest upward-facing surface under CTR (x, above, z)."""
    best = None
    for t in tris:
        if t.n[1] < 0.5:
            continue
        a, b, c = t.p
        v0, v1 = b - a, c - a
        d = np.array([x, 0, z]) - a
        den = v0[0] * v1[2] - v0[2] * v1[0]
        if abs(den) < 1e-9:
            continue
        s = (d[0] * v1[2] - d[2] * v1[0]) / den
        r = (v0[0] * d[2] - v0[2] * d[0]) / den
        if s < -1e-6 or r < -1e-6 or s + r > 1 + 1e-6:
            continue
        y = a[1] + s * v0[1] + r * v1[1]
        if y <= above and (best is None or y > best):
            best = y
    return best


def build_atlas(imgs, path):
    n = len(imgs)
    rows = math.ceil(n / ATLAS_COLS)
    atlas = Image.new('RGB', (ATLAS_COLS * LAYER_SIZE, rows * LAYER_SIZE))
    for i, data in enumerate(imgs):
        im = Image.open(io.BytesIO(data)).convert('RGB')
        assert im.size == (LAYER_SIZE, LAYER_SIZE), im.size
        atlas.paste(im, ((i % ATLAS_COLS) * LAYER_SIZE, (i // ATLAS_COLS) * LAYER_SIZE))
    atlas.save(path, quality=95)
    return atlas.size


def main(glb, outdir):
    os.makedirs(outdir, exist_ok=True)
    tris, imgs = load(glb)
    quads, singles = pair_quads(tris)
    out = []
    for pts, uvs, layer, n in quads:
        emit_quad(pts, uvs, layer, n, out)
    for t in singles:
        emit_triangle(t.p, t.uv, t.layer, t.n, out)
    print(f'{len(out)} quadblocks')

    # T spawn, facing north (CTR -z): heading 2048; the game adds 0x400 to spawn yaw
    spawn_h = np.array([-560.0, -774.0])
    sx, _, sz = to_ctr([spawn_h[0], spawn_h[1], 0.0])
    spawns = []
    for row in range(4):
        for col in range(2):
            x = sx + (col - 0.5) * 300
            z = sz + row * 300
            y = floor_height(tris, x, z, 4000)
            if y is None:
                y = 0
            spawns.append(((int(x), int(y) + 32, int(z)), (0, 2048 - 0x400, 0)))
    print('spawns', spawns[:2])

    # a placeholder loop of checkpoint nodes around the spawn (no quadblock uses them yet)
    nodes = []
    for i in range(4):
        ang = i * math.pi / 2
        nodes.append(Node((int(sx + 1000 * math.sin(ang)), int(spawns[0][0][1]), int(sz + 1000 * math.cos(ang))),
                          (4 - i) * 1000 // 8, (i + 1) % 4, (i - 1) % 4))

    lv = Level(quads=out, nodes=nodes, spawns=spawns,
               clear_colors=[(170, 190, 220, 1), (230, 200, 160, 1), (200, 210, 230, 1)],
               build_name='de_dust2')
    data, info = write_level(lv)
    data += b'\0' * ((-len(data)) % 2048)
    with open(os.path.join(outdir, 'dust2.lev'), 'wb') as f:
        f.write(data)
    size = build_atlas(imgs, os.path.join(outdir, 'dust2_atlas.jpg'))
    meta = dict(scale=SCALE, center=CENTER, atlas=dict(image='dust2_atlas.jpg', width=size[0], height=size[1]),
                spawn=spawns[0], info=info, bytes=len(data))
    with open(os.path.join(outdir, 'dust2.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    print(info, 'bytes', len(data))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

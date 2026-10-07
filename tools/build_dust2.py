"""Builds the Dust 2 track for CTR from the "De_Dust 2 with real light" model (Neo_minigan, CC-BY-4.0).

  python3 -I tools/build_dust2.py MODEL.glb DISC.bin OUTDIR

DISC.bin is your NTSC-U CTR disc image: Dust 2 is grafted onto Dingo Canyon's level (it
keeps that track's models -- weapon crates, wumpa fruit, the start banner -- its skybox and
its textures), so the output contains data from your disc. Never share it.

Writes
  OUTDIR/dust2.lev        a race round long A and mid (a CTR LEV file, see levwriter.py)
  OUTDIR/dust2_b.lev      a race the long way round, through B site and the tunnels
  OUTDIR/dust2_free.lev   the map with no laps, checkpoints everywhere
                          (each also as *_2p.lev, *_4p.lev and *_tt.lev: see MODES)
  OUTDIR/*_route.json     each race loop as a dense path, its checkpoints and AI lines (tests)
  OUTDIR/dust2_atlas.jpg  the model's textures in one image, sampled through tpage mode 3
  OUTDIR/dust2.json       numbers the page and the tests use (scale, spawn, atlas size, tracks)

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

# Kart lighting: the game shades a kart by the vertex colours of the floor under it (brightness
# 0x60 and up is full light, less fades it toward black: COLL_FIXED_PlayerSearch_UpdateLighting).
# Floors get the model's baked light there, sunlit sand (SUNLIT) at 0x60; the renderer draws
# atlas textures without vertex colours, so the level looks the same.
SUNLIT = 190.0          # luminance of sunlit sand in the model's light maps
SHADE_MIN = 20          # the darkest floor colour: a kart is never quite black
light_maps = None       # per atlas layer: blurred luminance, set by main()


def to_ctr(p):
    p = np.asarray(p, dtype=np.float64)
    return np.stack([(p[..., 0] - CENTER[0]) * SCALE, p[..., 2] * SCALE, -(p[..., 1] - CENTER[1]) * SCALE], axis=-1)


def dir_to_ctr(n):
    n = np.asarray(n, dtype=np.float64)
    return np.stack([n[..., 0], n[..., 2], -n[..., 1]], axis=-1)


class Tri:
    __slots__ = ('p', 'uv', 'layer', 'n', 'ph', 'nh', 'solid')

    def __init__(self, p, uv, layer, n, ph, nh):
        self.p = p        # (3,3) CTR space
        self.uv = uv      # (3,2) texels in the layer
        self.layer = layer
        self.n = n        # unit normal, CTR space (the side that faces the player)
        self.ph = ph      # (3,3) Hammer space
        self.nh = nh      # unit normal, Hammer space
        self.solid = True  # False: drawn but not collided with (stair risers under a ramp)


# Model edits for driving.
# Triangles to leave out: (mesh name) -> indices.
REMOVED = {}
# Door leaves swung open, so a kart fits: (mesh name) -> [(triangles, hinge (x, y), degrees CCW)].
SWUNG = {
    # mid doors stand half closed with a gap a kart can't fit through: open them along the frame
    'part8_part8_0': [
        ({300, 301, 302, 305, 306, 307, 867, 868}, (-288.0, 1633.0), -64.0),
        ({403, 404, 405, 408, 409, 410, 973, 974}, (-480.0, 1635.0), -63.0),
    ],
    # long doors make a zig-zag: open both leaves the rest of the way
    'part11_part11_0': [
        ({201, 202, 203, 204, 205, 215, 216, 217, 218, 219, 643, 644}, (544.0, 289.0), 60.0),
        ({210, 211, 212, 213, 214, 220, 221, 222, 223, 224, 645, 646}, (736.0, 288.0), 60.0),
    ],
}


def swing(p, n, hinge, deg):
    a = math.radians(deg)
    c, s_ = math.cos(a), math.sin(a)
    rot = np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])
    h = np.array([hinge[0], hinge[1], 0.0])
    return (p - h) @ rot.T + h, n @ rot.T


def load(glb):
    js, imgs = images(glb)
    # Images go in atlas cells 1..11, never 0: a near quadblock's "mosaic" layout word
    # (u0, v0, clut) is tested by the renderer as a possible pointer into the heap
    # (DrawLevelOvr1P_GetProjectedMidTexture); clut >= 1024 keeps it far from the heap.
    layer_of_mat = {i: 1 + js['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source']
                    for i, m in enumerate(js['materials'])}
    tris = []
    flipped = 0
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        layer = layer_of_mat[mat]
        skip = REMOVED.get(name, ())
        swings = SWUNG.get(name, ())
        for k in range(len(P)):
            if k in skip:
                continue
            p = P[k].copy()
            uv = UV[k] * LAYER_SIZE
            nk = N[k].copy()
            for ids, hinge, deg in swings:
                if k in ids:
                    p, nk = swing(p, nk, hinge, deg)
            geo = np.cross(p[1] - p[0], p[2] - p[0])
            area2 = np.linalg.norm(geo)
            if area2 < 1e-3:
                continue
            geo /= area2
            vn = nk.sum(axis=0)
            if np.dot(geo, vn) < 0:  # wound against its normals: turn it around
                p = p[[0, 2, 1]]
                uv = uv[[0, 2, 1]]
                geo = -geo
                flipped += 1
            tris.append(Tri(to_ctr(p), uv.copy(), layer, dir_to_ctr(geo), p, geo))
    patches = door_floor_patches(glb, tris)
    tris.extend(patches)
    print(f'{len(tris)} triangles ({flipped} turned to face their normals, {len(patches)} floor patches under swung doors)')
    fill_black_faces(tris, imgs)
    return tris, imgs


def fill_black_faces(tris, imgs, radius=700.0):
    """Faces the model's light baking left (mostly) black take one texel from around them: of
    the lit faces within radius (facing the same way if there are any), the sample nearest
    their median brightness, so a fill is no brighter than its surroundings. (The neighbour's
    own colour was too bright in covered spots; these faces are mostly tucked away.)"""
    lum = {}
    for i, data in enumerate(imgs):
        a = np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), dtype=np.float32)
        lum[i + 1] = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]

    def texel(layer, uv):
        L = lum[layer]
        return L[int(np.clip(uv[1], 0, LAYER_SIZE - 1)), int(np.clip(uv[0], 0, LAYER_SIZE - 1))]

    # barycentric sample points: the middle, the corners pulled 20% in, the edge middles pulled in
    weights = [(1 / 3, 1 / 3, 1 / 3)] + [tuple(0.8 * (k == j) + 0.1 for k in range(3)) for j in range(3)] + \
              [tuple(0.4 * (k != j) + 0.2 * (k == j) for k in range(3)) for j in range(3)]

    def samples(t):
        """Points across the face: (luminance, uv)."""
        return [(texel(t.layer, q), tuple(q)) for q in (np.dot(w, t.uv) for w in weights)]

    def kind(t):
        return 0 if t.n[1] > 0.7 else 2 if t.n[1] < -0.7 else 1

    black = [i for i, t in enumerate(tris) if sum(sm[0] < 10 for sm in samples(t)) * 2 >= len(weights)]
    blackset = set(black)
    centres = np.array([t.p.mean(axis=0) for t in tris])
    kinds = np.array([kind(t) for t in tris])
    filled = 0
    for i in black:
        t = tris[i]
        d = np.linalg.norm(centres - centres[i], axis=1)
        near = [k for k in np.argsort(d) if d[k] < radius and k not in blackset]
        same = [k for k in near if kinds[k] == kinds[i]]
        pool = [(lv, tris[k].layer, uv) for k in (same or near) for lv, uv in samples(tris[k]) if lv >= 10]
        if not pool:
            continue
        target = float(np.median([lv for lv, _, _ in pool]))
        _, layer, uv = min(pool, key=lambda sm: abs(sm[0] - target))
        t.layer = layer
        t.uv = np.array([uv, uv, uv])
        filled += 1
    print(f'{filled} of {len(black)} black faces take the colour around them')


def door_floor_patches(glb, tris):
    """The floor was cut around the closed door leaves: fill where a swung leaf stood.

    Each patch takes one floor color (the texel of the nearest floor at its middle)."""
    out = []
    floors = [t for t in tris if t.nh[2] > 0.99]
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        for ids, hinge, deg in SWUNG.get(name, ()):
            pts = np.concatenate([P[k] for k in ids])
            zmin = pts[:, 2].min()
            base = pts[np.abs(pts[:, 2] - zmin) < 1.0][:, :2]
            hull = convex_hull(base)
            if len(hull) < 3:
                continue
            mid = hull.mean(axis=0)
            best = None
            for t in floors:
                if abs(t.ph[0, 2] - zmin) > 1.0:
                    continue
                d = np.linalg.norm(t.ph[:, :2].mean(axis=0) - mid)
                if best is None or d < best[0]:
                    best = (d, t)
            if best is None:
                continue
            ft = best[1]
            uv = ft.uv.mean(axis=0)
            for i in range(1, len(hull) - 1):
                tri = np.array([[*hull[0], zmin], [*hull[i], zmin], [*hull[i + 1], zmin]])
                if np.cross(tri[1] - tri[0], tri[2] - tri[0])[2] < 0:
                    tri = tri[[0, 2, 1]]
                n = np.array([0.0, 0.0, 1.0])
                out.append(Tri(to_ctr(tri), np.array([uv, uv, uv]), ft.layer, dir_to_ctr(n), tri, n))
    return out


def convex_hull(pts):
    pts = sorted(set((round(float(x), 3), round(float(y), 3)) for x, y in pts))
    if len(pts) < 3:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


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
                if u.layer != t.layer or np.dot(u.n, t.n) < 0.9999 or u.solid != t.solid:
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
            quads.append((np.array(pts), np.array(uvs), t.layer, t.n, t.solid))
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


def surface_flags(n, solid=True):
    if not solid:
        return 0, 0  # drawn only: no collision search wants it
    if n[1] > 0.7:
        return FLAG_GROUND | FLAG_CAMERA_SEARCH, 0
    return FLAG_COLLISION_SURFACE, 0


def invisible_quad(P9, n, triangle=False):
    """A quadblock that collides but is never drawn (no textures): stair ramps."""
    P9 = [np.asarray(p) for p in P9]
    if np.dot(np.cross(P9[2] - P9[0], P9[1] - P9[0]), n) < 0:
        raise ValueError('wrong winding')
    flags, terrain = surface_flags(n)
    pos = [tuple(int(round(v)) for v in p) for p in P9]
    return Quad(pos=pos, faces=[None] * 4, low=None, flags=flags, terrain=terrain, triangle=triangle)


def quad_block(P9, UV9, layer, n, triangle, solid=True):
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
    flags, terrain = surface_flags(n, solid)
    pos = [tuple(int(round(v)) for v in p) for p in P9]
    color = None
    if flags & FLAG_GROUND and light_maps is not None:
        color = [floor_shade(layer, uv) for uv in UV9]
    return Quad(pos=pos, faces=faces, low=low, flags=flags, terrain=terrain, triangle=triangle,
                double_sided=DOUBLE_SIDED, color=color)


def floor_shade(layer, uv):
    """A floor vertex colour from the baked light at its texel (see SUNLIT)."""
    lum = light_maps[layer]
    x = int(np.clip(uv[0], 0, lum.shape[1] - 1))
    y = int(np.clip(uv[1], 0, lum.shape[0] - 1))
    v = int(round(np.clip(0x60 * lum[y, x] / SUNLIT, SHADE_MIN, 0xFF)))
    return (v, v, v)


def shade_ramps(out):
    """Invisible floors (stair ramps) take the shade of the nearest drawn floor vertex."""
    lit = [(p, c) for q in out if q.flags & FLAG_GROUND and q.color for p, c in zip(q.pos, q.color)]
    if not lit:
        return
    P = np.array([p for p, _ in lit], dtype=np.float64)
    C = [c for _, c in lit]
    for q in out:
        if q.flags & FLAG_GROUND and q.faces[0] is None and q.color is None:
            colors = []
            for p in q.pos:
                d = np.abs(P - np.array(p, dtype=np.float64)).sum(axis=1)
                colors.append(C[int(np.argmin(d))])
            q.color = colors


def load_light_maps(imgs):
    """Blurred luminance of each model texture, by atlas layer (cell 0 is empty)."""
    from PIL import ImageFilter
    maps = {}
    for i, data in enumerate(imgs):
        im = Image.open(io.BytesIO(data)).convert('RGB').filter(ImageFilter.BoxBlur(4))
        a = np.asarray(im, dtype=np.float32)
        maps[i + 1] = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return maps


def bilinear(c, s, t):
    # c: corners in slot order 0 (s=0,t=0), 1 (1,0), 2 (0,1), 3 (1,1)
    return (1 - s) * (1 - t) * c[0] + s * (1 - t) * c[1] + (1 - s) * t * c[2] + s * t * c[3]


def emit_quad(pts, uvs, layer, n, out, depth=0, solid=True):
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
            q = quad_block(P9, U9, layer, n, False, solid)
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
                    emit_quad(pp, np.array(uu), layer, n, out, depth + 1, solid)
                continue
            out.append(q)


def emit_triangle(p, uv, layer, n, out, solid=True):
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
                emit_quad(pts, uvs, layer, n, out, solid=solid)
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
                q = quad_block(P9, U9, layer, n, True, solid)
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


# Places on the map (Hammer x, y, facing in degrees: 0 = north, 90 = east)
LANDMARKS = {
    # the race loop, in order: round the block between T ramp and mid -- outside long ->
    # long doors -> long A -> CT ramp -> CT spawn -> mid doors -> mid -> back south of the block
    'race_start': (-280, -500, 90),
    'ring_bottom_e': (150, -500, 90),
    'start': (-1500, -700, 90),
    'ring_bottom': (100, -720, 90),
    'ring_east': (640, -100, 0),
    'long_doors': (640, 480, 0),
    'long_corner': (800, 950, 90),
    'long_bottom': (1430, 1100, 0),
    'long_start': (1430, 1330, 0),
    'long_top': (1430, 2300, 0),
    'a_site': (1150, 2700, 270),
    'a_west': (600, 2550, 270),
    'ct_spawn': (0, 2250, 180),
    'mid_doors': (-380, 1780, 180),
    'ct_south': (390, 2000, 180),
    'a_short_bottom': (320, 1560, 270),
    'catwalk_west': (0, 1520, 270),
    'mid_top': (-420, 1450, 180),
    'mid_bottom': (-420, 420, 180),
    'mid_exit': (-440, -250, 180),
    'ring_west': (-470, -100, 180),
    't_return': (-700, -720, 270),
    # elsewhere
    't_spawn': (-560, -774, 0),
    'b_site': (-1800, 2300, 0),
    'b_halls': (-800, 2300, 270),
    'upper_tunnels': (-1850, 1200, 0),
    'lower_tunnels': (-900, 1400, 90),
    't_to_tunnels': (-1700, 300, 0),
    'pit': (1430, 150, 0),
}


def heading(deg):
    """CTR yaw (4096 = full turn) for a compass heading: north is CTR -z (2048), east +x (1024)."""
    return int(round((2048 - deg * 4096 / 360) % 4096))


def landmark_positions(tris):
    out = {}
    for name, (hx, hy, deg) in LANDMARKS.items():
        x, _, z = to_ctr([hx, hy, 0.0])
        y = floor_height(tris, x, z, 4000)
        out[name] = [int(x), None if y is None else int(y), int(z), heading(deg)]
    return out


def build_atlas(imgs, path):
    n = len(imgs) + 1  # cell 0 stays empty (see load)
    rows = math.ceil(n / ATLAS_COLS)
    atlas = Image.new('RGB', (ATLAS_COLS * LAYER_SIZE, rows * LAYER_SIZE))
    for i, data in enumerate(imgs):
        im = Image.open(io.BytesIO(data)).convert('RGB')
        assert im.size == (LAYER_SIZE, LAYER_SIZE), im.size
        cell = i + 1
        atlas.paste(im, ((cell % ATLAS_COLS) * LAYER_SIZE, (cell // ATLAS_COLS) * LAYER_SIZE))
    atlas.save(path, quality=95)
    return atlas.size


def emit_ramp(ramp_h, out):
    """An invisible collision ramp over a staircase (4 Hammer points: foot l/r, head r/l)."""
    pts = to_ctr(np.array(ramp_h))
    n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
    n /= np.linalg.norm(n)
    if n[1] < 0:
        pts = pts[[0, 3, 2, 1]]
        n = -n
    A, B, C, D = pts
    corners = [A, D, B, C]
    if np.dot(np.cross(corners[2] - corners[0], corners[1] - corners[0]), n) < 0:
        corners = [A, B, D, C]
    len_s = max(np.linalg.norm(corners[1] - corners[0]), np.linalg.norm(corners[3] - corners[2]))
    len_t = max(np.linalg.norm(corners[2] - corners[0]), np.linalg.norm(corners[3] - corners[1]))
    ns, nt = max(1, math.ceil(len_s / MAX_EDGE)), max(1, math.ceil(len_t / MAX_EDGE))
    for i in range(ns):
        for j in range(nt):
            s0, s1, t0, t1 = i / ns, (i + 1) / ns, j / nt, (j + 1) / nt
            sm, tm = (s0 + s1) / 2, (t0 + t1) / 2
            grid = {0: (s0, t0), 4: (sm, t0), 1: (s1, t0), 5: (s0, tm), 6: (sm, tm), 7: (s1, tm),
                    2: (s0, t1), 8: (sm, t1), 3: (s1, t1)}
            out.append(invisible_quad([bilinear(corners, *grid[k]) for k in range(9)], n))


def add_stair_ramps(tris, out):
    from stairs import drivable_stairs, ramp_for
    stairs = drivable_stairs([(t.ph, t.nh) for t in tris])
    for st in stairs:
        for r in st:
            for i in r.tris:
                tris[i].solid = False
        emit_ramp(ramp_for(st), out)
    print(f'{len(stairs)} staircases and steps get ramps ({sum(len(s) for s in stairs)} risers)')


# The race loops, through landmarks. Both start on long A (the widest straight), heading north.
LOOPS = {
    # round the block between T ramp and mid: long A, CT spawn, mid doors, mid, outside long
    'dust2': ['long_start', 'long_top', 'ct_spawn', 'mid_doors', 'mid_top', 'mid_bottom', 'mid_exit', 'race_start',
              'ring_bottom_e', 'ring_east', 'long_doors', 'long_corner', 'long_bottom', 'long_start'],
    # the long way round: long A, CT spawn, B doors, B site, the tunnels, T spawn, outside long
    'dust2_b': ['long_start', 'long_top', 'ct_spawn', 'b_halls', 'b_site', 'upper_tunnels', 't_to_tunnels', 'start',
                'ring_bottom', 'ring_east', 'long_doors', 'long_corner', 'long_bottom', 'long_start'],
}
NODE_SPACING = 800.0     # checkpoint nodes along the route, CTR units
ROUTE_RADIUS = 14        # grid cells (64 units) around the route that count as on the track
ROUTE_REACH = 720.0      # and floors this close to it (xz distance + height difference), CTR units
FLAG_KILL_PLANE = 0x0200


def plan_route(g, landmarks, names):
    """Plans a race loop on the level's nav grid: dense CTR points from start back to start."""
    nodes = []
    for a, b in zip(names, names[1:]):
        la, lb = landmarks[a], landmarks[b]
        na = g.nearest(la[0], la[1] or 0, la[2])
        nb = g.nearest(lb[0], lb[1] or 0, lb[2])
        p = g.path(na, nb)
        if p is None:
            raise SystemExit(f'no route {a} -> {b}')
        nodes.extend(p if not nodes else p[1:])
    return nodes


def race_setup(out, g, landmarks, names):
    """Checkpoint nodes along a race loop, each floor quadblock's checkpoint, and the start grid."""
    from navgrid import route_cells
    for q in out:
        q.checkpoint = 0xFF
    path_nodes = plan_route(g, landmarks, names)
    pts = np.array([g.pos[n] for n in path_nodes], dtype=float)
    seg = np.linalg.norm(np.diff(pts[:, [0, 2]], axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(arc[-1])
    count = max(8, int(round(L / NODE_SPACING)))
    step = L / count

    def at(sv):
        i = min(int(np.searchsorted(arc, sv, side='right')) - 1, len(pts) - 2)
        f = (sv - arc[i]) / max(arc[i + 1] - arc[i], 1e-9)
        return pts[i] + (pts[i + 1] - pts[i]) * f

    nodes = []
    for i in range(count):
        p = at(i * step)
        nodes.append(Node((int(p[0]), int(p[1]), int(p[2])), int(round((L - i * step) / 8)),
                          (i + 1) % count, (i - 1) % count))
    # quadblocks near the route (through drivable cells) take the node behind them
    near = route_cells(g, path_nodes, ROUTE_RADIUS)
    tagged = 0
    for q in out:
        if not (q.flags & FLAG_GROUND):
            continue
        c = np.mean(np.array(q.pos, dtype=float), axis=0)
        nid = g.nearest(c[0], c[1], c[2])
        if nid is None or nid not in near:
            continue
        pi, _ = near[nid]
        q.checkpoint = min(int(arc[pi] // step), count - 1)
        tagged += 1
    # floors right by the route the grid didn't reach (curbs, ledges, crate tops) take the
    # node behind the nearest route point, so no part of the track is without a checkpoint
    for q in out:
        if not (q.flags & FLAG_GROUND) or q.checkpoint != 0xFF:
            continue
        c = np.mean(np.array(q.pos, dtype=float), axis=0)
        d = np.hypot(pts[:, 0] - c[0], pts[:, 2] - c[2]) + np.abs(pts[:, 1] - c[1])
        pi = int(np.argmin(d))
        if d[pi] < ROUTE_REACH:
            q.checkpoint = min(int(arc[pi] // step), count - 1)
            tagged += 1
    # start grid: two columns of four, the front row just behind node 0
    p0 = pts[0]
    ahead = at(3 * NODE_SPACING / 4)
    fwd = np.array([ahead[0] - p0[0], ahead[2] - p0[2]])
    fwd /= np.linalg.norm(fwd)
    side = np.array([-fwd[1], fwd[0]])
    yaw = int(round(math.atan2(fwd[0], fwd[1]) / (2 * math.pi) * 4096)) % 4096
    spawns = []
    for row in range(4):
        for col in range(2):
            xz = np.array([p0[0], p0[2]]) - fwd * (160 + row * 220) + side * ((col - 0.5) * 260)
            y = g.pos[g.nearest(xz[0], p0[1], xz[1])][1]
            spawns.append(((int(xz[0]), int(y) + 32, int(xz[1])), (0, (yaw - 0x400) % 4096, 0)))
    nav = nav_paths(g, pts, arc, step, count)
    print(f'race loop {L:.0f} units, {count} checkpoints, {tagged} floor quadblocks on the track, '
          f'{len(nav)} AI paths of {len(nav[0])} frames')
    route = dict(length=L, path=pts.tolist(), nodes=[n.pos for n in nodes],
                 ai=[[f['pos'] for f in path] for path in nav])
    return nodes, spawns, route, nav


NAV_SPACING = 400.0   # AI path frames, CTR units (retail tracks: ~150-700)
NAV_OFFSET = 260.0    # the two side lines, either side of the middle one


def drivable_at(g, x, y, z, min_clear=2):
    """The nav grid node under (x, z) on the floor nearest height y, if drivable with room around."""
    cx, cz = g.cell(x, z)
    if not (0 <= cx < g.nx and 0 <= cz < g.nz):
        return None
    best = None
    for k, (fy, _) in enumerate(g.floors[cx][cz]):
        nid = g.node.get((cx, cz, k))
        if nid is None or g.wall_dist[nid] < min_clear:
            continue
        if best is None or abs(fy - y) < abs(best[1] - y):
            best = (nid, fy)
    return best


def nav_paths(g, pts, arc, step, count):
    """Three AI racing lines round the loop: a smoothed middle and two offset either side."""
    L = float(arc[-1])
    # smooth the grid path (it zig-zags cell to cell), keeping points that stay drivable
    sm = pts.copy()
    for _ in range(6):
        nxt = sm.copy()
        for i in range(1, len(sm) - 1):
            lo, hi = max(0, i - 4), min(len(sm), i + 5)
            cand = sm[lo:hi].mean(axis=0)
            hit = drivable_at(g, cand[0], sm[i][1], cand[2])
            if hit is not None and abs(hit[1] - sm[i][1]) < 80:
                nxt[i] = [cand[0], hit[1], cand[2]]
        sm = nxt
    seg = np.linalg.norm(np.diff(sm[:, [0, 2]], axis=0), axis=1)
    sarc = np.concatenate([[0.0], np.cumsum(seg)])
    SL = float(sarc[-1])
    n = max(16, int(round(SL / NAV_SPACING)))

    def at(sv):
        i = min(int(np.searchsorted(sarc, sv, side='right')) - 1, len(sm) - 2)
        f = (sv - sarc[i]) / max(sarc[i + 1] - sarc[i], 1e-9)
        return sm[i] + (sm[i + 1] - sm[i]) * f

    centre = [at(i * SL / n) for i in range(n)]
    lines = []
    for side in (0.0, 1.0, -1.0):
        line = []
        for i, c in enumerate(centre):
            nx_ = centre[(i + 1) % n]
            pv = centre[(i - 1) % n]
            d = np.array([nx_[0] - pv[0], nx_[2] - pv[2]])
            d /= np.linalg.norm(d) + 1e-9
            lat = np.array([-d[1], d[0]])
            p = c.copy()
            if side:
                for off in (NAV_OFFSET, NAV_OFFSET * 0.66, NAV_OFFSET * 0.33):
                    q = np.array([c[0] + lat[0] * off * side, c[1], c[2] + lat[1] * off * side])
                    hit = drivable_at(g, q[0], c[1], q[2])
                    if hit is not None and abs(hit[1] - c[1]) < 80:
                        p = np.array([q[0], hit[1], q[2]])
                        break
            line.append(p)
        lines.append(line)
    paths = []
    for pi, line in enumerate(lines):
        frames = []
        for i, p in enumerate(line):
            q = line[(i + 1) % n]
            dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
            dxz = math.hypot(dx, dz)
            dxyz = math.sqrt(dxz * dxz + dy * dy)
            yaw = int(round(math.atan2(dx, dz) / (2 * math.pi) * 4096)) % 4096
            slope = int(round(math.atan2(dy, dxz) / (2 * math.pi) * 4096))
            frames.append(dict(
                pos=(int(p[0]), int(p[1]), int(p[2])),
                rot=((-slope >> 4) & 0xFF, (yaw >> 4) & 0xFF, 0, (slope >> 4) & 0xFF),
                distXYZ=int(dxyz), distXZ=int(dxz),
                flags=0,                        # terrain 0 (asphalt) in bits 3..7
                change=(((pi + 1) % 3) << 10) | i,  # overtaking: the same spot on the next line
                checkpoint=min(int((i * SL / n) / SL * L // step), count - 1),
                special=0))
        paths.append(frames)
    return paths


FREE_NODE_CELLS = 16   # free drive: a respawn node every 16 grid cells (1024 units)


def free_setup(out, g):
    """Checkpoints for free driving: nodes spread over everything drivable, all the same distance
    from the finish, so no lap ever counts and no mask grab ever calls a shortcut, while a kart
    that falls still comes back near where it was (the node of its last floor)."""
    picks = []
    for (cx, cz, k), nid in g.node.items():
        if cx % FREE_NODE_CELLS == 0 and cz % FREE_NODE_CELLS == 0 and g.wall_dist[nid] >= 3:
            picks.append(nid)
    picks = picks[:127]
    pos = np.array([g.pos[n] for n in picks], dtype=float)
    # Each node's next is a twin straight above it: the wrong-way test (VehLap_UpdateProgress)
    # checks the kart's heading against the way from a node's next to that one's next, which is
    # then vertical, so it never says "wrong way" on the ground. Floors only point at the real
    # nodes, so respawns (which face the next node) never start at a twin.
    nodes = []
    n = len(pos)
    for i, p in enumerate(pos):
        nodes.append(Node((int(p[0]), int(p[1]), int(p[2])), 4000, n + i, n + i))
    for i, p in enumerate(pos):
        nodes.append(Node((int(p[0]), int(p[1]) + 1000, int(p[2])), 4000, i, i))
    checkpoints = {}
    for qi, q in enumerate(out):
        if not (q.flags & FLAG_GROUND) or q.faces[0] is None and q.flags & FLAG_KILL_PLANE:
            continue
        c = np.mean(np.array(q.pos, dtype=float), axis=0)
        d = np.linalg.norm(pos[:, [0, 2]] - c[[0, 2]], axis=1) + np.abs(pos[:, 1] - c[1]) * 3
        checkpoints[qi] = int(np.argmin(d))
    print(f'free drive: {len(nodes)} respawn nodes')
    return nodes, checkpoints


def kill_plane(out, y=-1600, size=4096):
    """Invisible, under the whole map: falling onto it sends the kart back to the track."""
    allp = np.array([p for q in out for p in q.pos], dtype=float)
    x0, z0 = allp[:, 0].min() - size, allp[:, 2].min() - size
    x1, z1 = allp[:, 0].max() + size, allp[:, 2].max() + size
    n = np.array([0.0, 1.0, 0.0])
    for x in np.arange(x0, x1, size):
        for z in np.arange(z0, z1, size):
            A = np.array([x, y, z])
            B = np.array([x + size, y, z])
            C = np.array([x, y, z + size])
            D = np.array([x + size, y, z + size])
            corners = [A, B, C, D]
            if np.dot(np.cross(corners[2] - corners[0], corners[1] - corners[0]), n) < 0:
                corners = [A, C, B, D]
            grid = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0), (0, 0.5), (0.5, 0.5), (1, 0.5), (0.5, 1)]
            q = invisible_quad([bilinear(corners, s_, t_) for s_, t_ in grid], n)
            q.flags = FLAG_COLLISION_SURFACE | FLAG_KILL_PLANE
            out.append(q)


# Dingo Canyon's level files, one per mode (BIGFILE entry 8 * level + 1, 3, 5, 7). Each mode
# loads its own texture file (the entry before) with its own VRAM layout, so Dust 2 is grafted
# onto each mode's level in turn: the file suffix and the base entry.
MODES = [('', 1), ('_2p', 3), ('_4p', 5), ('_tt', 7)]


def base_levels(disc):
    from psxiso import Disc
    from bigfile import Bigfile
    from ctrlev import Lev
    d = Disc(disc)
    big = None
    for name, lba, size, isdir in d.walk():
        if name.startswith('BIGFILE.BIG'):
            big = Bigfile(d.read(lba, size))
    if big is None:
        raise SystemExit('no BIGFILE.BIG on the disc')
    return {entry: Lev(big.get(entry)) for _, entry in MODES}


def base_flyin(lev):
    """Dingo Canyon's start-line fly-in: camera and look-at points relative to the start grid,
    so it works on any start with room around it."""
    h = lev.header()
    st1 = h['ptrSpawnType1']
    if lev.u32(st1) < 4:
        return None
    return lev.u32(st1 + 4 + 4 * 3)


def base_instances(lev):
    """InstDef indices of the base level by model name."""
    by = {}
    h = lev.header()
    for i in range(h['numInstances']):
        o = h['ptrInstDefs'] + 0x40 * i
        model = lev.u32(o + 0x10)
        name = lev.data[model:model + 16].split(b'\0')[0].decode('latin1')
        by.setdefault(name, []).append(i)
    return by


def place_pickups(route, g, by_model):
    """Weapon crates in rows across the track, wumpa fruit in lines along it, two fruit crates,
    and the start banner over the start line."""
    pts = np.array(route['path'])
    seg = np.linalg.norm(np.diff(pts[:, [0, 2]], axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    L = arc[-1]

    def frame(f):
        sv = (f % 1.0) * L
        i = min(int(np.searchsorted(arc, sv, side='right')) - 1, len(pts) - 2)
        t = (sv - arc[i]) / max(arc[i + 1] - arc[i], 1e-9)
        p = pts[i] + (pts[i + 1] - pts[i]) * t
        d = pts[min(i + 6, len(pts) - 1)] - pts[max(i - 6, 0)]
        d = np.array([d[0], d[2]]) / (np.hypot(d[0], d[2]) + 1e-9)
        return p, d, np.array([-d[1], d[0]])

    def floor_point(x, y, z, reach=192):
        """The drivable floor at (x, z), or the nearest one within reach (rings of grid cells)."""
        for r in range(0, reach + 1, 32):
            ring = [(0.0, 0.0)] if r == 0 else [(r * math.cos(a), r * math.sin(a))
                                                 for a in np.linspace(0, 2 * math.pi, 8 + r // 8, endpoint=False)]
            for dx, dz in ring:
                hit = drivable_at(g, x + dx, y, z + dz, min_clear=1)
                if hit is not None and abs(hit[1] - y) < 160:
                    return (int(x + dx), int(hit[1]), int(z + dz))
        return None

    def floor_y(q, y):
        hit = drivable_at(g, q[0], y, q[2], min_clear=1)
        return None if hit is None or abs(hit[1] - y) >= 80 else hit[1]

    def across(p, lat, half=640, step=16):
        """The drivable stretch across the track at p, as lateral offsets (lo, hi): the run of
        floor through the middle, or the one nearest it."""
        runs, start, prev = [], None, None
        for o in range(-half, half + 1, step):
            good = floor_y(p + np.array([lat[0], 0, lat[1]]) * o, p[1]) is not None
            if good and start is None:
                start = o
            if not good and start is not None:
                runs.append((start, prev))
                start = None
            prev = o
        if start is not None:
            runs.append((start, prev))
        if not runs:
            return None
        return min(runs, key=lambda r: 0 if r[0] <= 0 <= r[1] else min(abs(r[0]), abs(r[1])))

    NUDGES = (0, 0.006, -0.006, 0.012, -0.012, 0.018, -0.018, 0.024, -0.024, 0.03, -0.03)
    out = []
    # weapon crates: rows of four across the track, evenly spread over its drivable width
    # (nudged along the track where it's too narrow)
    crates = list(by_model.get('crate_question', []))
    for f in (0.17, 0.40, 0.63, 0.86):
        for df in NUDGES:
            p, d, lat = frame(f + df)
            run = across(p, lat)
            if run is None or (run[1] - run[0]) - 2 * 70 < 3 * 110:
                continue
            lo, hi = run[0] + 70, run[1] - 70
            gap = min(220.0, (hi - lo) / 3)
            yaw = int(round(math.atan2(d[0], d[1]) / (2 * math.pi) * 4096)) % 4096
            for k in range(4):
                q = p + np.array([lat[0], 0, lat[1]]) * ((lo + hi) / 2 + (k - 1.5) * gap)
                y = floor_y(q, p[1])
                if crates and y is not None:
                    out.append(dict(src=crates.pop(0), pos=(int(q[0]), int(y), int(q[2])), rot=(0, yaw, 0)))
            break
        else:
            print(f'  no room for a row of weapon crates at {f:.2f} of the loop')
    # wumpa fruit: lines of four along the track, a little off the middle
    fruit = list(by_model.get('fruit', []))
    for f in (0.07, 0.29, 0.51, 0.74):
        done = False
        for df in NUDGES:
            p, d, lat = frame(f + df)
            for side in (90, 0, -90, 180, -180):
                line = [p + np.array([d[0], 0, d[1]]) * k * 160 + np.array([lat[0], 0, lat[1]]) * side for k in range(4)]
                ys = [floor_y(q, p[1]) for q in line]
                if all(y is not None for y in ys):
                    for q, y in zip(line, ys):
                        if fruit:
                            out.append(dict(src=fruit.pop(0), pos=(int(q[0]), int(y), int(q[2])), rot=(0, 0, 0)))
                    done = True
                    break
            if done:
                break
        if not done:
            print(f'  no room for a line of wumpa fruit at {f:.2f} of the loop')
    boxes = list(by_model.get('crate_fruit', []))
    for f, sidev in ((0.47, 1), (0.93, -1)):
        p, d, lat = frame(f)
        q = floor_point(*(p + np.array([lat[0], 0, lat[1]]) * 180 * sidev))
        if q and boxes:
            out.append(dict(src=boxes.pop(0), pos=q, rot=(0, 0, 0)))
    for i in by_model.get('startbanner', [])[:1]:
        p, d, lat = frame(0.0)
        yaw = int(round(math.atan2(d[0], d[1]) / (2 * math.pi) * 4096)) % 4096
        out.append(dict(src=i, pos=(int(p[0]), int(p[1]) + 959, int(p[2])), rot=(0, (yaw - 2048) % 4096, 0)))
    return out


def write_modes(outdir, name, out, nodes, spawns, nav, route, g, bases):
    """The track as one LEV per mode, each grafted onto that mode's Dingo Canyon level."""
    hitbox_of = {'crate_question': (76, 48), 'crate_fruit': (76, 48), 'fruit': (64, 64)}
    info = None
    for suffix, entry in MODES:
        base = bases[entry]
        by_model = base_instances(base)
        names = {i: n for n, ids in by_model.items() for i in ids}
        pickups = place_pickups(route, g, by_model)
        hitboxes = []
        for k, pk in enumerate(pickups):
            kind = names.get(pk['src'])
            if kind in hitbox_of:
                r, lift = hitbox_of[kind]
                hitboxes.append(dict(inst=k, radius=r, lift=lift, flags=0x4C0))
        lv = Level(quads=out, nodes=nodes, spawns=spawns,
                   clear_colors=[(170, 190, 220, 1), (230, 200, 160, 1), (200, 210, 230, 1)],
                   build_name='de_dust2', nav_paths=nav, base=base, instances=pickups, hitboxes=hitboxes,
                   flyin=base_flyin(base))
        data, mode_info = write_level(lv)
        data += b'\0' * ((-len(data)) % 2048)
        with open(os.path.join(outdir, f'{name}{suffix}.lev'), 'wb') as f:
            f.write(data)
        print(f'  {name}{suffix}.lev: {len(pickups)} pickups, {len(data)} bytes')
        if info is None:
            info = dict(mode_info, bytes=len(data))
    return info


def main(glb, disc, outdir):
    global light_maps
    from navgrid import NavGrid
    os.makedirs(outdir, exist_ok=True)
    tris, imgs = load(glb)
    light_maps = load_light_maps(imgs)
    out = []
    add_stair_ramps(tris, out)
    quads, singles = pair_quads(tris)
    for pts, uvs, layer, n, solid in quads:
        emit_quad(pts, uvs, layer, n, out, solid=solid)
    for t in singles:
        emit_triangle(t.p, t.uv, t.layer, t.n, out, solid=t.solid)
    shade_ramps(out)
    print(f'{len(out)} quadblocks')

    landmarks = landmark_positions(tris)
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in out])
    kill_plane(out)
    bases = base_levels(disc)
    tracks = {}
    first = None
    for name, stops in LOOPS.items():
        print(f'{name}:')
        nodes, spawns, route, nav = race_setup(out, g, landmarks, stops)
        info = write_modes(outdir, name, out, nodes, spawns, nav, route, g, bases)
        with open(os.path.join(outdir, f'{name}_route.json'), 'w') as f:
            json.dump(route, f)
        tracks[name] = dict(lev=f'{name}.lev', route=f'{name}_route.json', length=route['length'],
                            spawn=spawns[0], stops=stops)
        print(info)
        if first is None:
            first = (spawns, nav, route, info)

    # free drive: the first loop's start, pickups and AI lines, checkpoints everywhere, no laps
    spawns, nav, route, info = first
    print('dust2_free:')
    free_nodes, free_cp = free_setup(out, g)
    for qi, q in enumerate(out):
        q.checkpoint = free_cp.get(qi, 0xFF)
    write_modes(outdir, 'dust2_free', out, free_nodes, spawns, nav, route, g, bases)
    size = build_atlas(imgs, os.path.join(outdir, 'dust2_atlas.jpg'))
    meta = dict(scale=SCALE, center=CENTER, atlas=dict(image='dust2_atlas.jpg', width=size[0], height=size[1]),
                spawn=spawns[0], info=info, landmarks=landmarks, tracks=tracks,
                modes=[suffix for suffix, _ in MODES])
    with open(os.path.join(outdir, 'dust2.json'), 'w') as f:
        json.dump(meta, f, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])

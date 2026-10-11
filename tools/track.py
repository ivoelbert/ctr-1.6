"""The track pipeline every map goes through: textured, lit triangles in map units in, CTR
level files out (one per mode, each grafted onto Dingo Canyon's), with their textures' atlas and
minimap. tools/build_map.py feeds it a Counter-Strike map.

A map's units (Hammer's) go to CTR's as SCALE * (x - cx, z - FLOOR_Z, -(y - cy)): CTR is
right-handed with y up (a kart facing -z turns left toward -x). Collision in CTR is one-sided: a
quadblock's front is (p2 - p0) x (p1 - p0), so every face is wound to face the side its map
normal points to (into the playable space).
"""
import hashlib
import io
import itertools
import json
import math
import os
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from levwriter import (FLAG_CAMERA_SEARCH, FLAG_COLLISION_SURFACE, FLAG_GROUND, Level, Node, Quad,  # noqa: E402
                       TexLayout, write_level)

SCALE = 4.0             # CTR units per map unit
CENTER = (0.0, 0.0)     # map x, y of the map's middle (CTR's origin): set by the builder
MAX_EDGE = 800.0        # longest quadblock edge, CTR units
# floors: the renderer gives up on big faces right under the camera (a big floor quad showed
# as a hole to the void), so floors are cut along a world grid of FLOOR_CELL units (as retail
# floors are about that size). A grid, not each triangle split its own way: neighbours then
# share the same vertices along their edges (T-junctions leave dotted cracks).
FLOOR_CELL = 256.0
FLOOR_MAX_EDGE = 400.0   # a cell's diagonal and then some: grid pieces are never split again


def max_edge(n):
    return FLOOR_MAX_EDGE if n[1] > 0.7 else MAX_EDGE
LAYER_SIZE = 1024       # each model texture is 1024 x 1024
ATLAS_COLS = 4
PAGE_ALIGN = 32         # texture page origins are 32-texel aligned (TF_VIRTUAL_ATLAS)
CTRV_ALIGN = 64         # a "CTRV" atlas's textures: 64-texel aligned origins (see layout)
MAX_UV_SPAN = 255 - PAGE_ALIGN
TPAGE_ATLAS = 3 << 7    # color mode 3

# Kart lighting: the game shades a kart by the vertex colours of the floor under it (brightness
# 0x60 and up is full light, less fades it toward black: COLL_FIXED_PlayerSearch_UpdateLighting).
# Floors get the model's baked light there, sunlit sand (SUNLIT) at 0x60; the renderer draws
# atlas textures without vertex colours, so the level looks the same.
SUNLIT = 190.0          # luminance of sunlit sand in the model's light maps
SHADE_MIN = 20          # the darkest floor colour: a kart is never quite black
light_maps = None       # per atlas layer: blurred luminance, set by main()


FLOOR_Z = 0.0           # Hammer z at CTR y 0 (the engine draws karts on water terrain only above
                        # y 0: a map with water puts its surface there)


def to_ctr(p):
    p = np.asarray(p, dtype=np.float64)
    return np.stack([(p[..., 0] - CENTER[0]) * SCALE, (p[..., 2] - FLOOR_Z) * SCALE, -(p[..., 1] - CENTER[1]) * SCALE], axis=-1)


def dir_to_ctr(n):
    n = np.asarray(n, dtype=np.float64)
    return np.stack([n[..., 0], n[..., 2], -n[..., 1]], axis=-1)


DOUBLE_SIDED = 0x100   # on a Tri's terrain: drawn from both sides (foliage, fences)


class Tri:
    __slots__ = ('p', 'uv', 'layer', 'n', 'ph', 'nh', 'solid', 'terrain')

    def __init__(self, p, uv, layer, n, ph, nh):
        self.p = p        # (3,3) CTR space
        self.uv = uv      # (3,2) texels in the layer; (3,5) with the vertex colours (r, g, b)
        self.layer = layer
        self.n = n        # unit normal, CTR space (the side that faces the player)
        self.ph = ph      # (3,3) Hammer space
        self.nh = nh      # unit normal, Hammer space
        self.solid = True  # False: drawn but not collided with (stair risers under a ramp)
        self.terrain = 0   # CTR terrain type (enum TerrainType): 0 asphalt, 4 water...; | DOUBLE_SIDED


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
                if u.layer != t.layer or np.dot(u.n, t.n) < 0.9999 or u.solid != t.solid or u.terrain != t.terrain:
                    continue
                uuv = u.uv
                if len(t.uv[0]) >= WRAP_CHANNELS:
                    # a repeating texture: u's uvs may be whole repeats off t's
                    if np.abs(uuv[0][5:9] - t.uv[0][5:9]).max() > 0.01:
                        continue
                    code = int(round(t.uv[0][7]))
                    size = np.array([32 << (code & 3), 32 << ((code >> 2) & 3)], dtype=float)
                    shift = np.round((t.uv[(e + 1) % 3][:2] - uuv[f][:2]) / size) * size
                    if shift.any():
                        uuv = uuv.copy()
                        uuv[:, :2] += shift
                        local = (uuv[:, :2] - uuv[0][5:7]) / uv_scale(uuv[0])
                        if local.min() < 0 or local.max() > 255:
                            continue
                # cyclic quad: t = (A, B, C) with shared edge A->B (index e), u has B->A
                A, B, C = t.p[e], t.p[(e + 1) % 3], t.p[(e + 2) % 3]
                D = u.p[(f + 2) % 3]
                uA, uB, uC = t.uv[e], t.uv[(e + 1) % 3], t.uv[(e + 2) % 3]
                uD = uuv[(f + 2) % 3]
                if abs(np.dot(D - A, t.n)) > 0.5:
                    continue
                # same texture mapping on both sides of the edge
                if np.abs(uuv[f][:2] - uB[:2]).max() > 0.75 or np.abs(uuv[(f + 1) % 3][:2] - uA[:2]).max() > 0.75:
                    continue
                # predict D's uv from t's affine map
                M = np.array([B - A, C - A]).T  # 3x2
                coef, *_ = np.linalg.lstsq(M, D - A, rcond=None)
                pred = uA + coef[0] * (uB - uA) + coef[1] * (uC - uA)
                if np.abs(pred[:2] - uD[:2]).max() > 0.75:
                    continue
                if t.n[1] > 0.7:
                    # floors stay inside their grid cell (see grid_cut_floors)
                    q4 = np.array([A, D, B, C])
                    c0 = np.floor((q4[:, [0, 2]].min(axis=0) + 0.5) / FLOOR_CELL)
                    c1 = np.floor((q4[:, [0, 2]].max(axis=0) - 0.5) / FLOOR_CELL)
                    if np.any(c0 != c1):
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
            quads.append((np.array(pts), np.array(uvs), t.layer, t.n, t.solid, t.terrain))
    singles = [t for i, t in enumerate(tris) if not used[i]]
    print(f'{len(quads)} quads from pairs, {len(singles)} triangles left')
    return quads, singles


def page_for(uvs):
    """32-aligned page origin holding all uvs, or None if they span too much."""
    lo = np.floor(uvs[:, :2].min(axis=0) / PAGE_ALIGN) * PAGE_ALIGN
    lo = np.clip(lo, 0, LAYER_SIZE - PAGE_ALIGN)
    hi = uvs[:, :2].max(axis=0)
    if (hi - lo).max() > 255:
        return None
    return lo


def layout(uv4, layer, origin, wrap=0, shift=0):
    rel = np.clip(np.round((uv4[:, :2] - origin) / (1 << shift)), 0, 255).astype(int)
    if wrap:
        # a repeating texture ("CTRV" atlas): its origin 64-aligned, so the layer has 6 bits
        # (59 layers: 60-63 are where the never-drawn layer 15's CLUT falls, see INVISIBLE)
        assert int(origin[0]) % CTRV_ALIGN == 0 and int(origin[1]) % CTRV_ALIGN == 0 and layer < 60
        clut = (shift << 14) | (layer << 8) | ((int(origin[1]) // CTRV_ALIGN) << 4) | (int(origin[0]) // CTRV_ALIGN)
    else:
        clut = (shift << 14) | (layer << 10) | ((int(origin[1]) // PAGE_ALIGN) << 5) | (int(origin[0]) // PAGE_ALIGN)
    return TexLayout(uv=tuple((int(u), int(v)) for u, v in rel), clut=clut, tpage=TPAGE_ATLAS | wrap)


# A repeating texture ("CTRV" atlas): uv carries, after the colours, the texture's origin in the
# layer (64-aligned), its wrap code for the atlas shader (tpage bits 0-4: 16 | log2(w / 32)
# | log2(h / 32) << 2) and a uv scale's log2 (CLUT bits 14-15), and the uvs count from that
# origin, up to 255 texels times the scale.
WRAP_CHANNELS = 9


def uv_scale(uv):
    """The texels one uv unit stands for (see WRAP_CHANNELS)."""
    return 1 << int(round(uv[8])) if len(uv) >= WRAP_CHANNELS else 1


FACE_CORNERS = [(0, 4, 5, 6), (4, 1, 6, 7), (5, 6, 2, 8), (6, 7, 8, 3)]


def surface_flags(n, solid=True):
    if not solid:
        return 0, 0  # drawn only: no collision search wants it
    if n[1] > 0.7:
        return FLAG_GROUND | FLAG_CAMERA_SEARCH, 0
    return FLAG_COLLISION_SURFACE, 0


# Collision-only quadblocks (stair ramps, the kill plane) are left out of the visibility lists,
# and in case some draw path doesn't look there, their texture is atlas layer 15, which the
# atlas shader discards (a quadblock without textures is drawn black).
INVISIBLE = TexLayout(uv=((0, 0), (0, 0), (0, 0), (0, 0)), clut=15 << 10, tpage=TPAGE_ATLAS)


def invisible_quad(P9, n, triangle=False):
    """A quadblock that collides but is never drawn: stair ramps."""
    P9 = [np.asarray(p) for p in P9]
    if np.dot(np.cross(P9[2] - P9[0], P9[1] - P9[0]), n) < 0:
        raise ValueError('wrong winding')
    flags, terrain = surface_flags(n)
    pos = [tuple(int(round(v)) for v in p) for p in P9]
    return Quad(pos=pos, faces=[INVISIBLE] * 4, low=INVISIBLE, flags=flags, terrain=terrain, triangle=triangle,
                hidden=True)


def quad_block(P9, UV9, layer, n, triangle, solid=True, terrain=0):
    """A Quad from 9 slot positions/uvs (CTR space), wound so its front faces n."""
    P9 = [np.asarray(p) for p in P9]
    front = np.cross(P9[2] - P9[0], P9[1] - P9[0])
    if np.dot(front, n) < 0:
        raise ValueError('wrong winding')
    wrap = shift = 0
    if len(UV9[0]) >= WRAP_CHANNELS:
        origin = np.round(np.asarray(UV9[0][5:7], dtype=float))
        wrap = int(round(UV9[0][7]))
        shift = int(round(UV9[0][8]))
        rel = (np.array([uv[:2] for uv in UV9], dtype=float) - origin) / (1 << shift)
        if rel.min() < -0.5 or rel.max() > 255.5:
            return None
    else:
        origin = page_for(np.array(UV9))
        if origin is None:
            return None
    faces = [layout(np.array([UV9[c] for c in fc]), layer, origin, wrap, shift) for fc in FACE_CORNERS]
    low = layout(np.array([UV9[c] for c in (0, 1, 2, 3)]), layer, origin, wrap, shift)
    flags, _ = surface_flags(n, solid)
    double = bool(terrain & DOUBLE_SIDED)
    terrain &= 0xFF
    pos = [tuple(int(round(v)) for v in p) for p in P9]
    color = None
    if len(UV9[0]) > 2:
        # vertex colours: they light the textures (a "CTRV" atlas) and, on floors, the karts
        color = [tuple(int(min(max(round(c), 0), 255)) for c in uv[2:5]) for uv in UV9]
    elif flags & FLAG_GROUND and light_maps is not None:
        color = [floor_shade(layer, uv) for uv in UV9]
    return Quad(pos=pos, faces=faces, low=low, flags=flags, terrain=terrain, triangle=triangle,
                color=color, double_sided=double)


def floor_shade(layer, uv):
    """A floor vertex colour from the baked light at its texel (see SUNLIT)."""
    lum = light_maps[layer]
    # min/max, not np.clip: the same numbers, and this runs for every floor vertex
    x = int(min(max(uv[0], 0), lum.shape[1] - 1))
    y = int(min(max(uv[1], 0), lum.shape[0] - 1))
    v = int(round(min(max(0x60 * lum[y, x] / SUNLIT, SHADE_MIN), 0xFF)))
    return (v, v, v)


def shade_ramps(out):
    """Invisible floors (stair ramps) take the shade of the nearest drawn floor vertex."""
    lit = [(p, c) for q in out if q.flags & FLAG_GROUND and q.color for p, c in zip(q.pos, q.color)]
    if not lit:
        return
    P = np.array([p for p, _ in lit], dtype=np.float64)
    C = [c for _, c in lit]
    for q in out:
        if q.flags & FLAG_GROUND and q.hidden and q.color is None:
            colors = []
            for p in q.pos:
                d = np.abs(P - np.array(p, dtype=np.float64)).sum(axis=1)
                colors.append(C[int(np.argmin(d))])
            q.color = colors


def bilinear(c, s, t):
    # c: corners in slot order 0 (s=0,t=0), 1 (1,0), 2 (0,1), 3 (1,1)
    return (1 - s) * (1 - t) * c[0] + s * (1 - t) * c[1] + (1 - s) * t * c[2] + s * t * c[3]


def hlen(a, b):
    """Horizontal (xz) length of a - b."""
    return math.hypot(a[0] - b[0], a[2] - b[2])


def emit_quad(pts, uvs, layer, n, out, depth=0, solid=True, cut=None, terrain=0):
    """pts/uvs in cyclic order A, B, C, D (CCW about n). Tessellates into quadblocks, and into
    pieces at most `cut` long horizontally when given (see painter_cuts)."""
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
    scale = uv_scale(ucorners[0])
    uv_s = max(np.abs(ucorners[1][:2] - ucorners[0][:2]).max(), np.abs(ucorners[3][:2] - ucorners[2][:2]).max()) / scale
    uv_t = max(np.abs(ucorners[2][:2] - ucorners[0][:2]).max(), np.abs(ucorners[3][:2] - ucorners[1][:2]).max()) / scale
    ns = max(1, math.ceil(len_s / max_edge(n)), math.ceil(uv_s / MAX_UV_SPAN * 1.0001))
    nt = max(1, math.ceil(len_t / max_edge(n)), math.ceil(uv_t / MAX_UV_SPAN * 1.0001))
    if cut:
        hs = max(hlen(corners[1], corners[0]), hlen(corners[3], corners[2]))
        ht = max(hlen(corners[2], corners[0]), hlen(corners[3], corners[1]))
        ns = max(ns, math.ceil(hs / cut - 1e-6))
        nt = max(nt, math.ceil(ht / cut - 1e-6))
    for i in range(ns):
        for j in range(nt):
            s0, s1 = i / ns, (i + 1) / ns
            t0, t1 = j / nt, (j + 1) / nt
            sm, tm = (s0 + s1) / 2, (t0 + t1) / 2
            grid = {0: (s0, t0), 4: (sm, t0), 1: (s1, t0), 5: (s0, tm), 6: (sm, tm), 7: (s1, tm),
                    2: (s0, t1), 8: (sm, t1), 3: (s1, t1)}
            P9 = [bilinear(corners, *grid[k]) for k in range(9)]
            U9 = [bilinear(ucorners, *grid[k]) for k in range(9)]
            q = quad_block(P9, U9, layer, n, False, solid, terrain)
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
                    emit_quad(pp, np.array(uu), layer, n, out, depth + 1, solid, cut, terrain)
                continue
            out.append(q)


def emit_triangle(p, uv, layer, n, out, solid=True, cut=None, terrain=0):
    """Subdivides a triangle into a k x k grid: parallelogram cells become quadblocks, the
    diagonal row triangle quadblocks. cut: as for emit_quad."""
    a, b, c = p
    ua, ub, uc = uv
    longest = max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
    uvlong = max(np.abs(ub[:2] - ua[:2]).max(), np.abs(uc[:2] - ua[:2]).max(), np.abs(uc[:2] - ub[:2]).max()) / uv_scale(ua)
    k = max(1, math.ceil(longest / max_edge(n)), math.ceil(uvlong / MAX_UV_SPAN * 1.0001))
    if cut:
        k = max(k, math.ceil(max(hlen(b, a), hlen(c, a), hlen(c, b)) / cut - 1e-6))

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
                emit_quad(pts, uvs, layer, n, out, solid=solid, cut=cut, terrain=terrain)
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
                q = quad_block(P9, U9, layer, n, True, solid, terrain)
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


def heading(deg):
    """CTR yaw (4096 = full turn) for a compass heading: north is CTR -z (2048), east +x (1024)."""
    return int(round((2048 - deg * 4096 / 360) % 4096))


def dilate(im, steps=24):
    """Spreads each baked island's edge colours into the black gaps around it (the usual light
    map padding), so a triangle that reaches a little past its island isn't black at the edge."""
    a = np.asarray(im, dtype=np.float32)
    known = a.max(axis=2) > 4
    for _ in range(steps):
        if known.all():
            break
        acc = np.zeros_like(a)
        cnt = np.zeros(a.shape[:2], dtype=np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            src = np.roll(np.roll(a * known[..., None], dy, axis=0), dx, axis=1)
            k = np.roll(np.roll(known, dy, axis=0), dx, axis=1)
            acc += src
            cnt += k
        grow = ~known & (cnt > 0)
        a[grow] = acc[grow] / cnt[grow][:, None]
        known = known | grow
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8))


def build_atlas(imgs, path):
    n = len(imgs) + 1  # cell 0 stays empty (see load)
    rows = math.ceil(n / ATLAS_COLS)
    atlas = Image.new('RGB', (ATLAS_COLS * LAYER_SIZE, rows * LAYER_SIZE))
    for i, data in enumerate(imgs):
        im = dilate(Image.open(io.BytesIO(data)).convert('RGB'))
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
    ns, nt = max(1, math.ceil(len_s / max_edge(n))), max(1, math.ceil(len_t / max_edge(n)))
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
        if not (q.flags & FLAG_GROUND) or q.hidden and q.flags & FLAG_KILL_PLANE:
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
# loads its own texture file (the entry before) with its own VRAM layout, so a map is grafted
# onto each mode's level in turn: the file suffix and the base entry.
MODES = [('', 1), ('_2p', 3), ('_4p', 5), ('_tt', 7)]


def base_levels(disc):
    """Dingo Canyon's level and texture (VRM) files for each mode, by level entry."""
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
    return {entry: Lev(big.get(entry)) for _, entry in MODES}, {entry: big.get(entry - 1) for _, entry in MODES}


# The minimap: CTR draws a track's map as two 80 x 40 halves that share one 4-bit image, each
# half through its own palette (the top half shows the high two bits of each texel, the bottom
# half the low two), additively blended. The palettes: clear, opaque white (a route), an
# added grey (edges) and an opaque dark slate (the floors, like Counter-Strike's radar). Racer
# icons go at icon start + world position * icon size / world range (UI_Map_GetIconPos); the
# image sits with its bottom-right corner at (500, 195) on the 512 x 240 screen.
MAP_SIZE = 80
MAP_SCREEN = (420, 115)    # its top-left corner on screen
MAP_CLEAR, MAP_WHITE, MAP_EDGE, MAP_FLOOR = 0, 1, 2, 3
MAP_COLORS = (0x0000, 0x7FFF, 0xA108, 0x1CC6)   # 15-bit BGR; 0x8000 = blended


def drivable_cells(g, start):
    """The (x, z) middles of the drivable grid's cells a kart can reach from node `start`: what
    the minimap shows (not roofs, nor floors no one gets to)."""
    return np.array([(g.pos[nid][0], g.pos[nid][2]) for nid in sorted(g.reachable(start))], dtype=float)


def minimap_window(cells, margin=0.03):
    """A square of the world (x0, z0, side) around the drivable cells."""
    x0, x1 = cells[:, 0].min(), cells[:, 0].max()
    z0, z1 = cells[:, 1].min(), cells[:, 1].max()
    side = max(x1 - x0, z1 - z0) * (1 + 2 * margin)
    return ((x0 + x1) / 2 - side / 2, (z0 + z1) / 2 - side / 2, side)


def minimap_placement(window):
    """struct UIMap (+ topHalfMode) for a window, north up (mode 0: x right, z down)."""
    x0, z0, side = window
    rng = int(round(side))
    start_x = int(round(MAP_SCREEN[0] - x0 * MAP_SIZE / rng))
    start_y = int(round(MAP_SCREEN[1] - z0 * MAP_SIZE / rng)) + 16
    return (int(x0) + rng, int(z0) + rng, int(x0), int(z0), MAP_SIZE, MAP_SIZE // 2, start_x, start_y, 0, 0)


def minimap_image(cells, window, route=None, scale=4, cell=64.0):
    """The map: the drivable cells (drivable_cells, `cell` units square) in slate, a race loop
    over them in white."""
    from PIL import ImageDraw
    x0, z0, side = window
    n = MAP_SIZE * scale
    k = n / side
    floor = Image.new('L', (n, n), 0)
    d = ImageDraw.Draw(floor)
    for x, z in cells:
        d.rectangle([(x - cell / 2 - x0) * k, (z - cell / 2 - z0) * k, (x + cell / 2 - x0) * k, (z + cell / 2 - z0) * k], fill=255)
    cover = np.asarray(floor.resize((MAP_SIZE, MAP_SIZE), Image.BOX), dtype=np.float32) / 255
    img = np.full((MAP_SIZE, MAP_SIZE), MAP_CLEAR, dtype=np.uint8)
    img[cover > 0.4] = MAP_FLOOR
    img[(cover > 0.15) & (cover <= 0.4)] = MAP_EDGE
    if route is None:
        return img
    line = Image.new('L', (n, n), 0)
    pts = [((p[0] - x0) * k, (p[2] - z0) * k) for p in route]
    ImageDraw.Draw(line).line(pts + [pts[0]], fill=255, width=int(2.2 * scale), joint='curve')
    lc = np.asarray(line.resize((MAP_SIZE, MAP_SIZE), Image.BOX), dtype=np.float32) / 255
    img[lc > 0.35] = MAP_WHITE
    return img


def map_icon(base):
    """Where a base level's map is in VRAM: (page x, page y, u, v, width, height, the top
    half's palette x, y, the bottom half's palette x, y)."""
    h = base.header()
    ltl = h['levTexLookup']
    icons = base.u32(ltl + 4)
    found = {}
    for i in range(base.u32(ltl)):
        o = icons + 0x20 * i
        found[base.data[o:o + 16].split(b'\0')[0]] = struct.unpack_from('<BBHBBHBB', base.data, o + 20)
    if b'map-proto8-01' not in found or b'map-proto8-02' not in found:
        raise SystemExit('the base level has no minimap')
    u0, v0, clut, u1, v1, tpage, u2, v2 = found[b'map-proto8-01']
    clut2 = found[b'map-proto8-02'][2]
    return ((tpage & 0xF) * 64, ((tpage >> 4) & 1) * 256, u0, v0, u1 - u0 + 1, v2 - v0 + 1,
            (clut & 0x3F) * 16, clut >> 6, (clut2 & 0x3F) * 16, clut2 >> 6)


def patch_vrm(vrm, icon, img):
    """A copy of a VRM (16-bit VRAM blocks) with the 4-bit map texels redrawn from img."""
    page_x, page_y, u0, v0, w, h, top_x, top_y, bottom_x, bottom_y = icon
    assert (w, h) == (MAP_SIZE, MAP_SIZE // 2), (w, h)
    out = bytearray(vrm)
    blocks = []
    o = 4
    while o + 4 <= len(out):
        size = struct.unpack_from('<I', out, o)[0]
        if size == 0:
            break
        _, bx, by, bw, bh = struct.unpack_from('<IHHHH', out, o + 4 + 8)
        blocks.append((o + 4 + 8 + 12, bx, by, bw, bh))
        o += 4 + size

    def put(x, y, word):
        for data, bx, by, bw, bh in blocks:
            if bx <= x < bx + bw and by <= y < by + bh:
                struct.pack_into('<H', out, data + 2 * ((y - by) * bw + (x - bx)), word)
                return
        raise SystemExit(f'VRAM {x},{y} is in no block of the VRM')

    for i in range(16):
        put(top_x + i, top_y, MAP_COLORS[i >> 2])
        put(bottom_x + i, bottom_y, MAP_COLORS[i & 3])
    texels = (img[:h].astype(np.uint16) << 2) | img[h:]
    for row in range(h):
        y = page_y + v0 + row
        for col in range(0, w, 4):
            x = page_x + (u0 + col) // 4
            word = 0
            for j in range(4):
                word |= int(texels[row, col + j]) << (4 * ((u0 + col + j) % 4))
            put(x, y, word)
    return bytes(out)


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


def write_modes(outdir, name, out, nodes, spawns, nav, route, g, bases, vrms, minimap, build_name, clear_colors, keep_sky=True,
                pickups=False):
    """The track as one LEV per mode, each grafted onto that mode's Dingo Canyon level, and that
    mode's texture file with the track's minimap drawn in. Its weapon crates and fruit only with
    pickups (races and battles: free drive has none, just the start banner)."""
    hitbox_of = {'crate_question': (76, 48), 'crate_fruit': (76, 48), 'fruit': (64, 64)}
    window, map_img = minimap
    info = None
    for suffix, entry in MODES:
        base = bases[entry]
        with open(os.path.join(outdir, f'{name}{suffix}.vrm'), 'wb') as f:
            f.write(patch_vrm(vrms[entry], map_icon(base), map_img))
        by_model = base_instances(base)
        names = {i: n for n, ids in by_model.items() for i in ids}
        placed = [pk for pk in place_pickups(route, g, by_model) if pickups or names.get(pk['src']) == 'startbanner']
        hitboxes = []
        for k, pk in enumerate(placed):
            kind = names.get(pk['src'])
            if kind in hitbox_of:
                r, lift = hitbox_of[kind]
                hitboxes.append(dict(inst=k, radius=r, lift=lift, flags=0x4C0))
        lv = Level(quads=out, nodes=nodes, spawns=spawns,
                   clear_colors=clear_colors,
                   build_name=build_name, nav_paths=nav, base=base, keep_sky=keep_sky, instances=placed, hitboxes=hitboxes,
                   flyin=base_flyin(base), minimap=minimap_placement(window))
        data, mode_info = write_level(lv)
        data += b'\0' * ((-len(data)) % 2048)
        with open(os.path.join(outdir, f'{name}{suffix}.lev'), 'wb') as f:
            f.write(data)
        print(f'  {name}{suffix}.lev: {len(placed)} instances, {len(data)} bytes')
        if info is None:
            info = dict(mode_info, bytes=len(data))
    return info


def _split(poly, axis, c, eps=0.01):
    """A convex polygon (list of (pos, uv, ph)) cut by the plane pos[axis] = c: (below, above)."""
    lo, hi = [], []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da, db = a[0][axis] - c, b[0][axis] - c
        if da <= eps:
            lo.append(a)
        if da >= -eps:
            hi.append(a)
        if (da < -eps and db > eps) or (da > eps and db < -eps):
            f = da / (da - db)
            m = tuple(a[k] + (b[k] - a[k]) * f for k in range(3))
            lo.append(m)
            hi.append(m)
    return lo, hi


def grid_cut_floors(tris, cell=None, near=None):
    """Floor triangles cut along the lines x, z = cell * i (CTR units; FLOOR_CELL by default), as
    fans of triangles; only those near(t) says a kart's camera can get close to, when given."""
    cell = cell or FLOOR_CELL
    out = []
    cut = 0
    for t in tris:
        if t.n[1] <= 0.7 or (near is not None and not near(t)):
            out.append(t)
            continue
        polys = [[(t.p[k].astype(float), t.uv[k].astype(float), t.ph[k].astype(float)) for k in range(3)]]
        for axis in (0, 2):
            done = []
            for poly in polys:
                vals = [v[0][axis] for v in poly]
                for i in range(int(math.floor(min(vals) / cell)) + 1, int(math.ceil(max(vals) / cell))):
                    lo, hi = _split(poly, axis, i * cell)
                    if len(lo) >= 3:
                        done.append(lo)
                    poly = hi
                    if len(poly) < 3:
                        break
                if len(poly) >= 3:
                    done.append(poly)
            polys = done
        if len(polys) == 1 and len(polys[0]) == 3:
            out.append(t)
            continue
        cut += 1
        for poly in polys:
            for i in range(1, len(poly) - 1):
                a, b, c = poly[0], poly[i], poly[i + 1]
                p = np.array([a[0], b[0], c[0]])
                if np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])) < 1.0:
                    continue   # a sliver where a line grazed a corner
                r = Tri(p, np.array([a[1], b[1], c[1]]), t.layer, t.n, np.array([a[2], b[2], c[2]]), t.nh)
                r.solid = t.solid
                r.terrain = t.terrain
                out.append(r)
    print(f'{cut} floor triangles cut along the {cell:.0f}-unit grid: {len(tris)} -> {len(out)} triangles')
    return out


def _child(t, p, uv, ph):
    r = Tri(np.asarray(p, dtype=float), np.asarray(uv, dtype=float), t.layer, t.n, np.asarray(ph, dtype=float), t.nh)
    r.solid = t.solid
    r.terrain = t.terrain
    return r


def is_floor(t):
    return t.n[1] > 0.7


def fix_t_junctions(tris, eps=0.6, cell=32.0, which=is_floor):
    """Splits each floor triangle at the vertices of other floor triangles that lie on its edges,
    so neighbours share every vertex along their common edges (a T-junction is a dotted crack,
    and on floors, which the camera looks down at, they showed). Walls are left as they are:
    their seams hardly show, and splitting them too runs past the format's 65536 vertices."""
    grid = {}
    seen = set()
    for t in tris:
        if not which(t):
            continue
        for p in t.p:
            key = tuple(np.round(p, 2))
            if key not in seen:
                seen.add(key)
                grid.setdefault(tuple(np.floor(p / cell).astype(int)), []).append(p)

    def cells_along(a, b):
        n = int(np.linalg.norm(b - a) / (cell / 2)) + 1
        out = set()
        for s_ in range(n + 1):
            p = a + (b - a) * (s_ / n)
            base = np.floor(p / cell)
            frac = p / cell - base
            opts = [[int(base[k])] + ([int(base[k]) - 1] if frac[k] * cell < eps else []) +
                    ([int(base[k]) + 1] if (1 - frac[k]) * cell < eps else []) for k in range(3)]
            for x in opts[0]:
                for y in opts[1]:
                    for z in opts[2]:
                        out.add((x, y, z))
        return out

    def on_edge(a, b):
        """Vertices on the open segment a-b, as (fraction along it, position), in order."""
        d = b - a
        L2 = float(np.dot(d, d))
        if L2 < 1e-6:
            return []
        found = {}
        for key in cells_along(a, b):
            for v in grid.get(key, ()):
                f = float(np.dot(v - a, d)) / L2
                if f * f * L2 <= eps * eps or (1 - f) * (1 - f) * L2 <= eps * eps or not 0 < f < 1:
                    continue
                if np.linalg.norm(a + d * f - v) <= eps:
                    found[tuple(np.round(v, 2))] = (f, v)
        return sorted(found.values(), key=lambda fv: fv[0])

    out, splits = [], 0
    for t in tris:
        if not which(t):
            out.append(t)
            continue
        # each edge's extra vertices, found once; then split recursively without new queries
        pts = [on_edge(t.p[e], t.p[(e + 1) % 3]) for e in range(3)]
        if not any(pts):
            out.append(t)
            continue

        def split(P, UV, PH, E):
            # P, UV, PH: 3 corners; E[e]: list of (f, pos) on edge e (corner e -> e + 1)
            for e in range(3):
                if E[e]:
                    i, j, k = e, (e + 1) % 3, (e + 2) % 3
                    f, v = E[e][0]
                    uv = UV[i] + (UV[j] - UV[i]) * f
                    ph = PH[i] + (PH[j] - PH[i]) * f
                    rest = [((g - f) / (1 - f), w) for g, w in E[e][1:]]
                    # (i, v, k): edges i-v (none), v-k (inside), k-i (edge k's points)
                    e1 = [None] * 3
                    e1[0], e1[1], e1[2] = [], [], E[k]
                    # (v, j, k): edges v-j (the rest of this edge), j-k (edge j's points), k-v (inside)
                    e2 = [rest, E[j], []]
                    split([P[i], v, P[k]], [UV[i], uv, UV[k]], [PH[i], ph, PH[k]], e1)
                    split([v, P[j], P[k]], [uv, UV[j], UV[k]], [ph, PH[j], PH[k]], e2)
                    return
            out.append(_child(t, P, UV, PH))

        split(list(t.p), list(t.uv), list(t.ph), pts)
        splits += sum(len(p) for p in pts)
    print(f'{splits} T-junctions closed: {len(tris)} -> {len(out)} triangles')
    return out


def level_polygons(tris, near=None):
    """emit_level's polygons, (quads, single triangles): floors cut along the grid, T-junctions
    closed, triangles paired. The same whatever the cuts, so painter_cuts makes them once."""
    return pair_quads(fix_t_junctions(grid_cut_floors(tris, near=near)))


def emit_level(tris, ramps, cuts=None, near=None, polygons=None):
    """Quadblocks for the model's triangles, after the stair ramps. Each gets .src, the polygon
    it comes from (('q', i): a merged pair, ('t', i): a lone triangle; None: a ramp), and
    cuts {src: length} cuts some shorter (see painter_cuts); near: see grid_cut_floors;
    polygons: level_polygons(tris, near), when already made."""
    cuts = cuts or {}
    out = list(ramps)
    for q in out:
        q.src = None
    quads, singles = polygons or level_polygons(tris, near)
    for i, (pts, uvs, layer, n, solid, terrain) in enumerate(quads):
        first = len(out)
        emit_quad(pts, uvs, layer, n, out, solid=solid, cut=cuts.get(('q', i)), terrain=terrain)
        for q in out[first:]:
            q.src = ('q', i)
    for i, t in enumerate(singles):
        first = len(out)
        emit_triangle(t.p, t.uv, t.layer, t.n, out, solid=t.solid, cut=cuts.get(('t', i)), terrain=t.terrain)
        for q in out[first:]:
            q.src = ('t', i)
    shade_ramps(out)
    return out


# The painter's order (tools/painter.py): CTR sorts each level face by its farthest corner, so
# a long wall seen along its length sorts as far as its far end and what stands just behind its
# near part gets painted over it (the A-site crates over the wall of long A). The audit renders
# the level from chase-camera views all over the drivable floor; the polygons whose quadblocks
# have something painted over them are cut into shorter pieces, which sort by nearer far
# corners, a round per length. The cuts cost vertices, which the format caps at 65536.
PAINTER_CUTS = (256.0, 128.0)
PAINTER_MIN_PIXELS = 40     # summed over the audit's views (at half the game's resolution)
VERTEX_BUDGET = 64000


def vertex_count(quads):
    """The level's vertices as write_level counts them: one per position and colour."""
    keys = set()
    for q in quads:
        colors = q.color or [(0x80, 0x80, 0x80)] * 9
        for p, c in zip(q.pos, colors):
            keys.add((tuple(p), tuple(c[:3])))
    return len(keys)


def face_drawn(q, fi):
    f = q.faces[fi]
    return not q.hidden and f is not None and (f.clut >> 10) != 15


def painter_cuts(tris, ramps, g, start, name, near=None, polygons=None):
    """The level (emit_level), with the polygons the painter's audit flags cut shorter (see
    above); with FAST, those the last full build of `name` cut (see FAST). polygons:
    level_polygons(tris, near), when already made."""
    import tempfile
    import painter
    t0 = time.time()
    polygons = polygons or level_polygons(tris, near)
    quads, singles = polygons
    keys = dict(zip([('q', i) for i in range(len(quads))] + [('t', i) for i in range(len(singles))],
                    polygon_keys([(pts, n, layer) for pts, _, layer, n, _, _ in quads] +
                                 [(t.p, t.n, t.layer) for t in singles])))
    if FAST:
        saved = load_checks(name).get('cuts', {})
        cuts = {src: saved[k] for src, k in keys.items() if k in saved}
        out = emit_level(tris, ramps, cuts, near, polygons)
        print(f'painter audit as the last full build had it (FAST): {len(cuts)} of its {len(saved)} cuts, '
              f'{vertex_count(out)} vertices')
        return out
    out = emit_level(tris, ramps, None, near, polygons)
    views = painter.chase_views(g, start)
    cuts = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            painter.painter_binary(tmp)
        except (OSError, subprocess.CalledProcessError) as e:
            print(f'painter audit skipped (no C compiler? {e})')
            return out
        for length in PAINTER_CUTS:
            per_quad, per_view = painter.audit(out, views, tmp, face_drawn, near_first=True)
            score = per_quad[:, 0] + per_quad[:, 1]
            more = dict(cuts)
            for qi in np.nonzero(score >= PAINTER_MIN_PIXELS)[0]:
                src = out[qi].src
                if src is not None and more.get(src, math.inf) > length:
                    more[src] = length
            seen = [v for v in per_view if v is not None]
            changed = sum(1 for k, v in more.items() if cuts.get(k) != v)
            print(f'painter audit: {sum(e for e, _ in seen)} + {sum(t for _, t in seen)} pixels painted out of order '
                  f'in {len(seen)} views; cutting {changed} polygons to {length:.0f}')
            cut_out = emit_level(tris, ramps, more, near, polygons)
            if vertex_count(cut_out) > VERTEX_BUDGET:
                # over budget: the worst offenders first, as many as fit (a binary search)
                by_src = {}
                for qi in np.nonzero(score >= PAINTER_MIN_PIXELS)[0]:
                    if out[qi].src is not None:
                        by_src[out[qi].src] = by_src.get(out[qi].src, 0) + score[qi]
                ranked = sorted((k for k, v in more.items() if cuts.get(k) != v), key=lambda k: -by_src.get(k, 0))
                lo, hi, best = 0, len(ranked), (cuts, out)
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    trial = dict(cuts)
                    trial.update({k: more[k] for k in ranked[:mid]})
                    trial_out = emit_level(tris, ramps, trial, near, polygons)
                    if vertex_count(trial_out) <= VERTEX_BUDGET:
                        lo, best = mid, (trial, trial_out)
                    else:
                        hi = mid
                print(f'  that makes {vertex_count(cut_out)} vertices, over {VERTEX_BUDGET}: the worst {lo} only')
                cuts, out = best
                break
            cuts, out = more, cut_out
        per_quad, per_view = painter.audit(out, views, tmp, face_drawn, near_first=True)
    seen = [v for v in per_view if v is not None]
    print(f'painter audit: {sum(e for e, _ in seen)} + {sum(t for _, t in seen)} pixels left out of order, '
          f'{vertex_count(out)} vertices ({time.time() - t0:.0f} s)')
    save_checks(name, cuts={keys[src]: length for src, length in cuts.items()})
    return out


# Fast builds: FAST=1 skips the slow check, the painter's audit, and takes its cuts from the last
# full build of the level (kept in build/checks/) for every polygon still there unchanged; new
# or changed polygons go uncut until the next full build. For iterating on a map: a level that
# ships is built in full.
FAST = os.environ.get('FAST') == '1'
CHECKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build', 'checks')


def polygon_keys(polygons):
    """An identity for each polygon (corners, facing, atlas layer) that holds from one build to
    the next: its corners in any order, the way it faces, its texture layer; numbered when the
    same polygon comes up again."""
    seen = {}
    keys = []
    for p, n, layer in polygons:
        corners = sorted(tuple(round(float(v), 1) + 0.0 for v in c) for c in p)
        facing = tuple(round(float(v), 3) + 0.0 for v in n)
        k = hashlib.sha1(repr((corners, facing, int(layer))).encode()).hexdigest()[:16]
        seen[k] = seen.get(k, 0) + 1
        keys.append(k if seen[k] == 1 else f'{k}.{seen[k]}')
    return keys


def load_checks(name):
    try:
        with open(os.path.join(CHECKS_DIR, f'{name}.json')) as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(f'FAST=1 takes the checks of a full build of {name} ({CHECKS_DIR}): build it in full first')


def save_checks(name, **parts):
    path = os.path.join(CHECKS_DIR, f'{name}.json')
    os.makedirs(CHECKS_DIR, exist_ok=True)
    checks = {}
    if os.path.exists(path):
        with open(path) as f:
            checks = json.load(f)
    checks.update(parts)
    with open(path, 'w') as f:
        json.dump(checks, f)


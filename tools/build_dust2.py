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
import itertools
import json
import math
import os
import struct
import subprocess
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


FLOOR_Z = 0.0           # Hammer z at CTR y 0 (the engine draws karts on water terrain only above
                        # y 0: a map with water puts its surface there)


def to_ctr(p):
    p = np.asarray(p, dtype=np.float64)
    return np.stack([(p[..., 0] - CENTER[0]) * SCALE, (p[..., 2] - FLOOR_Z) * SCALE, -(p[..., 1] - CENTER[1]) * SCALE], axis=-1)


def dir_to_ctr(n):
    n = np.asarray(n, dtype=np.float64)
    return np.stack([n[..., 0], n[..., 2], -n[..., 1]], axis=-1)


class Tri:
    __slots__ = ('p', 'uv', 'layer', 'n', 'ph', 'nh', 'solid', 'terrain')

    def __init__(self, p, uv, layer, n, ph, nh):
        self.p = p        # (3,3) CTR space
        self.uv = uv      # (3,2) texels in the layer
        self.layer = layer
        self.n = n        # unit normal, CTR space (the side that faces the player)
        self.ph = ph      # (3,3) Hammer space
        self.nh = nh      # unit normal, Hammer space
        self.solid = True  # False: drawn but not collided with (stair risers under a ramp)
        self.terrain = 0   # CTR terrain type (enum TerrainType): 0 asphalt, 4 water...


# Model edits for driving.
# Triangles to leave out: (mesh name) -> indices.
# Door leaves, taken out (by mesh name: one set of triangles per leaf). The mid doors stand half
# closed with a gap a kart can't fit through and the long doors make a zig-zag; swung open, the
# leaves z-fought with the frames and looked broken. The floor was cut around them: patched.
DOOR_LEAVES = {
    'part8_part8_0': [{300, 301, 302, 305, 306, 307, 867, 868}, {403, 404, 405, 408, 409, 410, 973, 974}],     # mid
    'part11_part11_0': [{201, 202, 203, 204, 205, 215, 216, 217, 218, 219, 643, 644},                          # long
                        {210, 211, 212, 213, 214, 220, 221, 222, 223, 224, 645, 646}],
}
REMOVED = {name: set().union(*leaves) for name, leaves in DOOR_LEAVES.items()}


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
        for k in range(len(P)):
            if k in skip:
                continue
            p = P[k].copy()
            uv = UV[k] * LAYER_SIZE
            nk = N[k].copy()
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
    slots = door_slot_fills(glb, layer_of_mat)
    tris.extend(slots)
    print(f'{len(tris)} triangles ({flipped} turned to face their normals, {len(patches)} floor patches and '
          f'{len(slots)} slot fills where door leaves were)')
    fill_black_faces(tris, imgs)
    return tris, imgs


def fill_black_faces(tris, imgs, radius=700.0):
    """Faces the model's light baking left (mostly) black. Most have a twin somewhere in the map,
    a lit triangle of the same shape (Dust 2 repeats its crates, frames and steps): they take
    the nearest twin's texture, corner for corner. The rest take one texel from around them: of
    the lit faces within radius (facing the same way if there are any), the sample nearest their
    median brightness, so a fill is no brighter than its surroundings."""
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

    # black means unbaked: every sample (near) zero. Dark faces stay as they are: the passages and
    # their crates are dark in the model's light, and a dark texture is not a broken one (taking
    # "mostly darker than 10" for black once repainted a dark crate in the long doors passage).
    rgb = {i + 1: np.asarray(Image.open(io.BytesIO(data)).convert('RGB')) for i, data in enumerate(imgs)}

    def brightest(t):
        A = rgb[t.layer]
        return max(int(A[int(np.clip(q[1], 0, LAYER_SIZE - 1)), int(np.clip(q[0], 0, LAYER_SIZE - 1))].max())
                   for q in (np.dot(w, t.uv) for w in weights))

    black = [i for i, t in enumerate(tris) if brightest(t) < 6]
    blackset = set(black)
    centres = np.array([t.p.mean(axis=0) for t in tris])
    kinds = np.array([kind(t) for t in tris])

    def edges(t):
        return [float(np.linalg.norm(t.ph[(k + 1) % 3] - t.ph[k])) for k in range(3)]

    def shape(t):
        return tuple(round(e * 2) / 2 for e in sorted(edges(t)))

    twins = {}
    for k, t in enumerate(tris):
        if k not in blackset and min(edges(t)) > 0.5:
            twins.setdefault(shape(t), []).append(k)

    # a quad's two halves: triangles sharing an edge in one plane
    def vkey(p):
        return tuple(np.round(p, 1))

    edge_tris = {}
    for k, t in enumerate(tris):
        for e in range(3):
            edge_tris.setdefault(frozenset((vkey(t.ph[e]), vkey(t.ph[(e + 1) % 3]))), []).append(k)

    def partner(k):
        t = tris[k]
        for e in range(3):
            for m in edge_tris.get(frozenset((vkey(t.ph[e]), vkey(t.ph[(e + 1) % 3]))), ()):
                if m != k and float(np.dot(tris[m].nh, t.nh)) > 0.999:
                    return m
        return None

    def copy_pair(i, j):
        """Black halves i, j of a quad take a lit quad's texture (twins sharing the same edge)."""
        ti, tj = tris[i], tris[j]
        shared = [vkey(p) for p in ti.ph if vkey(p) in {vkey(q) for q in tj.ph}]
        if len(shared) != 2:
            return False
        best = None
        for k in twins.get(shape(ti), ()):
            m = partner(k)
            if m is None or m in blackset or shape(tris[m]) != shape(tj) or kinds[k] != kinds[i]:
                continue
            tk, tm = tris[k], tris[m]
            sk = [vkey(p) for p in tk.ph if vkey(p) in {vkey(q) for q in tm.ph}]
            if len(sk) != 2:
                continue
            for c, d in ((sk[0], sk[1]), (sk[1], sk[0])):
                # corners of i and j onto corners of k and m: the shared edge either way round
                to_k = {shared[0]: c, shared[1]: d}
                oi = [vkey(p) for p in ti.ph if vkey(p) not in shared][0]
                oj = [vkey(p) for p in tj.ph if vkey(p) not in shared][0]
                ok = [vkey(p) for p in tk.ph if vkey(p) not in sk][0]
                om = [vkey(p) for p in tm.ph if vkey(p) not in sk][0]
                to_k[oi], to_m = ok, {shared[0]: c, shared[1]: d, oj: om}
                err = sum(abs(np.linalg.norm(np.subtract(a, b)) - np.linalg.norm(np.subtract(to_k[a], to_k[b])))
                          for a, b in ((shared[0], oi), (shared[1], oi)))
                err += sum(abs(np.linalg.norm(np.subtract(a, b)) - np.linalg.norm(np.subtract(to_m[a], to_m[b])))
                           for a, b in ((shared[0], oj), (shared[1], oj)))
                dist = float(np.linalg.norm(centres[k] - centres[i]))
                if err < 1.0 and (best is None or dist < best[0]):
                    best = (dist, k, m, dict(to_k), dict(to_m))
        if best is None:
            return False
        _, k, m, to_k, to_m = best
        uv_k = {vkey(p): uv for p, uv in zip(tris[k].ph, tris[k].uv)}
        uv_m = {vkey(p): uv for p, uv in zip(tris[m].ph, tris[m].uv)}
        ti.layer, tj.layer = tris[k].layer, tris[m].layer
        ti.uv = np.array([uv_k[to_k[vkey(p)]] for p in ti.ph])
        tj.uv = np.array([uv_m[to_m[vkey(p)]] for p in tj.ph])
        return True

    copied = filled = 0
    done = set()
    for i in black:
        j = partner(i)
        if i not in done and j is not None and j in blackset and j not in done and copy_pair(i, j):
            done |= {i, j}
            copied += 2
    for i in black:
        if i in done:
            continue
        t = tris[i]
        cands = [k for k in twins.get(shape(t), ()) if kinds[k] == kinds[i]] or twins.get(shape(t), [])
        if cands:
            k = min(cands, key=lambda k: float(np.linalg.norm(centres[k] - centres[i])))
            et, src = edges(t), tris[k]
            # corners matched so each edge lands on an edge of the same length (edge j runs from
            # corner j to corner j + 1)
            best = min(itertools.permutations(range(3)),
                       key=lambda pm: sum(abs(et[j] - float(np.linalg.norm(src.ph[pm[(j + 1) % 3]] - src.ph[pm[j]])))
                                          for j in range(3)))
            t.layer = src.layer
            t.uv = src.uv[list(best)].copy()
            copied += 1
            continue
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
    print(f'{len(black)} black faces: {copied} take a lit twin\'s texture, {filled} the colour around them')


def _chains(edges):
    """Edges (pairs of vertex keys) -> paths (lists of keys), each from one end to the other."""
    nbr = {}
    for a, b in edges:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    seen, paths = set(), []
    for start in [v for v, ns in nbr.items() if len(ns) == 1] + list(nbr):
        if start in seen:
            continue
        path, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [n for n in nbr[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            path.append(cur)
        paths.append(path)
    return paths


def door_slot_fills(glb, layer_of_mat):
    """The arches and jambs were modelled with a slot where each door leaf's top and hinge edges
    sat (the leaf filled it). With the leaves out, that slot shows the hollow wall and the sky:
    close it, zipping the two outlines the leaf's faces left (open edges of the remaining mesh),
    textured as the surface beside it."""
    key = lambda p: tuple(np.round(p, 1))  # noqa: E731
    out = []
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        leaves = DOOR_LEAVES.get(name, ())
        if not leaves:
            continue
        removed = set().union(*leaves)
        uvs = UV * LAYER_SIZE
        layer = layer_of_mat[mat]
        pos = {}
        edge_use = {}
        for k in range(len(P)):
            if k in removed:
                continue
            for e in range(3):
                a, b = key(P[k][e]), key(P[k][(e + 1) % 3])
                pos[a], pos[b] = P[k][e], P[k][(e + 1) % 3]
                edge_use.setdefault(frozenset((a, b)), []).append(k)
        for ids in leaves:
            # the leaf's two big faces: vertices by the side of the leaf they are on
            normals = []
            for k in ids:
                n = np.cross(P[k][1] - P[k][0], P[k][2] - P[k][0])
                normals.append((np.linalg.norm(n), n / (np.linalg.norm(n) + 1e-12), k))
            main = max(normals)[1]
            side = {}
            for _, n, k in normals:
                d = float(np.dot(n, main))
                if abs(d) > 0.9:
                    for p in P[k]:
                        side[key(p)] = 0 if d > 0 else 1
            zmin = min(p[2] for k in ids for p in P[k])
            open_edges = [[], []]
            owner = {}
            for e, ks in edge_use.items():
                if len(ks) != 1 or len(e) != 2:
                    continue
                a, b = tuple(e)
                if a not in side or b not in side or side[a] != side[b]:
                    continue
                if abs(pos[a][2] - zmin) < 0.5 and abs(pos[b][2] - zmin) < 0.5:
                    continue   # the floor cut: door_floor_patches
                open_edges[side[a]].append((a, b))
                owner[frozenset((a, b))] = ks[0]
            ca, cb = _chains(open_edges[0]), _chains(open_edges[1])
            if len(ca) != 1 or len(cb) != 1:
                continue
            A, B = ca[0], cb[0]
            if (np.linalg.norm(pos[A[0]] - pos[B[0]]) + np.linalg.norm(pos[A[-1]] - pos[B[-1]]) >
                    np.linalg.norm(pos[A[0]] - pos[B[-1]]) + np.linalg.norm(pos[A[-1]] - pos[B[0]])):
                B = B[::-1]
            i = j = 0
            while i < len(A) - 1 or j < len(B) - 1:
                if j == len(B) - 1 or (i < len(A) - 1 and
                                       np.linalg.norm(pos[A[i + 1]] - pos[B[j]]) <= np.linalg.norm(pos[A[i]] - pos[B[j + 1]])):
                    tri, ok = [A[i], A[i + 1], B[j]], owner[frozenset((A[i], A[i + 1]))]
                    i += 1
                else:
                    tri, ok = [A[i], B[j], B[j + 1]], owner[frozenset((B[j], B[j + 1]))]
                    j += 1
                ph = np.array([pos[v] for v in tri])
                n = np.cross(ph[1] - ph[0], ph[2] - ph[0])
                if np.linalg.norm(n) < 1e-6:
                    continue
                o = P[ok]
                on = np.cross(o[1] - o[0], o[2] - o[0])
                if np.dot(n, on) < 0:   # face the way the surface beside it faces
                    ph = ph[[0, 2, 1]]
                    n = -n
                # texture: the neighbour's mapping, carried across the slot
                e1, e2 = o[1] - o[0], o[2] - o[0]
                G = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
                uv = []
                for p in ph:
                    rhs = np.array([(p - o[0]) @ e1, (p - o[0]) @ e2])
                    u, v = np.linalg.solve(G, rhs)
                    uv.append(uvs[ok][0] + u * (uvs[ok][1] - uvs[ok][0]) + v * (uvs[ok][2] - uvs[ok][0]))
                nh = n / np.linalg.norm(n)
                out.append(Tri(to_ctr(ph), np.clip(np.array(uv), 0, LAYER_SIZE - 1), layer, dir_to_ctr(nh), ph, nh))
    return out


def door_floor_patches(glb, tris):
    """The floor was cut around the closed door leaves: fill where a leaf stood, with the texture
    of the floor beside it."""
    out = []
    floors = [t for t in tris if t.nh[2] > 0.99]
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        for ids in DOOR_LEAVES.get(name, ()):
            pts = np.concatenate([P[k] for k in ids])
            zmin = pts[:, 2].min()
            base = pts[np.abs(pts[:, 2] - zmin) < 1.0][:, :2]
            hull = convex_hull(base)
            if len(hull) < 3:
                continue
            mid = hull.mean(axis=0)
            # the biggest floor triangle near the door lends its texture: the patch is laid on it,
            # centred, so it samples the middle of that floor's island (the floor's own mapping,
            # extended under the door, ran into other islands: black and orange strips)
            near = [t for t in floors if abs(t.ph[0, 2] - zmin) <= 1.0 and
                    np.linalg.norm(t.ph[:, :2].mean(axis=0) - mid) < 160]
            if not near:
                continue
            area = lambda t: abs(np.cross(t.ph[1, :2] - t.ph[0, :2], t.ph[2, :2] - t.ph[0, :2])) / 2  # noqa: E731
            ft = max(near, key=area)
            A = np.column_stack([ft.ph[:, :2], np.ones(3)])
            try:
                to_uv = np.linalg.solve(A, ft.uv)   # Hammer (x, y, 1) -> texel, on that floor
            except np.linalg.LinAlgError:
                continue
            shift = ft.ph[:, :2].mean(axis=0) - mid
            for i in range(1, len(hull) - 1):
                tri = np.array([[*hull[0], zmin], [*hull[i], zmin], [*hull[i + 1], zmin]])
                if np.cross(tri[1] - tri[0], tri[2] - tri[0])[2] < 0:
                    tri = tri[[0, 2, 1]]
                n = np.array([0.0, 0.0, 1.0])
                uv = np.column_stack([tri[:, :2] + shift, np.ones(3)]) @ to_uv
                out.append(Tri(to_ctr(tri), np.clip(uv, 0, LAYER_SIZE - 1), ft.layer, dir_to_ctr(n), tri, n))
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
                if u.layer != t.layer or np.dot(u.n, t.n) < 0.9999 or u.solid != t.solid or u.terrain != t.terrain:
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
    origin = page_for(np.array(UV9))
    if origin is None:
        return None
    faces = [layout(np.array([UV9[c] for c in fc]), layer, origin) for fc in FACE_CORNERS]
    low = layout(np.array([UV9[c] for c in (0, 1, 2, 3)]), layer, origin)
    flags, _ = surface_flags(n, solid)
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
        if q.flags & FLAG_GROUND and q.hidden and q.color is None:
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
    uv_s = max(np.abs(ucorners[1] - ucorners[0]).max(), np.abs(ucorners[3] - ucorners[2]).max())
    uv_t = max(np.abs(ucorners[2] - ucorners[0]).max(), np.abs(ucorners[3] - ucorners[1]).max())
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
    uvlong = max(np.abs(ub - ua).max(), np.abs(uc - ua).max(), np.abs(uc - ub).max())
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
# loads its own texture file (the entry before) with its own VRAM layout, so Dust 2 is grafted
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
# half the low two), additively blended. Dust 2's palettes: clear, opaque white (the loop), an
# added grey (edges) and an opaque dark slate (the floors, like Counter-Strike's radar). Racer
# icons go at icon start + world position * icon size / world range (UI_Map_GetIconPos); the
# image sits with its bottom-right corner at (500, 195) on the 512 x 240 screen.
MAP_SIZE = 80
MAP_SCREEN = (420, 115)    # its top-left corner on screen
MAP_CLEAR, MAP_WHITE, MAP_EDGE, MAP_FLOOR = 0, 1, 2, 3
MAP_COLORS = (0x0000, 0x7FFF, 0xA108, 0x1CC6)   # 15-bit BGR; 0x8000 = blended


def minimap_window(out, margin=0.03):
    """A square of the world (x0, z0, side) around everything drivable."""
    pts = np.array([p for q in out if q.flags & FLAG_GROUND and not q.flags & FLAG_KILL_PLANE for p in q.pos], dtype=float)
    x0, x1 = pts[:, 0].min(), pts[:, 0].max()
    z0, z1 = pts[:, 2].min(), pts[:, 2].max()
    side = max(x1 - x0, z1 - z0) * (1 + 2 * margin)
    return ((x0 + x1) / 2 - side / 2, (z0 + z1) / 2 - side / 2, side)


def minimap_placement(window):
    """struct UIMap (+ topHalfMode) for a window, north up (mode 0: x right, z down)."""
    x0, z0, side = window
    rng = int(round(side))
    start_x = int(round(MAP_SCREEN[0] - x0 * MAP_SIZE / rng))
    start_y = int(round(MAP_SCREEN[1] - z0 * MAP_SIZE / rng)) + 16
    return (int(x0) + rng, int(z0) + rng, int(x0), int(z0), MAP_SIZE, MAP_SIZE // 2, start_x, start_y, 0, 0)


def minimap_image(out, window, route=None, scale=4):
    """The map: floors in slate, a race loop over them in white."""
    from PIL import ImageDraw
    x0, z0, side = window
    n = MAP_SIZE * scale
    k = n / side
    floor = Image.new('L', (n, n), 0)
    d = ImageDraw.Draw(floor)
    for q in out:
        if not q.flags & FLAG_GROUND or q.flags & FLAG_KILL_PLANE:
            continue
        ring = [q.pos[i] for i in ((0, 1, 2) if q.triangle else (0, 1, 3, 2))]
        d.polygon([((p[0] - x0) * k, (p[2] - z0) * k) for p in ring], fill=255)
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


DUST2_SKY = [(170, 190, 220, 1), (230, 200, 160, 1), (200, 210, 230, 1)]


def write_modes(outdir, name, out, nodes, spawns, nav, route, g, bases, vrms, minimap, build_name='de_dust2',
                clear_colors=DUST2_SKY):
    """The track as one LEV per mode, each grafted onto that mode's Dingo Canyon level, and that
    mode's texture file with the track's minimap drawn in."""
    hitbox_of = {'crate_question': (76, 48), 'crate_fruit': (76, 48), 'fruit': (64, 64)}
    window, map_img = minimap
    info = None
    for suffix, entry in MODES:
        base = bases[entry]
        with open(os.path.join(outdir, f'{name}{suffix}.vrm'), 'wb') as f:
            f.write(patch_vrm(vrms[entry], map_icon(base), map_img))
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
                   clear_colors=clear_colors,
                   build_name=build_name, nav_paths=nav, base=base, instances=pickups, hitboxes=hitboxes,
                   flyin=base_flyin(base), minimap=minimap_placement(window))
        data, mode_info = write_level(lv)
        data += b'\0' * ((-len(data)) % 2048)
        with open(os.path.join(outdir, f'{name}{suffix}.lev'), 'wb') as f:
            f.write(data)
        print(f'  {name}{suffix}.lev: {len(pickups)} pickups, {len(data)} bytes')
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


def emit_level(tris, ramps, cuts=None, near=None):
    """Quadblocks for the model's triangles, after the stair ramps. Each gets .src, the polygon
    it comes from (('q', i): a merged pair, ('t', i): a lone triangle; None: a ramp), and
    cuts {src: length} cuts some shorter (see painter_cuts); near: see grid_cut_floors."""
    cuts = cuts or {}
    out = list(ramps)
    for q in out:
        q.src = None
    tris = fix_t_junctions(grid_cut_floors(tris, near=near))
    quads, singles = pair_quads(tris)
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


def painter_cuts(tris, ramps, out, g, start, near=None):
    """`out` again, with the polygons the painter's audit flags cut shorter (see above)."""
    import tempfile
    import time
    import painter
    t0 = time.time()
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
            cut_out = emit_level(tris, ramps, more, near)
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
                    trial_out = emit_level(tris, ramps, trial, near)
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
    return out


def door_frames(glb, tris, margin=256.0, above=192.0):
    """Triangles around the doorways whose leaves were taken out: the frames and arches have
    faces that only the leaves hid from behind (seen through gaps in the arch from a few spots
    only, too few for the ray sampling to be sure of), so they all get twins."""
    boxes = []
    for mat, P, UV, _, name, N in triangles(glb, with_normals=True):
        for leaves in [DOOR_LEAVES.get(name, ())]:
            if not leaves:
                continue
            pts = np.concatenate([P[k] for ids in leaves for k in ids])
            boxes.append((pts.min(axis=0) - [margin, margin, 0.0], pts.max(axis=0) + [margin, margin, above]))
    out = set()
    for k, t in enumerate(tris):
        c = t.ph.mean(axis=0)
        if any(np.all(c >= lo) and np.all(c <= hi) for lo, hi in boxes):
            out.add(k)
    return out


def reversed_twins(tris, exposed):
    """Back-to-back copies of the triangles seen from behind (see visibility.py): CTR draws and
    collides with one side of a face, so a twin facing the other way closes the hole."""
    out = []
    for k in sorted(exposed):
        t = tris[k]
        r = Tri(t.p[[0, 2, 1]].copy(), t.uv[[0, 2, 1]].copy(), t.layer, -t.n, t.ph[[0, 2, 1]].copy(), -t.nh)
        r.solid = t.solid
        r.terrain = t.terrain
        out.append(r)
    return out


def main(glb, disc, outdir):
    global light_maps
    import time
    from navgrid import NavGrid
    from visibility import exposed_backfaces
    os.makedirs(outdir, exist_ok=True)
    tris, imgs = load(glb)
    light_maps = load_light_maps(imgs)
    ramps = []
    add_stair_ramps(tris, ramps)
    out = emit_level(tris, ramps)
    landmarks = landmark_positions(tris)
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in out])

    # faces seen from behind from anywhere a kart can drive to get a twin facing the other way
    t0 = time.time()
    s = landmarks[LOOPS['dust2'][0]]
    exposed = exposed_backfaces([t.p for t in tris], [t.n for t in tris], g, g.nearest(s[0], s[1] or 0, s[2]))
    twins = reversed_twins(tris, set(exposed) | door_frames(glb, tris))
    print(f'{len(twins)} triangles seen from behind get a reversed twin ({time.time() - t0:.0f} s)')
    if twins:
        out = emit_level(tris + twins, ramps)
    out = painter_cuts(tris + twins, ramps, out, g, g.nearest(s[0], s[1] or 0, s[2]))
    print(f'{len(out)} quadblocks')
    kill_plane(out)
    bases, vrms = base_levels(disc)
    window = minimap_window(out)
    tracks = {}
    first = None
    for name, stops in LOOPS.items():
        print(f'{name}:')
        nodes, spawns, route, nav = race_setup(out, g, landmarks, stops)
        map_img = minimap_image(out, window, route['path'])
        info = write_modes(outdir, name, out, nodes, spawns, nav, route, g, bases, vrms, (window, map_img))
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
    write_modes(outdir, 'dust2_free', out, free_nodes, spawns, nav, route, g, bases, vrms,
                (window, minimap_image(out, window)))
    size = build_atlas(imgs, os.path.join(outdir, 'dust2_atlas.jpg'))
    meta = dict(scale=SCALE, center=CENTER, atlas=dict(image='dust2_atlas.jpg', width=size[0], height=size[1]),
                spawn=spawns[0], info=info, landmarks=landmarks, tracks=tracks,
                modes=[suffix for suffix, _ in MODES])
    with open(os.path.join(outdir, 'dust2.json'), 'w') as f:
        json.dump(meta, f, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])

"""Builds part of Bayview, Need for Speed: Underground 2's city, as a CTR level, from your PS2 disc.

    python3 -I tools/build_bayview.py NFSU2.iso CTR_DISC.bin OUTDIR [AREA]
    python3 -I tools/build_bayview.py --areas         (lists them)

NFSU2.iso is your Need for Speed: Underground 2 disc image (PS2, NTSC-U, SLUS-21065); AREA is
one of AREAS. tools/nfsu2/ reads the city: its meshes, textures and the night's light, which
NFSU2 bakes into vertex colours. A CTR level holds 65,536 vertices, so an area is a loop of
streets through its waypoints and what's along it (buildings and terrain farther out than
props). Every texture goes into the atlas once, repeating in place ("CTRV" atlas: the faces
keep their uvs, lit by their vertex colours), and the track pipeline (tools/track.py) makes the
level, as for Counter-Strike's maps: free drive, NAME_free.lev and the rest.

DRY=1 stops before the painter's audit (to see the vertex count); VISIBILITY=0 keeps what the
chase camera never sees.

The level holds data from both discs: keep it to yourself.
"""
import io
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_map  # noqa: E402
import track  # noqa: E402
from nfsu2.world import BUILDING, PROP, TERRAIN, Bayview  # noqa: E402

FLOOR = 3               # a corridor kind besides nfsu2.world's: the city's floors
SCALE = 64.0            # CTR units per metre: streets about as wide, to a kart, as Dust 2's
# Stretches of the city (metres: x east, y north): a loop of streets through waypoints (free
# drive starts at the first, facing the second), and what's along it.
AREAS = {
    'citycore': dict(title='City Core', waypoints=[(-955, -335), (-700, -515), (-640, -250)]),
    'coalharbor': dict(title='Coal Harbor', waypoints=[(-1300, -1652), (-940, -1550), (-1004, -1660), (-1232, -1832)]),
    'jackson': dict(title='Jackson Heights', waypoints=[(-2230, 2190), (-1810, 2160), (-1790, 1920), (-2120, 1870)]),
    # experiments past 65,536 vertices (vertex banks): the same loop, far more round it
    'citycorexl': dict(title='City Core XL', waypoints=[(-955, -335), (-700, -515), (-640, -250)],
                       corridor={TERRAIN: 150.0, BUILDING: 150.0, PROP: 60.0, FLOOR: 60.0}, min_prop=0.0,
                       full_detail=True, vertices=400000, experiment=True),
}
NIGHT = [(8, 10, 24, 1), (40, 34, 60, 1), (14, 16, 34, 1)]
# Left out: race barriers (only up during races), the panoramas (skylines and hills for far
# away, over the streets), and the light shafts and glows NFSU2 draws
# additively (their textures aren't in the packs).
SKIP_SOLIDS = ('XO_TRACKBARRIER', 'PAN_', 'LIGHTMASK', 'SFXFLARE')
SKIP_TEXTURES = ('SFX_', 'HEADLIGHTGLOW', 'LIGHTGLOW')
GROUND_TEXTURES = ('RDP', 'TRN', 'ARC_SIDEWALK', 'ARC_CURB', 'ARC_PAVE')
NAV_CELL = 128          # CTR units
MIN_PROP = 3.0          # metres: props smaller than this (trash cans, bollards, little signs) go
# metres either side of the route kept: buildings and the city's own walls and terrain (its
# floors less: what's farther is seen, not driven on), props only by the road
CORRIDOR = {TERRAIN: 60.0, BUILDING: 60.0, PROP: 18.0, FLOOR: 30.0}
PAD = 8                 # texels of each texture's wrap-around border in the atlas
LAYERS = 14
CUTOUT = 0.02           # cutouts are more than this much see-through (see is_cutout): drawn, not collided with
BRIGHTNESS, GAMMA = 1.15, 0.8
VIEW_EVERY = 2          # chase views on every other grid cell (128 CTR units), 8 headings each
MIN_PIXELS = 4
FLOOR_CELL = 1536.0     # CTR units
LOW_WALL = 0.4          # metres


def wrap_texture(im):
    """A texture as the atlas shader can repeat it: power-of-two sides from 32 to 256 texels
    (smaller ones repeated, bigger ones halved)."""
    h, w = im.shape[:2]
    while w > 256 or h > 256:
        im = np.asarray(Image.fromarray(im).resize((max(1, w // 2) if w > 256 else w, max(1, h // 2) if h > 256 else h), Image.LANCZOS))
        h, w = im.shape[:2]
    return np.tile(im, (max(1, 32 // h), max(1, 32 // w), 1))


def pack_textures(textures, used, cutouts):
    """Places every used texture once in 1024 x 1024 layers, on shelves, its origin 32-aligned
    (the atlas shader's page) and with a PAD-texel wrapped border (for filtering across its
    repeats). Returns ({hash: (layer, x, y, w, h, scale)}, {layer: RGBA array}): scale is the
    texture's original size over the size placed (its uvs, in repeats, times scale give
    texels... of what is placed)."""
    def opaque(h):
        im = textures[h].rgba
        if h in cutouts:
            return im
        im = im.copy()
        im[..., 3] = 255
        return im
    imgs = {h: wrap_texture(opaque(h)) for h in used}
    for _ in range(4):
        rects, layers = {}, {}
        layer, x, y, shelf = 1, 0, 0, 0

        def up(v):
            return -(-v // track.PAGE_ALIGN) * track.PAGE_ALIGN

        order = sorted(imgs, key=lambda h: (-imgs[h].shape[0], -imgs[h].shape[1]))
        ok = True
        for h in order:
            im = imgs[h]
            th, tw = im.shape[:2]
            ox, oy = up(x + PAD), up(y + PAD)
            if ox + tw + PAD > track.LAYER_SIZE:
                x, y, shelf = 0, y + shelf, 0
                ox, oy = up(PAD), up(y + PAD)
            if oy + th + PAD > track.LAYER_SIZE:
                layer, x, y, shelf = layer + 1, 0, 0, 0
                ox, oy = up(PAD), up(PAD)
            if layer > LAYERS:
                ok = False
                break
            canvas = layers.setdefault(layer, np.zeros((track.LAYER_SIZE, track.LAYER_SIZE, 4), np.uint8))
            canvas[oy - PAD:oy + th + PAD, ox - PAD:ox + tw + PAD] = np.pad(im, ((PAD, PAD), (PAD, PAD), (0, 0)), mode='wrap')
            rects[h] = (layer, ox, oy, tw, th)
            x = ox + tw + PAD
            shelf = max(shelf, oy + th + PAD - y)
        if ok:
            return rects, layers
        biggest = max(im.shape[0] * im.shape[1] for im in imgs.values())
        imgs = {h: (wrap_texture(np.asarray(Image.fromarray(im).resize((max(32, im.shape[1] // 2), max(32, im.shape[0] // 2)), Image.LANCZOS)))
                    if im.shape[0] * im.shape[1] >= biggest // 2 else im) for h, im in imgs.items()}
    raise SystemExit('the textures never fit the atlas')


def wrap_code(w, h):
    """The atlas shader's tpage bits for a texture w x h repeating (see track.WRAP_CHANNELS)."""
    return 16 | int(math.log2(w // 32)) | int(math.log2(h // 32)) << 2


def clip(poly, k, c, keep_below):
    """A polygon (rows: attributes, column k the one cut) clipped to column k <= c (or >= c)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ia = (a[k] <= c) if keep_below else (a[k] >= c)
        ib = (b[k] <= c) if keep_below else (b[k] >= c)
        if ia:
            out.append(a)
        if ia != ib:
            t = (c - a[k]) / (b[k] - a[k])
            out.append(a + (b - a) * t)
    return out if len(out) >= 3 else None


MAX_SHIFT = 3           # uvs scaled up to 8 times (see track.WRAP_CHANNELS)


def wrap_pieces(rows, k, size):
    """A polygon (rows: x, y, z, s, t (texels), colours) cut along column k so that each piece
    spans at most 255 texels times the biggest uv scale from the repeat its smallest value is in."""
    limit = 255 << MAX_SHIFT
    out, todo = [], [rows]
    while todo:
        poly = todo.pop()
        lo, hi = min(r[k] for r in poly), max(r[k] for r in poly)
        base = math.floor(lo / size + 1e-9) * size
        if hi - base <= limit:
            out.append(poly)
            continue
        c = base + limit if base + limit > lo + 1 else base + size
        below, above = clip(poly, k, c, True), clip(poly, k, c, False)
        if below is None or above is None:
            out.append(poly)
            continue
        out.append(below)
        todo.append(above)
    return out


def uv_shift(local):
    """The smallest uv scale (its log2) that brings local texels (from the repeat's origin)
    under 256."""
    top = float(local.max())
    shift = 0
    while top / (1 << shift) > 255 and shift < MAX_SHIFT:
        shift += 1
    return shift


def is_cutout(rgba):
    """A see-through texture (foliage, fences): its alpha is all but on or off. NFSU2 gives
    roads and pavements alpha too, but as how much they reflect: GROUND_TEXTURES are opaque
    whatever their alpha."""
    a = rgba[..., 3]
    return (a < 64).mean() > CUTOUT and ((a >= 64) & (a < 192)).mean() < 0.1


def light(c):
    """NFSU2's baked night light (0x80 = 1), brightened: the game adds reflections and glow
    on top, CTR draws the colours alone."""
    return np.minimum(128 * BRIGHTNESS * (c / 128.0) ** GAMMA, 255)


def orient(groups, world, route):
    """NFSU2's walls face either way (the PS2 doesn't cull): each is turned to face the
    route, and ground (roads, pavements, terrain) that faces down is turned up. The
    triangles' corners (and uvs, colours) are reordered in place."""
    from scipy.spatial import cKDTree
    tree = cKDTree(route)
    flipped = 0
    for h, (P, UV, C, _) in groups.items():
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ln = np.linalg.norm(n, axis=1) + 1e-12
        up = n[:, 2] / ln
        c = P.mean(axis=1)
        _, i = tree.query(c[:, :2])
        to_route = route[i] - c[:, :2]
        ground = world.textures[h].name.startswith(GROUND_TEXTURES)
        wall = np.abs(up) <= 0.7
        flip = (wall & (np.sum(n[:, :2] * to_route, axis=1) < 0)) | ((up < -0.7) & ground)
        P[flip] = P[flip][:, ::-1]
        UV[flip] = UV[flip][:, ::-1]
        C[flip] = C[flip][:, ::-1]
        flipped += int(flip.sum())
    print(f'{flipped} triangles turned round')


def make_tris(world, groups, rects, cutouts, near):
    """track.Tri for every piece: uv = atlas texels, then the vertex colours, the texture's
    origin and wrap code (track.WRAP_CHANNELS). Walls are drawn from both sides."""
    tris = []
    for th, (P, UV, C, _) in groups.items():
        if th not in rects:
            continue
        layer, ox, oy, w, h = rects[th]
        tw, thh = world.textures[th].rgba.shape[1], world.textures[th].rgba.shape[0]
        # uvs in the placed texture's texels (a repeated small texture: its own size)
        sx, sy = min(tw, w), min(thh, h)
        code = wrap_code(w, h)
        cutout = th in cutouts
        for k in range(len(P)):
            n = np.cross(P[k, 1] - P[k, 0], P[k, 2] - P[k, 0])
            if np.linalg.norm(n) < 1e-6:
                continue
            n /= np.linalg.norm(n)
            floor = n[2] > 0.7
            # see-through walls (foliage, fences) are only drawn; floors always hold the kart;
            # walls lower than a kerb's height are driven over, as NFSU2's cars do
            low = np.ptp(P[k, :, 2]) < LOW_WALL
            solid = floor or not (cutout or low)
            rows = np.concatenate([P[k], UV[k] * (sx, sy), light(C[k, :, :3])], axis=1)
            pieces = []
            for a in wrap_pieces(list(rows), 3, w):
                pieces += wrap_pieces(a, 4, h)
            for piece in pieces:
                piece = np.array(piece)
                base = np.floor(piece[:, 3:5].min(axis=0) / (w, h) + 1e-9) * (w, h)
                local = np.maximum(piece[:, 3:5] - base, 0)
                shift = uv_shift(local)
                local = np.minimum(local, 255 << shift)
                pts = piece[:, :3]
                attrs = np.concatenate([local, piece[:, 5:8]], axis=1)
                polys = build_map.floor_cells(pts) if floor and near(track.to_ctr(pts)) else [pts]
                for poly in polys:
                    a = interpolate(pts, attrs, poly) if len(polys) > 1 else attrs
                    for i in range(1, len(poly) - 1):
                        idx = [0, i, i + 1]
                        p = np.asarray(poly)[idx]
                        if np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])) < 1e-6:
                            continue
                        b = a[idx]
                        tuv = np.concatenate([np.stack([ox + b[:, 0], oy + b[:, 1]], axis=1), b[:, 2:5],
                                              np.tile([ox, oy, code, shift], (3, 1))], axis=1)
                        t = track.Tri(track.to_ctr(p), tuv, layer, track.dir_to_ctr(n), p.copy(), n.copy())
                        t.solid = solid
                        if cutout or not floor:
                            t.terrain |= track.DOUBLE_SIDED
                        tris.append(t)
    print(f'{len(tris)} triangles')
    return tris


def interpolate(pts, attrs, poly):
    """attrs (per point of the convex polygon pts) at the points of poly, a piece of it, by the
    barycentrics of the fan triangle each lies in."""
    pts = np.asarray(pts)
    out = []
    for q in poly:
        best = None
        for i in range(1, len(pts) - 1):
            a, b, c = pts[0], pts[i], pts[i + 1]
            v0, v1, v2 = b - a, c - a, q - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            d20, d21 = v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-12:
                continue
            v = (d11 * d20 - d01 * d21) / den
            w_ = (d00 * d21 - d01 * d20) / den
            u = 1 - v - w_
            err = -min(u, v, w_)
            if best is None or err < best[0]:
                best = (err, attrs[0] * u + attrs[i] * v + attrs[i + 1] * w_)
        if best is None:
            # a degenerate polygon: the nearest corner's
            best = (0, attrs[int(np.argmin(np.linalg.norm(pts - q, axis=1)))])
        out.append(best[1])
    return np.array(out)


def visible_only(groups, cutouts, g, start, build_dir):
    """The triangles a kart's chase camera sees from somewhere it can drive to (at least
    MIN_PIXELS pixels over all the views): the backs and tops of buildings, what's inside
    them and what's hidden behind them go."""
    from painter import chase_views
    from visibility import visible_pixels
    keys = list(groups)
    P = np.concatenate([groups[k][0] for k in keys])
    owner = np.concatenate([np.full(len(groups[k][0]), i) for i, k in enumerate(keys)])
    cut = np.array([keys[i] in cutouts for i in owner])
    ctr = track.to_ctr(P)
    n = np.cross(ctr[:, 1] - ctr[:, 0], ctr[:, 2] - ctr[:, 0])
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    views = chase_views(g, start, every=VIEW_EVERY, headings=8)
    t0 = time.time()
    wall = np.abs(n[:, 1]) <= 0.7
    px = visible_pixels(ctr, n, ~cut, cut | wall, views, os.path.join(build_dir, '.tools'))
    keep = px >= MIN_PIXELS
    print(f'visibility: {keep.sum()} of {len(keep)} triangles seen from {len(views)} views ({time.time() - t0:.0f} s)')
    out = {}
    for i, k in enumerate(keys):
        m = keep[owner == i]
        if m.any():
            out[k] = tuple(a[m] for a in groups[k])
    return out


def point_in(p, x, y):
    (ax, ay), (bx, by), (cx, cy) = p[0, :2], p[1, :2], p[2, :2]
    d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
    d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
    d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def nav_quads(groups, cutouts=()):
    """The drivable grid's input straight from the triangles (no textures, no cuts): a
    triangle quadblock each, floor or wall (see-through foliage left out)."""
    out = []
    for h, (P, *_) in groups.items():
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ln = np.linalg.norm(n, axis=1)
        C = track.to_ctr(P)
        for k in range(len(P)):
            if ln[k] < 1e-6:
                continue
            floor = n[k, 2] / ln[k] > 0.7
            if h in cutouts and not floor:
                continue
            c = C[k]
            flags = track.FLAG_GROUND if floor else track.FLAG_COLLISION_SURFACE
            out.append((flags, [c[0], c[1], c[2], c[2], (c[0] + c[1]) / 2, (c[0] + c[2]) / 2, (c[1] + c[2]) / 2, (c[1] + c[2]) / 2, c[2]], True))
    return out


def is_road(name):
    return name.startswith(('RDP', 'TRN_ROAD', 'TRN_ASPH')) or 'ROAD' in name


def street_node(g, groups, world, x, y):
    """The drivable grid node on the road nearest map (x, y), on its lowest floor there (the
    street, not a bridge over it)."""
    best = None
    for h, (P, *_) in groups.items():
        if not is_road(world.textures[h].name):
            continue
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        up = n[:, 2] > 0.7 * (np.linalg.norm(n, axis=1) + 1e-12)
        c = P.mean(axis=1)
        d = np.hypot(c[:, 0] - x, c[:, 1] - y) + np.where(up, 0, 1e9) + c[:, 2] * 0.01
        k = int(np.argmin(d))
        if best is None or d[k] < best[0]:
            best = (d[k], c[k])
    if best is None or best[0] > 1e8:
        raise SystemExit(f'no road near {x}, {y}')
    c = track.to_ctr(best[1])
    nid = g.nearest(c[0], c[1], c[2])
    if nid is None:
        raise SystemExit(f'nowhere to drive near {x}, {y}')
    return nid


def road_cells(g, groups, world):
    """The drivable grid's cells (cx, cz) that road surfaces cover."""
    cells = set()
    for h, (P, *_) in groups.items():
        if not is_road(world.textures[h].name):
            continue
        C = track.to_ctr(P)
        for t in C:
            x0, z0 = g.cell(t[:, 0].min(), t[:, 2].min())
            x1, z1 = g.cell(t[:, 0].max(), t[:, 2].max())
            a, b, c = t[0][[0, 2]], t[1][[0, 2]], t[2][[0, 2]]
            for cx in range(x0, x1 + 1):
                for cz in range(z0, z1 + 1):
                    p = np.array(g.center(cx, cz))
                    d1 = np.cross(b - a, p - a)
                    d2 = np.cross(c - b, p - b)
                    d3 = np.cross(a - c, p - c)
                    if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
                        cells.add((cx, cz))
    return cells


OFF_ROAD = 20.0         # the route planner's cost of a step off the road


def plan_loop(g, nodes, roads):
    """A loop through the grid nodes (in order, back to the first), on the roads (cells in
    roads) where it can, each leg avoiding the cells the loop has already been on: [node ids]."""
    import heapq
    used = set()
    loop = []
    for a, b in zip(nodes, nodes[1:] + nodes[:1]):
        tx, _, tz = g.pos[b]
        openq = [(0.0, a)]
        cost = {a: 0.0}
        came = {}
        while openq:
            _, n = heapq.heappop(openq)
            if n == b:
                break
            for m, step in g.neighbours(n):
                x, _, z = g.pos[m]
                pen = {1: 4.0, 2: 2.5, 3: 1.6, 4: 1.2}.get(g.wall_dist[m], 1.0) * (6.0 if m in used else 1.0)
                if g.cell(x, z) not in roads:
                    pen *= OFF_ROAD
                c = cost[n] + step * pen
                if c < cost.get(m, 1e18):
                    cost[m] = c
                    came[m] = n
                    x, _, z = g.pos[m]
                    heapq.heappush(openq, (c + math.hypot(x - tx, z - tz), m))
        if b not in came and a != b:
            raise SystemExit('no way through the waypoints')
        leg = [b]
        while leg[-1] != a:
            leg.append(came[leg[-1]])
        leg = leg[::-1]
        for n in leg:
            x, _, z = g.pos[n]
            cx, cz = g.cell(x, z)
            for dx in range(-6, 7):
                for dz in range(-6, 7):
                    for k in range(len(g.floors[cx + dx][cz + dz]) if 0 <= cx + dx < g.nx and 0 <= cz + dz < g.nz else 0):
                        m = g.node.get((cx + dx, cz + dz, k))
                        if m is not None:
                            used.add(m)
        loop.extend(leg[1:] if loop else leg)
    return loop


def corridor(groups, route, reach):
    """The triangles near the route (map x, y points), by any corner or the middle: within
    reach[kind] metres (kinds: nfsu2.world's, and FLOOR); and the floor edges the cut leaves
    open, as (a, b) points."""
    from scipy.spatial import cKDTree
    dense = [route[0]]
    for a, b in zip(route, route[1:]):
        n = max(1, int(np.linalg.norm(b - a) / 2.0))
        dense += [a + (b - a) * (i / n) for i in range(1, n + 1)]
    route = np.array(dense)
    tree = cKDTree(route)
    out = {}
    kept_floor_edges, cut_floor_edges = {}, set()

    def key(p):
        return (round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2))
    for h, (P, UV, C, K) in groups.items():
        pts = np.concatenate([P, P.mean(axis=1, keepdims=True)], axis=1)
        d = tree.query(pts[..., :2].reshape(-1, 2))[0].reshape(len(P), 4).min(axis=1)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        floor = n[:, 2] > 0.7 * (np.linalg.norm(n, axis=1) + 1e-12)
        keep = d <= np.where(floor & (K == TERRAIN), reach[FLOOR], np.array([reach[k] for k in range(3)])[K])
        # big triangles the route runs over, though their corners and middle are far from it
        big = np.max([np.linalg.norm(P[:, a, :2] - P[:, b, :2], axis=1) for a, b in ((0, 1), (1, 2), (0, 2))], axis=0)
        for k in np.nonzero(~keep & (big > 20.0))[0]:
            for i in tree.query_ball_point(P[k].mean(axis=0)[:2], big[k]):
                if point_in(P[k], *route[i]):
                    keep[k] = True
                    break
        for k in np.nonzero(floor)[0]:
            for e in range(3):
                a, b = P[k, e], P[k, (e + 1) % 3]
                if keep[k]:
                    kept_floor_edges[(key(a), key(b))] = (a, b)
                else:
                    cut_floor_edges.add((key(b), key(a)))
        if keep.any():
            out[h] = (P[keep], UV[keep], C[keep], K[keep])
    # a kept floor's edge that a cut floor had on its other side: the corridor ends there
    open_edges = [ab for k, ab in kept_floor_edges.items() if k in cut_floor_edges]
    return out, open_edges


def edge_walls(open_edges, out, height=4.0):
    """Invisible walls on the corridor's open floor edges, facing in (map points)."""
    for a, b in open_edges:
        # a -> b runs counter-clockwise round its floor (seen from above): the floor is on
        # the left, the wall faces that way
        d = (b - a)[:2]
        if np.linalg.norm(d) < 0.05:
            continue
        inward = np.array([-d[1], d[0], 0.0]) / np.linalg.norm(d)
        A, B = track.to_ctr(a), track.to_ctr(b)
        up = np.array([0.0, height * track.SCALE, 0.0])
        n = track.dir_to_ctr(inward)
        corners = [A, B, A + up, B + up]
        # invisible_quad wants (p2 - p0) x (p1 - p0) along n
        if np.dot(np.cross(corners[2] - corners[0], corners[1] - corners[0]), n) < 0:
            corners = [B, A, B + up, A + up]
        grid = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0), (0, 0.5), (0.5, 0.5), (1, 0.5), (0.5, 1)]
        out.append(track.invisible_quad([track.bilinear(corners, s_, t_) for s_, t_ in grid], n))


def find_route(world, groups, cutouts, cfg, cache):
    """The loop through the area's waypoints (map x, y, z points: z the floor's), from the
    cache when the waypoints are the same."""
    from navgrid import NavGrid
    if os.path.exists(cache) and json.load(open(cache))['waypoints'] == [list(w) for w in cfg['waypoints']]:
        route = np.array(json.load(open(cache))['route'])
        if route.shape[1] == 3:
            return route
    wps = np.array(cfg['waypoints'], dtype=float)
    g = NavGrid(nav_quads(groups, cutouts))
    wp_nodes = [street_node(g, groups, world, x, y) for x, y in wps]
    loop = plan_loop(g, wp_nodes, road_cells(g, groups, world))
    route = np.array([[g.pos[n][0] / SCALE + track.CENTER[0], -g.pos[n][2] / SCALE + track.CENTER[1],
                       g.pos[n][1] / SCALE + track.FLOOR_Z] for n in loop])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(dict(waypoints=[list(w) for w in cfg['waypoints']], route=route.tolist()), open(cache, 'w'))
    return route


def main(iso, disc, outdir, area='citycore'):
    import navgrid
    from navgrid import NavGrid
    # 2 m grid cells: a city is big, its streets wide
    navgrid.CELL = NAV_CELL
    t_start = time.time()
    cfg = AREAS[area]
    os.makedirs(outdir, exist_ok=True)
    world = Bayview(iso)
    wps = np.array(cfg['waypoints'], dtype=float)
    margin = max(120.0, max({**CORRIDOR, **cfg.get('corridor', {})}.values()) + 20.0)
    bounds = (wps[:, 0].min() - margin, wps[:, 1].min() - margin, wps[:, 0].max() + margin, wps[:, 1].max() + margin)
    world.low_detail = not cfg.get('full_detail', False)
    track.VERTEX_BUDGET = cfg.get('vertices', 64000)
    groups = world.triangles(bounds, SKIP_SOLIDS, cfg.get('min_prop', MIN_PROP))
    # left out: untextured effects and the glows NFSU2 adds on top (their black is see-through)
    groups = {h: g for h, g in groups.items() if h in world.textures and not world.textures[h].name.startswith(SKIP_TEXTURES)}
    print(f'{sum(len(g[0]) for g in groups.values())} triangles round the waypoints, {len(groups)} textures')
    track.SCALE = SCALE
    allp = np.concatenate([g[0].reshape(-1, 3) for g in groups.values()])
    track.CENTER = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    track.FLOOR_Z = float(np.percentile(allp[:, 2], 1))
    print(f'centre {track.CENTER}, floor z {track.FLOOR_Z:.1f}')
    # NFSU2's floors are small (half the streets' triangles have sides under 10 m): the floor
    # grid only cuts its big terrain
    track.FLOOR_CELL = FLOOR_CELL
    track.FLOOR_MAX_EDGE = FLOOR_CELL * 1.6
    track.MAX_EDGE = 1200.0
    track.light_maps = None

    # the route: through the waypoints and back to the first, on the drivable grid
    cutouts = {h for h in groups if is_cutout(world.textures[h].rgba) and not world.textures[h].name.startswith(GROUND_TEXTURES)}
    route = find_route(world, groups, cutouts, cfg, os.path.join(outdir, '.tools', f'{area}_route.json'))
    length = float(np.sum(np.linalg.norm(np.diff(route[:, :2], axis=0), axis=1)))
    print(f'route: {len(wps)} waypoints, {length:.0f} m round')
    groups, open_edges = corridor(groups, route[:, :2], {**CORRIDOR, **cfg.get('corridor', {})})
    orient(groups, world, route[:, :2])
    allp = np.concatenate([g[0].reshape(-1, 3) for g in groups.values()])
    kill_y = int((allp[:, 2].min() - track.FLOOR_Z) * SCALE) - 600
    print(f'{sum(len(g[0]) for g in groups.values())} triangles along it, {len(open_edges)} open floor edges')

    rects, layers = pack_textures(world.textures, list(groups), cutouts)
    print(f'{len(rects)} textures in {len(layers)} atlas layers')
    g = NavGrid(nav_quads(groups, cutouts))
    start = street_node(g, groups, world, *wps[0])
    near = build_map.near_drivable(g, start)
    if os.environ.get('VISIBILITY') != '0':
        groups = visible_only(groups, cutouts, g, start, outdir)
    tris = make_tris(world, groups, rects, cutouts, near)
    tri_near = lambda t: near(t.p)   # noqa: E731
    ramps = []
    track.add_stair_ramps(tris, ramps)
    edge_walls(open_edges, ramps)
    polygons = track.level_polygons(tris, tri_near)
    out = track.emit_level(tris, ramps, near=tri_near, polygons=polygons)
    print(f'{len(out)} quadblocks, {track.vertex_count(out)} vertices')
    if os.environ.get('DRY') == '1':
        return
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in out])
    start = street_node(g, groups, world, *wps[0])
    # the free route's landmarks: the loop every 150 m or so, on the drivable cell nearest
    # each point (at its height) that the start reaches
    reach = g.reachable(start)
    reach_pos = np.array([g.pos[n] for n in sorted(reach)])
    pts = [g.pos[start]]
    walked = 0.0
    for a, b in zip(route, route[1:]):
        walked += float(np.linalg.norm(b[:2] - a[:2]))
        if walked >= 150.0:
            walked = 0.0
            c = track.to_ctr(b)
            d = np.hypot(reach_pos[:, 0] - c[0], reach_pos[:, 2] - c[2]) + np.abs(reach_pos[:, 1] - c[1]) * 2
            pts.append(tuple(reach_pos[int(np.argmin(d))]))
    names = [f'p{i}' for i in range(len(pts))]
    landmarks = {nm: [int(p[0]), int(p[1]), int(p[2]), 0] for nm, p in zip(names, pts)}
    p0, p1 = np.array(pts[0]), np.array(pts[1])
    landmarks['p0'][3] = int(round(math.atan2(p1[0] - p0[0], p1[2] - p0[2]) / (2 * math.pi) * 4096)) % 4096
    out = track.painter_cuts(tris, ramps, g, start, area, near=tri_near, polygons=polygons)
    print(f'{len(out)} quadblocks')
    track.kill_plane(out, y=kill_y)
    bases, vrms = track.base_levels(disc)
    cells = track.drivable_cells(g, start)
    window = track.minimap_window(cells)
    name = area
    nodes, spawns, route_info, nav = track.race_setup(out, g, landmarks, names + ['p0'])
    free_nodes, free_cp = track.free_setup(out, g)
    for qi, q in enumerate(out):
        q.checkpoint = free_cp.get(qi, 0xFF)
    info = track.write_modes(outdir, f'{name}_free', out, free_nodes, spawns, nav, route_info, g, bases, vrms,
                             (window, track.minimap_image(cells, window, route=route_info['path'], cell=NAV_CELL)), build_name='bayview',
                             clear_colors=NIGHT, keep_sky=False)
    print(info)
    with open(os.path.join(outdir, f'{name}_free_route.json'), 'w') as f:
        json.dump(route_info, f)
    imgs, masks = [], []
    for k in range(1, max(layers) + 1):
        a = layers.get(k, np.zeros((track.LAYER_SIZE, track.LAYER_SIZE, 4), np.uint8))
        buf = io.BytesIO()
        Image.fromarray(np.maximum(a[..., :3], 5)).save(buf, format='PNG')
        imgs.append(buf.getvalue())
        masks.append(a[..., 3])
    size = track.build_atlas(imgs, os.path.join(outdir, f'{name}_atlas.jpg'))
    mask = Image.new('L', size, 255)
    for i, m in enumerate(masks):
        cell = i + 1
        mask.paste(Image.fromarray(np.where(m >= 128, 255, 0).astype(np.uint8)),
                   ((cell % track.ATLAS_COLS) * track.LAYER_SIZE, (cell // track.ATLAS_COLS) * track.LAYER_SIZE))
    mask.save(os.path.join(outdir, f'{name}_mask.png'), optimize=True)
    meta = dict(map=area, scale=SCALE, center=track.CENTER,
                atlas=dict(image=f'{name}_atlas.jpg', mask=f'{name}_mask.png', vertexColors=True, width=size[0], height=size[1]),
                spawn=spawns[0], info=info, landmarks=landmarks, tracks={}, modes=[suffix for suffix, _ in track.MODES])
    with open(os.path.join(outdir, f'{name}.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    listing = os.path.join(outdir, 'maps.json')
    built = json.load(open(listing)) if os.path.exists(listing) else {}
    built[name] = cfg['title']
    with open(listing, 'w') as f:
        json.dump(dict(sorted(built.items())), f, indent=1)
    print(f'built in {time.time() - t_start:.0f} s')


if __name__ == '__main__':
    if sys.argv[1:] == ['--areas']:
        print(' '.join(a for a, cfg in AREAS.items() if not cfg.get('experiment')))
    else:
        main(*sys.argv[1:5])

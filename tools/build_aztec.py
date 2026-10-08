"""Builds Counter-Strike 1.6's de_aztec as a CTR level, from the game's own map file.

    python3 -I tools/build_aztec.py CSTRIKE_DIR DISC.bin OUTDIR

CSTRIKE_DIR is a Counter-Strike install's cstrike folder (maps/de_aztec.bsp, and the WADs a map
needs when it doesn't carry its textures). Free drive only for now: aztec_free.lev (and its 2P,
4P and Time Trial versions), their VRMs, aztec.json and aztec_atlas.jpg; a race loop comes later.
The map goes through tools/goldsrc.py (its faces, textures and baked light, edited as below) and
then through the same pipeline as Dust 2 (tools/build_dust2.py).
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
import build_dust2 as d2  # noqa: E402
import goldsrc  # noqa: E402

MAP = 'de_aztec'
DENSITY = 0.45          # atlas texels per map unit (CS textures are about 1 texel per unit): the
                        # renderer has 14 atlas layers of 1024 x 1024
SCALE = 4.0             # CTR units per map unit, as Dust 2

# Map edits.
# Brush entities by class: 'solid' collides, 'decor' is only drawn, 'water' is a floor (see
# below). Others (triggers, buy zones, bomb targets) aren't drawn.
ENTITY_KINDS = {'worldspawn': 'solid', 'func_wall': 'solid', 'func_breakable': 'solid',
                'func_illusionary': 'decor', 'func_water': 'water'}
REMOVE_MODELS = set()   # brush models left out ('*N' in the entities)
# Faces retextured: the tops of the walls (z 192), which no one sees in CS, are a 16-pixel barrel
# texture that reads as flat yellow from a kart camera on higher ground.
TEXTURE_SWAP = {'barrel2b': '-1AzWll'}
# Water: CS swims in it; CTR drives on shallow water (Papu's Pyramid), so the surface of the
# river and the pool is a floor with the water terrain (70% speed, the water sound), drawn with
# the water texture brightened (GoldSrc draws it fullbright and see-through over the riverbed).
TERRAIN_WATER = 4
WATER_BRIGHTNESS = 4.0
DENSITY_WATER = 0.15    # the water texture is a small, uniform tile
WATER_Z = -528          # the river's surface: faces wholly under it are hidden by it, left out
DENSITY_TOPS = 0.25     # the wall tops, barely seen
# Alpha-tested textures ('{': vines, ladder rungs) aren't drawn yet (the atlas has no alpha).

# Places on the map (map x, y, z near the floor, compass heading: 0 = north, 90 = east)
LANDMARKS_H = {
    't_spawn': (2280, 116, -240, 270),
    'ct_spawn': (-2993, 147, -289, 90),
}
FREE_ROUTE = ['t_spawn', 'ct_spawn', 't_spawn']   # free drive borrows its start, pickups and AI lines
SKY = [(110, 125, 135, 1), (165, 170, 160, 1), (130, 140, 150, 1)]   # overcast: Aztec is rainy


def wads_for(bsp_data, cstrike):
    """The WADs the map names (worldspawn's 'wad'), from cstrike/ or valve/ next to it."""
    ents = goldsrc.parse_entities(bsp_data[bsp_data.find(b'{'):].decode('latin1', 'replace'))
    names = [os.path.basename(w.replace('\\', '/')) for w in ents[0].get('wad', '').split(';') if w]
    out = []
    for n in names:
        for d in (cstrike, os.path.join(os.path.dirname(cstrike.rstrip('/')), 'valve')):
            p = os.path.join(d, n)
            if os.path.exists(p):
                out.append(goldsrc.Wad(open(p, 'rb').read()))
                break
    return out


def select_faces(bsp):
    """[(face, kind)] for the faces drawn, kind 'solid' | 'decor' | 'water'."""
    owners = bsp.model_entities()
    sel = []
    skipped = {}
    # A liquid's surface is drawn from both sides, so a water brush (a thin box) has an up-facing
    # face at its bottom too, seen from inside: only each one's top surface is the water floor.
    tops = {}
    for mi, m in enumerate(bsp.models):
        for fi in range(m['firstface'], m['firstface'] + m['numfaces']):
            if bsp.face_texture(fi)[0].startswith('!') and bsp.face_normal(fi)[2] > 0.7:
                tops[mi] = max(tops.get(mi, -1e9), float(bsp.face_points(fi)[:, 2].max()))
    for mi, m in enumerate(bsp.models):
        e = owners.get(mi)
        kind = None if e is None else ENTITY_KINDS.get(e.get('classname'))
        if kind is None or mi in REMOVE_MODELS:
            continue
        if e.get('rendermode', '0') != '0' and e.get('renderamt', '255') == '0':
            continue   # drawn invisible
        for fi in range(m['firstface'], m['firstface'] + m['numfaces']):
            name = bsp.face_texture(fi)[0]
            low = name.lower()
            if low in goldsrc.TOOL_TEXTURES:
                continue
            if name.startswith('{'):
                skipped[name] = skipped.get(name, 0) + 1
                continue
            if name.startswith('!') or kind == 'water':
                if bsp.face_normal(fi)[2] > 0.7 and bsp.face_points(fi)[:, 2].min() > tops.get(mi, 1e9) - 1:
                    sel.append((fi, 'water'))
                continue
            if bsp.face_points(fi)[:, 2].max() <= WATER_Z + 1:
                skipped['under water'] = skipped.get('under water', 0) + 1
                continue
            sel.append((fi, kind))
    print(f'{len(sel)} faces drawn; left out: {skipped}')
    return sel


def load_map(cstrike):
    path = os.path.join(cstrike, 'maps', MAP + '.bsp')
    data = open(path, 'rb').read()
    bsp = goldsrc.Bsp(data, wads_for(data, cstrike))
    missing = sorted({n for n, _, rgba in bsp.textures if rgba is None and n.lower() not in goldsrc.TOOL_TEXTURES})
    if missing:
        print('warning: textures not found:', missing)
    by_name = {n.lower(): i for i, (n, _, _) in enumerate(bsp.textures)}
    for old, new in TEXTURE_SWAP.items():
        if old.lower() in by_name and new.lower() in by_name:
            n, size, _ = bsp.textures[by_name[old.lower()]]
            bsp.textures[by_name[old.lower()]] = (n, size, bsp.textures[by_name[new.lower()]][2])
    sel = select_faces(bsp)
    kind_of = dict(sel)
    swapped = {old.lower() for old in TEXTURE_SWAP}

    def density_of(fi):
        if kind_of[fi] == 'water':
            return DENSITY_WATER
        if bsp.face_texture(fi)[0].lower() in swapped:
            return DENSITY_TOPS
        return None

    t0 = time.time()
    charts, layers, light, _ = goldsrc.bake(bsp, [fi for fi, _ in sel], density=DENSITY, density_of=density_of,
                                            fullbright=WATER_BRIGHTNESS)
    print(f'baked {len(charts)} faces into {len(layers)} atlas layers ({time.time() - t0:.0f} s)')
    if max(layers) > 14:
        raise SystemExit(f'{max(layers)} atlas layers: the renderer has 14 (lower DENSITY)')
    # Images as the GLB pipeline has them: encoded, one per layer from 1. No texel quite black:
    # build_atlas spreads colour into black gaps between islands.
    imgs = []
    for k in range(1, max(layers) + 1):
        a = np.maximum(layers.get(k, np.zeros((d2.LAYER_SIZE, d2.LAYER_SIZE, 3), np.uint8)), 5)
        buf = io.BytesIO()
        Image.fromarray(a).save(buf, format='PNG')
        imgs.append(buf.getvalue())
    # Kart lighting (d2.floor_shade): light maps in the units of the Dust 2 model's sunlit sand
    sun = float(goldsrc.light_multiplier(np.array(192.0)))
    maps = {k: v * (d2.SUNLIT / sun) for k, v in light.items()}
    return bsp, sel, charts, imgs, maps


def make_tris(bsp, sel, charts, near=None):
    """Triangles, as d2.load makes them. Floors near(polygon in CTR space) says the kart can get
    close to (all, by default) are cut into the floor grid's cells first."""
    tris = []
    for fi, kind in sel:
        if fi not in charts:
            continue
        chart = charts[fi]
        pts = bsp.face_points(fi)
        n = bsp.face_normal(fi)
        if kind != 'water' and pts[:, 2].min() < WATER_Z:
            # the river's surface hides what's under it, and painted after it (a wall's
            # near corner sorts in front of a wide stretch of water) it shows through
            pts = _clip(pts, 2, WATER_Z, False)
            if pts is None:
                continue
        floor = n[2] > 0.7
        pieces = floor_cells(pts) if floor and (near is None or near(d2.to_ctr(pts))) else [pts]
        for poly in pieces:
            uv = chart.uv(bsp, fi, poly)
            for i in range(1, len(poly) - 1):
                idx = [0, i, i + 1]
                p = poly[idx]
                geo = np.cross(p[1] - p[0], p[2] - p[0])
                if np.linalg.norm(geo) < 1e-3:
                    continue
                if np.dot(geo, n) < 0:
                    idx = [0, i + 1, i]
                    p = poly[idx]
                t = d2.Tri(d2.to_ctr(p), uv[idx].copy(), chart.layer, d2.dir_to_ctr(n), p.copy(), n.copy())
                t.solid = kind != 'decor'
                if kind == 'water':
                    t.terrain = TERRAIN_WATER
                tris.append(t)
    print(f'{len(tris)} triangles')
    return tris


def _clip(poly, axis, c, keep_below):
    """The part of a convex polygon (n, 3) on one side of the plane p[axis] = c."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da, db = a[axis] - c, b[axis] - c
        ina = da <= 1e-6 if keep_below else da >= -1e-6
        inb = db <= 1e-6 if keep_below else db >= -1e-6
        if ina:
            out.append(a)
        if ina != inb and abs(da - db) > 1e-12:
            f = da / (da - db)
            if 1e-9 < f < 1 - 1e-9:
                out.append(a + (b - a) * f)
    return np.array(out) if len(out) >= 3 else None


def floor_cells(pts):
    """A floor polygon (map units) cut along the floor grid (d2.FLOOR_CELL in CTR space, so the
    same lines as d2.grid_cut_floors): whole cells come out as single quads, so the pipeline's
    pairing turns them back into one quadblock each, where cutting triangles one by one splits
    every cell their diagonal crosses."""
    step = d2.FLOOR_CELL / d2.SCALE
    polys = [np.asarray(pts, dtype=np.float64)]
    # CTR x = (x - cx) * scale, CTR z = -(y - cy) * scale: grid lines at x = cx + k * step and
    # y = cy - k * step
    for axis, base in ((0, d2.CENTER[0]), (1, d2.CENTER[1])):
        done = []
        for poly in polys:
            lo = math.floor((poly[:, axis].min() - base) / step)
            hi = math.ceil((poly[:, axis].max() - base) / step)
            rest = poly
            for k in range(lo + 1, hi):
                c = base + k * step
                below = _clip(rest, axis, c, True)
                above = _clip(rest, axis, c, False)
                if below is not None:
                    done.append(below)
                rest = above
                if rest is None:
                    break
            if rest is not None:
                done.append(rest)
        polys = done
    return polys


def spawn_points(bsp):
    pts = {}
    for cls in ('info_player_deathmatch', 'info_player_start'):
        pts[cls] = np.array([[float(v) for v in e['origin'].split()] for e in bsp.entities if e.get('classname') == cls])
    return pts


def landmark_positions(tris):
    out = {}
    for name, (hx, hy, hz, deg) in LANDMARKS_H.items():
        x, top, z = d2.to_ctr([hx, hy, hz + 32.0])
        y = d2.floor_height(tris, x, z, top)
        out[name] = [int(x), None if y is None else int(y), int(z), d2.heading(deg)]
    return out


# Floors the kart can get near are cut into cells of FLOOR_CELL CTR units (big floor quads under
# the camera showed as holes in Dust 2, at 256); others (roofs, ledges no one reaches) stay whole.
FLOOR_CELL = 512.0
WALL_EDGE = 1200.0      # longest wall quadblock edge, CTR units (Dust 2: 800): the vertex budget
NEAR_XZ = 1024.0        # CTR units from a reachable drivable cell (and within NEAR_Y of its
NEAR_Y = 640.0          # height)


def near_drivable(g, start):
    """near(points (n, 3), CTR space): is a polygon within reach of a grid cell the kart can
    drive to from `start`?"""
    from visibility import reachable
    cell = NEAR_XZ
    buckets = {}
    for nid in reachable(g, start):
        x, y, z = g.pos[nid]
        buckets.setdefault((int(x // cell), int(z // cell)), []).append((x, y, z))

    def near(p):
        lo, hi = p.min(axis=0), p.max(axis=0)
        for cx in range(int((lo[0] - cell) // cell), int((hi[0] + cell) // cell) + 1):
            for cz in range(int((lo[2] - cell) // cell), int((hi[2] + cell) // cell) + 1):
                for (x, y, z) in buckets.get((cx, cz), ()):
                    dx = max(lo[0] - x, 0.0, x - hi[0])
                    dz = max(lo[2] - z, 0.0, z - hi[2])
                    if dx * dx + dz * dz <= cell * cell and lo[1] - NEAR_Y <= y <= hi[1] + NEAR_Y:
                        return True
        return False
    return near


def main(cstrike, disc, outdir):
    from navgrid import NavGrid
    from visibility import exposed_backfaces
    os.makedirs(outdir, exist_ok=True)
    d2.SCALE = SCALE
    # the river's surface at CTR y 0: karts on water terrain are drawn only above y 0 (half
    # sunk in it), so retail levels have their water there
    d2.FLOOR_Z = WATER_Z
    # the map's middle goes to CTR's origin (map units)
    bsp_probe = goldsrc.Bsp(open(os.path.join(cstrike, 'maps', MAP + '.bsp'), 'rb').read())
    m0 = bsp_probe.models[0]
    pts = np.concatenate([bsp_probe.face_points(fi) for fi in range(m0['firstface'], m0['firstface'] + m0['numfaces'])
                          if bsp_probe.face_texture(fi)[0].lower() not in goldsrc.TOOL_TEXTURES])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    d2.CENTER = (round(float(lo[0] + hi[0]) / 2), round(float(lo[1] + hi[1]) / 2))
    kill_y = int((lo[2] - WATER_Z) * SCALE) - 600
    d2.FLOOR_CELL = FLOOR_CELL
    d2.FLOOR_MAX_EDGE = FLOOR_CELL * 1.6
    d2.MAX_EDGE = WALL_EDGE
    bsp, sel, charts, imgs, d2.light_maps = load_map(cstrike)

    # the drivable grid from whole floors, then the floor grid only near what's reachable
    tris = make_tris(bsp, sel, charts, near=lambda p: False)
    ramps = []
    d2.add_stair_ramps(tris, ramps)
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in d2.emit_level(tris, ramps)])
    landmarks = landmark_positions(tris)
    s = landmarks[FREE_ROUTE[0]]
    near = near_drivable(g, g.nearest(s[0], s[1] or 0, s[2]))
    tris = make_tris(bsp, sel, charts, near)
    tri_near = lambda t: near(t.p)   # noqa: E731 (d2's floor grid: leave the far floors whole)
    ramps = []
    d2.add_stair_ramps(tris, ramps)
    out = d2.emit_level(tris, ramps, near=tri_near)
    print(f'{len(out)} quadblocks, {d2.vertex_count(out)} vertices')
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in out])
    start = g.nearest(s[0], s[1] or 0, s[2])
    t0 = time.time()
    exposed = exposed_backfaces([t.p for t in tris], [t.n for t in tris], g, start)
    twins = d2.reversed_twins(tris, set(exposed))
    print(f'{len(twins)} triangles seen from behind get a reversed twin ({time.time() - t0:.0f} s)')
    if twins:
        out = d2.emit_level(tris + twins, ramps, near=tri_near)
    out = d2.painter_cuts(tris + twins, ramps, out, g, start, near=tri_near)
    print(f'{len(out)} quadblocks')
    d2.kill_plane(out, y=kill_y)
    bases, vrms = d2.base_levels(disc)
    window = d2.minimap_window(out)

    print('aztec_free:')
    nodes, spawns, route, nav = d2.race_setup(out, g, landmarks, FREE_ROUTE)
    free_nodes, free_cp = d2.free_setup(out, g)
    for qi, q in enumerate(out):
        q.checkpoint = free_cp.get(qi, 0xFF)
    info = d2.write_modes(outdir, 'aztec_free', out, free_nodes, spawns, nav, route, g, bases, vrms,
                          (window, d2.minimap_image(out, window)), build_name=MAP, clear_colors=SKY)
    print(info)
    with open(os.path.join(outdir, 'aztec_free_route.json'), 'w') as f:
        json.dump(route, f)
    size = d2.build_atlas(imgs, os.path.join(outdir, 'aztec_atlas.jpg'))
    meta = dict(map=MAP, scale=SCALE, center=d2.CENTER, atlas=dict(image='aztec_atlas.jpg', width=size[0], height=size[1]),
                spawn=spawns[0], info=info, landmarks=landmarks, tracks={}, modes=[suffix for suffix, _ in d2.MODES])
    with open(os.path.join(outdir, 'aztec.json'), 'w') as f:
        json.dump(meta, f, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])

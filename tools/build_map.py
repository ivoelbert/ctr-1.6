"""Builds a Counter-Strike 1.6 map as a CTR level, from the game's own map file.

    python3 -I tools/build_map.py MAP CSTRIKE_DIR DISC.bin OUTDIR        (MAP: de_dust2, de_aztec)

CSTRIKE_DIR is a Counter-Strike install's cstrike folder (maps/MAP.bsp, and the WADs a map needs
when it doesn't carry its textures); tools/maps/MAP.py says what to change for driving (see
tools/maps/__init__.py). The map goes through tools/goldsrc.py (its faces, textures and baked
light) and then the track pipeline, tools/track.py. Each map is a free drive for now: NAME_free.lev
and its 2P, 4P and Time Trial versions, their VRMs, NAME.json and NAME_atlas.jpg, where NAME is
the map's name without its prefix (dust2); OUTDIR/maps.json lists the maps built there.
Experiments: DENSITY=texels per unit (the atlas has 63 layers), VERTICES=the painter's budget
(past 65,536: vertex banks), NAME=another name for the files.

The level holds data from your CTR disc (it is grafted onto Dingo Canyon's) and from
Counter-Strike's map: keep it to yourself.
"""
import collections
import importlib
import io
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import goldsrc  # noqa: E402
import track  # noqa: E402

SCALE = 4.0             # CTR units per map unit
# Brush entities by class: 'solid' collides, 'decor' is only drawn, 'water' is a floor (see
# below). Others (triggers, buy zones, bomb targets) aren't drawn.
ENTITY_KINDS = {'worldspawn': 'solid', 'func_wall': 'solid', 'func_breakable': 'solid',
                'func_illusionary': 'decor', 'func_water': 'water'}
# Water: Counter-Strike swims in it; CTR drives on shallow water (Papu's Pyramid), so a water
# surface is a floor with the water terrain (70% speed, the water sound), drawn with the water
# texture brightened (GoldSrc draws it fullbright and see-through over the bottom).
TERRAIN_WATER = 4
WATER_BRIGHTNESS = 4.0
DENSITY_WATER = 0.15    # water textures are small, uniform tiles
# Floors the kart can get near are cut along the floor grid (a map's FLOOR_CELL), others (roofs,
# ledges no one reaches) stay whole: near is within NEAR_XZ CTR units of a drivable cell the
# kart can reach, and within NEAR_Y of its height.
NEAR_XZ = 1024.0
NEAR_Y = 640.0


def wads_for(bsp_data, cstrike):
    """The WADs the map names (worldspawn's 'wad'), from cstrike/ or valve/ next to it."""
    worldspawn = goldsrc.Bsp(bsp_data).entities[0]
    names = [os.path.basename(w.replace('\\', '/')) for w in worldspawn.get('wad', '').split(';') if w]
    out = []
    for n in names:
        for d in (cstrike, os.path.join(os.path.dirname(cstrike.rstrip('/')), 'valve')):
            p = os.path.join(d, n)
            if os.path.exists(p):
                out.append(goldsrc.Wad(open(p, 'rb').read()))
                break
    return out


def select_faces(bsp, cfg):
    """[(face, kind)] for the faces drawn, kind 'solid' | 'decor' | 'water'."""
    kinds = dict(ENTITY_KINDS, **getattr(cfg, 'ENTITY_KINDS', {}))
    remove = getattr(cfg, 'REMOVE_MODELS', set())
    water_z = getattr(cfg, 'WATER_Z', None)
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
        kind = None if e is None else kinds.get(e.get('classname'))
        if kind is None or mi in remove:
            continue
        if e.get('rendermode', '0') != '0' and e.get('renderamt', '0') == '0':
            continue   # drawn invisible (renderamt is 0 when the map doesn't say: Aztec's black boxes)
        for fi in range(m['firstface'], m['firstface'] + m['numfaces']):
            name = bsp.face_texture(fi)[0]
            if name.lower() in goldsrc.TOOL_TEXTURES:
                continue
            if name.startswith('{'):
                # alpha-tested (vines, ladder rungs): the atlas has no alpha yet
                skipped[name] = skipped.get(name, 0) + 1
                continue
            if name.startswith('!') or kind == 'water':
                if bsp.face_normal(fi)[2] > 0.7 and bsp.face_points(fi)[:, 2].min() > tops.get(mi, 1e9) - 1:
                    sel.append((fi, 'water'))
                continue
            if water_z is not None and bsp.face_points(fi)[:, 2].max() <= water_z + 1:
                skipped['under water'] = skipped.get('under water', 0) + 1
                continue
            sel.append((fi, kind))
    print(f'{len(sel)} faces drawn; left out: {skipped}')
    return sel


def merge_faces(bsp, sel):
    """select_faces' faces with the pieces the map compiler split surfaces into joined back
    (goldsrc.merge_coplanar), kind by kind: fewer, bigger polygons, fewer vertices."""
    out = []
    for kind in dict.fromkeys(k for _, k in sel):
        out += [(fi, kind) for fi in goldsrc.merge_coplanar(bsp, [fi for fi, k in sel if k == kind])]
    print(f'{len(out)} faces once merged ({len(sel)} in the file)')
    return out


def load_map(cstrike, map_name, cfg):
    """The map with its edits, baked into atlas layers: (bsp, sel, charts, layer images (PNG),
    light maps for the karts' shade)."""
    data = open(os.path.join(cstrike, 'maps', map_name + '.bsp'), 'rb').read()
    bsp = goldsrc.Bsp(data, wads_for(data, cstrike))
    missing = sorted({n for n, _, rgba in bsp.textures if rgba is None and n.lower() not in goldsrc.TOOL_TEXTURES})
    if missing:
        print('warning: textures not found:', missing)
    by_name = {n.lower(): i for i, (n, _, _) in enumerate(bsp.textures)}
    for old, new in getattr(cfg, 'TEXTURE_SWAP', {}).items():
        if old.lower() in by_name and new.lower() in by_name:
            n, size, _ = bsp.textures[by_name[old.lower()]]
            bsp.textures[by_name[old.lower()]] = (n, size, bsp.textures[by_name[new.lower()]][2])
    sel = merge_faces(bsp, select_faces(bsp, cfg))
    kind_of = dict(sel)
    density_by_texture = {k.lower(): v for k, v in getattr(cfg, 'TEXTURE_DENSITY', {}).items()}

    def density_of(fi):
        if kind_of[fi] == 'water':
            return DENSITY_WATER
        return density_by_texture.get(bsp.face_texture(fi)[0].lower())

    t0 = time.time()
    charts, layers, light, _ = goldsrc.bake(bsp, [fi for fi, _ in sel], density=float(os.environ.get('DENSITY', getattr(cfg, 'DENSITY', 0.45))),
                                            density_of=density_of, fullbright=WATER_BRIGHTNESS)
    print(f'baked {len(charts)} faces into {len(layers)} atlas layers ({time.time() - t0:.0f} s)')
    if max(layers) > 63:
        raise SystemExit(f'{max(layers)} atlas layers: the renderer has 63 (lower the map\'s DENSITY)')
    # one encoded image per layer from 1; no texel quite black: build_atlas spreads colour into
    # the black gaps between charts
    imgs = []
    for k in range(1, max(layers) + 1):
        a = np.maximum(layers.get(k, np.zeros((track.LAYER_SIZE, track.LAYER_SIZE, 3), np.uint8)), 5)
        buf = io.BytesIO()
        Image.fromarray(a).save(buf, format='PNG')
        imgs.append(buf.getvalue())
    # the karts' shade (track.floor_shade) counts light in units of sunlit sand
    sun = float(goldsrc.light_multiplier(np.array(192.0)))
    maps = {k: v * (track.SUNLIT / sun) for k, v in light.items()}
    return bsp, sel, charts, imgs, maps


def make_tris(bsp, sel, charts, cfg, near=None):
    """The track's triangles. Floors near(polygon in CTR space) says the kart can get close to
    (all, by default) are cut into the floor grid's cells first."""
    water_z = getattr(cfg, 'WATER_Z', None)
    split_face = getattr(cfg, 'split_face', None)
    tris = []
    for fi, kind in sel:
        if fi not in charts:
            continue
        chart = charts[fi]
        pts = bsp.face_points(fi)
        n = bsp.face_normal(fi)
        if water_z is not None and kind != 'water' and pts[:, 2].min() < water_z:
            # the water's surface hides what's under it, and painted after it (a wall's near
            # corner sorts in front of a wide stretch of water) it shows through
            pts = goldsrc.clip_polygon(pts, 2, water_z, False)
            if pts is None:
                continue
        floor = n[2] > 0.7
        pieces = floor_cells(pts) if floor and (near is None or near(track.to_ctr(pts))) else [pts]
        solid = [kind != 'decor'] * len(pieces)
        if kind != 'decor' and split_face is not None:
            pieces, solid = split_face(pts, n) or (pieces, solid)
        for poly, poly_solid in zip(pieces, solid):
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
                t = track.Tri(track.to_ctr(p), uv[idx].copy(), chart.layer, track.dir_to_ctr(n), p.copy(), n.copy())
                t.solid = poly_solid
                if kind == 'water':
                    t.terrain = TERRAIN_WATER
                tris.append(t)
    print(f'{len(tris)} triangles')
    return tris


def floor_cells(pts):
    """A floor polygon (map units) cut along the floor grid (track.FLOOR_CELL in CTR space, so the
    same lines as track.grid_cut_floors): whole cells come out as single quads, so the pipeline's
    pairing turns them back into one quadblock each, where cutting triangles one by one splits
    every cell their diagonal crosses."""
    step = track.FLOOR_CELL / track.SCALE
    polys = [np.asarray(pts, dtype=np.float64)]
    # CTR x = (x - cx) * scale, CTR z = -(y - cy) * scale: grid lines at x = cx + k * step and
    # y = cy - k * step
    for axis, base in ((0, track.CENTER[0]), (1, track.CENTER[1])):
        done = []
        for poly in polys:
            lo = math.floor((poly[:, axis].min() - base) / step)
            hi = math.ceil((poly[:, axis].max() - base) / step)
            rest = poly
            for k in range(lo + 1, hi):
                c = base + k * step
                below = goldsrc.clip_polygon(rest, axis, c, True)
                above = goldsrc.clip_polygon(rest, axis, c, False)
                if below is not None:
                    done.append(below)
                rest = above
                if rest is None:
                    break
            if rest is not None:
                done.append(rest)
        polys = done
    return polys


def spawn_landmarks(bsp):
    """t_spawn and ct_spawn: the middle of each team's spawn points, facing the way most of them
    face (x, y, z, compass heading)."""
    out = {}
    for name, cls in (('t_spawn', 'info_player_deathmatch'), ('ct_spawn', 'info_player_start')):
        spawns = [e for e in bsp.entities if e.get('classname') == cls]
        if not spawns:
            continue
        o = np.array([[float(v) for v in e['origin'].split()] for e in spawns]).mean(axis=0)
        # Counter-Strike's yaw: 0 is east, 90 north
        yaws = collections.Counter(round(float(e.get('angles', '0 0 0').split()[1])) for e in spawns)
        out[name] = (round(o[0]), round(o[1]), round(o[2]), (90 - yaws.most_common(1)[0][0]) % 360)
    return out


def landmark_positions(tris, landmarks):
    """{name: [CTR x, floor y (None when there's no floor), z, yaw]}."""
    out = {}
    for name, (hx, hy, hz, deg) in landmarks.items():
        x, top, z = track.to_ctr([hx, hy, hz + 32.0])
        y = track.floor_height(tris, x, z, top)
        out[name] = [int(x), None if y is None else int(y), int(z), track.heading(deg)]
    return out


def near_drivable(g, start):
    """near(points (n, 3), CTR space): is a polygon within reach of a grid cell the kart can
    drive to from `start`?"""
    cell = NEAR_XZ
    buckets = {}
    for nid in g.reachable(start):
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


def main(map_name, cstrike, disc, outdir):
    from navgrid import NavGrid
    t_start = time.time()
    cfg = importlib.import_module('maps.' + map_name)
    name = os.environ.get('NAME', map_name.split('_', 1)[-1])
    track.VERTEX_BUDGET = int(os.environ.get('VERTICES', track.VERTEX_BUDGET))
    os.makedirs(outdir, exist_ok=True)
    track.SCALE = SCALE
    # a map with water has its surface at CTR y 0: karts on water terrain are drawn only above
    # y 0 (half sunk in it), so retail levels have their water there
    water_z = getattr(cfg, 'WATER_Z', None)
    track.FLOOR_Z = 0.0 if water_z is None else water_z
    # the map's middle goes to CTR's origin (map units)
    bsp_probe = goldsrc.Bsp(open(os.path.join(cstrike, 'maps', map_name + '.bsp'), 'rb').read())
    m0 = bsp_probe.models[0]
    pts = np.concatenate([bsp_probe.face_points(fi) for fi in range(m0['firstface'], m0['firstface'] + m0['numfaces'])
                          if bsp_probe.face_texture(fi)[0].lower() not in goldsrc.TOOL_TEXTURES])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    track.CENTER = (round(float(lo[0] + hi[0]) / 2), round(float(lo[1] + hi[1]) / 2))
    kill_y = int((lo[2] - track.FLOOR_Z) * SCALE) - 600
    floor_cell = getattr(cfg, 'FLOOR_CELL', 512.0)
    track.FLOOR_CELL = floor_cell
    track.FLOOR_MAX_EDGE = floor_cell * 1.6
    track.MAX_EDGE = getattr(cfg, 'WALL_EDGE', 1200.0)
    bsp, sel, charts, imgs, track.light_maps = load_map(cstrike, map_name, cfg)
    landmarks_h = dict(spawn_landmarks(bsp), **getattr(cfg, 'LANDMARKS', {}))
    free_route = getattr(cfg, 'FREE_ROUTE', ['t_spawn', 'ct_spawn', 't_spawn'])
    extra_quads = getattr(cfg, 'extra_quads', lambda bsp, sel, charts, out: None)

    # the drivable grid from whole floors, then the floor grid only near what's reachable
    tris = make_tris(bsp, sel, charts, cfg, near=lambda p: False)
    ramps = []
    track.add_stair_ramps(tris, ramps)
    extra_quads(bsp, sel, charts, ramps)
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in track.emit_level(tris, ramps)])
    landmarks = landmark_positions(tris, landmarks_h)
    s = landmarks[free_route[0]]
    near = near_drivable(g, g.nearest(s[0], s[1] or 0, s[2]))
    tris = make_tris(bsp, sel, charts, cfg, near)
    tri_near = lambda t: near(t.p)   # noqa: E731 (the floor grid: leave the far floors whole)
    ramps = []
    track.add_stair_ramps(tris, ramps)
    extra_quads(bsp, sel, charts, ramps)
    polygons = track.level_polygons(tris, tri_near)
    out = track.emit_level(tris, ramps, near=tri_near, polygons=polygons)
    print(f'{len(out)} quadblocks, {track.vertex_count(out)} vertices')
    g = NavGrid([(q.flags, q.pos, q.triangle) for q in out])
    start = g.nearest(s[0], s[1] or 0, s[2])
    out = track.painter_cuts(tris, ramps, g, start, name, near=tri_near, polygons=polygons)
    print(f'{len(out)} quadblocks')
    track.kill_plane(out, y=kill_y)
    bases, vrms = track.base_levels(disc)
    cells = track.drivable_cells(g, start)
    window = track.minimap_window(cells)

    print(f'{name}_free:')
    nodes, spawns, route, nav = track.race_setup(out, g, landmarks, free_route)
    free_nodes, free_cp = track.free_setup(out, g)
    for qi, q in enumerate(out):
        q.checkpoint = free_cp.get(qi, 0xFF)
    info = track.write_modes(outdir, f'{name}_free', out, free_nodes, spawns, nav, route, g, bases, vrms,
                             (window, track.minimap_image(cells, window)), build_name=map_name,
                             clear_colors=getattr(cfg, 'SKY', [(170, 190, 220, 1), (230, 200, 160, 1), (200, 210, 230, 1)]))
    print(info)
    with open(os.path.join(outdir, f'{name}_free_route.json'), 'w') as f:
        json.dump(route, f)
    size = track.build_atlas(imgs, os.path.join(outdir, f'{name}_atlas.jpg'))
    meta = dict(map=map_name, scale=SCALE, center=track.CENTER, atlas=dict(image=f'{name}_atlas.jpg', width=size[0], height=size[1]),
                spawn=spawns[0], info=info, landmarks=landmarks, tracks={}, modes=[suffix for suffix, _ in track.MODES])
    with open(os.path.join(outdir, f'{name}.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    # the launcher's list of maps: every map built in outdir
    listing = os.path.join(outdir, 'maps.json')
    built = json.load(open(listing)) if os.path.exists(listing) else {}
    built[name] = getattr(cfg, 'TITLE', name)
    with open(listing, 'w') as f:
        json.dump(dict(sorted(built.items())), f, indent=1)
    print(f'built in {time.time() - t_start:.0f} s' + (' (FAST: the painter\'s cuts of the last full build)' if track.FAST else ''))


if __name__ == '__main__':
    main(*sys.argv[1:5])

"""Builds a stretch of Bayview bigger than one CTR level holds, as tiles the engine streams.

    python3 -I tools/build_world.py NFSU2.iso CTR_DISC.bin OUTDIR [WORLD]

A level's positions are 16-bit: about a kilometre across at 64 units a metre. A world is cut
into square tiles (TILE metres) in one coordinate system, each a mesh-only level file
(OUTDIR/WORLD_tiles/T_I_J.lev, in coordinates from its own centre); the engine keeps the 3 x 3
tiles round the kart put together as the level's mesh, centred on the middle one, and moves
everything when the kart crosses into the next (engine/platform/native_world.c). The world
starts as an area of tools/build_bayview.py (its start, respawns, minimap and the rest:
WORLD_free.lev and its modes), built in the world's coordinates with the world's atlas; its own
mesh gives way to the tiles. OUTDIR/WORLD_tiles/index.bin lists the tiles.

The level holds data from both discs: keep it to yourself.
"""
import json
import os
import pickle
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_bayview as bb  # noqa: E402
import levwriter  # noqa: E402
import track  # noqa: E402
from nfsu2.world import Bayview  # noqa: E402

TILE = 256.0            # metres: 16384 units, 3 x 3 of them within 16-bit positions
WORLDS = {
    # City Core's loop to start, and Coal Harbor 1.3 km south of it
    'bayworld': dict(title='Bayview (open)', start='citycore', bounds=(-1400.0, -1950.0, -200.0, 350.0)),
}
LEAF_QUADS = 24         # quadblocks a BSP leaf holds, at least
TILE_LEAVES = 512       # a window's BSP holds 16383 nodes: 9 tiles' (the kd-tree halves to a
                        # power of two leaves: 1023 nodes) and the top
KILL_Y = -1600          # CTR units under the floor: a kart that falls this far is put back


def tile_kill_plane(out, half, y):
    """Invisible kill-plane quadblocks across a tile (its own coordinates)."""
    n = np.array([0.0, 1.0, 0.0])
    step = 4096
    for x in range(-half, half, step):
        for z in range(-half, half, step):
            A, B = np.array([x, y, z], float), np.array([x + step, y, z], float)
            C, D = np.array([x, y, z + step], float), np.array([x + step, y, z + step], float)
            c = [A, B, C, D]
            if np.dot(np.cross(C - A, B - A), n) < 0:
                c = [A, C, B, D]
            grid = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0), (0, 0.5), (0.5, 0.5), (1, 0.5), (0.5, 1)]
            q = track.invisible_quad([track.bilinear(c, s, t) for s, t in grid], n)
            q.flags = track.FLAG_COLLISION_SURFACE | track.FLAG_KILL_PLANE
            out.append(q)


def main(iso, disc, outdir, name='bayworld'):
    t_start = time.time()
    cfg = WORLDS[name]
    world = Bayview(iso)
    world.low_detail = False
    x0, y0, x1, y1 = cfg['bounds']
    groups = world.triangles((x0, y0, x1, y1), bb.SKIP_SOLIDS)
    groups = {h: g for h, g in groups.items() if h in world.textures and not world.textures[h].name.startswith(bb.SKIP_TEXTURES)}
    print(f'{sum(len(g[0]) for g in groups.values())} triangles in the world, {len(groups)} textures')
    allp = np.concatenate([g[0].reshape(-1, 3) for g in groups.values()])
    floor_z = float(np.percentile(allp[:, 2], 1))
    # the world's origin: the middle of its start area, where tile (0, 0) is centred
    wps = np.array(bb.AREAS[cfg['start']]['waypoints'], dtype=float)
    center = ((wps[:, 0].min() + wps[:, 0].max()) / 2, (wps[:, 1].min() + wps[:, 1].max()) / 2)
    cutouts = {h for h in groups if bb.is_cutout(world.textures[h].rgba) and not world.textures[h].name.startswith(bb.GROUND_TEXTURES)}
    rects, layers = bb.pack_textures(world.textures, list(groups), cutouts)
    print(f'{len(rects)} textures in {len(layers)} atlas layers')

    cache = os.path.join(outdir, '.tools', f'{name}_tris.pickle')
    if os.environ.get('TILES_ONLY') == '1' and os.path.exists(cache):
        # the start level as it is, and the triangles as the last build made them
        tris = pickle.load(open(cache, 'rb'))
        track.SCALE, track.CENTER, track.FLOOR_Z = bb.SCALE, center, floor_z
        track.FLOOR_CELL, track.FLOOR_MAX_EDGE, track.MAX_EDGE = bb.FLOOR_CELL, bb.FLOOR_CELL * 1.6, 1200.0
        track.light_maps = None
    else:
        # the starting level, in the world's coordinates, with the world's atlas
        bb.main(iso, disc, outdir, cfg['start'], world=world, name=name, center=center, floor_z=floor_z,
                atlas=(rects, layers), quick=True)
        # the tiles (track's settings as the start level left them: the world's centre and floor)
        track.CENTER, track.FLOOR_Z = center, floor_z
        t0 = time.time()
        tris = bb.make_tris(world, groups, rects, cutouts, lambda p: True)
        print(f'  ({time.time() - t0:.0f} s)')
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, 'wb') as f:
            pickle.dump(tris, f, protocol=pickle.HIGHEST_PROTOCOL)
    # no stair ramps: tools/stairs.py's sizes are Counter-Strike's units, and NFSU2's walls
    # lower than a kerb are driven over anyway (build_bayview.LOW_WALL)
    ramps = []
    size = int(TILE * bb.SCALE)
    half = size // 2
    cells = {}
    for t in tris:
        c = t.p.mean(axis=0)
        cells.setdefault((int(np.floor((c[0] + half) / size)), int(np.floor((c[2] + half) / size))), ([], []))[0].append(t)
    for q in ramps:
        c = np.mean(q.pos, axis=0)
        key = (int(np.floor((c[0] + half) / size)), int(np.floor((c[2] + half) / size)))
        cells.setdefault(key, ([], []))[1].append(q)
    tile_dir = os.path.join(outdir, f'{name}_tiles')
    os.makedirs(tile_dir, exist_ok=True)
    index = []
    for (i, j), (ttris, tramps) in sorted(cells.items()):
        if not ttris:
            continue
        t0 = time.time()
        out = track.emit_level(ttris, tramps, near=lambda t: True)
        off = np.array([i * size, 0, j * size])
        for q in out:
            q.pos = [tuple(int(round(v)) for v in np.asarray(p) - off) for p in q.pos]
        tile_kill_plane(out, half, KILL_Y)
        span = np.abs(np.array([p for q in out for p in q.pos])).max(axis=0)
        assert span[0] < 0x7000 and span[2] < 0x7000, f'tile {i},{j} reaches {span}'
        data, _ = levwriter.write_level(levwriter.Level(quads=out, max_leaf_quads=max(LEAF_QUADS, -(-len(out) // TILE_LEAVES))))
        with open(os.path.join(tile_dir, f'T_{i}_{j}.lev'), 'wb') as f:
            f.write(data)
        index.append((i, j, len(data)))
        print(f'tile {i},{j}: {len(out)} quadblocks, {track.vertex_count(out)} vertices, {len(data) >> 10} KB ({time.time() - t0:.0f} s)')
    # index.bin: 'WRLD', tile size (units), count, then per tile (i, j) s16 and its file's bytes
    with open(os.path.join(tile_dir, 'index.bin'), 'wb') as f:
        f.write(struct.pack('<4sii', b'WRLD', size, len(index)))
        for i, j, n in index:
            f.write(struct.pack('<hhI', i, j, n))
    meta_path = os.path.join(outdir, f'{name}.json')
    meta = json.load(open(meta_path))
    meta['world'] = dict(tiles=f'{name}_tiles', tile=size, count=len(index))
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=1)
    listing = os.path.join(outdir, 'maps.json')
    built = json.load(open(listing))
    built[name] = cfg['title']
    with open(listing, 'w') as f:
        json.dump(dict(sorted(built.items())), f, indent=1)
    print(f'{len(index)} tiles; built in {time.time() - t_start:.0f} s')


if __name__ == '__main__':
    main(*sys.argv[1:5])

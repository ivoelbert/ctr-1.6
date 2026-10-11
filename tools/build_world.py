"""Builds Bayview bigger than one CTR level holds (all of it), as tiles the engine streams.

    python3 -I tools/build_world.py NFSU2.iso CTR_DISC.bin OUTDIR [WORLD]

A level's positions are 16-bit: about a kilometre across at 64 units a metre. A world is cut
into square tiles (TILE metres) in one coordinate system, each a mesh-only level file
(OUTDIR/WORLD_tiles/T_I_J.lev, in coordinates from its own centre); the engine keeps the 3 x 3
tiles round the kart put together as the level's mesh, centred on the middle one, and moves
everything when the kart crosses into the next (engine/platform/native_world.c). The world
starts as an area of tools/build_bayview.py (its start, respawns, minimap and the rest:
WORLD_free.lev and its modes), built in the world's coordinates with the world's atlas; its own
mesh gives way to the tiles. OUTDIR/WORLD_tiles/index.bin lists the tiles.

    AROUND='bayview_free 15303,958,8413,2505 ...' python3 -I tools/build_world.py ...   (a P line)

rebuilds just the tiles round there (AROUND_TILES out: 1, the 3 x 3; 0, the one) in a world
built whole before with the same textures, and patches its index and minimap: seconds, not the
whole city's minutes. TILES_ONLY=1 rebuilds every tile but not the start level.

The level holds data from both discs: keep it to yourself.
"""
import hashlib
import json
import os
import re
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
    # all of it: the city's sections reach x -3133 to 1830, y -2069 to 3450
    'bayview': dict(title='Bayview', start='citycore', bounds=(-3300.0, -2200.0, 2000.0, 3600.0)),
}
LEAF_QUADS = 24         # quadblocks a BSP leaf holds, at least
TILE_LEAVES = 512       # a window's BSP holds 16383 nodes: 9 tiles' (the kd-tree halves to a
                        # power of two leaves: 1023 nodes) and the top
KILL_Y = -1600          # CTR units under the floor: a kart that falls this far is put back
MAX_HEIGHT = 32000      # CTR units: 16-bit positions
MAP_FINE = 2.0          # metres a texel of a tile's map raster
MAP_TEXEL = 8.0         # metres a texel of the world's map (the minimap shows 80 of them across)


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


# a tile's job runs in a worker forked from the builder, which leaves the world here
_JOB = {}


def build_tile(ij):
    """Tile (i, j): its triangles (those with middles in it), as a level file in coordinates
    from its centre; (i, j, file bytes, quadblocks), or None when it's empty."""
    i, j = ij
    world, rects, cutouts, center, size, tile_dir = (_JOB[k] for k in ('world', 'rects', 'cutouts', 'center', 'size', 'tile_dir'))
    half = size // 2
    m = size / bb.SCALE
    x0 = center[0] + (i * size - half) / bb.SCALE
    y1 = center[1] - (j * size - half) / bb.SCALE
    groups = world.triangles((x0, y1 - m, x0 + m, y1), bb.SKIP_SOLIDS)
    groups = {h: g for h, g in groups.items() if h in rects}
    if not groups:
        return None
    raster = tile_map(world, groups, center, i, j, size)
    t0 = time.time()
    tris = bb.make_tris(world, groups, rects, cutouts, lambda p: True)
    if not tris:
        return None
    # no stair ramps: tools/stairs.py's sizes are Counter-Strike's units, and NFSU2's walls
    # lower than a kerb are driven over anyway (build_bayview.LOW_WALL)
    out = track.emit_level(tris, [], near=lambda t: True)
    off = np.array([i * size, 0, j * size])
    for q in out:
        q.pos = [tuple(int(round(v)) for v in np.asarray(p) - off) for p in q.pos]
    # heights are 16-bit too: 500 m over the city's floor (the hills' far side) is left out
    high = [q for q in out if max(abs(p[1]) for p in q.pos) > MAX_HEIGHT]
    if high:
        out = [q for q in out if max(abs(p[1]) for p in q.pos) <= MAX_HEIGHT]
        print(f'tile {i},{j}: {len(high)} quadblocks out of reach above or below', flush=True)
    if not out:
        return None
    tile_kill_plane(out, half, KILL_Y)
    span = np.abs(np.array([p for q in out for p in q.pos])).max(axis=0)
    assert span[0] < 0x7000 and span[2] < 0x7000, f'tile {i},{j} reaches {span}'
    data, _ = levwriter.write_level(levwriter.Level(quads=out, max_leaf_quads=max(LEAF_QUADS, -(-len(out) // TILE_LEAVES))))
    with open(os.path.join(tile_dir, f'T_{i}_{j}.lev'), 'wb') as f:
        f.write(data)
    print(f'tile {i},{j}: {len(out)} quadblocks, {track.vertex_count(out)} vertices, {len(data) >> 10} KB ({time.time() - t0:.0f} s)',
          flush=True)
    return i, j, len(data), len(out), raster


def tile_map(world, groups, center, i, j, size):
    """The tile's ground from above, MAP_FINE metres a texel: 2 where roads are, 1 for the
    pavements and the rest of the ground (uint8, rows along CTR z)."""
    from PIL import Image, ImageDraw
    n = int(round(size / bb.SCALE / MAP_FINE))
    img = Image.new('L', (n, n), 0)
    d = ImageDraw.Draw(img)
    x0, z0 = i * size - size // 2, j * size - size // 2
    k = 1.0 / (MAP_FINE * bb.SCALE)
    for value, kinds in ((1, bb.GROUND_TEXTURES), (2, ('RDP',))):
        for h, (P, _, _, _) in groups.items():
            if not world.textures[h].name.startswith(kinds):
                continue
            nz = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])[:, 2]
            for tri in P[np.abs(nz) > 1e-9]:
                pts = [(((x - center[0]) * bb.SCALE - x0) * k, (-(y - center[1]) * bb.SCALE - z0) * k) for x, y, _ in tri]
                d.polygon(pts, fill=value)
    return np.asarray(img, dtype=np.uint8)


def world_map(done, i0, j0, i1, j1, size, center):
    """The world's map: the tiles' rasters at MAP_TEXEL metres a texel, as the minimap's
    two-bit values (track.MAP_FLOOR for roads, track.MAP_EDGE for the rest of the ground)."""
    n = int(round(size / bb.SCALE / MAP_FINE))
    fine = np.zeros(((j1 - j0 + 1) * n, (i1 - i0 + 1) * n), np.uint8)
    for d in done:
        if d is not None:
            i, j = d[0], d[1]
            fine[(j - j0) * n:(j - j0 + 1) * n, (i - i0) * n:(i - i0 + 1) * n] = d[4]
    f = int(round(MAP_TEXEL / MAP_FINE))
    h, w = fine.shape[0] // f, fine.shape[1] // f
    blocks = fine[:h * f, :w * f].reshape(h, f, w, f)
    road = (blocks == 2).mean(axis=(1, 3))
    ground = (blocks >= 1).mean(axis=(1, 3))
    out = np.full((h, w), track.MAP_CLEAR, np.uint8)
    out[ground > 0.3] = track.MAP_EDGE
    out[road > 0.2] = track.MAP_FLOOR
    return out


def main(iso, disc, outdir, name='bayview'):
    t_start = time.time()
    cfg = WORLDS[name]
    # AROUND: a P line, or its x,y,z
    around = os.environ.get('AROUND')
    if around:
        found = re.search(r'(-?\d+),(-?\d+),(-?\d+)', around)
        if not found:
            sys.exit(f'build_world: AROUND={around!r} has no x,y,z')
        around = tuple(int(v) for v in found.groups())
    world = Bayview(iso)
    world.low_detail = False
    x0, y0, x1, y1 = cfg['bounds']
    groups = world.triangles((x0, y0, x1, y1), bb.SKIP_SOLIDS)
    groups = {h: g for h, g in groups.items() if h in world.textures and not world.textures[h].name.startswith(bb.SKIP_TEXTURES)}
    print(f'{sum(len(g[0]) for g in groups.values())} triangles in the world, {len(groups)} textures')
    allp = np.concatenate([g[0].reshape(-1, 3) for g in groups.values()])
    floor_z = float(np.percentile(allp[:, 2], 1))
    del allp
    # the world's origin: the middle of its start area, where tile (0, 0) is centred
    wps = np.array(bb.AREAS[cfg['start']]['waypoints'], dtype=float)
    center = ((wps[:, 0].min() + wps[:, 0].max()) / 2, (wps[:, 1].min() + wps[:, 1].max()) / 2)
    cutouts = {h for h in groups if bb.is_cutout(world.textures[h].rgba) and not world.textures[h].name.startswith(bb.GROUND_TEXTURES)}
    rects, layers = bb.pack_textures(world.textures, list(groups), cutouts)
    print(f'{len(rects)} textures in {len(layers)} atlas layers')
    del groups

    # the atlas the tiles' texture coordinates point into: a rebuild of some tiles needs the same
    atlas_id = hashlib.sha1(json.dumps(sorted((str(h), list(r)) for h, r in rects.items())).encode()).hexdigest()[:16]
    meta_path = os.path.join(outdir, f'{name}.json')
    if around:
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        if meta.get('world', {}).get('atlas') != atlas_id:
            sys.exit(f'build_world: {name} was built with other textures (or not at all): build all of it, without AROUND')
    elif os.environ.get('TILES_ONLY') != '1':
        # the starting level, in the world's coordinates, with the world's atlas
        bb.main(iso, disc, outdir, cfg['start'], world=world, name=name, center=center, floor_z=floor_z,
                atlas=(rects, layers), quick=True)
    # the tiles, in track's settings as the start level leaves them (the world's centre and floor)
    track.SCALE, track.CENTER, track.FLOOR_Z = bb.SCALE, center, floor_z
    track.FLOOR_CELL, track.FLOOR_MAX_EDGE, track.MAX_EDGE = bb.FLOOR_CELL, bb.FLOOR_CELL * 1.6, 1200.0
    track.light_maps = None
    size = int(TILE * bb.SCALE)
    half = size // 2
    tile_dir = os.path.join(outdir, f'{name}_tiles')
    os.makedirs(tile_dir, exist_ok=True)
    i0 = int(np.ceil(((x0 - center[0]) * bb.SCALE - half) / size))
    i1 = int(np.floor(((x1 - center[0]) * bb.SCALE + half) / size))
    j0 = int(np.ceil((-(y1 - center[1]) * bb.SCALE - half) / size))
    j1 = int(np.floor((-(y0 - center[1]) * bb.SCALE + half) / size))
    cells = [(i, j) for j in range(j0, j1 + 1) for i in range(i0, i1 + 1)]
    if around:
        # a P line's position (the world's coordinates): its tile and those AROUND_TILES round it
        x, _, z = around
        reach = int(os.environ.get('AROUND_TILES', 1))
        ci, cj = int(np.floor((x + half) / size)), int(np.floor((z + half) / size))
        cells = [(i, j) for i, j in cells if abs(i - ci) <= reach and abs(j - cj) <= reach]
        print(f'{len(cells)} tiles round {ci},{cj}', flush=True)
    else:
        print(f'{len(cells)} tiles to look at ({i1 - i0 + 1} x {j1 - j0 + 1})', flush=True)
    _JOB.update(world=world, rects=rects, cutouts=cutouts, center=center, size=size, tile_dir=tile_dir)
    workers = min(int(os.environ.get('WORKERS', 6)), len(cells))
    if workers > 1:
        import multiprocessing
        with multiprocessing.get_context('fork').Pool(workers) as pool:
            done = pool.map(build_tile, cells, chunksize=1)
    else:
        done = [build_tile(c) for c in cells]
    index_path, map_path = os.path.join(tile_dir, 'index.bin'), os.path.join(tile_dir, 'map.bin')
    # index.bin: 'WRLD', tile size (units), count, then per tile (i, j) s16 and its file's bytes
    sizes = {}
    if around:
        raw = open(index_path, 'rb').read()
        for k in range(struct.unpack_from('<i', raw, 8)[0]):
            i, j, n = struct.unpack_from('<hhI', raw, 12 + 8 * k)
            sizes[i, j] = n
        for c in cells:
            sizes.pop(c, None)
            path = os.path.join(tile_dir, f'T_{c[0]}_{c[1]}.lev')
            if os.path.exists(path) and not any(d is not None and d[:2] == c for d in done):
                os.remove(path)  # empty now
    sizes.update({(d[0], d[1]): d[2] for d in done if d is not None})
    index = sorted(sizes.items(), key=lambda e: (e[0][1], e[0][0]))
    with open(index_path, 'wb') as f:
        f.write(struct.pack('<4sii', b'WRLD', size, len(index)))
        for (i, j), n in index:
            f.write(struct.pack('<hhI', i, j, n))
    # map.bin: 'WMAP', units a texel, the corner texel (0, 0) starts at (x, z), width, height,
    # then a byte a texel (the minimap's two-bit values), rows along z
    if around:
        raw = open(map_path, 'rb').read()
        _, unit, mx, mz, w, h = struct.unpack_from('<4siiiii', raw, 0)
        grid = np.frombuffer(raw, np.uint8, w * h, 24).reshape(h, w).copy()
        for c in cells:
            block = world_map([d for d in done if d is not None and d[:2] == c], c[0], c[1], c[0], c[1], size, center)
            r0, c0 = (c[1] * size - half - mz) // unit, (c[0] * size - half - mx) // unit
            grid[r0:r0 + block.shape[0], c0:c0 + block.shape[1]] = block
    else:
        grid = world_map(done, i0, j0, i1, j1, size, center)
        unit, mx, mz = int(MAP_TEXEL * bb.SCALE), i0 * size - half, j0 * size - half
    with open(map_path, 'wb') as f:
        f.write(struct.pack('<4siiiii', b'WMAP', unit, mx, mz, grid.shape[1], grid.shape[0]))
        f.write(grid.tobytes())
    from PIL import Image
    Image.fromarray((grid * 80).astype(np.uint8)).save(os.path.join(outdir, '.tools', f'{name}_map.png'))
    print(f'map: {grid.shape[1]} x {grid.shape[0]} texels of {MAP_TEXEL:.0f} m')
    meta = json.load(open(meta_path))
    meta['world'] = dict(tiles=f'{name}_tiles', tile=size, count=len(index), atlas=atlas_id)
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=1)
    if not around:
        listing = os.path.join(outdir, 'maps.json')
        built = json.load(open(listing))
        built[name] = cfg['title']
        for area in bb.AREAS:  # the city holds them all: their own levels leave the list
            built.pop(area, None)
        with open(listing, 'w') as f:
            json.dump(dict(sorted(built.items())), f, indent=1)
    print(f'{len(cells)} tiles looked at ({sum(1 for d in done if d)} with something in them), {sum(d[3] for d in done if d)} quadblocks, '
          f'{sum(d[2] for d in done if d) >> 20} MB; {len(index)} in the world; built in {time.time() - t_start:.0f} s')

if __name__ == '__main__':
    main(*sys.argv[1:5])

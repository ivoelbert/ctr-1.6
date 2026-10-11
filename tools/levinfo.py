"""What a built level file holds, without the game: its mesh, terrain, instances and BSP; and
what's at a spot.

    python3 -I tools/levinfo.py LEV                  (summary, its instances)
    python3 -I tools/levinfo.py LEV x,y,z [radius]   (the quadblocks within radius of a spot,
                                                      CTR units, the level's own coordinates)

A world tile (WORLD_tiles/T_I_J.lev) is in coordinates from its tile's centre: tile (i, j) of
size S covers x from i*S - S/2, z from j*S - S/2 in the world's.
"""
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctrlev import Lev  # noqa: E402

TERRAIN = ['asphalt', 'dirt', 'grass', 'wood', 'water', 'stone', 'ice', 'track', 'icy road', 'snow', 'none',
           'hardpack', 'metal', 'fast water', 'mud', 'sideslip', 'river asphalt', 'steam asphalt',
           'ocean asphalt', 'slow grass', 'slow dirt']


def terrain_name(t):
    return TERRAIN[t] if t < len(TERRAIN) else str(t)


def main(path, spot=None, radius=512):
    lev = Lev(open(path, 'rb').read())
    m = lev.mesh_info()
    base = m['ptrQuadBlockArray']
    quads = [lev.quadblock(base, i) for i in range(m['numQuadBlock'])]
    print(f'{os.path.basename(path)}: {m["numQuadBlock"]} quadblocks, {m["numVertex"]} vertices, {m["numBspNodes"]} BSP nodes')
    if spot is None:
        terrain = collections.Counter(q['terrain_type'] for q in quads)
        print('terrain:', ', '.join(f'{terrain_name(t)} {n}' for t, n in terrain.most_common()))
        flags = collections.Counter(q['quadFlags'] for q in quads)
        print('quad flags:', ', '.join(f'{f:#06x} {n}' for f, n in flags.most_common(8)))
        lo = [min(q['bbox'][k] for q in quads) for k in range(3)]
        hi = [max(q['bbox'][k + 3] for q in quads) for k in range(3)]
        print(f'extent: {lo} to {hi}')
        h = lev.header()
        kinds = collections.Counter()
        for i in range(h['numInstances']):
            o = h['ptrInstDefs'] + 0x40 * i
            model = lev.u32(o + 0x10)
            name = lev.data[model:model + 16].split(b'\0')[0].decode('latin1') if model else '?'
            kinds[name] += 1
            pos, rot = struct.unpack_from('<hhh', lev.data, o + 0x30), struct.unpack_from('<hhh', lev.data, o + 0x36)
            print(f'  instance {i}: {name} at {pos}, rotation {rot}')
        print(f'{h["numInstances"]} instances' + (': ' + ', '.join(f'{k} {n}' for k, n in kinds.items()) if kinds else ''))
        return
    x, y, z = spot
    near = []
    for i, q in enumerate(quads):
        b = q['bbox']
        d = [max(b[k] - c, 0, c - b[k + 3]) for k, c in enumerate((x, y, z))]
        if max(d) <= radius:
            near.append((sum(v * v for v in d), i, q))
    near.sort()
    print(f'{len(near)} quadblocks within {radius} of {x},{y},{z} (nearest first):')
    for _, i, q in near[:40]:
        b = q['bbox']
        print(f'  {i}: box {b[:3]} to {b[3:]}, {terrain_name(q["terrain_type"])}, flags {q["quadFlags"]:#06x}, '
              f'checkpoint {q["checkpointIndex"]}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    spot = tuple(int(v) for v in re.findall(r'-?\d+', sys.argv[2])[:3]) if len(sys.argv) > 2 else None
    main(sys.argv[1], spot, int(sys.argv[3]) if len(sys.argv) > 3 else 512)

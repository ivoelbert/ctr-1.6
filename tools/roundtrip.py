"""Rebuilds a retail track's LEV with levwriter (a test of the writer, not a tool for players).

  python3 -I tools/roundtrip.py work/disc/BIGFILE.BIG BIGFILE_ENTRY OUT.bin

(Time Trial and Relic Race load entry 8 * level + 7; 1P races 8 * level + 1.)

Keeps the quadblocks (positions, vertex colors, texture layouts, flags, checkpoints), the
checkpoint nodes, spawns and sky colors; rebuilds the BSP, the PVS (everything visible) and
the normal dividends; drops instances, models, water, skybox and AI paths.
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from bigfile import Bigfile, level_index
from ctrlev import Lev
from levwriter import Level, Node, Quad, write_level


def extract(lev):
    h = lev.header()
    mi = lev.mesh_info()
    vb = mi['ptrVertexArray']
    qb = mi['ptrQuadBlockArray']
    quads = []

    def icon_group(ptr):
        if ptr == 0:
            return None
        if ptr & 1:  # AnimTex: use its current frame
            ptr = lev.u32(ptr - 1)
        return lev.data[ptr:ptr + 0x30]

    for i in range(mi['numQuadBlock']):
        q = lev.quadblock(qb, i)
        pos = [struct.unpack_from('<hhh', lev.data, vb + 16 * k) for k in q['index']]
        col = [tuple(lev.data[vb + 16 * k + 8:vb + 16 * k + 16]) for k in q['index']]
        low = q['ptr_texture_low']
        quads.append(Quad(
            pos=pos,
            faces=[icon_group(p) for p in q['ptr_texture_mid']],
            low=None if low == 0 else lev.data[low:low + 12],
            color=col,
            flags=q['quadFlags'],
            terrain=q['terrain_type'],
            checkpoint=q['checkpointIndex'],
            triangle=q['index'][2] == q['index'][3],
            draw_order_low=q['draw_order_low'],
            draw_order_high=q['draw_order_high'],
        ))
    nodes = []
    o = h['ptr_restart_points']
    for i in range(h['cnt_restart_points']):
        x, y, z, d = struct.unpack_from('<hhhH', lev.data, o + 12 * i)
        f, l, bk, r = lev.data[o + 12 * i + 8:o + 12 * i + 12]
        nodes.append(Node((x, y, z), d, f, bk, l, r))
    spawns = [((s[0], s[1], s[2]), (s[3], s[4], s[5])) for s in h['DriverSpawn']]
    lv = Level(quads=quads, nodes=nodes, spawns=spawns, clear_colors=h['clearColor'],
               config_flags=h['configFlags'] & ~4, glow=h['glowGradient'], build_name='roundtrip')
    if KEEP_BSP:
        bsp = []
        for i in range(mi['numBspNodes']):
            n = lev.bsp(mi['bspRoot'], i)
            if n['flag'] & 1:
                bsp.append(dict(leaf=True, box=n['box'], first=(n['ptrQuadBlockArray'] - qb) // 0x5C, count=n['numQuads']))
            else:
                bsp.append(dict(leaf=False, box=n['box'], axis=n['axis'], children=tuple(None if c == 0xFFFF else c & 0x3FFF for c in n['childID'][:2])))
        lv.bsp = (bsp, list(range(len(quads))))
    return lv


KEEP_BSP = False


if __name__ == '__main__':
    KEEP_BSP = '--keep-bsp' in sys.argv
    sys.argv = [a for a in sys.argv if a != '--keep-bsp']
    big = Bigfile(sys.argv[1])
    lev = Lev(big.get(int(sys.argv[2])))
    data, info = write_level(extract(lev))
    data += b'\0' * ((-len(data)) % 2048)
    open(sys.argv[3], 'wb').write(data)
    print(info, 'bytes', len(data))

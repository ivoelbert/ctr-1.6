"""Map of a generated Dust 2 level for route planning, in Hammer coordinates.

  python3 -I tools/floor_map.py LEV OUT.png ["x,y x,y ..." waypoints] [TRACE.txt ...]

Floors (quadFlags & 0x1000) are filled by height (dark blue low .. yellow high), invisible
stair ramps are outlined in cyan, walls are white lines. Waypoints are green, traces red
(autopilot/trace output: frame, x, y, z in CTR units).
"""
import json
import struct
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from ctrlev import Lev

SC = 0.25
MNX, MXY = -2560, 3776
W, H = int((1920 - MNX) * SC) + 1, int((MXY + 1536) * SC) + 1


def main():
    lev_path, out = sys.argv[1], sys.argv[2]
    wps = sys.argv[3] if len(sys.argv) > 3 else ''
    traces = sys.argv[4:]
    meta = json.load(open('build/lev/dust2.json'))
    S = meta['scale']
    CX, CY = meta['center']

    def px_ctr(x, z):
        hx, hy = x / S + CX, CY - z / S
        return ((hx - MNX) * SC, (MXY - hy) * SC)

    lev = Lev(open(lev_path, 'rb').read())
    mi = lev.mesh_info()
    vb, qb = mi['ptrVertexArray'], mi['ptrQuadBlockArray']
    floors, walls, ramps = [], [], []
    ys = []
    for i in range(mi['numQuadBlock']):
        q = lev.quadblock(qb, i)
        P = [struct.unpack_from('<hhh', lev.data, vb + 16 * k) for k in q['index']]
        tri = q['index'][2] == q['index'][3]
        ring = [P[0], P[1], P[2]] if tri else [P[0], P[1], P[3], P[2]]
        y = sum(p[1] for p in ring) / len(ring)
        if q['quadFlags'] & 0x1000:
            if q['ptr_texture_mid'][0] == 0 and q['ptr_texture_low'] == 0:
                ramps.append(ring)
            else:
                floors.append((y, ring))
                ys.append(y)
        elif q['quadFlags'] & 0x2000:
            b = q['bbox']
            if b[4] - b[1] > 40:
                walls.append(ring)
    lo, hi = min(ys), max(ys)
    im = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)
    for x in range(-2560, 1921, 256):
        d.line([((x - MNX) * SC, 0), ((x - MNX) * SC, H)], fill=(30, 30, 60))
        d.text(((x - MNX) * SC + 2, 2), str(x), fill=(120, 120, 200))
    for y in range(-1536, 3777, 256):
        d.line([(0, (MXY - y) * SC), (W, (MXY - y) * SC)], fill=(30, 30, 60))
        d.text((2, (MXY - y) * SC + 2), str(y), fill=(120, 120, 200))
    for y, ring in sorted(floors, key=lambda t: t[0]):
        t = (y - lo) / (hi - lo + 1e-9)
        col = (int(30 + 225 * t), int(40 + 180 * t), int(160 * (1 - t) + 40))
        d.polygon([px_ctr(p[0], p[2]) for p in ring], fill=col)
    for ring in walls:
        pts = [px_ctr(p[0], p[2]) for p in ring]
        d.line(pts + [pts[0]], fill=(255, 255, 255), width=1)
    for ring in ramps:
        pts = [px_ctr(p[0], p[2]) for p in ring]
        d.line(pts + [pts[0]], fill=(0, 255, 255), width=2)
    if wps:
        pts = []
        for p in wps.split():
            hx, hy = map(float, p.split(','))
            pts.append(((hx - MNX) * SC, (MXY - hy) * SC))
        d.line(pts, fill=(0, 255, 0), width=2)
        for i, (x, y) in enumerate(pts):
            d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 255, 0), width=2)
            d.text((x + 7, y - 7), str(i), fill=(0, 255, 0))
    for tr in traces:
        tp = []
        for line in open(tr):
            f = line.split('\t')
            if len(f) >= 4 and f[0].strip().lstrip('-').isdigit():
                tp.append(px_ctr(float(f[1]), float(f[3])))
        if len(tp) > 1:
            d.line(tp, fill=(255, 50, 50), width=2)
    d.text((W - 300, H - 14), f'floor height {lo / S:.0f}..{hi / S:.0f} (Hammer z)', fill=(255, 255, 255))
    im.save(out)


if __name__ == '__main__':
    main()

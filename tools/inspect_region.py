"""Top-down height map of a generated level around a point, with an optional kart trace.

  python3 -I tools/inspect_region.py LEV CX CZ RADIUS OUT.png [TRACE.txt]

CX, CZ, RADIUS in CTR units. Floors (quadFlags & 0x1000) are colored by height (blue low,
red high), other surfaces gray by height, walls outlined; the trace (trace.mjs output) is
drawn in white with a dot every 30 frames.
"""
import struct
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from ctrlev import Lev


def color_for(y, lo, hi, floor):
    t = 0 if hi == lo else max(0.0, min(1.0, (y - lo) / (hi - lo)))
    if floor:
        return (int(40 + 215 * t), int(80 + 60 * (1 - abs(t - 0.5) * 2)), int(255 * (1 - t)))
    g = int(60 + 120 * t)
    return (g, g, g)


def main():
    path, cx, cz, radius, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
    trace = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != '-' else None
    ymax_cut = float(sys.argv[7]) if len(sys.argv) > 7 else 1e9  # leave out anything higher (roofs)
    lev = Lev(open(path, 'rb').read())
    mi = lev.mesh_info()
    vb, qb = mi['ptrVertexArray'], mi['ptrQuadBlockArray']
    size = 900
    sc = size / (2 * radius)

    def px(x, z):
        return ((x - (cx - radius)) * sc, (z - (cz - radius)) * sc)

    polys = []
    for i in range(mi['numQuadBlock']):
        q = lev.quadblock(qb, i)
        b = q['bbox']
        if b[3] < cx - radius or b[0] > cx + radius or b[5] < cz - radius or b[2] > cz + radius:
            continue
        P = [struct.unpack_from('<hhh', lev.data, vb + 16 * k) for k in q['index']]
        tri = q['index'][2] == q['index'][3]
        ring = [P[0], P[1], P[2]] if tri else [P[0], P[1], P[3], P[2]]
        ymax = max(p[1] for p in ring)
        if min(p[1] for p in ring) > ymax_cut:
            continue
        floor = (q['quadFlags'] & 0x1000) != 0
        polys.append((ymax, ring, floor, q))
    if not polys:
        print('nothing here')
        return
    lo = min(min(p[1] for p in r) for _, r, _, _ in polys)
    hi = max(y for y, _, _, _ in polys)
    im = Image.new('RGB', (size, size), (10, 10, 20))
    d = ImageDraw.Draw(im)
    for ymax, ring, floor, q in sorted(polys, key=lambda t: t[0]):
        pts = [px(p[0], p[2]) for p in ring]
        ys = sum(p[1] for p in ring) / len(ring)
        vertical = (max(p[0] for p in pts) - min(p[0] for p in pts)) < 2 or (max(p[1] for p in pts) - min(p[1] for p in pts)) < 2
        if vertical:
            d.line(pts + [pts[0]], fill=(255, 255, 0), width=2)
        else:
            d.polygon(pts, fill=color_for(ys, lo, hi, floor), outline=(0, 0, 0))
    if trace:
        pts = []
        for line in open(trace):
            f = line.split('\t')
            if len(f) < 4 or not f[0].strip().isdigit():
                continue
            pts.append(px(float(f[1]), float(f[3])))
        if len(pts) > 1:
            d.line(pts, fill=(255, 255, 255), width=2)
        for p in pts:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=(255, 255, 255))
    d.text((5, 5), f'center ({cx:.0f},{cz:.0f}) r {radius:.0f}  y {lo}..{hi}  (+x right, +z down = south)', fill=(255, 255, 255))
    im.save(out)


if __name__ == '__main__':
    main()

"""Draws waypoints (Hammer) and an autopilot trace (CTR) on the gridded Dust 2 map.

  python3 -I tools/route_map.py BASE.png OUT.png "x,y x,y ..." [TRACE.txt]
BASE.png comes from tools/topdown_grid.py (scale 0.25, origin -2560, 3776)."""
import json, sys
from PIL import Image, ImageDraw

base, out, wps = sys.argv[1], sys.argv[2], sys.argv[3]
trace = sys.argv[4] if len(sys.argv) > 4 else None
meta = json.load(open('build/lev/dust2.json'))
S = meta['scale']; CX, CY = meta['center']
sc, mnx, mxy = 0.25, -2560, 3776
im = Image.open(base).convert('RGB')
d = ImageDraw.Draw(im)
def px(hx, hy): return ((hx - mnx) * sc, (mxy - hy) * sc)
pts = [tuple(map(float, p.split(','))) for p in wps.split()]
d.line([px(*p) for p in pts], fill=(0, 255, 0), width=2)
for i, p in enumerate(pts):
    x, y = px(*p); d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 255, 0), width=2); d.text((x + 6, y - 6), str(i), fill=(0, 255, 0))
if trace:
    tp = []
    for line in open(trace):
        f = line.split('\t')
        if len(f) < 4: continue
        hx = float(f[1]) / S + CX; hy = CY - float(f[3]) / S
        tp.append(px(hx, hy))
    if len(tp) > 1: d.line(tp, fill=(255, 60, 60), width=2)
im.save(out)

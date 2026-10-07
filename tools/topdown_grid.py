"""Top-down render of the Dust 2 model with a Hammer-unit grid, to pick landmarks."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
import topdown

src, out = sys.argv[1], sys.argv[2]
scale = 0.25
topdown.render(src, out, scale, float(sys.argv[3]) if len(sys.argv) > 3 else None)
im = Image.open(out).convert('RGB')
d = ImageDraw.Draw(im)
mnx, mxy = -2560, 3776
for x in range(-2560, 1921, 256):
    px = (x - mnx) * scale
    d.line([(px, 0), (px, im.height)], fill=(0, 120, 255), width=1)
    d.text((px + 2, 2), str(x), fill=(255, 255, 0))
for y in range(-1536, 3777, 256):
    py = (mxy - y) * scale
    d.line([(0, py), (im.width, py)], fill=(0, 120, 255), width=1)
    d.text((2, py + 2), str(y), fill=(255, 255, 0))
im.save(out)

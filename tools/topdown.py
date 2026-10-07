"""Top-down picture of the Dust 2 model: each triangle in its texture's color, higher on top."""
import sys, io
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from gltf import triangles, images

def render(glb, out, scale=0.2, upmost=None):
    js, imgs = images(glb)
    tex_img = [Image.open(io.BytesIO(b)).convert('RGB') for b in imgs]
    tex_of_mat = {i: js['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source'] for i, m in enumerate(js['materials'])}
    tris = []
    for mat, P, UV, _, name in triangles(glb):
        img = tex_img[tex_of_mat[mat]]
        arr = np.asarray(img)
        c = UV.mean(axis=1)
        px = np.clip((c[:, 0] * img.width).astype(int), 0, img.width - 1)
        py = np.clip((c[:, 1] * img.height).astype(int), 0, img.height - 1)
        cols = arr[py, px]
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        for k in range(len(P)):
            tris.append((P[k, :, 2].max(), P[k], tuple(int(v) for v in cols[k]), abs(n[k, 2]) / (np.linalg.norm(n[k]) + 1e-9)))
    allp = np.concatenate([t[1] for t in tris])
    mn, mx = allp.min(0), allp.max(0)
    W, H = int((mx[0] - mn[0]) * scale) + 1, int((mx[1] - mn[1]) * scale) + 1
    im = Image.new('RGB', (W, H), (20, 20, 30))
    d = ImageDraw.Draw(im)
    for zmax, P, col, up in sorted(tris, key=lambda t: t[0]):
        if upmost is not None and zmax > upmost:
            continue
        if up < 0.3:
            col = tuple(int(c * 0.5) for c in col)
        pts = [((p[0] - mn[0]) * scale, (mx[1] - p[1]) * scale) for p in P]
        d.polygon(pts, fill=col)
    im.save(out)
    print('bounds', mn, mx, 'image', W, H)

if __name__ == '__main__':
    render(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.2,
           float(sys.argv[4]) if len(sys.argv) > 4 else None)

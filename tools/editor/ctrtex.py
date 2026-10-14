"""CTR's own track textures for the track editor, from your disc: each race track's most used
surface textures (the near level of detail of its quadblocks' faces, read out of its VRM's
VRAM: 4- or 8-bit, through their palettes), as one sheet and a list the editor reads.

    python3 -I tools/editor/ctrtex.py CTR_DISC.bin OUTDIR

OUTDIR/editor_ctrtex.png (128 x 128 cells, 16 a row) and OUTDIR/editor_ctrtex.json:
[{ id, label, track, cell, terrain }]. They hold the disc's textures: keep them to yourself.
"""
import hashlib
import json
import os
import struct
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bigfile import Bigfile, level_index  # noqa: E402
from ctrlev import Lev  # noqa: E402
from psxiso import Disc  # noqa: E402

TRACKS = ['Dingo Canyon', 'Dragon Mines', 'Blizzard Bluff', 'Crash Cove', 'Tiger Temple', "Papu's Pyramid", "Roo's Tubes",
          'Hot Air Skyway', 'Sewer Speedway', 'Mystery Caves', 'Cortex Castle', 'N. Gin Labs', 'Polar Pass', 'Oxide Station',
          'Coco Park', 'Tiny Arena', 'Slide Coliseum', 'Turbo Track']
PER_TRACK = 16      # the most used textures of each
CELL = 128          # each scaled to a cell this big
ROW = 16            # cells a row of the sheet


def vram_of(vrm):
    """VRAM (512 rows of 1024 16-bit words) from a VRM's blocks: (size, then a TIM-like header:
    16, flags, size, x, y, w, h, and the words)."""
    vram = np.zeros((512, 1024), np.uint16)
    o = 4
    while o + 4 <= len(vrm):
        size = struct.unpack_from('<I', vrm, o)[0]
        if size == 0:
            break
        _, _, _, x, y, w, h = struct.unpack_from('<IIIHHHH', vrm, o + 4)
        words = np.frombuffer(vrm, np.uint16, w * h, o + 4 + 20).reshape(h, w)
        vram[y:y + h, x:x + w] = words
        o += 4 + size
    return vram


def texture(vram, uv, clut, tpage):
    """The rectangle a layout's uvs span, as RGBA (colour 0 is see-through, as the PS1 draws it)."""
    us = [p[0] for p in uv]
    vs = [p[1] for p in uv]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    w, h = u1 - u0 + 1, v1 - v0 + 1
    if w < 8 or h < 8:
        return None
    mode = (tpage >> 7) & 3
    px, py = (tpage & 0xF) * 64, ((tpage >> 4) & 1) * 256
    cx, cy = (clut & 0x3F) * 16, clut >> 6
    u = np.arange(u0, u1 + 1)
    v = np.arange(v0, v1 + 1)[:, None]
    if py + v1 >= 512 or cy >= 512:
        return None     # not a texture of this VRM (a layout's spare words)
    if mode == 0:
        words = vram[py + v, (px + u // 4) % 1024]
        idx = (words >> (4 * (u % 4))) & 0xF
        pal = vram[cy, cx:cx + 16]
    elif mode == 1:
        words = vram[py + v, (px + u // 2) % 1024]
        idx = (words >> (8 * (u % 2))) & 0xFF
        pal = vram[cy, cx:cx + 256]
        if len(pal) < 256:
            return None
    else:
        return None
    c = pal[idx].astype(np.uint32)
    rgba = np.zeros(c.shape + (4,), np.uint8)
    rgba[..., 0] = (c & 31) * 255 // 31
    rgba[..., 1] = ((c >> 5) & 31) * 255 // 31
    rgba[..., 2] = ((c >> 10) & 31) * 255 // 31
    rgba[..., 3] = np.where(c == 0, 0, 255)
    return rgba


def main(disc_path, outdir):
    from PIL import Image
    d = Disc(disc_path)
    big = None
    for name, lba, size, isdir in d.walk():
        if name.startswith('BIGFILE.BIG'):
            big = Bigfile(d.read(lba, size))
    if big is None:
        sys.exit('ctrtex: no BIGFILE.BIG on the disc')
    found = []
    seen = set()
    for lid, track in enumerate(TRACKS):
        lev = Lev(big.get(level_index(lid)))
        vram = vram_of(big.get(level_index(lid) - 1))
        m = lev.mesh_info()
        uses = Counter()
        what = {}
        terrains = {}
        for i in range(m['numQuadBlock']):
            q = lev.quadblock(m['ptrQuadBlockArray'], i)
            for p in q['ptr_texture_mid']:
                if not p:
                    continue
                # the near level of detail (the third layout of the group)
                u0, v0, clut, u1, v1, tpage, u2, v2, u3, v3 = struct.unpack_from('<BBHBBHBBBB', lev.data, p + 24)
                key = (clut, tpage, min(u0, u1, u2, u3), min(v0, v1, v2, v3), max(u0, u1, u2, u3), max(v0, v1, v2, v3))
                uses[key] += 1
                what[key] = ((u0, v0), (u1, v1), (u2, v2), (u3, v3)), clut, tpage
                terrains.setdefault(key, Counter())[q['terrain_type']] += 1
        kept = 0
        for key, n in uses.most_common():
            if kept >= PER_TRACK:
                break
            rgba = texture(vram, *what[key])
            if rgba is None or (rgba[..., 3] == 0).mean() > 0.02:
                continue    # cut-outs and bits of murals: not for laying over a road
            if rgba[..., :3].std() < 4:
                continue    # a flat colour (the editor has those)
            h = hashlib.sha1(rgba.tobytes()).hexdigest()[:12]
            if h in seen:
                continue
            seen.add(h)
            kept += 1
            img = Image.fromarray(rgba, 'RGBA').resize((CELL, CELL), Image.BICUBIC)
            found.append(dict(img=img, track=track, lid=lid, n=kept, terrain=terrains[key].most_common(1)[0][0]))
        print(f'{track}: {kept} textures')
    rows = -(-len(found) // ROW)
    sheet = Image.new('RGBA', (ROW * CELL, rows * CELL), (0, 0, 0, 0))
    listing = []
    for k, f in enumerate(found):
        sheet.paste(f['img'], ((k % ROW) * CELL, (k // ROW) * CELL))
        slug = ''.join(ch for ch in f['track'].lower() if ch.isalnum())
        listing.append(dict(id=f'ctr-{slug}-{f["n"]}', label=f'{f["track"]} {f["n"]}', track=f['track'], cell=k, terrain=f['terrain']))
    os.makedirs(outdir, exist_ok=True)
    sheet.save(os.path.join(outdir, 'editor_ctrtex.png'))
    with open(os.path.join(outdir, 'editor_ctrtex.json'), 'w') as fh:
        json.dump(dict(cell=CELL, row=ROW, textures=listing), fh, indent=1)
    print(f'{len(found)} CTR textures in {outdir}/editor_ctrtex.png')


if __name__ == '__main__':
    main(*sys.argv[1:3])

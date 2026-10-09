"""Texture packs (chunk 0xB3300000): {name hash: Texture}.

A pack has a table of 124-byte entries (0x33310004: name, hash, offsets and sizes of the
indices and palette, width, height, bits per pixel) and the data (0x33320002). Indices are
stored as the GS holds them (see gs.py); 256-colour palettes in the GS's CSM1 order; alpha
0x80 is opaque.
"""
import struct
from collections import namedtuple

import numpy as np

from . import bun, gs

Texture = namedtuple('Texture', 'name rgba')


def csm1(pal):
    """256-colour palettes: entries 8-15 and 16-23 of each 32 are swapped (CSM1)."""
    if len(pal) != 256:
        return pal
    p = pal.reshape(8, 4, 8, 4).copy()
    p[:, [1, 2]] = p[:, [2, 1]]
    return p.reshape(256, 4)


def read_pack(d, off, size):
    info = data = None
    for cid, o, sz in bun.walk(d, off, off + size, {0x33310004, 0x33320002}):
        if cid == 0x33310004:
            info = (o, sz)
        elif cid == 0x33320002:
            data = (o, sz)
    if info is None or data is None:
        return {}
    base = bun.skip_padding(d, data[0])
    out = {}
    for i in range(info[1] // 124):
        e = d[info[0] + 124 * i: info[0] + 124 * (i + 1)]
        name = e[12:36].split(b'\0')[0].decode('latin1')
        h, _, _, pix_off, pal_off, pix_size, pal_size, _, wh, fmt = struct.unpack_from('<10I', e, 36)
        w, ht = wh & 0xffff, wh >> 16
        bpp = (fmt >> 16) & 0xff
        raw = d[base + pix_off: base + pix_off + pix_size]
        if bpp == 8 and len(raw) >= w * ht:
            idx = gs.write_read(raw, 32, max(1, w // 2), max(1, ht // 2), max(1, w // 128), 8, w, ht, max(2, w // 64))
        elif bpp == 4 and len(raw) * 2 >= w * ht:
            idx = gs.write_read(raw, 16, max(1, w // 2), max(1, ht // 2), max(1, w // 128), 4, w, ht, max(2, w // 64))
        else:
            continue
        pal = csm1(np.frombuffer(d, np.uint8, pal_size, base + pal_off).reshape(-1, 4).copy())
        pal[:, 3] = np.minimum(255, pal[:, 3].astype(int) * 2)
        out[h] = Texture(name, pal[np.minimum(idx, len(pal) - 1)])
    return out

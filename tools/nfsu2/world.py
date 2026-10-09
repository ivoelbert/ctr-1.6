"""Bayview, NFSU2's city, put together from its streaming sections.

Each section (bun.Section) has scenery (0x80034100): a table of kinds (0x34102: name, the hashes
of the solid's levels of detail) and instances (0x34103, 64 bytes: bounding box, kind, position,
rotation as 3x3 16-bit fixed point, 8192 = 1). Most of the city is chopped per section and
placed in place (identity); props (street lights, trees, signs) are solids of the X sections,
placed many times. Textures come from every section's packs.
"""
import struct

import numpy as np

from . import bun, mesh, textures
from .disc import Nfsu2

TERRAIN, BUILDING, PROP = 0, 1, 2


class Bayview:
    def __init__(self, iso_path):
        game = Nfsu2(iso_path)
        self.stream = game.file('TRACKS\\STREAML4RA.BUN')
        self.sections = bun.sections(game.file('TRACKS\\L4RA.BUN'))
        self.globalb = game.file('GLOBAL\\GLOBALB.BUN')
        self.solids = {}
        self._loaded = set()
        self.low_detail = True
        self.textures = {}
        for sec in self.sections:
            if sec.name[0] == 'X':
                self._load(sec)
            for cid, o, s in bun.chunks(self.stream, sec.offset, sec.offset + sec.size):
                if cid == 0xb3300000:
                    self.textures.update(textures.read_pack(self.stream, o, s))
        for cid, o, s in bun.walk(self.globalb, 0, len(self.globalb), {0xb3300000}):
            for h, t in textures.read_pack(self.globalb, o, s).items():
                self.textures.setdefault(h, t)

    def _load(self, sec):
        if sec.name not in self._loaded:
            self._loaded.add(sec.name)
            self.solids.update(mesh.solids(self.stream, sec.offset, sec.offset + sec.size))

    def scenery(self, sec):
        """[(kind name, solid or None, position (3,), rotation (3, 3), flags)] of a section;
        a solid's points are placed at point @ rotation + position. A kind lists its levels of
        detail, most detailed first (A, B, Z): props (X sections) take their simplest that isn't a
        flat stand-in when low_detail."""
        self._load(sec)
        d = self.stream
        out = []
        for _, o, s in bun.walk(d, sec.offset, sec.offset + sec.size, {0x80034100}):
            kinds, placed = [], []
            for c2, o2, s2 in bun.chunks(d, o, o + s):
                if c2 == 0x34102:
                    q = bun.skip_padding(d, o2)
                    for i in range((o2 + s2 - q) // 68):
                        e = d[q + 68 * i: q + 68 * (i + 1)]
                        kinds.append((e[:32].split(b'\0')[0].decode('latin1'), struct.unpack_from('<3I', e, 32)))
                elif c2 == 0x34103:
                    q = bun.skip_padding(d, o2)
                    for i in range((o2 + s2 - q) // 64):
                        e = d[q + 64 * i: q + 64 * (i + 1)]
                        kind, flags = struct.unpack_from('<2H', e, 24)
                        pos = np.array(struct.unpack_from('<3f', e, 32))
                        rot = np.array(struct.unpack_from('<9h', e, 44), float).reshape(3, 3) / 8192.0
                        placed.append((kind, flags, pos, rot))
            for kind, flags, pos, rot in placed:
                if kind < len(kinds):
                    name, lods = kinds[kind]
                    solid = self.solids.get(lods[0])
                    if self.low_detail and solid is not None and solid['name'].startswith('X'):
                        # props: their simplest level of detail that is still the model (some
                        # last levels are a stand-in for far away: a flat LOD_ texture)
                        for h in lods[::-1]:
                            low = self.solids.get(h) if h else None
                            if low is not None and not any(self.textures[t].name.startswith('LOD_')
                                                           for t in low['tex'] if t in self.textures):
                                solid = low
                                break
                    out.append((name, solid, pos, rot, flags))
        return out

    def triangles(self, bounds, skip=(), min_prop=0.0):
        """The city's triangles with their middles in bounds (x0, y0, x1, y1), by texture:
        {texture hash: (positions (m, 3, 3), uv (m, 3, 2), rgba (m, 3, 4), kind (m,))}, kind
        TERRAIN (the sections' own, chopped city), BUILDING (XB_ solids) or PROP (the rest of
        the X sections' solids), leaving out the solids whose names start with any of skip, and
        props whose bounding boxes' diagonals are under min_prop metres."""
        x0, y0, x1, y1 = bounds
        out = {}
        for sec in self.sections:
            if sec.name[0] in '-XYZ':
                continue
            if sec.cx + sec.radius < x0 or sec.cx - sec.radius > x1 or sec.cy + sec.radius < y0 or sec.cy - sec.radius > y1:
                continue
            for name, solid, pos, rot, flags in self.scenery(sec):
                if solid is None or solid['name'].upper().startswith(tuple(skip)):
                    continue
                bb = solid['bbox']
                if solid['name'].startswith('X') and np.linalg.norm(np.subtract(bb[4:7], bb[0:3])) < min_prop:
                    continue
                kind = BUILDING if solid['name'].startswith('XB') else PROP if solid['name'].startswith('X') else TERRAIN
                for bpos, uv, col, tris, ti in solid['batches']:
                    if not tris:
                        continue
                    idx = np.array(tris)
                    P = (bpos @ rot + pos)[idx]
                    c = P.mean(axis=1)
                    keep = (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
                    if not keep.any():
                        continue
                    th = solid['tex'][ti] if ti < len(solid['tex']) else 0
                    lst = out.setdefault(th, ([], [], [], []))
                    lst[0].append(P[keep])
                    lst[1].append(uv[idx][keep])
                    lst[2].append(col[idx][keep])
                    lst[3].append(np.full(int(keep.sum()), kind))
        return {k: tuple(np.concatenate(v) for v in vs) for k, vs in out.items()}

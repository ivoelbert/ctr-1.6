"""Vice City put together: every model the map files place outdoors, in daylight.

DATA/GTA_VC.DAT lists the object definitions (IDE: objs, and tobj for those shown at some
hours only: id, model, texture dictionary, ...) and the placements (IPL inst: id, model,
interior, position, scale, rotation as a quaternion x, y, z, w). Left out: the low-detail
stand-ins for far away (models named LOD...), the interiors (interior 0 is outdoors; 13
shows everywhere), the night versions of what changes with the hour (a tobj not shown at
noon), the islands' own stand-ins (islandlod...) and the shadows the PS2 lays over the ground
(models named ...shad..., and see-through textures named so: CTR would draw them black), and
the other overlays the game blends (blended_overlay: grime, shade, tyre tracks). What
OBJECT.DAT makes a physics object (lamp posts, bins, benches, signs) is LOOSE. A
model's textures are in its own dictionary, else in generic.txd.

The sea is the game's own, not a model: one level, 6 m (DATA/WATER.DAT), everywhere the
ground is lower. It is made here as square floors (WATER_CELL metres) with waterclear256 from
MODELS/PARTICLE.TXD, wherever nothing in the cell reaches the sea's level; the seabed under
them goes.

Positions are metres, x east, y north, z up: Bayview's frame, so build_world takes either.
"""
import hashlib
import re

import numpy as np

from . import rw
from .disc import ViceCityDisc

TERRAIN, BUILDING, PROP = 0, 1, 2
LOOSE = 4               # build_bayview.LOOSE: drawn, not collided with
NOON = 12
# midday's ambient light for the map (TIMECYC.DAT, sunny, "Amb"): the game adds it to the
# vertex colours baked into the models (RenderWare's prelight: 255 = 1.0), up to 1.0; CTR's
# vertex colours have 0x80 = 1.0, and a little more (as Bayview's: CTR draws no reflections)
AMBIENT = (125, 120, 85)
BRIGHTNESS = 1.15
SEA_LEVEL = 6.0
WATER_CELL = 16.0       # metres
WATER_TEXTURE = 'waterclear256@sea'
WATER_COLOUR = (90, 170, 170, 255)   # midday's (TIMECYC.DAT, WaterRGBA), over the grey texture: 0x80 = 1
TERRAIN_SIZE = 40.0     # metres across: a model this wide is ground (streets, blocks, beach)
PROP_SIZE = 8.0         # and one this small a prop


def records(text):
    """(section, fields) for each line of an IDE or IPL file."""
    sec = None
    for line in text.splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        if line == 'end':
            sec = None
        elif sec is None:
            sec = line
        else:
            yield sec, [f.strip() for f in line.split(',')]


def quat_matrix(x, y, z, w):
    """The rotation (row vectors: p @ m) the game makes of an IPL quaternion: its inverse."""
    x, y, z = -x, -y, -z
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                     [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                     [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])


def blended_overlay(name, rgba):
    """A texture the game blends over what's under it, which CTR (no blending for a level's
    faces) would draw solid: ground shadows, and the grime, shade and tyre tracks laid over
    walls and roads (black64 under every balcony on Ocean Drive) - mostly see-through, and all
    but black or all but invisible."""
    a = rgba[..., 3].astype(float)
    soft = ((a > 8) & (a < 240)).mean()
    if 'shad' in name and (a < 64).mean() > 0.3:
        return True
    return soft > 0.3 and (a.mean() < 64 or rgba[..., :3].mean() < 12)


LAYER_GAP = 0.04        # metres: faces this close in the same plane are layers of each other
LAYER_LIFT = 0.05       # and the upper ones go this far off, per layer (CTR's unit is 1.6 cm)
LAYER_MARGIN = 2.0      # metres round the bounds looked at for what's under a face
LAYER_CELL = 8.0        # metres: the squares a plane's triangles are compared within


def lift_layers(parts, owners, boxes):
    """The game lays details on its faces in the same plane (trim, signs, window frames over a
    wall) and draws them after, so they win; with a depth buffer two faces in one plane fight,
    and flicker as the camera moves. For each part's triangles (parts: (m, 3, 3) arrays, owners:
    their (instance, mesh)), the offset that lifts the upper of each such pair off the lower:
    LAYER_LIFT for each layer under it, away from the lower one's model (its box's middle) or
    up. Upper: the later mesh in one model (drawn later), else the smaller model's (a sign on a
    building)."""
    P = np.concatenate(parts)
    owner = np.concatenate([np.full((len(p), 2), o) for p, o in zip(parts, owners)])
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-4
    n = n / np.maximum(ln, 1e-12)[:, None]
    n *= np.sign(n[np.arange(len(n)), np.abs(n).argmax(axis=1)])[:, None]
    d = (n * P[:, 0]).sum(axis=1)
    box = boxes[owner[:, 0]]
    size = np.maximum(box[:, 2] - box[:, 0], box[:, 3] - box[:, 1])
    middle = np.stack([(box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2], axis=1)
    groups = {}
    for i in np.nonzero(ok)[0]:
        groups.setdefault(tuple(np.round(n[i] * 50).astype(int)), []).append(i)
    under = {}          # triangle: the owners of the faces it lies on
    for g, idx in groups.items():
        if len(idx) < 2:
            continue
        idx = np.array(idx)
        idx = idx[np.argsort(d[idx])]
        # the plane's own axes: its triangles' extents in it
        nn = n[idx[0]]
        u = np.cross(nn, [0.0, 0.0, 1.0] if abs(nn[2]) < 0.9 else [1.0, 0.0, 0.0])
        u /= np.linalg.norm(u)
        v = np.cross(nn, u)
        Q = P[idx]
        qu, qv = Q @ u, Q @ v
        lo = np.stack([qu.min(axis=1), qv.min(axis=1)], axis=1)
        hi = np.stack([qu.max(axis=1), qv.max(axis=1)], axis=1)
        dd = d[idx]
        # the plane's triangles by LAYER_CELL squares of it: only those sharing one are compared
        cells = {}
        c0 = np.floor(lo / LAYER_CELL).astype(int)
        c1 = np.minimum(np.floor(hi / LAYER_CELL).astype(int), c0 + 8)
        for a in range(len(idx)):
            for cu in range(c0[a, 0], c1[a, 0] + 1):
                for cv in range(c0[a, 1], c1[a, 1] + 1):
                    cells.setdefault((cu, cv), []).append(a)
        seen = set()
        for members in cells.values():
            if len(members) < 2:
                continue
            for x, a in enumerate(members):         # in order of d: idx is sorted
                for c in members[x + 1:]:
                    if dd[c] - dd[a] >= LAYER_GAP:
                        break
                    if (a, c) in seen:
                        continue
                    seen.add((a, c))
                    i, j = idx[a], idx[c]
                    if (owner[i] == owner[j]).all():
                        continue
                    if not ((lo[a] < hi[c] - 0.01).all() and (lo[c] < hi[a] - 0.01).all()):
                        continue
                    if owner[i, 0] == owner[j, 0]:
                        top, low = (i, j) if owner[i, 1] > owner[j, 1] else (j, i)
                    else:
                        top, low = (i, j) if size[i] < size[j] else (j, i)
                    under.setdefault(top, {})[tuple(owner[low])] = low
    offset = np.zeros((len(P), 3))
    for top, lows in under.items():
        low = next(iter(lows.values()))
        nn = n[top]
        if abs(nn[2]) > 0.7:
            side = 1.0      # flat: up (its normal points up)
        else:
            out = P[top].mean(axis=0)[:2] - middle[low]
            side = 1.0 if out @ nn[:2] >= 0 else -1.0
        offset[top] = nn * side * LAYER_LIFT * len(lows)
    out, at = [], 0
    for p in parts:
        out.append(offset[at:at + len(p)])
        at += len(p)
    return out


def skipped_model(name):
    return name.startswith(('lod', 'islandlod')) or 'shad' in name


class ViceCity:
    # What the builders (build_bayview, build_world) take from a world: see nfsu2.world.Bayview.
    # The start: down Ocean Drive, along the beach, and back up the streets behind it.
    name, title, start = 'vicecity', 'Vice City', 'oceandrive'
    areas = {
        'oceandrive': dict(title='Ocean Drive', waypoints=[(291, -1000), (255, -1350), (70, -1250), (90, -950)]),
    }
    # the backdrop (CAM_ClearScreen: the first colour above the horizon, the second under it):
    # midday's sky, and under the horizon a grey between the roads' and the sea's, so the
    # hairline cracks between the models' pieces don't show bright blue
    clear_colors = [(90, 180, 255, 1), (80, 96, 96, 1), (90, 200, 255, 1)]
    # what the start level keeps along its loop, metres (by kind: build_bayview.CORRIDOR's): the
    # streets. Vice City is dense, the game's memory holds a level of about 30 MB, and in the
    # world the tiles take the start level's mesh's place: its route and respawns are what count
    corridor = {0: 20.0, 1: 20.0, 2: 20.0, 3: 20.0}
    skip_solids = ()
    skip_textures = ()
    ground_textures = ()
    # no border round each texture in the atlas: Vice City's 3,000-odd textures fit without them,
    # and the shader wraps the filtering itself (a "CTRW" atlas, engine/platform/native_renderer.c)
    atlas_border = 0
    # CTR's height 0 at the sea: the engine draws a kart on water only above it (half sunk)
    floor_z = SEA_LEVEL
    double_sided_floors = True
    back_to_back = False    # the models' faces turn either way: every wall drawn from both sides
    stair_unit = 0.0254     # metres an inch: ramps over the kerbs and steps (tools/stairs.py's sizes)
    # its kerbs reach a few centimetres under the road, its pavements slope to drain: a step's
    # floors within 6 inches of its riser's ends, up to 14 degrees off flat
    stair_floor_tol, stair_floor_nz = 6.0, 0.97

    @staticmethod
    def is_road(name):
        """A road's texture (the routes keep to them, the minimap shows them)."""
        return any(k in name for k in ('road', 'tarmac', 'runway', 'tar_', 'asphalt'))

    is_map_road = is_road

    @staticmethod
    def is_map_ground(name):
        return any(k in name for k in ('pave', 'grass', 'sand', 'conc', 'cobbl', 'dirt', 'path', 'carpark', 'slab', 'ground', 'golf'))

    @staticmethod
    def light(c):
        """The colours as the game lights them at noon (see triangles), 0x80 = 1."""
        return np.minimum(c, 255)

    @staticmethod
    def terrain(name):
        """Water is driven on, at full speed (CTR's fast water)."""
        return 13 if name == 'waterclear256' else 0

    def __init__(self, iso_path):
        self.disc = ViceCityDisc(iso_path)
        dat = self.disc.text('DATA/GTA_VC.DAT')
        defs = {}
        for line in dat.splitlines():
            if line.startswith('IDE '):
                for sec, f in records(self.disc.text(line.split()[1])):
                    if sec == 'objs':
                        defs[int(f[0])] = (f[1].lower(), f[2].lower())
                    elif sec == 'tobj':
                        on, off = int(f[-2]), int(f[-1])
                        shown = on <= NOON < off if on < off else (NOON >= on or NOON < off)
                        if shown:
                            defs[int(f[0])] = (f[1].lower(), f[2].lower())
        self.instances = []     # (model, txd, position (3,), rotation (3, 3), scale (3,))
        for line in dat.splitlines():
            if not line.startswith('IPL ') or 'MAPS' not in line.upper():
                continue
            for sec, f in records(self.disc.text(line.split()[1])):
                if sec != 'inst' or len(f) < 13:
                    continue
                d = defs.get(int(f[0]))
                if d is None or skipped_model(d[0]) or f[2] not in ('0', '13'):
                    continue
                if not self.disc.has(d[0] + '.dff'):
                    continue
                v = [float(x) for x in f[3:13]]
                self.instances.append((d[0], d[1], np.array(v[0:3]), quat_matrix(*v[6:10]), np.array(v[3:6])))
        # what a car knocks over (OBJECT.DAT's objects lighter than the fixed ones' 9999 kg):
        # drawn, but the kart drives through
        self.loose = set()
        for line in self.disc.text('DATA/OBJECT.DAT').splitlines():
            f = line.split(';')[0].replace(',', ' ').split()
            if len(f) >= 2:
                try:
                    if float(f[1]) < 9999:
                        self.loose.add(f[0].lower())
                except ValueError:
                    pass
        self.models = {}
        self.textures = {}
        self._txds = {}
        self._keys = {}
        self._boxes = None

    def model(self, name):
        if name not in self.models:
            meshes = rw.read_clump(self.disc.file(name + '.dff'))
            # damaged versions (frames named ..._dam) are swapped in when a thing breaks, and
            # the simpler levels of detail (..._l1, _l2) farther away: the most detailed (_l0)
            self.models[name] = [m for m in meshes if not m[5].endswith('_dam') and not re.search(r'_l[1-9]$', m[5])]
        return self.models[name]

    def txd(self, name):
        if name not in self._txds:
            self._txds[name] = rw.read_txd(self.disc.file(name + '.txd')) if self.disc.has(name + '.txd') else {}
        return self._txds[name]

    def texture_key(self, txd, tex):
        """The texture a model's material names (in its own dictionary, else generic's), loaded
        into self.textures, as 'name@content hash': the districts' dictionaries share many
        images, and the atlas holds each once. None when it's in neither, or a shadow."""
        if (txd, tex) not in self._keys:
            key = None
            for d in (txd, 'generic'):
                t = self.txd(d).get(tex)
                if t is None:
                    continue
                if not blended_overlay(tex, t.rgba):
                    key = f'{tex}@{hashlib.sha1(t.rgba.tobytes() + str(t.rgba.shape).encode()).hexdigest()[:10]}'
                    self.textures.setdefault(key, t)
                break
            self._keys[txd, tex] = key
        return self._keys[txd, tex]

    def boxes(self):
        """Each instance's box on the map (x0, y0, x1, y1), its models loaded."""
        if self._boxes is None:
            out = []
            for name, txd, pos, rot, scale in self.instances:
                pts = [m[0] for m in self.model(name) if len(m[0])]
                if not pts:
                    out.append((1, 1, 0, 0))
                    continue
                P = (np.concatenate(pts) * scale) @ rot + pos
                out.append((P[:, 0].min(), P[:, 1].min(), P[:, 0].max(), P[:, 1].max()))
            self._boxes = np.array(out, float)
        return self._boxes

    def sea(self):
        """The water cells: a boolean grid (rows along y) of WATER_CELL squares from the corner
        (x0, y0) = self.sea_origin, true where nothing reaches SEA_LEVEL. Each triangle above
        it marks the cells its points (corners and points across it, a cell apart) fall in."""
        if getattr(self, '_sea', None) is not None:
            return self._sea
        b = self.boxes()
        ok = b[:, 2] >= b[:, 0]
        x0, y0 = np.floor(b[ok, 0].min() / WATER_CELL) * WATER_CELL - WATER_CELL, np.floor(b[ok, 1].min() / WATER_CELL) * WATER_CELL - WATER_CELL
        nx = int((b[ok, 2].max() - x0) / WATER_CELL) + 2
        ny = int((b[ok, 3].max() - y0) / WATER_CELL) + 2
        land = np.zeros((ny, nx), bool)
        for name, txd, pos, rot, scale in self.instances:
            for P0, uv, col, tris, tex, _ in self.model(name):
                if not len(tris):
                    continue
                P = ((P0 * scale) @ rot + pos)[tris]
                P = P[P[:, :, 2].max(axis=1) > SEA_LEVEL]
                if not len(P):
                    continue
                edge = np.max([np.linalg.norm(P[:, a, :2] - P[:, c, :2], axis=1) for a, c in ((0, 1), (1, 2), (0, 2))], axis=0)
                steps = np.ceil(edge / WATER_CELL).astype(int) + 1
                for k in np.unique(steps):
                    Q = P[steps == k]
                    u, v = np.meshgrid(np.linspace(0, 1, k + 1), np.linspace(0, 1, k + 1))
                    inside = u + v <= 1
                    u, v = u[inside], v[inside]
                    pts = Q[:, None, 0] + u[None, :, None] * (Q[:, None, 1] - Q[:, None, 0]) + v[None, :, None] * (Q[:, None, 2] - Q[:, None, 0])
                    pts = pts[pts[..., 2] > SEA_LEVEL]
                    i = ((pts[:, 0] - x0) / WATER_CELL).astype(int)
                    j = ((pts[:, 1] - y0) / WATER_CELL).astype(int)
                    land[np.clip(j, 0, ny - 1), np.clip(i, 0, nx - 1)] = True
        self.sea_origin = (x0, y0)
        self._sea = ~land
        return self._sea

    def water(self, bounds):
        """The sea's floors with their middles in bounds: (positions (m, 3, 3), uv, rgba)."""
        sea = self.sea()
        x0, y0 = self.sea_origin
        bx0, by0, bx1, by1 = bounds
        i0, i1 = max(0, int((bx0 - x0) // WATER_CELL) - 1), min(sea.shape[1], int((bx1 - x0) // WATER_CELL) + 2)
        j0, j1 = max(0, int((by0 - y0) // WATER_CELL) - 1), min(sea.shape[0], int((by1 - y0) // WATER_CELL) + 2)
        P = []
        for j in range(j0, j1):
            for i in range(i0, i1):
                cx, cy = x0 + (i + 0.5) * WATER_CELL, y0 + (j + 0.5) * WATER_CELL
                if not sea[j, i] or not (bx0 <= cx <= bx1 and by0 <= cy <= by1):
                    continue
                a = np.array([x0 + i * WATER_CELL, y0 + j * WATER_CELL, SEA_LEVEL])
                dx, dy = np.array([WATER_CELL, 0, 0]), np.array([0, WATER_CELL, 0])
                # two triangles, counter-clockwise from above (facing up)
                P += [[a, a + dx, a + dx + dy], [a, a + dx + dy, a + dy]]
        P = np.array(P, float).reshape(-1, 3, 3)
        uv = (P[..., :2] - np.array([x0, y0])) / WATER_CELL
        uv = uv - np.floor(uv.min(axis=1, keepdims=True))
        col = np.empty(P.shape[:2] + (4,))
        col[...] = WATER_COLOUR
        return P, uv, col

    def under_sea(self, P):
        """Triangles (m, 3, 3) wholly under the sea's level in water cells: the seabed."""
        sea = self.sea()
        x0, y0 = self.sea_origin
        c = P.mean(axis=1)
        i = np.clip(((c[:, 0] - x0) / WATER_CELL).astype(int), 0, sea.shape[1] - 1)
        j = np.clip(((c[:, 1] - y0) / WATER_CELL).astype(int), 0, sea.shape[0] - 1)
        return (P[:, :, 2].max(axis=1) <= SEA_LEVEL) & sea[j, i]

    def triangles(self, bounds, skip=()):
        """The city's triangles with their middles in bounds (x0, y0, x1, y1), by texture key:
        {key: (positions (m, 3, 3), uv (m, 3, 2), rgba (m, 3, 4), kind (m,))}, the models
        whose names start with any of skip left out. Colours have midday's ambient added; the
        layers laid on other faces are lifted off them (lift_layers)."""
        x0, y0, x1, y1 = bounds
        # a margin, for the faces under those at the edge (the lifts are the same either side)
        m = LAYER_MARGIN
        b = self.boxes()
        hit = np.nonzero((b[:, 2] >= x0 - m) & (b[:, 0] <= x1 + m) & (b[:, 3] >= y0 - m) & (b[:, 1] <= y1 + m))[0]
        amb = np.array(AMBIENT, float)
        pieces = []     # (key, P, uv, rgba, kind, middle in bounds, instance, mesh)
        for k in hit:
            name, txd, pos, rot, scale = self.instances[k]
            if name.startswith(tuple(skip)):
                continue
            size = max(b[k, 2] - b[k, 0], b[k, 3] - b[k, 1])
            kind = TERRAIN if size >= TERRAIN_SIZE else PROP if size < PROP_SIZE else BUILDING
            if name in self.loose:
                kind |= LOOSE
            for mi, (P0, uv, col, tris, tex, _) in enumerate(self.model(name)):
                if not len(tris):
                    continue
                key = self.texture_key(txd, tex)
                if key is None:
                    continue
                P = ((P0 * scale) @ rot + pos)[tris]
                c = P.mean(axis=1)
                near = (c[:, 0] >= x0 - m) & (c[:, 0] <= x1 + m) & (c[:, 1] >= y0 - m) & (c[:, 1] <= y1 + m)
                near[near] &= ~self.under_sea(P[near])
                if not near.any():
                    continue
                P = P[near]
                c = c[near]
                C = col[tris][near].copy()
                C[..., :3] = np.minimum(C[..., :3] + amb, 255) * (128.0 / 255.0 * BRIGHTNESS)
                T = uv[tris][near]
                # the PS2 doesn't cull, and the models' strips start either way round: what's
                # flat faces up (ceilings too: build_bayview draws this world's floors from both
                # sides)
                n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
                down = n[:, 2] < -0.7 * np.linalg.norm(n, axis=1)
                P[down], T[down], C[down] = P[down][:, ::-1], T[down][:, ::-1], C[down][:, ::-1]
                inside = (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
                pieces.append((key, P, T, C, kind, inside, k, mi))
        out = {}
        if pieces:
            lift = lift_layers([p[1] for p in pieces], [(p[6], p[7]) for p in pieces], b)
            for (key, P, T, C, kind, inside, k, mi), dp in zip(pieces, lift):
                if not inside.any():
                    continue
                lst = out.setdefault(key, ([], [], [], []))
                lst[0].append((P + dp[:, None, :])[inside])
                lst[1].append(T[inside])
                lst[2].append(C[inside])
                lst[3].append(np.full(int(inside.sum()), kind))
        P, uv, col = self.water(bounds)
        if len(P):
            if WATER_TEXTURE not in self.textures:
                self.textures[WATER_TEXTURE] = rw.read_txd(self.disc.text_bytes('MODELS/PARTICLE.TXD'))['waterclear256']
            lst = out.setdefault(WATER_TEXTURE, ([], [], [], []))
            lst[0].append(P)
            lst[1].append(uv)
            lst[2].append(col)
            lst[3].append(np.full(len(P), TERRAIN))
        return {k: tuple(np.concatenate(v) for v in vs) for k, vs in out.items()}

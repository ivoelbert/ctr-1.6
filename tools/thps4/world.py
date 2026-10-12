"""A Tony Hawk's Pro Skater 4 level as a world for tools/build_world.py (see vicecity.world and
nfsu2.world for what a world gives the builders).

Every sector of the scene, every mesh, with its material's first pass's texture; positions in
metres, x east, y north, z up (the level's x, -z, y: inches, y up). The start is the level's
player one restart (level.player_start).
"""
import numpy as np

from . import level as L

TERRAIN, BUILDING, PROP = 0, 1, 2
TERRAIN_SIZE = 40.0     # metres across: a sector this wide is ground
PROP_SIZE = 4.0         # and one this small a prop

LEVELS = {
    'alc': 'Alcatraz', 'cnv': 'Carnival', 'hof': 'Chicago', 'jnk': 'Shipyard', 'kon': 'Kona',
    'lon': 'London', 'motox': 'Motocross', 'sch': 'College', 'sf2': 'San Francisco', 'zoo': 'Zoo',
    'skateshop': 'Skate Shop',
}


MAX_EDGE = 60.0         # metres: longer triangles are split (a tile holds 220 m round its middle)


def split_big(P, T, C):
    """Triangles (with their uvs and colours) with an edge over MAX_EDGE split in four, again
    until none is (Carnival's and London's backdrops are hundreds of metres across)."""
    outP, outT, outC = [], [], []
    todo = [(P, T, C)]
    while todo:
        P, T, C = todo.pop()
        e = np.max([np.linalg.norm(P[:, a] - P[:, b], axis=1) for a, b in ((0, 1), (1, 2), (0, 2))], axis=0)
        big = e > MAX_EDGE
        outP.append(P[~big]), outT.append(T[~big]), outC.append(C[~big])
        if big.any():
            parts = []
            for A in (P[big], T[big], C[big]):
                m01, m12, m02 = (A[:, 0] + A[:, 1]) / 2, (A[:, 1] + A[:, 2]) / 2, (A[:, 0] + A[:, 2]) / 2
                parts.append(np.concatenate([np.stack([A[:, 0], m01, m02], 1), np.stack([m01, A[:, 1], m12], 1),
                                             np.stack([m02, m12, A[:, 2]], 1), np.stack([m01, m12, m02], 1)]))
            todo.append(tuple(parts))
    return np.concatenate(outP), np.concatenate(outT), np.concatenate(outC)


def to_map(p):
    """Level positions (inches, y up) in metres, z up: (x, -z, y), a turn (as (x, z, y), a
    mirror, the signs read backwards)."""
    p = np.asarray(p, float) * L.INCH
    return np.stack([p[..., 0], -p[..., 2], p[..., 1]], -1)


class Thps4Level:
    clear_colors = [(110, 170, 230, 1), (150, 150, 150, 1), (110, 170, 230, 1)]
    skip_solids = ()
    skip_textures = ()
    ground_textures = ()
    atlas_border = 0
    double_sided_floors = True
    back_to_back = False
    floor_z = None
    stair_unit = 0.0254
    stair_floor_tol, stair_floor_nz = 6.0, 0.97
    stair_run_per_rise = 8.0
    corridor = {0: 40.0, 1: 40.0, 2: 40.0, 3: 40.0}
    # CTR units a metre: twice the cities' 64, so the kart is half as big against a skate park
    scale = 128.0
    # metres: farther BSP leaves aren't drawn (a park's views filled the frame's primitive memory)
    draw_distance = 120.0
    # faces up to about 70 degrees steep are ground: the kart rides up a quarter pipe and rolls
    # back, as on Sewer Speedway's (steeper, it stuck upside down on the coping)
    ground_ny = 0.35
    start_banner = False      # no start line in a skate park (in the skate shop it filled the view)
    start = 'start'
    auto_waypoints = True     # the start loop's other waypoints: places the start reaches
    landmark_spacing = 25.0   # metres between the respawn landmarks along the (short) start loop

    @staticmethod
    def is_road(name):
        return True         # a skate park's every floor is for riding: the routes keep to floors

    @staticmethod
    def is_map_road(name):
        return False        # the minimap: the floors as ground (as roads they were all dark)

    @staticmethod
    def is_map_ground(name):
        return True

    @staticmethod
    def light(c):
        """The baked light: 255 is full on the PC (128 on the PS2); CTR's 0x80 = 1, a little more
        (it draws the material's darkening passes no more than its decals)."""
        return np.minimum(c * (128.0 / 255.0) * 1.2, 255)

    def terrain(self, name):
        return 13 if name in self.water_textures else 0     # fast water: full speed

    @staticmethod
    def is_cutout(rgba):
        a = rgba[..., 3]
        return (a < 64).mean() > 0.05 and (a >= 192).mean() > 0.1

    def __init__(self, data_dir, code):
        self.code = code.lower()
        self.name = 'thps4_' + self.code
        self.title = 'THPS4 ' + LEVELS.get(self.code, code)
        scn, tex, qb = L.level_files(data_dir, code)
        found = L.read_textures(tex)
        self.textures = {f'{k:08x}': t for k, t in found.items()}
        self.materials, self.sectors = L.read_scene(scn, found)
        self.nodes = L.read_nodes(qb) if qb else []
        # what the level holds at its start: a sector whose LevelGeometry node isn't
        # CreatedAtStart comes with a goal or a cheat (Alcatraz's loop, the broken windows'
        # other halves, race planes)
        later = {n.checksum for n in self.nodes if n.cls == 'LevelGeometry' and 'CreatedAtStart' not in n.refs}
        self.sectors = [s_ for s_ in self.sectors if s_.checksum not in later]
        self.low_detail = False
        self.water_textures = set()
        start = L.player_start(self.nodes)
        allp = to_map(np.concatenate([s.positions for s in self.sectors]))
        lo, hi = allp.min(0), allp.max(0)
        self.bounds = (float(lo[0]) - 20, float(lo[1]) - 20, float(hi[0]) + 20, float(hi[1]) + 20)
        if start is None:
            centre = (lo + hi) / 2
            waypoints = [tuple(centre), (centre[0] + 20, centre[1], centre[2]), (centre[0], centre[1] + 20, centre[2])]
        else:
            s = to_map(start.position)
            others = sorted((to_map(n.position) for n in self.nodes if n.cls.lower() == 'restart'),
                            key=lambda p: np.linalg.norm(p - s))
            near = [p for p in others if 12 < np.linalg.norm(p[:2] - s[:2]) < 80 and abs(p[2] - s[2]) < 3]
            waypoints = [tuple(s)] + [tuple(p) for p in near[:2]]
            if len(waypoints) < 3:
                waypoints += [(s[0] + 15, s[1], s[2]), (s[0], s[1] + 15, s[2])][:3 - len(waypoints)]
        # other starts, should that one's floor be a ledge: the restarts, nearest the middle first
        mid = (lo + hi) / 2
        self.start_candidates = [tuple(float(v) for v in to_map(n.position)) for n in
                                 sorted((n for n in self.nodes if n.cls.lower() == 'restart'),
                                        key=lambda n: np.linalg.norm(to_map(n.position)[:2] - mid[:2]))]
        self.areas = {'start': dict(title=self.title, waypoints=[tuple(float(v) for v in w) for w in waypoints])}
        # water: the big flat sectors round a level (Alcatraz's bay), its floor at CTR's height 0
        self.water = set()
        for s_ in self.sectors:
            P = to_map(s_.positions)
            if np.ptp(P[:, :2], axis=0).max() > 250 and np.ptp(P[:, 2]) < 0.5:
                self.water.add(s_.checksum)
                self.floor_z = float(P[:, 2].mean())

    def triangles(self, bounds, skip=()):
        """The level's triangles with their middles in bounds, by texture: {key: (positions
        (m, 3, 3), uv (m, 3, 2), rgba (m, 3, 4), kind (m,))}."""
        x0, y0, x1, y1 = bounds
        out = {}
        for sec in self.sectors:
            P0 = to_map(sec.positions)
            lo, hi = P0.min(0), P0.max(0)
            if hi[0] < x0 or lo[0] > x1 or hi[1] < y0 or lo[1] > y1:
                continue
            size = max(hi[0] - lo[0], hi[1] - lo[1])
            kind = TERRAIN if size >= TERRAIN_SIZE else PROP if size < PROP_SIZE else BUILDING
            water = sec.checksum in self.water
            for mat, mflags, idx in sec.meshes:
                m = self.materials.get(mat)
                if m is None or not m.passes:
                    continue
                key = f'{m.passes[0][0]:08x}'
                if key not in self.textures:
                    continue
                if water:
                    if key + '@water' not in self.textures:
                        self.textures[key + '@water'] = L.Texture(key + '@water', self.textures[key].rgba)
                    key += '@water'
                    self.water_textures.add(key)
                tris = L.strip_triangles(idx, sec.positions)
                if not len(tris):
                    continue
                P, T0, C0 = split_big(P0[tris], sec.uv[tris], sec.colors[tris])
                c = P.mean(axis=1)
                keep = (c[:, 0] >= x0) & (c[:, 0] <= x1) & (c[:, 1] >= y0) & (c[:, 1] <= y1)
                if not keep.any():
                    continue
                P, T, C = P[keep], T0[keep], C0[keep].copy()
                n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
                down = n[:, 2] < -0.7 * np.linalg.norm(n, axis=1)
                P[down], T[down], C[down] = P[down][:, ::-1], T[down][:, ::-1], C[down][:, ::-1]
                C[..., 3] = 255
                lst = out.setdefault(key, ([], [], [], []))
                lst[0].append(P)
                lst[1].append(T)
                lst[2].append(C)
                lst[3].append(np.full(len(P), kind))
        return {k: tuple(np.concatenate(v) for v in vs) for k, vs in out.items()}

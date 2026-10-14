"""The track editor's field as a world for tools/build_world.py: a flat square of grass round the
origin, and its start in the middle. The page draws its own tiles over it (web/editor/), so all
this gives the game is a start level: where the karts start, the respawns, the minimap, the modes.
"""
from collections import namedtuple

import numpy as np

Texture = namedtuple('Texture', 'name rgba')

FIELD = 240.0       # metres across (the editor's build area is 3 x 3 tiles of 256 m: this sits inside)
CELL = 20.0         # metres a ground triangle pair


def grass(n=64, seed=7):
    """A plain grass texture (n x n RGBA): the field's, never seen once the editor's tiles are in."""
    rng = np.random.default_rng(seed)
    base = np.array([70, 140, 60], float)
    noise = rng.normal(0, 10, (n, n, 1))
    rgb = np.clip(base + noise, 0, 255)
    return np.concatenate([rgb, np.full((n, n, 1), 255.0)], -1).astype(np.uint8)


class EditorField:
    name = 'editor'
    title = 'Track Editor'
    listed = False      # not a map of the list: the launcher's editor panel opens it
    clear_colors = [(110, 170, 230, 1), (150, 150, 150, 1), (110, 170, 230, 1)]
    skip_solids = ()
    skip_textures = ()
    ground_textures = ('grass',)
    atlas_border = 0
    double_sided_floors = False
    back_to_back = True
    floor_z = 0.0
    corridor = {0: 40.0, 1: 40.0, 2: 40.0, 3: 40.0}
    scale = 64.0
    start_banner = False
    start = 'start'
    landmark_spacing = 25.0
    bounds = (-FIELD / 2 - 10, -FIELD / 2 - 10, FIELD / 2 + 10, FIELD / 2 + 10)
    low_detail = False

    def __init__(self, *_):
        self.textures = {'grass': Texture('grass', grass())}
        self.areas = {'start': dict(title=self.title, waypoints=[(0.0, 0.0, 0.0), (40.0, 0.0, 0.0), (0.0, 40.0, 0.0)])}

    @staticmethod
    def is_road(name):
        return True

    @staticmethod
    def is_map_road(name):
        return False

    @staticmethod
    def is_map_ground(name):
        return True

    @staticmethod
    def light(c):
        return c

    @staticmethod
    def terrain(name):
        return 0

    @staticmethod
    def is_cutout(rgba):
        return False

    def triangles(self, bounds, skip=()):
        """The field's triangles with their middles in bounds: {key: (positions (m, 3, 3),
        uv (m, 3, 2), rgba (m, 3, 4), kind (m,))}, metres, z up."""
        x0, y0, x1, y1 = bounds
        P, T = [], []
        n = int(FIELD // CELL)
        for i in range(n):
            for j in range(n):
                ax, ay = -FIELD / 2 + i * CELL, -FIELD / 2 + j * CELL
                a, b, c, d = (ax, ay, 0), (ax + CELL, ay, 0), (ax + CELL, ay + CELL, 0), (ax, ay + CELL, 0)
                for tri in ((a, b, c), (a, c, d)):
                    m = np.mean(tri, 0)
                    if x0 <= m[0] <= x1 and y0 <= m[1] <= y1:
                        P.append(tri)
                        T.append([(p[0] / 4, p[1] / 4) for p in tri])
        if not P:
            return {}
        P, T = np.array(P, float), np.array(T, float)
        C = np.full(P.shape[:2] + (4,), 128.0)
        C[..., 3] = 255
        return {'grass': (P, T, C, np.zeros(len(P), int))}

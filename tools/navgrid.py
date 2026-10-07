"""A driving grid over a generated level: where a kart can be, and how to get between places.

Built from the LEV's own collision data (what the game collides with), in CTR units:
  - every GROUND quadblock (stair ramps included) is rasterized into CELL-sized cells,
    keeping each cell's floor heights (several where floors overlap, like tunnels);
  - every COLLISION_SURFACE quadblock blocks the cells its footprint crosses, for the
    floors whose kart-height band [floor + LOW, floor + HIGH] it overlaps;
  - a cell-floor is drivable when no blocked cell lies within CLEAR of it;
  - neighbours connect when their floors differ by at most STEP.
Paths are A* over drivable cell-floors, penalized near walls so they keep to the middle.
"""
import heapq
import math
import struct

import numpy as np

from ctrlev import Lev

CELL = 64
LOW, HIGH = 24, 160
STEP = 40
MAX_DROP = 600      # 150 Hammer units: a kart drops off ledges fine
CLEAR = 1           # cells (64 units) from any wall


def lev_quads(lev_path):
    """(flags, 9 positions, triangle) for each quadblock of a LEV file, in file order."""
    lev = Lev(open(lev_path, 'rb').read())
    mi = lev.mesh_info()
    vb, qb = mi['ptrVertexArray'], mi['ptrQuadBlockArray']
    out = []
    for i in range(mi['numQuadBlock']):
        q = lev.quadblock(qb, i)
        P = [struct.unpack_from('<hhh', lev.data, vb + 16 * k) for k in q['index']]
        out.append((q['quadFlags'], P, q['index'][2] == q['index'][3]))
    return out


class NavGrid:
    def __init__(self, source):
        """source: a LEV path, or a list of (flags, 9 positions, triangle) quadblocks."""
        quads = lev_quads(source) if isinstance(source, str) else source
        floors, walls = [], []
        for i, (flags, P, tri) in enumerate(quads):
            P = [np.array(p, dtype=float) for p in P]
            tris = [(P[0], P[1], P[2])] if tri else [(P[0], P[1], P[2]), (P[1], P[3], P[2])]
            if flags & 0x1000:
                floors.append((i, tris))
            elif flags & 0x2000:
                walls.append((i, tris))
        allp = np.array([p for _, ts in floors + walls for t in ts for p in t])
        self.x0, self.z0 = allp[:, 0].min() - CELL, allp[:, 2].min() - CELL
        self.nx = int((allp[:, 0].max() - self.x0) / CELL) + 2
        self.nz = int((allp[:, 2].max() - self.z0) / CELL) + 2
        # cell -> list of floor heights (merged within STEP/2)
        self.floors = [[[] for _ in range(self.nz)] for _ in range(self.nx)]
        for qi, ts in floors:
            for a, b, c in ts:
                self._raster_floor(a, b, c, qi)
        for x in range(self.nx):
            for z in range(self.nz):
                self.floors[x][z] = self._merge(self.floors[x][z])
        # walls: (x, z) -> list of (ymin, ymax)
        self.walls = {}
        for qi, ts in walls:
            for a, b, c in ts:
                self._raster_wall(a, b, c)
        self._build_nodes()

    def cell(self, x, z):
        return int((x - self.x0) / CELL), int((z - self.z0) / CELL)

    def center(self, cx, cz):
        return self.x0 + (cx + 0.5) * CELL, self.z0 + (cz + 0.5) * CELL

    def _raster_floor(self, a, b, c, qi):
        xs = [a[0], b[0], c[0]]
        zs = [a[2], b[2], c[2]]
        cx0, cz0 = self.cell(min(xs), min(zs))
        cx1, cz1 = self.cell(max(xs), max(zs))
        v0 = np.array([b[0] - a[0], b[2] - a[2]])
        v1 = np.array([c[0] - a[0], c[2] - a[2]])
        den = v0[0] * v1[1] - v0[1] * v1[0]
        if abs(den) < 1e-6:
            return
        for cx in range(max(cx0, 0), min(cx1, self.nx - 1) + 1):
            for cz in range(max(cz0, 0), min(cz1, self.nz - 1) + 1):
                px, pz = self.center(cx, cz)
                d = np.array([px - a[0], pz - a[2]])
                u = (d[0] * v1[1] - d[1] * v1[0]) / den
                v = (v0[0] * d[1] - v0[1] * d[0]) / den
                if u < -0.02 or v < -0.02 or u + v > 1.02:
                    continue
                y = a[1] + u * (b[1] - a[1]) + v * (c[1] - a[1])
                self.floors[cx][cz].append((y, qi))

    @staticmethod
    def _merge(hs):
        hs = sorted(hs)
        out = []
        for y, qi in hs:
            if out and y - out[-1][0] < STEP / 2:
                out[-1] = (max(out[-1][0], y), qi if y > out[-1][0] else out[-1][1])
            else:
                out.append((y, qi))
        return out

    def _raster_wall(self, a, b, c):
        ymin, ymax = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        # sample the triangle densely in xz
        pts = [a, b, c]
        n = 1 + int(max(np.linalg.norm(np.array([p[0], p[2]]) - np.array([q[0], q[2]])) for p in pts for q in pts) / (CELL / 2))
        for i in range(n + 1):
            for j in range(n + 1 - i):
                p = a + (b - a) * (i / n) + (c - a) * (j / n)
                key = self.cell(p[0], p[2])
                self.walls.setdefault(key, []).append((ymin, ymax))

    def _blocked(self, cx, cz, y):
        for (lo, hi) in self.walls.get((cx, cz), ()):
            if hi > y + LOW and lo < y + HIGH:
                return True
        return False

    def _build_nodes(self):
        """Drivable cell-floors: id per (cx, cz, k)."""
        self.node = {}
        self.pos = []
        self.wall_dist = []
        blocked = set()
        for cx in range(self.nx):
            for cz in range(self.nz):
                for k, (y, qi) in enumerate(self.floors[cx][cz]):
                    if self._blocked(cx, cz, y):
                        blocked.add((cx, cz, k))
        for cx in range(self.nx):
            for cz in range(self.nz):
                for k, (y, qi) in enumerate(self.floors[cx][cz]):
                    if (cx, cz, k) in blocked:
                        continue
                    near_wall = 99   # walls: the kart can't be there
                    near_edge = 99   # drops and holes: it can, but paths keep away
                    for dx in range(-4, 5):
                        for dz in range(-4, 5):
                            x2, z2 = cx + dx, cz + dz
                            if not (0 <= x2 < self.nx and 0 <= z2 < self.nz):
                                continue
                            dd = max(abs(dx), abs(dz))
                            if self._blocked(x2, z2, y):
                                near_wall = min(near_wall, dd)
                            elif not any(abs(y2 - y) < STEP for y2, _ in self.floors[x2][z2]):
                                near_edge = min(near_edge, dd)
                    if near_wall <= CLEAR:
                        continue
                    self.node[(cx, cz, k)] = len(self.pos)
                    px, pz = self.center(cx, cz)
                    self.pos.append((px, y, pz))
                    self.wall_dist.append(min(near_wall, near_edge + 1))

    def nearest(self, x, y, z):
        cx, cz = self.cell(x, z)
        best = None
        for r in range(0, 12):
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if max(abs(dx), abs(dz)) != r:
                        continue
                    for k, (fy, _) in enumerate(self.floors[cx + dx][cz + dz] if 0 <= cx + dx < self.nx and 0 <= cz + dz < self.nz else []):
                        nid = self.node.get((cx + dx, cz + dz, k))
                        if nid is None:
                            continue
                        d = math.hypot(dx, dz) * CELL + abs(fy - y) * 2
                        if best is None or d < best[0]:
                            best = (d, nid)
            if best:
                return best[1]
        return None

    def neighbours(self, nid):
        x, y, z = self.pos[nid]
        cx, cz = self.cell(x, z)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dz == 0:
                    continue
                x2, z2 = cx + dx, cz + dz
                if not (0 <= x2 < self.nx and 0 <= z2 < self.nz):
                    continue
                level = False
                for k, (y2, _) in enumerate(self.floors[x2][z2]):
                    if abs(y2 - y) < STEP:
                        level = True
                    m = self.node.get((x2, z2, k))
                    if m is None:
                        continue
                    if y2 - y > STEP:      # can't climb
                        continue
                    if y - y2 > MAX_DROP:  # too far to fall
                        continue
                    yield m, math.hypot(dx, dz) * CELL
                if level:
                    continue
                # an edge: the kart flies over it to a lower floor a few cells on
                for r in (2, 3):
                    x3, z3 = cx + dx * r, cz + dz * r
                    if not (0 <= x3 < self.nx and 0 <= z3 < self.nz):
                        break
                    for k, (y3, _) in enumerate(self.floors[x3][z3]):
                        m = self.node.get((x3, z3, k))
                        if m is not None and STEP <= y - y3 <= MAX_DROP:
                            yield m, math.hypot(dx, dz) * CELL * r

    def path(self, a, b):
        """A* from node a to node b; returns node ids."""
        tx, ty, tz = self.pos[b]
        openq = [(0, a)]
        g = {a: 0}
        came = {}
        while openq:
            _, n = heapq.heappop(openq)
            if n == b:
                out = [n]
                while n in came:
                    n = came[n]
                    out.append(n)
                return out[::-1]
            for m, cost in self.neighbours(n):
                pen = {1: 4.0, 2: 2.5, 3: 1.6, 4: 1.2}.get(self.wall_dist[m], 1.0)
                ng = g[n] + cost * pen
                if ng < g.get(m, 1e18):
                    g[m] = ng
                    came[m] = n
                    x, y, z = self.pos[m]
                    heapq.heappush(openq, (ng + math.hypot(x - tx, z - tz), m))
        return None


def simplify(points, tol=96.0):
    """Douglas-Peucker in xz."""
    pts = np.array(points, dtype=float)
    if len(pts) < 3:
        return pts.tolist()

    def rec(i, j):
        a, b = pts[i][[0, 2]], pts[j][[0, 2]]
        ab = b - a
        L = np.linalg.norm(ab)
        best, bi = 0, None
        for k in range(i + 1, j):
            p = pts[k][[0, 2]]
            # distance to the segment (to the point, for a closed loop)
            d = abs(np.cross(ab, p - a)) / L if L > 1e-6 else np.linalg.norm(p - a)
            if d > best:
                best, bi = d, k
        if best > tol:
            return rec(i, bi)[:-1] + rec(bi, j)
        return [i, j]
    return [pts[k].tolist() for k in rec(0, len(pts) - 1)]


def route_cells(g, path_nodes, radius):
    """Multi-source BFS from the route's grid nodes: node id -> (route position index, cells away),
    for every drivable cell-floor within `radius` cells of the route (through drivable cells)."""
    from collections import deque
    best = {}
    q = deque()
    for i, n in enumerate(path_nodes):
        if n not in best:
            best[n] = (i, 0)
            q.append(n)
    while q:
        n = q.popleft()
        i, d = best[n]
        if d >= radius:
            continue
        for m, _ in g.neighbours(n):
            if m not in best:
                best[m] = (i, d + 1)
                q.append(m)
    return best

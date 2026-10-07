"""Finds the steps and staircases of the Dust 2 model, in Hammer units.

A riser is a vertical face at most MAX_RISE tall; risers in one plane at the same heights
merge into a segment. Segments chain into a staircase when each next riser starts at the
height the last one ends, stands parallel behind it (within MAX_TREAD) and overlaps it
sideways. Each staircase becomes a ramp: from its foot (the first riser's line, pushed out
by one tread, or by RUN_PER_RISE for a single step) to its head (the last riser's top line).
"""
import math
import numpy as np

MAX_RISE = 24.0
MIN_RISE = 1.0
MAX_TREAD = 64.0
RUN_PER_RISE = 3.0   # a lone step gets a ramp 3x as long as it is tall


class Riser:
    def __init__(self, a, b, z0, z1, n):
        self.a = np.array(a, dtype=float)   # endpoints in xy
        self.b = np.array(b, dtype=float)
        self.z0, self.z1 = z0, z1           # bottom, top
        self.n = np.array(n, dtype=float)   # unit xy normal: points down the stairs (to the lower side)
        self.tris = []                      # triangle ids of the model

    @property
    def dir(self):
        d = self.b - self.a
        return d / (np.linalg.norm(d) + 1e-9)

    def offset(self):
        return float(np.dot(self.a, self.n))

    def lateral(self):
        t = self.dir
        s = sorted([float(np.dot(self.a, t)), float(np.dot(self.b, t))])
        return s


def find_risers(tris):
    """tris: list of (P (3,3) Hammer, n (3,) unit normal facing the player). Returns risers."""
    groups = {}
    for i, (P, n) in enumerate(tris):
        if abs(n[2]) > 0.05:
            continue
        z0, z1 = P[:, 2].min(), P[:, 2].max()
        h = z1 - z0
        if h < MIN_RISE or h > MAX_RISE:
            continue
        nxy = n[:2] / (np.linalg.norm(n[:2]) + 1e-9)
        key = (round(nxy[0], 2), round(nxy[1], 2), round(float(np.dot(P[0, :2], nxy)), 0), round(z0, 0), round(z1, 0))
        groups.setdefault(key, []).append(i)
    risers = []
    for (nx, ny, off, z0, z1), ids in groups.items():
        nxy = np.array([nx, ny])
        t = np.array([-ny, nx])
        # merge into contiguous lateral spans
        spans = []
        for i in ids:
            P = tris[i][0]
            s = [float(np.dot(p[:2], t)) for p in P]
            spans.append((min(s), max(s), i))
        spans.sort()
        cur = None
        for lo, hi, i in spans:
            if cur and lo <= cur[1] + 0.5:
                cur[1] = max(cur[1], hi)
                cur[2].append(i)
            else:
                if cur:
                    risers.append((cur, nxy, t, off, z0, z1))
                cur = [lo, hi, [i]]
        if cur:
            risers.append((cur, nxy, t, off, z0, z1))
    out = []
    for (lo, hi, ids), nxy, t, off, z0, z1 in risers:
        if hi - lo < 8:
            continue
        base = nxy * off
        r = Riser(base + t * lo, base + t * hi, z0, z1, nxy)
        r.tris = ids
        out.append(r)
    return out


def chain(risers):
    """Groups risers into staircases (lists ordered from the bottom up)."""
    nxt = {}
    for i, r in enumerate(risers):
        best = None
        for j, s in enumerate(risers):
            if i == j or abs(s.z0 - r.z1) > 0.6 or np.dot(s.n, r.n) < 0.99:
                continue
            # s stands behind r (up the stairs is -n)
            d = r.offset() - s.offset()
            if d < 4 or d > MAX_TREAD:
                continue
            a, b = r.lateral(), s.lateral()
            overlap = min(a[1], b[1]) - max(a[0], b[0])
            if overlap < 16:
                continue
            if best is None or d < best[0]:
                best = (d, j)
        if best:
            nxt[i] = best[1]
    has_prev = set(nxt.values())
    stairs = []
    for i in range(len(risers)):
        if i in has_prev:
            continue
        seq = [i]
        while seq[-1] in nxt and nxt[seq[-1]] not in seq:
            seq.append(nxt[seq[-1]])
        stairs.append([risers[k] for k in seq])
    return stairs


def ramp_for(stair):
    """Ramp quad (4 xyz points, Hammer): foot left, foot right, head right, head left."""
    first, last = stair[0], stair[-1]
    n = first.n
    t = first.dir
    lo = max(r.lateral()[0] for r in stair)
    hi = min(r.lateral()[1] for r in stair)
    if hi - lo < 8:
        lo, hi = first.lateral()
    if len(stair) > 1:
        tread = (first.offset() - last.offset()) / (len(stair) - 1)
    else:
        tread = (first.z1 - first.z0) * RUN_PER_RISE
    foot_off = first.offset() + tread
    head_off = last.offset()
    foot = [n * foot_off + t * lo, n * foot_off + t * hi]
    head = [n * head_off + t * hi, n * head_off + t * lo]
    return [np.array([foot[0][0], foot[0][1], first.z0]), np.array([foot[1][0], foot[1][1], first.z0]),
            np.array([head[0][0], head[0][1], last.z1]), np.array([head[1][0], head[1][1], last.z1])]


def floor_at(floors, x, y, z, tol=1.0):
    """True if a horizontal floor triangle at height z (within tol) covers (x, y)."""
    for P in floors:
        if abs(P[0, 2] - z) > tol:
            continue
        a, b, c = P[:, :2]
        v0, v1, d = b - a, c - a, np.array([x, y]) - a
        den = v0[0] * v1[1] - v0[1] * v1[0]
        if abs(den) < 1e-9:
            continue
        u = (d[0] * v1[1] - d[1] * v1[0]) / den
        v = (v0[0] * d[1] - v0[1] * d[0]) / den
        if u >= -1e-6 and v >= -1e-6 and u + v <= 1 + 1e-6:
            return True
    return False


def drivable_stairs(tris):
    """Staircases with a floor at the foot of the first riser and on top of the last one."""
    floors = [P for P, n in tris if n[2] > 0.99]
    out = []
    for st in chain(find_risers(tris)):
        first, last = st[0], st[-1]
        mid_a = (first.a + first.b) / 2
        mid_b = (last.a + last.b) / 2
        if not floor_at(floors, *(mid_a + first.n * 6), first.z0):
            continue
        if not floor_at(floors, *(mid_b - last.n * 6), last.z1):
            continue
        out.append(st)
    return out

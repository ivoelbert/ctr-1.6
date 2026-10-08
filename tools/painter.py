"""Which level faces the game paints over with faces behind them (painter.c does the work).

CTR has no depth buffer: a level face is filed into an ordering-table slot by its farthest
corner's depth >> 6 (the sub-faces of a face subdivided near the camera inherit its slot), and
the slots are painted far to near; faces in one slot are painted in reverse order of the
quadblocks' turn. A long face seen along its length sorts by its far end, so whatever sits
just behind its near part can get painted over it: on Dust 2, the A-site crates over the wall
of long A. audit() renders the level from chase-camera views over the drivable floor and
counts, per face, the pixels where it is in front but something behind it lands in a nearer
slot (painted later: an error) or the same one (a tie: it depends on the order).
"""
import math
import os
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from levwriter import build_bsp

HERE = os.path.dirname(os.path.abspath(__file__))
FACE_CORNERS = [(0, 4, 5, 6), (4, 1, 6, 7), (5, 6, 2, 8), (6, 7, 8, 3)]

# the 1P chase camera, from the game: 169 units behind the kart, 93 above it, looking 4.4
# degrees up; the view matrix's down row carries the screen's aspect (216 lines over 512)
CAM_BACK = 169.0
CAM_UP = 93.0
CAM_PITCH = math.asin(313 / 4096)
ASPECT = 2296 / 4096
# rendered at half the game's 512 x 216 (focal length 256)
WIDTH, HEIGHT, FOCAL = 256, 108, 128.0


def painter_binary(build_dir):
    exe = os.path.join(build_dir, 'painter')
    src = os.path.join(HERE, 'painter.c')
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        os.makedirs(build_dir, exist_ok=True)
        subprocess.run(['cc', '-O2', '-o', exe, src, '-lm'], check=True)
    return exe


def chase_views(g, start, every=4, headings=8):
    """(eye, 3x3 view matrix, anchor) for the chase camera behind a kart on every `every`th
    drivable grid cell reachable from `start`, facing `headings` ways."""
    ok = g.reachable(start)
    views = []
    cp, sp = math.cos(CAM_PITCH), math.sin(CAM_PITCH)
    for (cx, cz, _), nid in sorted(g.node.items()):
        if nid not in ok or cx % every or cz % every:
            continue
        x, y, z = g.pos[nid]
        for h in range(headings):
            a = 2 * math.pi * h / headings
            fx, fz = math.sin(a), math.cos(a)
            fwd = np.array([fx * cp, sp, fz * cp])
            right = np.array([-fz, 0.0, fx])
            down = np.cross(fwd, right) * ASPECT
            eye = np.array([x - fx * CAM_BACK, y + CAM_UP, z - fz * CAM_BACK])
            views.append((eye, np.array([right, down, fwd]), np.array([x, y + 40.0, z])))
    return views


def level_faces(quads, visible):
    """The drawn faces: (4 corners in PS1 order, quadblock index, face index, double-sided)."""
    faces = []
    for qi, q in enumerate(quads):
        for fi, corners in enumerate(FACE_CORNERS):
            if not visible(q, fi):
                continue
            P = [q.pos[c] for c in corners]
            if len({tuple(p) for p in P}) < 3:
                continue
            faces.append((P, qi, fi, q.double_sided))
    return faces


def audit(quads, views, build_dir, visible, near_first=False, max_leaf=6):
    """Per quadblock: [pixels where something behind it is painted over it from a nearer
    slot, from the same slot, pixels where it is painted over something in front of it,
    views with errors], and per view: (error pixels, same-slot error pixels) or None when its
    camera was inside something. near_first: the BSP walked near side first. The views are
    shared out among a painter process per CPU (every count is a sum over views)."""
    faces = level_faces(quads, visible)
    nodes, order = build_bsp(quads, max_leaf)
    turn = np.empty(len(quads), dtype=np.int64)
    turn[np.array(order)] = np.arange(len(order))
    body = bytearray()
    for P, qi, fi, ds in faces:
        body += struct.pack('<12f3i', *[float(c) for p in P for c in p], 0, 1 if ds else 0, int(turn[qi]))
    for n in nodes:
        if n['leaf']:
            body += struct.pack('<7i', 1, 0, 0, -1, -1, n['first'], n['count'])
        else:
            ax = max(range(3), key=lambda a: abs(n['axis'][a]))
            c = [-1 if x is None else x for x in n['children']]
            body += struct.pack('<7i', 0, ax, n['axis'][3], c[0], c[1], 0, 0)
    exe = painter_binary(build_dir)
    # PAINTER_VIEW=n (painter.c's dump of view n) numbers the views of one process
    jobs = 1 if os.environ.get('PAINTER_VIEW') else max(1, min(os.cpu_count() or 1, len(views)))

    def run(j):
        mine = range(j, len(views), jobs)
        buf = bytearray(struct.pack('<6if', len(faces), len(mine), WIDTH, HEIGHT, len(nodes), 1 if near_first else 0, FOCAL))
        buf += body
        for i in mine:
            eye, m, anchor = views[i]
            buf += struct.pack('<15f', *eye, *m.reshape(9), *anchor)
        return subprocess.run([exe], input=bytes(buf), capture_output=True, check=True).stdout

    with ThreadPoolExecutor(jobs) as pool:
        outs = list(pool.map(run, range(jobs)))
    per_face = np.zeros((len(faces), 4), dtype=np.int64)
    per_view = np.zeros((len(views), 2), dtype=np.int32)
    for j, out in enumerate(outs):
        per_face += np.frombuffer(out, dtype=np.uint32, count=4 * len(faces)).reshape(-1, 4)
        per_view[j::jobs] = np.frombuffer(out, dtype=np.int32, offset=16 * len(faces)).reshape(-1, 2)
    per_quad = np.zeros((len(quads), 4), dtype=np.int64)
    for (P, qi, fi, ds), row in zip(faces, per_face):
        per_quad[qi] += row
    return per_quad, [None if e < 0 else (int(e), int(t)) for e, t in per_view]

"""Which triangles a kart's camera can see at all (visible.c renders them with a depth buffer
from chase-camera views over the drivable floor): the rest can be left out of a level."""
import os
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from painter import FOCAL, HEIGHT, WIDTH

HERE = os.path.dirname(os.path.abspath(__file__))


def binary(build_dir):
    exe = os.path.join(build_dir, 'visible')
    src = os.path.join(HERE, 'visible.c')
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        os.makedirs(build_dir, exist_ok=True)
        subprocess.run(['cc', '-O2', '-o', exe, src, '-lm'], check=True)
    return exe


def visible_pixels(tris, normals, occludes, double, views, build_dir):
    """Pixels (summed over views, at half the game's resolution) where each triangle (CTR
    space, (m, 3, 3)) is the nearest thing: occludes says which hide what's behind them
    (cutouts don't), double which are seen from both sides."""
    flags = occludes.astype(np.int32) | (double.astype(np.int32) << 1)
    rec = np.zeros(len(tris), dtype=[('p', '<f4', 9), ('n', '<f4', 3), ('f', '<i4')])
    rec['p'] = tris.reshape(-1, 9)
    rec['n'] = normals
    rec['f'] = flags
    body = rec.tobytes()
    exe = binary(build_dir)
    jobs = max(1, min(os.cpu_count() or 1, len(views)))

    def run(j):
        mine = views[j::jobs]
        buf = bytearray(struct.pack('<4if', len(tris), len(mine), WIDTH, HEIGHT, FOCAL)) + body
        for eye, m, _ in mine:
            buf += struct.pack('<12f', *eye, *m.reshape(9))
        return subprocess.run([exe], input=bytes(buf), capture_output=True, check=True).stdout

    with ThreadPoolExecutor(jobs) as pool:
        outs = list(pool.map(run, range(jobs)))
    return sum(np.frombuffer(o, dtype=np.uint32).astype(np.int64) for o in outs)

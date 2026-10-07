"""Plans a route through landmarks on the nav grid and draws it.

  python3 -I tools/route.py LEV "landmark landmark ..." OUT.png [WAYPOINTS.json]

Prints the path as Hammer waypoints (for tools/e2e/autopilot.mjs) and writes them, with
the full CTR path, to WAYPOINTS.json.
"""
import json
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from navgrid import NavGrid, simplify  # noqa: E402


def load_grid(lev):
    cache = 'build/navgrid.pkl'
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(lev):
        return pickle.load(open(cache, 'rb'))
    g = NavGrid(lev)
    pickle.dump(g, open(cache, 'wb'))
    return g


def plan(g, names, landmarks):
    full = []
    for a, b in zip(names, names[1:]):
        la, lb = landmarks[a], landmarks[b]
        na = g.nearest(la[0], la[1] or 0, la[2])
        nb = g.nearest(lb[0], lb[1] or 0, lb[2])
        p = g.path(na, nb)
        if p is None:
            raise SystemExit(f'no path {a} -> {b}')
        pts = [g.pos[n] for n in p]
        full.extend(pts if not full else pts[1:])
    return full


def main():
    lev, names, out = sys.argv[1], sys.argv[2].split(), sys.argv[3]
    meta = json.load(open('build/lev/dust2.json'))
    S, (CX, CY) = meta['scale'], meta['center']
    g = load_grid(lev)
    full = plan(g, names, meta['landmarks'])
    simple = simplify(full, 96)
    hammer = [(round(x / S + CX), round(CY - z / S)) for x, y, z in simple]
    print('length', round(sum(((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5 for a, b in zip(full, full[1:]))), 'units,', len(simple), 'waypoints')
    print(' '.join(f'{x},{y}' for x, y in hammer))
    if len(sys.argv) > 4:
        json.dump(dict(names=names, path=full, waypoints=simple, hammer=hammer), open(sys.argv[4], 'w'))
    tmp = 'build/route_trace.txt'
    with open(tmp, 'w') as f:
        for i, (x, y, z) in enumerate(full):
            f.write(f'{i}\t{x}\t{y}\t{z}\n')
    os.system(f"python3 -I tools/floor_map.py {lev} {out} \"{' '.join(f'{x},{y}' for x, y in hammer)}\" {tmp}")


if __name__ == '__main__':
    main()

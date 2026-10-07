"""Which faces of a level can be seen from behind from where the karts go.

The Dust 2 model is drawn double-sided (its materials say so), so it has faces that only look
right from one side and are seen from the other in places: around the doors, where the leaves
were taken out. CTR culls back faces (and collides on one side only), so such a face is a hole.
exposed_backfaces() casts rays from points over the drivable cells reachable from the start and
returns the triangles some ray hits first from behind.
"""
from collections import deque

import numpy as np


def reachable(g, start):
    """Nav grid node ids reachable from `start` by driving (BFS over the grid's links)."""
    seen = {start}
    dq = deque([start])
    while dq:
        n = dq.popleft()
        for m, _ in g.neighbours(n):
            if m not in seen:
                seen.add(m)
                dq.append(m)
    return seen


def exposed_backfaces(P, N, g, start, every=3, heights=(160,), rays=96, reach=6000.0, seed=1):
    """P: (T, 3, 3) triangle corners and N: (T, 3) their front normals, level units. Returns
    {triangle: (front hits, back hits)} for the triangles some ray hits first from behind."""
    P = np.asarray(P, dtype=np.float32)
    N = np.asarray(N, dtype=np.float32)
    v0 = P[:, 0]
    e1 = P[:, 1] - P[:, 0]
    e2 = P[:, 2] - P[:, 0]
    centre = P.mean(axis=1)
    radius = np.linalg.norm(P - centre[:, None, :], axis=2).max(axis=1)

    rng = np.random.default_rng(seed)
    D = rng.normal(size=(rays, 3))
    D[:, 1] *= 0.5            # a chase camera looks around more than up or down
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    D = D.astype(np.float32)

    ok = reachable(g, start)
    views = []
    for (cx, cz, _), nid in g.node.items():
        if nid in ok and cx % every == 0 and cz % every == 0:
            x, y, z = g.pos[nid]
            for h in heights:
                views.append((x, y + h, z))

    front = np.zeros(len(P), dtype=np.int64)
    back = np.zeros(len(P), dtype=np.int64)
    for o in np.asarray(views, dtype=np.float32):
        sel = np.nonzero(np.linalg.norm(centre - o, axis=1) < reach + radius)[0]
        if len(sel) == 0:
            continue
        a, b, c = v0[sel], e1[sel], e2[sel]
        pvec = np.cross(D[:, None, :], c[None, :, :])                  # (R, S, 3)
        det = np.einsum('sk,rsk->rs', b, pvec)
        with np.errstate(divide='ignore', invalid='ignore'):
            inv = 1.0 / det
            tvec = o[None, :] - a                                       # (S, 3)
            u = np.einsum('sk,rsk->rs', tvec, pvec) * inv
            qvec = np.cross(tvec, b)                                    # (S, 3)
            v = (D @ qvec.T) * inv
            t = np.einsum('sk,sk->s', c, qvec)[None, :] * inv
        hit = (np.abs(det) > 1e-6) & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1.0) & (t < reach)
        t = np.where(hit, t, np.inf)
        first = np.argmin(t, axis=1)
        rows = np.nonzero(np.isfinite(t[np.arange(len(D)), first]))[0]
        k = sel[first[rows]]
        facing = np.einsum('rk,rk->r', D[rows], N[k])
        np.add.at(front, k[facing < 0], 1)
        np.add.at(back, k[facing >= 0], 1)
    return {int(k): (int(front[k]), int(back[k])) for k in np.nonzero(back)[0]}

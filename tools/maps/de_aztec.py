"""de_aztec: the river and the pool are water to drive through, and the rope bridge holds."""
import numpy as np

import goldsrc
import track

TITLE = 'Aztec'
SKY = [(110, 125, 135, 1), (165, 170, 160, 1), (130, 140, 150, 1)]   # overcast: Aztec is rainy
# The tops of the walls (z 192), which no one sees in Counter-Strike, are a 16-pixel barrel
# texture that reads as flat yellow from a kart on higher ground: the walls' stone instead.
TEXTURE_SWAP = {'barrel2b': '-1AzWll'}
TEXTURE_DENSITY = {'barrel2b': 0.25}
WATER_Z = -528          # the river's surface

# The rope bridge over the river is decor (func_illusionary): Counter-Strike's players walk on
# clip brushes under its planks, and clip fills its rails down to the deck. Here an invisible
# floor along the planks' tops, in the three planes of the beams under them (map x, z), across
# its width (map y); and invisible walls, facing the deck, under its rails (map y of the rail's
# inner side, x from and to, z of the rail's top). Where the rails are broken, the river is a
# long way down.
BRIDGE_DECK = [(-1024, -192), (-832, -208), (-480, -208), (-256, -192)]
BRIDGE_Y = (640, 768)
BRIDGE_RAILS = [(644, -1008, -892, -163), (644, -818, -590, -180), (764, -596, -480, -176)]
RAIL_ABOVE = 16         # map units over the rail's top: a hopping kart doesn't clear it


def deck_z(x):
    """The bridge deck's height (map units) at map x."""
    xs, zs = zip(*BRIDGE_DECK)
    return float(np.interp(x, xs, zs))


def extra_quads(bsp, sel, charts, out):
    """The bridge's invisible deck and rail walls, as stair ramps are made. The deck takes the
    light on the planks for the kart's shade."""
    y0, y1 = BRIDGE_Y
    first = len(out)
    for (xa, za), (xb, zb) in zip(BRIDGE_DECK, BRIDGE_DECK[1:]):
        track.emit_ramp([(xa, y0, za), (xa, y1, za), (xb, y1, zb), (xb, y0, zb)], out)
    deck = out[first:]
    for y, xa, xb, top in BRIDGE_RAILS:
        bottom = min(deck_z(xa), deck_z(xb)) - 8
        quad = [(xa, y, bottom), (xb, y, bottom), (xb, y, top + RAIL_ABOVE), (xa, y, top + RAIL_ABOVE)]
        # emit_ramp faces (B - A) x (D - A), map -y when x grows along A B: turned to the deck
        if (y < (y0 + y1) / 2) == (xb > xa):
            quad = quad[::-1]
        track.emit_ramp(quad, out)
    planks = []
    for fi, kind in sel:
        p = bsp.face_points(fi)
        lo, hi = p.min(axis=0), p.max(axis=0)
        if (kind == 'decor' and fi in charts and bsp.face_normal(fi)[2] > 0.7 and lo[0] >= BRIDGE_DECK[0][0]
                and hi[0] <= BRIDGE_DECK[-1][0] and lo[1] >= y0 and hi[1] <= y1
                and abs(p[:, 2].mean() - deck_z(p[:, 0].mean())) < 4):
            planks.append((fi, lo, hi))
    if not planks:
        raise SystemExit('no bridge planks: has the map changed?')
    centers = np.array([(lo[:2] + hi[:2]) / 2 for _, lo, hi in planks])
    for q in deck:
        q.color = []
        for x, _, z in q.pos:
            hx, hy = x / track.SCALE + track.CENTER[0], -z / track.SCALE + track.CENTER[1]
            fi, lo, hi = planks[int(np.argmin(np.abs(centers - (hx, hy)).sum(axis=1)))]
            n = bsp.face_normal(fi)
            p0 = bsp.face_points(fi)[0]
            px, py = np.clip(hx, lo[0] + 1, hi[0] - 1), np.clip(hy, lo[1] + 1, hi[1] - 1)
            pz = p0[2] - (n[0] * (px - p0[0]) + n[1] * (py - p0[1])) / n[2]
            q.color.append(track.floor_shade(charts[fi].layer, charts[fi].uv(bsp, fi, [(px, py, pz)])[0]))
    print(f'the bridge: {len(deck)} deck and {len(out) - first - len(deck)} rail quadblocks, on {len(planks)} planks')


def split_face(pts, n):
    """The walls under the landings that face the bridge are only drawn across its width: their
    top edge is the deck's end, and a kart (which rides a hair below a floor) leaving the bridge
    ran into it."""
    for (x, z), facing in ((BRIDGE_DECK[0], 1), (BRIDGE_DECK[-1], -1)):
        if (n[0] * facing > 0.99 and np.all(np.abs(pts[:, 0] - x) < 0.5) and abs(pts[:, 2].max() - z) < 0.5
                and pts[:, 1].min() < BRIDGE_Y[1] and pts[:, 1].max() > BRIDGE_Y[0]):
            y0, y1 = BRIDGE_Y
            middle = goldsrc.clip_polygon(pts, 1, y0, False)
            middle = None if middle is None else goldsrc.clip_polygon(middle, 1, y1, True)
            pieces = [(goldsrc.clip_polygon(pts, 1, y0, True), True), (middle, False),
                      (goldsrc.clip_polygon(pts, 1, y1, False), True)]
            pieces = [(p, s) for p, s in pieces if p is not None]
            return [p for p, _ in pieces], [s for _, s in pieces]
    return None

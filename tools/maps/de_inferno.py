"""de_inferno, as Counter-Strike has it."""

TITLE = 'Inferno'
SKY = [(150, 185, 225, 1), (235, 215, 175, 1), (190, 210, 235, 1)]   # a clear Italian summer
DENSITY = 0.93          # its many walls take 70 atlas layers at 1.0: 59 of the 63

import numpy as np

import track

# CT spawn's two ramps up to the platform by the lamp post side by side: the left one (map x
# 1952-2224) climbs to the platform at z 128, the right one, a little flatter, runs into the
# wooden wall at z 120. Between them a sloped ledge (the left ramp's side, 3-8 units over the
# right one) stops the kart; Counter-Strike's players just step it. An invisible floor over
# the right ramp's last 48 units tilts it up to the left ramp's edge, and the ledge's wall
# doesn't collide.
LEDGE_X = 2224
BRIDGE_X = 2272
RAMP_Y = (2496, 2624)


def left_ramp_z(y):
    return 80 + (y - 2496) * 48 / 128


def right_ramp_z(y):
    return 80 + max(y - 2504, 0) * 40 / 120


def extra_quads(bsp, sel, charts, out):
    y0, y1 = RAMP_Y
    track.emit_ramp([(LEDGE_X, y0, left_ramp_z(y0)), (BRIDGE_X, y0, right_ramp_z(y0)),
                     (BRIDGE_X, y1, right_ramp_z(y1)), (LEDGE_X, y1, left_ramp_z(y1))], out)


def split_face(pts, n):
    y0, y1 = RAMP_Y
    if (n[0] > 0.99 and np.all(np.abs(pts[:, 0] - LEDGE_X) < 0.5) and abs(pts[:, 1].min() - y0) < 0.5
            and abs(pts[:, 1].max() - y1) < 0.5 and pts[:, 2].max() <= 128.5):
        return [pts], [False]
    return None

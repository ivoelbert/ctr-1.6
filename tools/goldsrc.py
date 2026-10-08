"""Reads GoldSrc maps (Half-Life, Counter-Strike 1.6: BSP version 30) and bakes them for CTR.

A map file holds the world (brush model 0) and the brush entities (models 1..n: func_wall,
func_breakable, func_water...) as convex polygons ("faces"), each with a texture mapping
(texinfo: s and t axes with offsets, in texels), the textures themselves (8-bit with a palette;
a map built without -wadinclude leaves them in WAD files, see Wad) and the baked light: per face,
a grid of RGB samples every 16 texels over the face's texture extent, one grid per light style.
The entities lump is the editor's key/value text ({"classname" "func_wall" "model" "*3" ...}).

bake() turns faces into what tools/build_dust2.py's pipeline takes: every face gets its own
chart in 1024 x 1024 atlas layers, filled with its texture times its light, as the game draws
it, so the level carries CS 1.6's lighting the way the Dust 2 model's baked textures did.
"""
import math
import re
import struct

import numpy as np

LUMPS = ['entities', 'planes', 'textures', 'vertices', 'visibility', 'nodes', 'texinfo', 'faces',
         'lighting', 'clipnodes', 'leaves', 'marksurfaces', 'edges', 'surfedges', 'models']
PLANE = np.dtype([('n', '<f4', 3), ('d', '<f4'), ('type', '<i4')])
TEXINFO = np.dtype([('s', '<f4', 4), ('t', '<f4', 4), ('miptex', '<i4'), ('flags', '<i4')])
FACE = np.dtype([('plane', '<u2'), ('side', '<u2'), ('firstedge', '<i4'), ('numedges', '<u2'),
                 ('texinfo', '<u2'), ('styles', 'u1', 4), ('lightofs', '<i4')])
MODEL = np.dtype([('mins', '<f4', 3), ('maxs', '<f4', 3), ('origin', '<f4', 3), ('headnode', '<i4', 4),
                  ('visleafs', '<i4'), ('firstface', '<i4'), ('numfaces', '<i4')])

# textures the compile tools or the engine never draw
TOOL_TEXTURES = {'sky', 'aaatrigger', 'clip', 'origin', 'null', 'skip', 'hint', 'bevel', 'clipbevel', 'clipsight'}


def parse_entities(text):
    ents = []
    cur = None
    for m in re.finditer(r'\{|\}|"([^"]*)"\s*"([^"]*)"', text):
        tok = m.group(0)
        if tok == '{':
            cur = {}
        elif tok == '}':
            if cur is not None:
                ents.append(cur)
            cur = None
        elif cur is not None:
            cur[m.group(1)] = m.group(2)
    return ents


def decode_miptex(data, offset, palette=None):
    """(name, RGBA uint8 array) of a miptex at `offset`; None for the pixels when they live in a
    WAD. '{' textures (alpha tested) show palette index 255 as clear."""
    name = data[offset:offset + 16].split(b'\0')[0].decode('latin1')
    w, h = struct.unpack_from('<II', data, offset + 16)
    mips = struct.unpack_from('<4I', data, offset + 24)
    if mips[0] == 0:
        return name, (w, h), None
    pix = np.frombuffer(data, np.uint8, w * h, offset + mips[0]).reshape(h, w)
    if palette is None:
        end = offset + mips[3] + (w // 8) * (h // 8)
        count = struct.unpack_from('<H', data, end)[0]
        palette = np.frombuffer(data, np.uint8, 3 * count, end + 2).reshape(count, 3)
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., :3] = palette[pix]
    rgba[..., 3] = 255
    if name.startswith('{'):
        rgba[pix == 255, 3] = 0
    return name, (w, h), rgba


class Wad:
    """A WAD3 texture file: {lower-case name: RGBA}."""

    def __init__(self, data):
        if data[:4] != b'WAD3':
            raise ValueError('not a WAD3 file')
        n, off = struct.unpack_from('<ii', data, 4)
        self.textures = {}
        for i in range(n):
            e = off + 32 * i
            pos, disk, size, typ, comp = struct.unpack_from('<iiibb', data, e)
            name = data[e + 16:e + 32].split(b'\0')[0].decode('latin1')
            if typ == 0x43 and not comp:   # miptex
                tname, _, rgba = decode_miptex(data, pos)
                if rgba is not None:
                    self.textures[name.lower()] = rgba


class Bsp:
    def __init__(self, data, wads=()):
        version = struct.unpack_from('<i', data, 0)[0]
        if version != 30:
            raise ValueError(f'BSP version {version}: not a GoldSrc map (30)')
        self.lump = {}
        for i, name in enumerate(LUMPS):
            off, length = struct.unpack_from('<ii', data, 4 + 8 * i)
            self.lump[name] = data[off:off + length]
        self.entities = parse_entities(self.lump['entities'].decode('latin1'))
        self.planes = np.frombuffer(self.lump['planes'], PLANE)
        self.vertices32 = np.frombuffer(self.lump['vertices'], '<f4').reshape(-1, 3)
        self.vertices = self.vertices32.astype(np.float64)
        self.edges = np.frombuffer(self.lump['edges'], '<u2').reshape(-1, 2)
        self.surfedges = np.frombuffer(self.lump['surfedges'], '<i4')
        self.texinfo = np.frombuffer(self.lump['texinfo'], TEXINFO)
        self.faces = np.frombuffer(self.lump['faces'], FACE)
        self.models = np.frombuffer(self.lump['models'], MODEL)
        self.lighting = np.frombuffer(self.lump['lighting'], np.uint8)
        # textures: embedded, else from the WADs
        tl = self.lump['textures']
        n = struct.unpack_from('<i', tl, 0)[0]
        offs = struct.unpack_from('<%di' % n, tl, 4)
        self.textures = []      # (name, (w, h), RGBA or None)
        lookup = {}
        for w in wads:
            lookup.update(w.textures)
        for o in offs:
            if o < 0:
                self.textures.append(('', (16, 16), None))
                continue
            name, size, rgba = decode_miptex(tl, o)
            if rgba is None:
                rgba = lookup.get(name.lower())
            self.textures.append((name, size, rgba))

    # the entities that own each brush model ('*3' -> 3); model 0 is the world
    def model_entities(self):
        out = {0: self.entities[0]}
        for e in self.entities:
            m = e.get('model', '')
            if m.startswith('*'):
                out[int(m[1:])] = e
        return out

    def face_points(self, fi):
        f = self.faces[fi]
        se = self.surfedges[f['firstedge']:f['firstedge'] + f['numedges']]
        idx = np.where(se >= 0, self.edges[np.abs(se), 0], self.edges[np.abs(se), 1])
        return self.vertices[idx]

    def face_normal(self, fi):
        f = self.faces[fi]
        n = self.planes[f['plane']]['n'].astype(np.float64)
        return -n if f['side'] else n

    def face_texture(self, fi):
        return self.textures[self.texinfo[self.faces[fi]['texinfo']]['miptex']]

    def face_st(self, fi, pts):
        ti = self.texinfo[self.faces[fi]['texinfo']]
        s = pts @ ti['s'][:3].astype(np.float64) + float(ti['s'][3])
        t = pts @ ti['t'][:3].astype(np.float64) + float(ti['t'][3])
        return s, t

    def light_extents(self, fi):
        """The face's light grid: (first sample's s, t on the 16-texel grid, columns, rows). As
        the engine's CalcSurfaceExtents: each texture coordinate is summed in double precision
        from the file's floats and stored as a float (the x87 code it was built as), which
        decides the grid size when a corner sits right on a multiple of 16."""
        f = self.faces[fi]
        se = self.surfedges[f['firstedge']:f['firstedge'] + f['numedges']]
        idx = np.where(se >= 0, self.edges[np.abs(se), 0], self.edges[np.abs(se), 1])
        v = self.vertices32[idx].astype(np.float64)
        ti = self.texinfo[f['texinfo']]
        out = []
        for ax in ('s', 't'):
            vec = ti[ax].astype(np.float64)
            val = (v[:, 0] * vec[0] + v[:, 1] * vec[1] + v[:, 2] * vec[2] + vec[3]).astype(np.float32)
            lo = math.floor(float(val.min()) / 16)
            hi = math.ceil(float(val.max()) / 16)
            out.append((lo, hi))
        (bs0, bs1), (bt0, bt1) = out
        return bs0 * 16, bt0 * 16, bs1 - bs0 + 1, bt1 - bt0 + 1

    def face_light(self, fi):
        """(RGB float grid (h, w, 3), s0, t0): the face's light, every 16 texels from texture
        coordinates (s0, t0), styles summed; None when the face has none (water, sky)."""
        f = self.faces[fi]
        if f['lightofs'] < 0:
            return None
        s0, t0, w, h = self.light_extents(fi)
        styles = [x for x in f['styles'] if x != 255]
        size = w * h * 3
        light = np.zeros((h, w, 3), np.float64)
        for k, _ in enumerate(styles):
            o = f['lightofs'] + k * size
            if o + size > len(self.lighting):
                break
            light += self.lighting[o:o + size].reshape(h, w, 3)
        return light, s0, t0


def _sample_light(light, s0, t0, s, t):
    """Bilinear light at texture coordinates (s, t) (arrays): samples sit every 16 texels."""
    h, w, _ = light.shape
    x = np.clip((s - s0) / 16.0, 0, w - 1)
    y = np.clip((t - t0) / 16.0, 0, h - 1)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    top = light[y0, x0] * (1 - fx) + light[y0, x1] * fx
    bot = light[y1, x0] * (1 - fx) + light[y1, x1] * fx
    return top * (1 - fy) + bot * fy


class Chart:
    """Where a face went in the atlas: its layer, and texel = st * scale + origin, where st are the
    face's texture coordinates (Bsp.face_st)."""

    def __init__(self, layer, origin, scale):
        self.layer = layer
        self.origin = origin
        self.scale = scale

    def uv(self, bsp, fi, pts):
        """Atlas texels (n, 2) of map points on face fi."""
        s, t = bsp.face_st(fi, np.asarray(pts, dtype=np.float64))
        return np.stack([s * self.scale[0] + self.origin[0], t * self.scale[1] + self.origin[1]], axis=1)


class Packer:
    """Shelf packing of rectangles into square layers."""

    def __init__(self, size, first_layer):
        self.size = size
        self.layer = first_layer
        self.x = self.y = self.row_h = 0

    def place(self, w, h):
        if w > self.size or h > self.size:
            raise ValueError(f'chart {w}x{h} larger than a layer')
        if self.x + w > self.size:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        if self.y + h > self.size:
            self.layer += 1
            self.x = self.y = self.row_h = 0
        at = (self.layer, self.x, self.y)
        self.x += w
        self.row_h = max(self.row_h, h)
        return at


# Light to brightness, fitted to the Dust 2 model built from the same lightmaps (its colours over
# the texture's, at 10,000 matched points): about light / 116, GoldSrc's overbright lightmaps.
# Shadows (a multiplier under 1) are lifted SHADOW_LIFT of the way to the plain texture: Dust 2's
# dark corners read as too dark at CTR's size.
LIGHT_GAIN = 2.2
LIGHT_GAMMA = 1.05
SHADOW_LIFT = 0.15


def light_multiplier(light, gain=LIGHT_GAIN, gamma=LIGHT_GAMMA, lift=SHADOW_LIFT):
    """Texture multiplier for light values (0..255 a style, styles summed)."""
    m = np.power(np.clip(light / 255.0 * gain, 0, None), 1.0 / gamma)
    return np.where(m < 1.0, m + lift * (1.0 - m), m)


def bake(bsp, faces, density=0.5, layer_size=1024, first_layer=1, pad=2, supersample=3,
         gain=LIGHT_GAIN, gamma=LIGHT_GAMMA, lift=SHADOW_LIFT, fullbright=1.0, density_of=None):
    """Atlas charts for `faces` (face indices): each face's texture times its light, at `density`
    chart texels per map unit (or density_of(face), when that's given and not None), the light
    turned into a texture multiplier by light_multiplier; faces without light (water) take the
    multiplier `fullbright`. Returns (charts {face: Chart}, layers {layer: RGB uint8}, light
    {layer: float32 luminance of the multiplier: 1 shows the plain texture}, alpha {layer: bool
    mask of clear texels, for '{' textures})."""
    jobs = []
    for fi in faces:
        pts = bsp.face_points(fi)
        s, t = bsp.face_st(fi, pts)
        ti = bsp.texinfo[bsp.faces[fi]['texinfo']]
        ls = float(np.linalg.norm(ti['s'][:3]))
        lt = float(np.linalg.norm(ti['t'][:3]))
        if ls < 1e-6 or lt < 1e-6:
            continue
        d = density if density_of is None or density_of(fi) is None else density_of(fi)
        ks, kt = d / ls, d / lt                      # chart texels per texture texel
        w = math.ceil((s.max() - s.min()) * ks) + 2 * pad
        h = math.ceil((t.max() - t.min()) * kt) + 2 * pad
        fit = min(1.0, (layer_size - 2 * pad) / max(w, h))
        if fit < 1.0:
            ks, kt = ks * fit, kt * fit
            w = math.ceil((s.max() - s.min()) * ks) + 2 * pad
            h = math.ceil((t.max() - t.min()) * kt) + 2 * pad
        jobs.append((fi, pts, s, t, ks, kt, w, h))
    jobs.sort(key=lambda j: (-j[7], -j[6]))
    packer = Packer(layer_size, first_layer)
    charts = {}
    layers = {}
    light_layers = {}
    alpha = {}
    sub = (np.arange(supersample) + 0.5) / supersample
    for fi, pts, s, t, ks, kt, w, h in jobs:
        layer, x0, y0 = packer.place(w, h)
        if layer not in layers:
            layers[layer] = np.zeros((layer_size, layer_size, 3), np.float32)
            light_layers[layer] = np.zeros((layer_size, layer_size), np.float32)
            alpha[layer] = np.zeros((layer_size, layer_size), bool)
        smin, tmin = s.min(), t.min()
        charts[fi] = Chart(layer, (x0 + pad - smin * ks, y0 + pad - tmin * kt), (ks, kt))
        # texture coordinates of each chart texel's sub-samples
        gx = (np.arange(w)[None, :, None, None] + sub[None, None, None, :] - pad) / ks + smin
        gy = (np.arange(h)[:, None, None, None] + sub[None, None, :, None] - pad) / kt + tmin
        S = np.broadcast_to(gx, (h, w, supersample, supersample))
        T = np.broadcast_to(gy, (h, w, supersample, supersample))
        name, (tw, th), rgba = bsp.face_texture(fi)
        if rgba is None:
            tex = np.full((h, w, supersample, supersample, 4), 128.0)
            tex[..., 3] = 255
        else:
            tex = rgba[np.floor(T).astype(int) % rgba.shape[0], np.floor(S).astype(int) % rgba.shape[1]].astype(np.float32)
        lit = bsp.face_light(fi)
        if lit is None:
            mul = np.full((h, w, 1), float(fullbright))
            lum = np.full((h, w), float(fullbright), np.float32)
        else:
            grid, s0, t0 = lit
            L = _sample_light(grid, s0, t0, S.mean(axis=(2, 3)), T.mean(axis=(2, 3)))
            mul = light_multiplier(L, gain, gamma, lift)
            lum = (0.299 * mul[..., 0] + 0.587 * mul[..., 1] + 0.114 * mul[..., 2]).astype(np.float32)
        a = tex[..., 3:4] / 255.0
        rgb = (tex[..., :3] * a).sum(axis=(2, 3)) / np.maximum(a.sum(axis=(2, 3)), 1e-6)
        layers[layer][y0:y0 + h, x0:x0 + w] = rgb * mul
        light_layers[layer][y0:y0 + h, x0:x0 + w] = lum
        alpha[layer][y0:y0 + h, x0:x0 + w] = a.mean(axis=(2, 3))[..., 0] < 0.5
    out = {k: np.clip(v + 0.5, 0, 255).astype(np.uint8) for k, v in layers.items()}
    return charts, out, light_layers, alpha

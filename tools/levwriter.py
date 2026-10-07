"""Writes CTR level files (LEV) from quadblocks: engine/include/namespace_Level.h.

The file is u32 dataSize, the level data, then the pointer map (u32 byte count and the
offsets of every pointer slot). Pointers are written as offsets into the data; the game's
LOAD_RunPtrMap adds the load address to each slot in the map. Null pointers stay 0 and
stay out of the map.

What gets written:
  - the Level header, mesh_info, quadblocks (with their bounding boxes and the per-triangle
    normal dividends COLL uses), vertices, a BSP tree over the quadblocks,
  - one PVS that sees everything, and the VisMem buffers the game copies it into,
  - texture layouts (IconGroup4) per quadblock face,
  - checkpoint nodes, driver spawns, an empty SpawnType1 and an empty texture lookup.
"""
import math
import struct
from dataclasses import dataclass, field

QUAD_SIZE = 0x5C
VERT_SIZE = 0x10
BSP_SIZE = 0x20
LEVEL_SIZE = 0x1F4

FLAG_GROUND = 0x1000
FLAG_CAMERA_SEARCH = 0x0800
FLAG_COLLISION_SURFACE = 0x2000
FLAG_NO_CAMERA_RESPAWN_PROBE = 0x4000

# Hi-LOD triangles as COLL tests them (COLL_FIXED_QUADBLK_GetNormVecs_HiLOD), then low LOD.
HI_TRIS = [(0, 4, 5), (4, 6, 5), (6, 4, 1), (5, 6, 2), (8, 6, 7), (7, 3, 8), (1, 7, 6), (2, 6, 8)]
LO_TRIS = [(0, 1, 2), (1, 3, 2)]

# Face corners in TextureLayout order (u0v0, u1v1, u2v2, u3v3) for draw-order face flags 0
# (226's 4x1 selectors: 0x00506478, 0x5014788c, 0x647828a0, 0x788ca03c).
FACE_CORNERS = [(0, 4, 5, 6), (4, 1, 6, 7), (5, 6, 2, 8), (6, 7, 8, 3)]


@dataclass
class TexLayout:
    """One PSX texture layout: per-corner (u, v) in a 256x256 page, a CLUT and a tpage."""
    uv: tuple  # ((u0,v0),(u1,v1),(u2,v2),(u3,v3))
    clut: int
    tpage: int

    def pack(self):
        (u0, v0), (u1, v1), (u2, v2), (u3, v3) = self.uv
        return struct.pack('<BBHBBHBBBB', u0, v0, self.clut, u1, v1, self.tpage, u2, v2, u3, v3)


@dataclass
class Quad:
    """A quadblock. pos: 9 vertex positions (CTR ints) in the 3x3 order
         0 4 1
         5 6 7
         2 8 3
    For a triangle quadblock pass corners 0,1,2 and midpoints 4 (0-1), 5 (0-2), 6 (1-2);
    slots 3, 7, 8 then repeat 2, 6, 2 as in Naughty Dog's files.
    faces: 4 TexLayouts (or None for an invisible face), low: TexLayout for the far LOD."""
    pos: list
    faces: list
    low: object
    color: list = None          # 9 (r,g,b) or 8-byte (hi rgba + lo rgba) vertex colors; default neutral 0x80
    flags: int = FLAG_COLLISION_SURFACE
    terrain: int = 0
    checkpoint: int = 0xFF
    double_sided: bool = False
    triangle: bool = False
    draw_order_low: int = None  # raw value (face flags, draw order); None = 0 + double-sided bit
    draw_order_high: int = 0


@dataclass
class Node:
    pos: tuple
    dist_to_finish: int  # in units of 8 (the game shifts it left by 3)
    forward: int
    backward: int
    left: int = 0xFF
    right: int = 0xFF


@dataclass
class Level:
    quads: list
    nodes: list = field(default_factory=list)
    spawns: list = field(default_factory=list)  # 8 x ((x,y,z),(rx,ry,rz))
    clear_colors: list = field(default_factory=lambda: [(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)])
    config_flags: int = 0
    glow: list = None
    build_name: str = 'Dust 2'
    max_leaf_quads: int = 6
    bsp: tuple = None  # (nodes, order) to use instead of building one (tests)
    nav_paths: list = field(default_factory=list)  # up to 3 lists of NavFrame dicts (AI racing lines)
    # Graft onto a retail level: its data stays (models, skybox, textures, animated textures)
    # and the header is repointed at this level's mesh, checkpoints, AI paths and instances.
    base: object = None          # a ctrlev.Lev
    instances: list = field(default_factory=list)  # dicts: src (index in base InstDefs), pos, rot
    # pickups the karts touch through BSP leaf hitbox lists: dicts inst (index in instances),
    # radius, lift (hitbox centre above the instance), flags
    hitboxes: list = field(default_factory=list)
    flyin: int = None   # data offset (in the base) of a start-line fly-in camera path
    icons: list = field(default_factory=list)  # (name, global index, TexLayout)
    icon_groups: list = field(default_factory=list)  # (name, groupID, [icon indices])


class Blob:
    def __init__(self):
        self.buf = bytearray()
        self.ptr_slots = []

    def alloc(self, size, align=4):
        pad = (-len(self.buf)) % align
        self.buf += b'\0' * pad
        off = len(self.buf)
        self.buf += b'\0' * size
        return off

    def put(self, off, fmt, *vals):
        struct.pack_into('<' + fmt, self.buf, off, *vals)

    def ptr(self, slot, target):
        """A pointer at `slot` to data offset `target` (None = null, and out of the map)."""
        if target is None:
            self.put(slot, 'I', 0)
            self.ptr_slots = [s for s in self.ptr_slots if s != slot]
            return
        self.put(slot, 'I', target)
        self.ptr_slots.append(slot)

    def finish(self):
        pad = (-len(self.buf)) % 4
        self.buf += b'\0' * pad
        slots = sorted(set(self.ptr_slots))
        out = bytearray(struct.pack('<I', len(self.buf)))
        out += self.buf
        out += struct.pack('<I', 4 * len(slots))
        out += struct.pack('<%dI' % len(slots), *slots)
        return bytes(out)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def normal_dividends(pos, triangle):
    """triNormalVecBitShift and the 10 dividends: (4096 << shift) / |edgeA x edgeB| per triangle,
    the largest shift that keeps every dividend in an s16 (matches retail files exactly)."""
    lens = []
    for i, (a, b, c) in enumerate(HI_TRIS + LO_TRIS):
        if triangle and (i in (4, 5, 6, 7, 9)):
            lens.append(None)
            continue
        n = _cross(_sub(pos[c], pos[a]), _sub(pos[b], pos[a]))
        lod = 2 if i >= 8 else 0
        n = tuple(x >> lod for x in n)  # arithmetic shift, as CTR_MipsSra
        lens.append(math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]))
    for shift in range(18, -1, -1):
        divs = []
        ok = True
        for L in lens:
            if L is None:
                divs.append(0)
                continue
            if L == 0:
                divs.append(0)
                continue
            d = int((4096 << shift) / L)
            if d > 0x7FFF:
                ok = False
                break
            divs.append(d)
        if ok:
            return shift, divs
    return 0, [0] * 10


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3]), max(a[4], b[4]), max(a[5], b[5]))


def build_bsp(quads, max_leaf):
    """kd-tree over quadblock bounding-box centers. Returns (nodes, quad order).

    nodes: list of dicts {leaf, box, children (ids, leaf-flagged) | first, count}; node 0 is
    the root. Quadblocks are reordered so each leaf owns a contiguous run."""
    boxes = [bbox(q.pos) for q in quads]
    centers = [((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2) for b in boxes]
    nodes = []
    order = []

    def make(idx, depth):
        me = len(nodes)
        nodes.append(None)
        box = boxes[idx[0]]
        for i in idx[1:]:
            box = _union(box, boxes[i])
        if len(idx) <= max_leaf:
            first = len(order)
            order.extend(idx)
            nodes[me] = dict(leaf=True, box=box, first=first, count=len(idx))
            return me
        # split on the widest horizontal axis of the centers (y only when it dominates)
        spans = []
        for ax in range(3):
            vals = [centers[i][ax] for i in idx]
            spans.append(max(vals) - min(vals))
        ax = max(range(3), key=lambda a: spans[a] * (0.5 if a == 1 else 1.0))
        idx = sorted(idx, key=lambda i: centers[i][ax])
        mid = len(idx) // 2
        split = centers[idx[mid]][ax]
        left = make(idx[:mid], depth + 1)
        right = make(idx[mid:], depth + 1)
        axis = [0, 0, 0]
        axis[ax] = 0x1000
        nodes[me] = dict(leaf=False, box=box, children=(left, right), axis=(axis[0], axis[1], axis[2], int(split)))
        return me

    make(list(range(len(quads))), 0)
    return nodes, order


def tree_depth(nodes, i=0):
    n = nodes[i]
    if n['leaf']:
        return 1
    return 1 + max(tree_depth(nodes, c) for c in n['children'] if c is not None)


def write_level(lv: Level):
    b = Blob()
    if lv.base is not None:
        b.buf = bytearray(lv.base.data)
        b.ptr_slots = list(lv.base.ptr_slots)
        hdr = 0
    else:
        hdr = b.alloc(LEVEL_SIZE)

    # BSP first: it fixes the quadblock order
    nodes, order = lv.bsp if lv.bsp else build_bsp(lv.quads, lv.max_leaf_quads)
    quads = [lv.quads[i] for i in order]
    nq = len(quads)
    nn = len(nodes)
    assert nn < 0x4000, 'too many BSP nodes'

    # vertices: 9 per quadblock (duplicates are fine, the format indexes them)
    verts = []
    vindex = {}
    quad_vidx = []
    for q in quads:
        colors = q.color or [(0x80, 0x80, 0x80)] * 9
        ids = []
        for k in range(9):
            c = colors[k]
            if len(c) == 3:
                c = (c[0], c[1], c[2], 0, c[0], c[1], c[2], 0)
            key = (tuple(q.pos[k]), tuple(c))
            if key not in vindex:
                vindex[key] = len(verts)
                verts.append(key)
            ids.append(vindex[key])
        quad_vidx.append(ids)
    assert len(verts) < 0x10000, 'too many vertices'

    mesh = b.alloc(0x20)
    quad_off = b.alloc(QUAD_SIZE * nq)
    vert_off = b.alloc(VERT_SIZE * len(verts))
    bsp_off = b.alloc(BSP_SIZE * nn)

    # PVS: every BSP node and quadblock visible
    leaf_words = (nn + 31) // 32
    face_words = (nq + 31) // 32
    vis_leaf = b.alloc(4 * leaf_words)
    vis_face = b.alloc(4 * face_words)
    b.put(vis_leaf, '%dI' % leaf_words, *([0xFFFFFFFF] * leaf_words))
    b.put(vis_face, '%dI' % face_words, *([0xFFFFFFFF] * face_words))
    pvs = b.alloc(0x10)
    b.ptr(pvs + 0, vis_leaf)
    b.ptr(pvs + 4, vis_face)
    # Level instances (grafted): new InstDefs copied from the base, at their new places
    inst_defs = None
    inst_list = None
    if lv.base is not None and lv.instances:
        base_defs = lv.base.u32(0x10)
        inst_defs = b.alloc(0x40 * len(lv.instances))
        for i, inst in enumerate(lv.instances):
            src = base_defs + 0x40 * inst['src']
            o = inst_defs + 0x40 * i
            b.buf[o:o + 0x40] = lv.base.data[src:src + 0x40]
            b.ptr(o + 0x10, lv.base.u32(src + 0x10))   # its model, in the base data
            b.put(o + 0x2C, 'I', 0)                     # ptrInstance: filled in at load
            b.put(o + 0x30, 'hhh', *inst['pos'])
            b.put(o + 0x36, 'hhh', *inst['rot'])
        # everything is visible from everywhere: one list, which LevInstDef_UnPack turns
        # from InstDef into Instance pointers once per quadblock that references it
        inst_list = b.alloc(4 * (len(lv.instances) + 1))
        for i in range(len(lv.instances)):
            b.ptr(inst_list + 4 * i, inst_defs + 0x40 * i)
        b.ptr(pvs + 8, inst_list)
    # a second PVS without instances, so the list above is toggled an odd number of times
    pvs_plain = b.alloc(0x10)
    b.ptr(pvs_plain + 0, vis_leaf)
    b.ptr(pvs_plain + 4, vis_face)

    # VisMem: per-player destination lists the game copies the PVS into, and BSP render lists
    vismem = b.alloc(0x90)
    for p in range(4):
        b.ptr(vismem + 0x00 + 4 * p, b.alloc(4 * leaf_words))
        b.ptr(vismem + 0x10 + 4 * p, b.alloc(4 * face_words))
        b.ptr(vismem + 0x20 + 4 * p, b.alloc(4))  # water vertices: none
        b.ptr(vismem + 0x30 + 4 * p, b.alloc(4))  # scenery vertices: none
        b.ptr(vismem + 0x80 + 4 * p, b.alloc(8 * nn))

    # texture layouts, shared when identical
    layouts = {}

    def layout_off(tl):
        """A TexLayout (written as far/middle/near/mosaic copies) or raw IconGroup4 bytes."""
        if tl is None:
            return None
        if isinstance(tl, (bytes, bytearray)):
            key = bytes(tl).ljust(0x30, b'\0')
        else:
            key = tl.pack() * 4
        if key not in layouts:
            off = b.alloc(0x30)
            b.buf[off:off + 0x30] = key
            layouts[key] = off
        return layouts[key]

    # vertices
    for i, (pos, col) in enumerate(verts):
        o = vert_off + VERT_SIZE * i
        b.put(o, 'hhhH', pos[0], pos[1], pos[2], 0)
        b.buf[o + 8:o + 16] = bytes(col)

    # quadblocks
    for qi, q in enumerate(quads):
        o = quad_off + QUAD_SIZE * qi
        b.put(o, '9H', *quad_vidx[qi])
        b.put(o + 0x12, 'H', q.flags)
        dol = q.draw_order_low if q.draw_order_low is not None else (0x80000000 if q.double_sided else 0)
        b.put(o + 0x14, 'II', dol, q.draw_order_high)
        for f in range(4):
            b.ptr(o + 0x1C + 4 * f, layout_off(q.faces[f]))
        b.put(o + 0x2C, '6h', *bbox(q.pos))
        b.put(o + 0x38, 'BBBb', q.terrain, 0, 0, 0)
        b.put(o + 0x3C, 'hBb', qi, q.checkpoint, 0)
        tl = layout_off(q.low)
        if tl is not None:
            # ptr_texture_low points at a single TextureLayout (the "far" member works)
            b.ptr(o + 0x40, tl)
        else:
            b.ptr(o + 0x40, None)
        # the last quadblock takes the plain PVS when the count would leave the list as InstDefs
        odd_fix = inst_list is not None and nq % 2 == 0 and qi == nq - 1
        b.ptr(o + 0x44, pvs_plain if odd_fix else pvs)
        shift, divs = normal_dividends(q.pos, q.triangle)
        b.put(o + 0x3F, 'b', shift)
        b.put(o + 0x48, '10h', *divs)

    # pickup hitboxes, listed in every leaf they overlap (the list ends with a zero flag)
    boxes = []
    for hb in lv.hitboxes:
        if inst_defs is None:
            break
        px, py, pz = lv.instances[hb['inst']]['pos']
        r = hb['radius']
        c = (px, py + hb['lift'], pz)
        boxes.append((hb, c, (c[0] - r, c[1] - r, c[2] - r, c[0] + r, c[1] + r, c[2] + r)))

    def overlaps(a, bb):
        return a[0] <= bb[3] and bb[0] <= a[3] and a[1] <= bb[4] and bb[1] <= a[4] and a[2] <= bb[5] and bb[2] <= a[5]

    # BSP nodes (node id = array index; children flagged 0x4000 when leaves)
    for ni, n in enumerate(nodes):
        o = bsp_off + BSP_SIZE * ni
        bx = n['box']
        if n['leaf']:
            b.put(o, 'Hh', 1, ni)
            b.put(o + 4, '6h', *bx)
            b.put(o + 0x10, 'I', 0)
            mine = [x for x in boxes if overlaps(bx, x[2])]
            if mine:
                arr = b.alloc(BSP_SIZE * (len(mine) + 1))
                for k, (hb, c, hbox) in enumerate(mine):
                    e = arr + BSP_SIZE * k
                    r = hb['radius']
                    b.put(e, 'Hh', hb['flags'], 0)
                    b.put(e + 4, '6h', *hbox)
                    b.put(e + 0x10, 'hhhhhh', c[0], c[1], c[2], r, r * r, 0)
                    b.ptr(e + 0x1C, inst_defs + 0x40 * hb['inst'])
                b.ptr(o + 0x14, arr)
            else:
                b.ptr(o + 0x14, None)
            b.put(o + 0x18, 'I', n['count'])
            b.ptr(o + 0x1C, quad_off + QUAD_SIZE * n['first'])
        else:
            b.put(o, 'Hh', 0, ni)
            b.put(o + 4, '6h', *bx)
            b.put(o + 0x10, '4h', *n['axis'])
            ids = [0xFFFF if c is None else (c | (0x4000 if nodes[c]['leaf'] else 0)) for c in n['children']]
            b.put(o + 0x18, '4H', ids[0], ids[1], 0, 0)

    # mesh_info
    b.put(mesh, 'III', nq, len(verts), 0)
    b.ptr(mesh + 0x0C, quad_off)
    b.ptr(mesh + 0x10, vert_off)
    b.put(mesh + 0x14, 'I', 0)
    b.ptr(mesh + 0x18, bsp_off)
    b.put(mesh + 0x1C, 'I', nn)

    # checkpoint nodes
    nodes_off = None
    if lv.nodes:
        nodes_off = b.alloc(0x0C * len(lv.nodes))
        for i, nd in enumerate(lv.nodes):
            o = nodes_off + 0x0C * i
            b.put(o, 'hhhH', nd.pos[0], nd.pos[1], nd.pos[2], nd.dist_to_finish)
            b.put(o + 8, 'BBBB', nd.forward, nd.left, nd.backward, nd.right)

    # SpawnType1: count 0 (no fly-in or end-of-race cameras, as battle maps), but seven
    # null slots after it: GhostReplay_Init1 reads the N. Tropy/Oxide ghost slots (4, 5)
    # without checking the count, and native treats a null tape as no ghost.
    # With a fly-in (camera path data, relative to the start grid) the count is 7: slot 2 is
    # the end-of-race cameras (none: a zero count), slot 3 the fly-in.
    st1 = b.alloc(4 + 4 * 7)
    if lv.flyin is not None:
        eor = b.alloc(4)
        b.put(st1, 'I', 7)
        b.ptr(st1 + 4 + 4 * 2, eor)
        b.ptr(st1 + 4 + 4 * 3, lv.flyin)

    # animated textures: an empty list is one AnimTex whose first word points at itself
    # (CTR_CycleTex_LEV walks the list without a null check); a base keeps its own
    anim = None
    if lv.base is None:
        anim = b.alloc(0x10)
        b.ptr(anim, anim)

    # texture lookup: named icons the game finds by name (minimap pieces, effects)
    ltl = None if lv.base is not None else b.alloc(0x10)
    if lv.icons and ltl is not None:
        icons_off = b.alloc(0x20 * len(lv.icons))
        for i, (name, gidx, tl) in enumerate(lv.icons):
            o = icons_off + 0x20 * i
            b.buf[o:o + 16] = name.encode('ascii')[:15].ljust(16, b'\0')
            b.put(o + 16, 'i', gidx)
            b.buf[o + 20:o + 32] = tl.pack()
        b.put(ltl, 'I', len(lv.icons))
        b.ptr(ltl + 4, icons_off)
        groups_ptrs = b.alloc(4 * max(1, len(lv.icon_groups)))
        for gi, (gname, gid, members) in enumerate(lv.icon_groups):
            go = b.alloc(0x14 + 4 * len(members))
            b.buf[go:go + 16] = gname.encode('ascii')[:15].ljust(16, b'\0')
            b.put(go + 16, 'hh', gid, len(members))
            for k, m in enumerate(members):
                b.ptr(go + 0x14 + 4 * k, icons_off + 0x20 * m)
            b.ptr(groups_ptrs + 4 * gi, go)
        b.put(ltl + 8, 'I', len(lv.icon_groups))
        b.ptr(ltl + 12, groups_ptrs)

    # AI paths: LevNavTable -> 3 NavHeader pointers -> header (magic 0xECFD) + NavFrames
    nav_table = None
    if lv.nav_paths:
        nav_table = b.alloc(4 * 3)
        for pi, frames in enumerate(lv.nav_paths[:3]):
            hdr_off = b.alloc(0x4C + 0x14 * len(frames))
            b.put(hdr_off, 'hhi', -0x1303, len(frames), frames[0]['pos'][1] if frames else 0)
            b.put(hdr_off + 8, 'I', 0)  # "last": the game fills it in
            for fi, f in enumerate(frames):
                o = hdr_off + 0x4C + 0x14 * fi
                b.put(o, 'hhh', *f['pos'])
                b.buf[o + 6:o + 10] = bytes(f['rot'])
                b.put(o + 10, 'hhhh', f['distXYZ'], f['distXZ'], f['flags'], f['change'])
                b.put(o + 18, 'BB', f['checkpoint'], f['special'])
            b.ptr(nav_table + 4 * pi, hdr_off)

    # build strings
    strs = {}
    for k, s in (('start', 'Tue Oct  6 2026'), ('end', 'Tue Oct  6 2026'), ('type', lv.build_name)):
        so = b.alloc(len(s) + 1)
        b.buf[so:so + len(s)] = s.encode('ascii')
        strs[k] = so

    # Level header
    b.ptr(hdr + 0x00, mesh)
    if lv.base is None:
        b.ptr(hdr + 0x08, anim)
        b.ptr(hdr + 0x3C, ltl)
        glow = lv.glow or [(0, 0, 0, 0)] * 3
        for i, (pf, pt, cf, ct) in enumerate(glow):
            b.put(hdr + 0x48 + 12 * i, 'hhII', pf, pt, cf, ct)
        b.put(hdr + 0xD8, 'II', 0, lv.config_flags)
        for i, (r, g, bb, en) in enumerate(lv.clear_colors):
            b.buf[hdr + 0x160 + 4 * i:hdr + 0x164 + 4 * i] = bytes([r, g, bb, en])
    else:
        # the base's instances, water and extra spawn data belong to the old track
        b.put(hdr + 0x0C, 'I', len(lv.instances))
        b.ptr(hdr + 0x10, inst_defs)
        all_defs = None
        if inst_defs is not None:
            all_defs = b.alloc(4 * (len(lv.instances) + 1))
            for i in range(len(lv.instances)):
                b.ptr(all_defs + 4 * i, inst_defs + 0x40 * i)
        b.ptr(hdr + 0x24, all_defs)
        b.ptr(hdr + 0x28, None)          # visOVertSrc
        b.put(hdr + 0x34, 'I', 0)        # numWaterVertices
        b.ptr(hdr + 0x38, None)          # ptr_water
        b.put(hdr + 0x138, 'I', 0)       # numSpawnType2
        b.ptr(hdr + 0x13C, None)
        b.put(hdr + 0x140, 'I', 0)       # numSpawnType2_PosRot
        b.ptr(hdr + 0x144, None)
        b.put(hdr + 0x170, 'I', 0)       # visSCVertSrc
        b.ptr(hdr + 0x170, None)
        b.put(hdr + 0x174, 'I', 0)       # numSCVert
        b.ptr(hdr + 0x178, None)
    spawns = (lv.spawns + [((0, 0, 0), (0, 0, 0))] * 8)[:8]
    for i, (p, r) in enumerate(spawns):
        b.put(hdr + 0x6C + 12 * i, '6h', p[0], p[1], p[2], r[0], r[1], r[2])
    b.ptr(hdr + 0xE0, strs['start'])
    b.ptr(hdr + 0xE4, strs['end'])
    b.ptr(hdr + 0xE8, strs['type'])
    b.ptr(hdr + 0x134, st1)
    b.put(hdr + 0x148, 'I', len(lv.nodes))
    b.ptr(hdr + 0x14C, nodes_off)
    b.ptr(hdr + 0x188, nav_table)
    b.ptr(hdr + 0x190, vismem)

    info = dict(quads=nq, verts=len(verts), bsp_nodes=nn, depth=tree_depth(nodes), layouts=len(layouts))
    return b.finish(), info

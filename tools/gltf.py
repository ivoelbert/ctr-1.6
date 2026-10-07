"""Loads the triangles of a glTF binary (.glb) with their texture coordinates."""
import json, struct
import numpy as np

COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}

def load_glb(path):
    data = open(path, 'rb').read()
    magic, version, length = struct.unpack_from('<III', data, 0)
    assert magic == 0x46546C67
    off = 12
    js = binchunk = None
    while off < length:
        clen, ctype = struct.unpack_from('<II', data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk)
        elif ctype == 0x004E4942:
            binchunk = chunk
    return js, binchunk

def accessor(js, binchunk, idx):
    acc = js['accessors'][idx]
    bv = js['bufferViews'][acc['bufferView']]
    dtype = COMP[acc['componentType']]
    n = NCOMP[acc['type']]
    start = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
    stride = bv.get('byteStride', 0)
    count = acc['count']
    itemsize = np.dtype(dtype).itemsize * n
    if stride and stride != itemsize:
        raw = np.frombuffer(binchunk, dtype=np.uint8, count=stride * (count - 1) + itemsize, offset=start)
        rows = np.lib.stride_tricks.as_strided(raw, shape=(count, itemsize), strides=(stride, 1))
        arr = np.frombuffer(rows.copy().tobytes(), dtype=dtype).reshape(count, n)
    else:
        arr = np.frombuffer(binchunk, dtype=dtype, count=count * n, offset=start).reshape(count, n)
    return arr.astype(np.float64) if dtype == np.float32 else arr

def node_matrices(js):
    """World matrix of every node (column-major glTF matrices)."""
    mats = {}
    def local(node):
        if 'matrix' in node:
            return np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
        m = np.eye(4)
        if 'scale' in node:
            m = np.diag(list(node['scale']) + [1.0]) @ m
        if 'rotation' in node:
            x, y, z, w = node['rotation']
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            rm = np.eye(4)
            rm[:3, :3] = r
            m = rm @ m
        if 'translation' in node:
            t = np.eye(4)
            t[:3, 3] = node['translation']
            m = t @ m
        return m
    def visit(i, parent):
        node = js['nodes'][i]
        w = parent @ local(node)
        mats[i] = w
        for c in node.get('children', []):
            visit(c, w)
    for s in js.get('scenes', []):
        for root in s['nodes']:
            visit(root, np.eye(4))
    return mats

def triangles(path, world=False, with_normals=False):
    """Yields (material index, positions (n,3,3), uv0 (n,3,2), uv1 or None, mesh name).

    Positions are in the mesh's own space unless world=True."""
    js, b = load_glb(path)
    mats = node_matrices(js) if world else None
    for ni, node in enumerate(js['nodes']):
        if 'mesh' not in node:
            continue
        mesh = js['meshes'][node['mesh']]
        for prim in mesh['primitives']:
            pos = accessor(js, b, prim['attributes']['POSITION'])
            if world:
                h = np.c_[pos, np.ones(len(pos))] @ mats[ni].T
                pos = h[:, :3]
            uv0 = accessor(js, b, prim['attributes']['TEXCOORD_0'])
            uv1 = accessor(js, b, prim['attributes']['TEXCOORD_1']) if 'TEXCOORD_1' in prim['attributes'] else None
            nrm = accessor(js, b, prim['attributes']['NORMAL']) if 'NORMAL' in prim['attributes'] else None
            if world and nrm is not None:
                nrm = nrm @ np.linalg.inv(mats[ni][:3, :3])
            idx = accessor(js, b, prim['indices']).reshape(-1).astype(np.int64) if 'indices' in prim else np.arange(len(pos))
            tri = idx.reshape(-1, 3)
            if with_normals:
                yield (prim.get('material'), pos[tri], uv0[tri], None if uv1 is None else uv1[tri], mesh.get('name'),
                       None if nrm is None else nrm[tri])
            else:
                yield (prim.get('material'), pos[tri], uv0[tri], None if uv1 is None else uv1[tri], mesh.get('name'))

def images(path):
    js, b = load_glb(path)
    out = []
    for img in js['images']:
        bv = js['bufferViews'][img['bufferView']]
        out.append(b[bv.get('byteOffset', 0):bv.get('byteOffset', 0) + bv['byteLength']])
    return js, out

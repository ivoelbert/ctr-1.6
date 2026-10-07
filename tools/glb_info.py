import json, struct, sys

def load_glb(path):
    data = open(path, 'rb').read()
    magic, version, length = struct.unpack_from('<III', data, 0)
    assert magic == 0x46546C67, 'not glb'
    off = 12
    js = None; bin_ = None
    while off < length:
        clen, ctype = struct.unpack_from('<II', data, off); off += 8
        chunk = data[off:off+clen]; off += clen
        if ctype == 0x4E4F534A: js = json.loads(chunk)
        elif ctype == 0x004E4942: bin_ = chunk
    return js, bin_

if __name__ == '__main__':
    js, b = load_glb(sys.argv[1])
    print('asset', js.get('asset'))
    print('scenes', len(js.get('scenes', [])), 'nodes', len(js.get('nodes', [])), 'meshes', len(js.get('meshes', [])),
          'materials', len(js.get('materials', [])), 'textures', len(js.get('textures', [])), 'images', len(js.get('images', [])),
          'accessors', len(js.get('accessors', [])), 'bin', len(b) if b else 0)
    print('extensionsUsed', js.get('extensionsUsed'))
    for i, img in enumerate(js.get('images', [])):
        print('image', i, {k: v for k, v in img.items() if k != 'uri'})
    for i, m in enumerate(js.get('materials', [])):
        print('material', i, json.dumps(m)[:300])
    tot_tris = 0
    for i, me in enumerate(js.get('meshes', [])):
        for p in me['primitives']:
            acc = js['accessors'][p['attributes']['POSITION']]
            nidx = js['accessors'][p['indices']]['count'] if 'indices' in p else acc['count']
            tot_tris += nidx // 3
            if i < 40:
                print('mesh', i, me.get('name'), 'attrs', list(p['attributes'].keys()), 'verts', acc['count'], 'tris', nidx//3,
                      'mat', p.get('material'), 'mode', p.get('mode', 4), 'min', acc.get('min'), 'max', acc.get('max'))
    print('total tris', tot_tris)
    for i, n in enumerate(js.get('nodes', [])[:30]):
        print('node', i, {k: v for k, v in n.items()})

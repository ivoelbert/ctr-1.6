"""CTR's BIGFILE.BIG: a header of (sector offset, byte size) entries, then the files."""
import struct, sys, os

class Bigfile:
    def __init__(self, path):
        self.data = open(path, 'rb').read() if isinstance(path, str) else path
        _, self.count = struct.unpack_from('<II', self.data, 0)
        self.entries = [struct.unpack_from('<II', self.data, 8 + 8 * i) for i in range(self.count)]

    def get(self, index):
        off, size = self.entries[index]
        return self.data[off * 2048: off * 2048 + size]

# Level file groups (engine/game/LOAD/LOAD_Assets.c, LOAD_GetBigfileIndex)
LOD_INDEX = {1: 0, 2: 2, 3: 4, 4: 4, 5: 6}
NITRO_COURT = 18

def level_index(level_id, lod=1, kind=1):
    """kind: 0 = VRAM (.vrm), 1 = LEV, 2 = PTR."""
    if level_id < NITRO_COURT:
        return level_id * 8 + LOD_INDEX[lod] + kind
    if level_id - NITRO_COURT < 7:
        return 18 * 8 + (level_id - NITRO_COURT) * 8 + LOD_INDEX[lod] + kind
    raise ValueError(level_id)

if __name__ == '__main__':
    b = Bigfile(sys.argv[1])
    print('entries', b.count)
    for i, (off, size) in enumerate(b.entries[:220]):
        print(i, off, size)

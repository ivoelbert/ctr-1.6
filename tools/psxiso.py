"""Minimal ISO9660 reader for raw MODE2/2352 PSX disc images (Form 1 data at +24)."""
import struct, sys, os

SECTOR = 2352

class Disc:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)

    def read_sector(self, lba):
        self.f.seek(lba * SECTOR)
        raw = self.f.read(SECTOR)
        return raw[24:24 + 2048]

    def read(self, lba, nbytes):
        out = bytearray()
        while len(out) < nbytes:
            out += self.read_sector(lba)
            lba += 1
        return bytes(out[:nbytes])

    def raw_sectors(self, lba, count):
        self.f.seek(lba * SECTOR)
        return self.f.read(SECTOR * count)

    def walk(self):
        pvd = self.read_sector(16)
        assert pvd[1:6] == b'CD001', pvd[:8]
        root = pvd[156:156 + 34]
        lba, size = struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0]
        yield from self._walk_dir(lba, size, '')

    def _walk_dir(self, lba, size, prefix):
        data = self.read(lba, size)
        off = 0
        while off < len(data):
            rlen = data[off]
            if rlen == 0:
                off = (off // 2048 + 1) * 2048
                continue
            rec = data[off:off + rlen]
            elba = struct.unpack_from('<I', rec, 2)[0]
            esize = struct.unpack_from('<I', rec, 10)[0]
            flags = rec[25]
            nlen = rec[32]
            name = rec[33:33 + nlen]
            off += rlen
            if name in (b'\x00', b'\x01'):
                continue
            name = name.decode('ascii', 'replace')
            if flags & 2:
                yield (prefix + name + '/', elba, esize, True)
                yield from self._walk_dir(elba, esize, prefix + name + '/')
            else:
                yield (prefix + name, elba, esize, False)

if __name__ == '__main__':
    d = Disc(sys.argv[1])
    for name, lba, size, isdir in d.walk():
        print(f'{"D" if isdir else "F"} {lba:7d} {size:10d} {name}')

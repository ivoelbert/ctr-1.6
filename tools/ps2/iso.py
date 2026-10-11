"""ISO 9660 disc images: files by path."""
import struct

SECTOR = 2048


class Iso:
    """A minimal ISO 9660 reader: files by path."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        pvd = self.read(16 * SECTOR, SECTOR)
        if pvd[1:6] != b'CD001':
            raise ValueError(f'{path}: not an ISO 9660 image')
        self.root = self._record(pvd, 156)

    def read(self, offset, size):
        self.f.seek(offset)
        return self.f.read(size)

    @staticmethod
    def _record(buf, o):
        n = buf[o]
        lba, size = struct.unpack_from('<I', buf, o + 2)[0], struct.unpack_from('<I', buf, o + 10)[0]
        flags = buf[o + 25]
        name = buf[o + 33:o + 33 + buf[o + 32]].decode('latin1').split(';')[0]
        return dict(len=n, lba=lba, size=size, dir=bool(flags & 2), name=name)

    def _list(self, rec):
        buf = self.read(rec['lba'] * SECTOR, rec['size'])
        o, out = 0, []
        while o < len(buf):
            if buf[o] == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            r = self._record(buf, o)
            out.append(r)
            o += r['len']
        return out

    def find(self, path):
        rec = self.root
        for part in path.upper().split('/'):
            rec = next((r for r in self._list(rec) if r['name'].upper() == part), None)
            if rec is None:
                raise FileNotFoundError(path)
        return rec

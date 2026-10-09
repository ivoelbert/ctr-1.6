"""Need for Speed: Underground 2's files, read straight from your PS2 disc image (SLUS-21065).

The game keeps its files in NFSUNDER/ZZDATA0-3.BIN, indexed by NFSUNDER/ZDIR.BIN: 24-byte
entries (name hash, archive, sector in the archive, sector on the disc, size, checksum), the
name hash being EA's bStringHash of the path (TRACKS\\L4RA.BUN).
"""
import struct

SECTOR = 2048


def string_hash(s):
    h = 0xFFFFFFFF
    for c in s.encode('latin1'):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


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


class Nfsu2:
    """The game's files: Nfsu2(iso).file('TRACKS\\\\L4RA.BUN')."""

    def __init__(self, iso_path):
        self.iso = Iso(iso_path)
        zdir = self.iso.find('NFSUNDER/ZDIR.BIN')
        if self.iso.find('SYSTEM.CNF') and b'SLUS_210.65' not in self.iso.read(self.iso.find('SYSTEM.CNF')['lba'] * SECTOR, 64):
            raise ValueError('not Need for Speed: Underground 2 (USA, SLUS-21065)')
        data = self.iso.read(zdir['lba'] * SECTOR, zdir['size'])
        archives = {}
        self.entries = {}
        for i in range(len(data) // 24):
            h, archive, sector, _, size, _ = struct.unpack_from('<6I', data, 24 * i)
            if archive not in archives:
                archives[archive] = self.iso.find(f'NFSUNDER/ZZDATA{archive}.BIN')['lba']
            self.entries.setdefault(h, (archives[archive] + sector, size))

    def file(self, name):
        lba, size = self.entries[string_hash(name)]
        return self.iso.read(lba * SECTOR, size)

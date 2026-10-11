"""Need for Speed: Underground 2's files, read straight from your PS2 disc image (SLUS-21065).

The game keeps its files in NFSUNDER/ZZDATA0-3.BIN, indexed by NFSUNDER/ZDIR.BIN: 24-byte
entries (name hash, archive, sector in the archive, sector on the disc, size, checksum), the
name hash being EA's bStringHash of the path (TRACKS\\L4RA.BUN).
"""
import struct

from ps2.iso import SECTOR, Iso


def string_hash(s):
    h = 0xFFFFFFFF
    for c in s.encode('latin1'):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


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

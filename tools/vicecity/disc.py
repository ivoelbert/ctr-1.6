"""Grand Theft Auto: Vice City's files, read straight from your PS2 disc image (SLUS-20552).

The disc is plain ISO 9660: the map's text files (DATA/MAPS/*/*.IDE, *.IPL) are files of
their own, and the models, textures and collision are in MODELS/GTA3.IMG, indexed by
MODELS/GTA3.DIR (32-byte entries: sector, sector count, name).
"""
import struct

from ps2.iso import SECTOR, Iso


class ViceCityDisc:
    def __init__(self, iso_path):
        self.iso = Iso(iso_path)
        cnf = self.iso.find('SYSTEM.CNF')
        if b'SLUS_205.52' not in self.iso.read(cnf['lba'] * SECTOR, cnf['size']):
            raise ValueError('not Grand Theft Auto: Vice City (USA, SLUS-20552)')
        d = self.text_bytes('MODELS/GTA3.DIR')
        self.img = self.iso.find('MODELS/GTA3.IMG')['lba']
        self.entries = {}
        for o in range(0, len(d) - 31, 32):
            sector, count, name = struct.unpack_from('<II24s', d, o)
            self.entries[name.split(b'\0')[0].decode('latin1').lower()] = (sector, count)

    def text_bytes(self, path):
        rec = self.iso.find(path.replace('\\', '/'))
        return self.iso.read(rec['lba'] * SECTOR, rec['size'])

    def text(self, path):
        return self.text_bytes(path).decode('latin1')

    def has(self, name):
        return name.lower() in self.entries

    def file(self, name):
        """A file of GTA3.IMG by name (model.dff, textures.txd, zone.col)."""
        sector, count = self.entries[name.lower()]
        return self.iso.read((self.img + sector) * SECTOR, count * SECTOR)

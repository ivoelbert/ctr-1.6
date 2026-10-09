"""EA bChunk files: (u32 id, u32 size, data) records, nested when the id has bit 31 set.
Chunk data is often aligned with runs of 0x11 bytes."""
import struct
from collections import namedtuple

# A streaming section of the city (TRACKS\\L4RA.BUN chunk 0x34110): its slice of
# TRACKS\\STREAML4RA.BUN and its middle and radius (metres, x east, y north). Letters A-R are
# the city's sections; X holds the shared props (and the sky), Y texture packs.
Section = namedtuple('Section', 'name number offset size cx cy radius')


def chunks(d, off, end):
    """(id, data offset, size) of the chunks in [off, end)."""
    while off + 8 <= end:
        cid, size = struct.unpack_from('<II', d, off)
        yield cid, off + 8, size
        off += 8 + size


def walk(d, off, end, want):
    """Every chunk with an id in want, depth first."""
    for cid, o, s in chunks(d, off, end):
        if cid in want:
            yield cid, o, s
        if cid & 0x80000000:
            yield from walk(d, o, o + s, want)


def skip_padding(d, o):
    while d[o:o + 4] == b'\x11\x11\x11\x11':
        o += 4
    return o


def sections(l4ra):
    for cid, o, s in chunks(l4ra, 0, len(l4ra)):
        if cid == 0x34110:
            out = []
            for i in range(s // 80):
                e = l4ra[o + 80 * i: o + 80 * i + 80]
                u = struct.unpack('<20I', e)
                f = struct.unpack('<20f', e)
                out.append(Section(e[:8].split(b'\0')[0].decode(), u[2], u[5], u[6], f[9], f[10], f[11]))
            return out
    raise ValueError('no section table')

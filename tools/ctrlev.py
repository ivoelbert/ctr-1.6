"""Reads CTR level files (LEV): the structs of engine/include/namespace_Level.h.

A LEV file is: u32 ptrMapOffset, then the level data (pointers stored as offsets into
the data), then the pointer map: u32 byteCount and byteCount/4 offsets of pointer slots,
which LOAD_RunPtrMap turns into addresses.
"""
import struct

class Lev:
    def __init__(self, raw):
        self.raw = raw
        (self.map_offset,) = struct.unpack_from('<I', raw, 0)
        self.data = raw[4:4 + self.map_offset]
        (nbytes,) = struct.unpack_from('<I', raw, 4 + self.map_offset)
        self.ptr_slots = list(struct.unpack_from('<%dI' % (nbytes // 4), raw, 8 + self.map_offset))
        self.ptr_set = set(self.ptr_slots)
        self.trailer = raw[8 + self.map_offset + nbytes:]

    # raw readers on the data block (offsets are relative to data, as pointers are)
    def u8(self, o): return self.data[o]
    def s8(self, o): return struct.unpack_from('<b', self.data, o)[0]
    def u16(self, o): return struct.unpack_from('<H', self.data, o)[0]
    def s16(self, o): return struct.unpack_from('<h', self.data, o)[0]
    def u32(self, o): return struct.unpack_from('<I', self.data, o)[0]
    def s32(self, o): return struct.unpack_from('<i', self.data, o)[0]
    def ptr(self, o):
        v = self.u32(o)
        if o not in self.ptr_set and v != 0:
            return ('NOTPTR', v)
        return v if o in self.ptr_set else None

    def header(self):
        o = 0
        h = {}
        names = ['mesh_info', 'skybox', 'anim_tex', 'numInstances', 'ptrInstDefs', 'numModels', 'ptrModelsPtrArray',
                 'unk3', 'unk4', 'ptrInstDefPtrArray', 'visOVertSrc', 'null1', 'null2', 'numWaterVertices', 'ptr_water',
                 'levTexLookup', 'ptr_named_tex_array', 'ptr_tex_waterEnvMap']
        for i, n in enumerate(names):
            h[n] = self.u32(4 * i)
        h['glowGradient'] = [struct.unpack_from('<hhII', self.data, 0x48 + 12 * i) for i in range(3)]
        h['DriverSpawn'] = [struct.unpack_from('<6h', self.data, 0x6c + 12 * i) for i in range(8)]
        h['unk_Lev_CC'], h['unk_Lev_D0'], h['ptrLowTexArray'], h['clearColorRGBA'], h['configFlags'] = struct.unpack_from('<5I', self.data, 0xCC)
        h['build_start'], h['build_end'], h['build_type'] = struct.unpack_from('<3I', self.data, 0xE0)
        h['rainBuffer'] = self.data[0x104:0x134].hex()
        (h['ptrSpawnType1'], h['numSpawnType2'], h['ptrSpawnType2'], h['numSpawnType2_PosRot'], h['ptrSpawnType2_PosRot'],
         h['cnt_restart_points'], h['ptr_restart_points']) = struct.unpack_from('<7I', self.data, 0x134)
        h['unk_150'] = self.data[0x150:0x160].hex()
        h['clearColor'] = [tuple(self.data[0x160 + 4 * i:0x164 + 4 * i]) for i in range(3)]
        h['unk_16C'], h['visSCVertSrc'], h['numSCVert'], h['ptrSCVert'] = struct.unpack_from('<4I', self.data, 0x16C)
        h['stars'] = struct.unpack_from('<4h', self.data, 0x17C)
        h['splitLines'] = struct.unpack_from('<2h', self.data, 0x184)
        h['LevNavTable'] = self.u32(0x188)
        h['jumpVerticalSpeedCap'] = self.data[0x18C:0x190].hex()
        h['visMem'] = self.u32(0x190)
        h['footer'] = self.data[0x194:0x1F4].hex()
        return h

    def cstr(self, o):
        end = self.data.index(b'\0', o)
        return self.data[o:end].decode('latin1')

    def mesh_info(self):
        o = self.u32(0)
        f = struct.unpack_from('<8I', self.data, o)
        return dict(zip(['numQuadBlock', 'numVertex', 'unk1', 'ptrQuadBlockArray', 'ptrVertexArray', 'unk2', 'bspRoot', 'numBspNodes'], f))

    def vertex(self, base, i):
        o = base + 16 * i
        x, y, z, flags = struct.unpack_from('<hhhH', self.data, o)
        return dict(pos=(x, y, z), flags=flags, hi=tuple(self.data[o + 8:o + 12]), lo=tuple(self.data[o + 12:o + 16]))

    def quadblock(self, base, i):
        o = base + 0x5c * i
        q = {}
        q['off'] = o
        q['index'] = struct.unpack_from('<9H', self.data, o)
        q['quadFlags'] = self.u16(o + 0x12)
        q['draw_order_low'] = self.u32(o + 0x14)
        q['draw_order_high'] = self.u32(o + 0x18)
        q['ptr_texture_mid'] = struct.unpack_from('<4I', self.data, o + 0x1c)
        q['bbox'] = struct.unpack_from('<6h', self.data, o + 0x2c)
        q['terrain_type'], q['weather_intensity'], q['weather_vanishRate'] = self.data[o + 0x38:o + 0x3b]
        q['mulNormVecY'] = self.s8(o + 0x3b)
        q['blockID'] = self.s16(o + 0x3c)
        q['checkpointIndex'] = self.u8(o + 0x3e)
        q['triNormalVecBitShift'] = self.s8(o + 0x3f)
        q['ptr_texture_low'] = self.u32(o + 0x40)
        q['pvs'] = self.u32(o + 0x44)
        q['triNormalVecDividend'] = struct.unpack_from('<10h', self.data, o + 0x48)
        return q

    def bsp(self, base, i):
        o = base + 0x20 * i
        flag, id_ = struct.unpack_from('<Hh', self.data, o)
        box = struct.unpack_from('<6h', self.data, o + 4)
        n = dict(off=o, flag=flag, id=id_, box=box)
        if flag & 1:
            n['unk1'], n['bspHitboxArray'], n['numQuads'], n['ptrQuadBlockArray'] = struct.unpack_from('<4I', self.data, o + 0x10)
        else:
            n['axis'] = struct.unpack_from('<4h', self.data, o + 0x10)
            n['childID'] = struct.unpack_from('<4H', self.data, o + 0x18)
        return n

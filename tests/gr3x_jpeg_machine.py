"""Pinned IIIx JPEG formatter + file scatter writer, using the local v10 harness.

Heap, file I/O, startup singletons and device identity are fixtures. The JPEG
encoder is replaced by a generated 8x8 image. TIFF/EXIF/MakerNote layout, JPEG
APP1/APP7 assembly and scatter descriptors run the original ARM instructions.
"""
import importlib.util
import io
import os
from pathlib import Path
from PIL import Image
from darkslide import photo_recipe_native as N, photo_recipe_extension as E

from gr3x_recipe_io import Machine as ProductionIo, C, V


class Machine(ProductionIo):
    def __init__(self, raw, extension):
        super().__init__(raw, extension)
        self.jpeg_symbols = extension['native']['symbols']
        self.allowed.extend([(0x55357f28, 0x55357f30), (0x55357ec4, 0x55357ed0)])
        self.seek = 0
        self.file_bytes = bytearray()
        self.file_fail = False
        self.file_calls = []
        self.jpeg_entered = 0
        self.job, self.prop, self.photo, self.work = self.new_job()
        self.u.mem_write(self.photo+0x77c, b'\x12')
        self.call(0x53600ee8, C.FORMATTER)
        self.call(0x535cd9ac, 0x55357b70, 0)
        self.call(0x53601b98, C.FORMATTER)
        for at, ctor in ((0x17c, 0x5360a13c), (0x180, 0x5360a0a8)):
            obj = self.allocate(4)
            self.call(ctor, obj)
            self.put(C.FORMATTER+at, obj)
        self.put(C.SOURCE+8, self.photo)
        image = io.BytesIO()
        Image.new('RGB', (8, 8), (72, 90, 120)).save(image, format='JPEG')
        self.pixels = image.getvalue()
        for i in range(12):
            aux = 0x7000a000+256*i
            self.put(C.SOURCE+24+4*i, aux)
            self.allowed.append((aux, aux+128))
            self.u.mem_write(aux, bytes(128))
            self.u.mem_write(aux+0x2c, b'\1\1')
            if i < 3:
                at = self.allocate(len(self.pixels))
                self.u.mem_write(at, self.pixels)
                self.put(aux+0x34, at)
                self.put(aux+0x28, len(self.pixels))
        self.outer = 0x7000c000
        self.allowed.append((self.outer, self.outer+0x78))
        self.call(0x53603610, self.outer)
        preview = self.allocate(0x80)
        self.call(0x535fe5b0, preview)
        self.call(0x535fe71c, preview)
        self.put(self.outer+0x28, preview)
        self.call(0x53603578, self.outer)
        self.workspace = self.allocate(0x50000)
        for at, value in ((0x18, self.workspace), (0x1c, 0x50000), (0x20, C.FORMATTER),
                          (8, C.SOURCE), (0x30, self.workspace), (0x34, 0x50000), (0x3c, 12)):
            self.put(self.outer+at, value)
        self.u.mem_write(self.outer+0x38, b'\0')  # LE memory stream
        self.file_info = 0x7000d000
        self.allowed.append((self.file_info, self.file_info+0x100))
        self.put(C.SOURCE+4, self.file_info)
        self.put(self.file_info+4, 1)
        self.put(self.file_info+0x18, self.file_info+0x40)
        self.put(self.file_info+0x40, self.file_info+0x60)
        self.put(self.file_info+0x60+0x18, V.SERV+0x60)
        self.put(self.file_info+0x60+0x14, V.SERV+0x64)

    def block(self, u, a, n, x):
        if hasattr(self, 'ext') and E.TAIL <= a and a+n <= self.ext['catalog']:
            if a == self.jpeg_symbols['ds_jpeg_capture']:
                self.jpeg_entered += 1
            return
        if a in (V.SERV+0x60, V.SERV+0x64):
            r = [u.reg_read(self.reg(i)) for i in range(4)]
            V.need(r[0] == self.file_info+0x40 and r[1] == 1, 'file service identity')
            self.file_calls.append((a, r[2], r[3]))
            if self.file_fail:
                self.ret(0)
                return
            if a == V.SERV+0x60:
                self.seek = r[2]
            else:
                V.need(r[3] <= 0x50000 and self.seek+r[3] <= 0x100000, 'file bound')
                end = self.seek+r[3]
                self.file_bytes.extend(bytes(max(0, end-len(self.file_bytes))))
                self.file_bytes[self.seek:end] = bytes(u.mem_read(r[2], r[3]))
                self.seek = end
            self.ret(1)
            return
        if ((0x5360be00 <= a and a+n <= 0x5360c078) or
            (0x5360a028 <= a and a+n <= 0x5360a1c8) or
            (0x53153150 <= a and a+n <= 0x53153200)):
            self.executed.add(a)
            return
        return super().block(u, a, n, x)

    def output(self, slot=8, *, capture=True):
        self.u.mem_write(self.photo+0x77c, bytes([slot+10]))
        self.file_bytes.clear()
        self.file_calls.clear()
        if capture:
            result = self.call(0x53603938, self.outer, C.SOURCE)
        else:
            result = self.call(0x53603844, self.outer)
            self.put(self.outer+0x10, self.file_info)
            self.put(self.outer+0x14, self.file_info+0x40)
            if result:
                result = self.call(0x535fc588, self.outer)
        return result, bytes(self.file_bytes)

    def canaries(self):
        for lo, hi in self.allocations:
            V.need(bytes(self.u.mem_read(lo-8, 8)) == b'LEFT!!!!' and
                   bytes(self.u.mem_read(hi, 8)) == b'RIGHT!!!', 'heap canary')

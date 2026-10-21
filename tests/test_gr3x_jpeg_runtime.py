"""Actual JPEG capture call -> original metadata/scatter writer -> desktop read.

No camera, real sensor input, filesystem scheduling or flash installation.
"""
import io
import os
from pathlib import Path
import struct
import unittest
try:
    from PIL import Image
except ImportError:  # Pillow is only needed by these tests, not by the program
    raise unittest.SkipTest("Pillow not installed")
from darkslide import film_profiles as F, models, gr3x_recipe_merge as M
from darkslide import photo_recipe as P, photo_recipe_extension as E, photo_recipe_jpeg as J
try:
    import unicorn
except ImportError:
    unicorn = None


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD') and
                    os.environ.get('DARKSLIDE_RESEARCH_ROOT'), 'IIIx payload, local research and Unicorn required')
class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gr3x_jpeg_machine import Machine
        cls.Machine = Machine
        cls.raw = Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()

    def check_image(self, before, after, packet):
        self.assertEqual(J.extract(after), packet)
        self.assertEqual(Image.open(io.BytesIO(before)).tobytes(), Image.open(io.BytesIO(after)).tobytes())
        # Removing ONLY our APP15 segments reconstructs the exact stock file,
        # including EXIF, MakerNote, previews, entropy and original SOI bytes.
        spans = [(a,b) for marker,p,a,b,scan in J.markers(after)
                 if marker == 0xef and p.startswith(b'DSRECIPE')]
        restored = bytearray(after)
        for a,b in reversed(spans):del restored[a:b]
        self.assertEqual(bytes(restored), before)

    def test_sixteen_films_all_slots_reuse_and_stock_fallback(self):
        films = F.ready_profile_ids()
        self.assertEqual(len(films),16)
        for batch in range(0,16,4):
            selected = dict(zip(range(8,12),films[batch:batch+4]))
            profiles = {f:F.load_profile(f,models.GR3X.id) for f in selected.values()}
            merged = M.prepare(self.raw,[dict(kind='film',slot=s,film=f) for s,f in selected.items()],profiles)
            m = self.Machine(self.raw,merged['extension'])
            for slot in (*range(8,12), 8, 11):
                with self.subTest(film=selected[slot],slot=slot):
                    ok,base = m.output(slot,capture=False);self.assertEqual(ok,1)
                    allocs = list(m.allocations)
                    ok,out = m.output(slot);self.assertEqual(ok,1)
                    self.check_image(base,out,merged['packets'][slot])
                    self.assertEqual(m.allocations,allocs);m.canaries()
            ok,base = m.output(1,capture=False)
            ok,out = m.output(1)
            self.assertEqual(out,base)
            with self.assertRaisesRegex(ValueError,'未保存'):J.extract(out)
            self.assertEqual(m.jpeg_entered,7)
            print('JPEG_NATIVE_CATALOG',selected,'capture_calls',m.jpeg_entered,flush=True)

    def test_max_packet_two_chunks_capacity_and_file_failure(self):
        from test_photo_recipe_jpeg import packet_of_size
        packet = packet_of_size(P.encode(F.load_profile('gold200',models.GR3X.id),8),P.MAX_PACKET)
        ext = E.build_fragments(self.raw,{8:packet})
        m = self.Machine(self.raw,ext)
        _,base = m.output(capture=False)
        _,out = m.output()
        self.check_image(base,out,packet)
        self.assertEqual(len([1 for k,p,*_ in J.markers(out) if k==0xef and p.startswith(b'DSRECIPE')]),2)
        old_end = len(base)-len(m.pixels)
        new_end = len(out)-len(m.pixels)
        self.assertEqual(new_end%32,0)
        # Buffer exactly sufficient succeeds, one byte short retains stock JPEG.
        for cap,expected in ((new_end,out),(new_end-1,base),(old_end+1,base)):
            m.put(m.outer+0x1c,cap)
            ok,actual = m.output();self.assertEqual(ok,1);self.assertEqual(actual,expected);m.canaries()
        m.put(m.outer+0x1c,0x50000)
        m.file_fail=True
        ok,out=m.output();self.assertEqual(ok,0);self.assertEqual(out,b'')
        m.file_fail=False
        ok,out=m.output();self.assertEqual(ok,1);self.check_image(base,out,packet)
        print('JPEG_NATIVE_MAX',len(packet),old_end,new_end,flush=True)

    def test_missing_corrupt_packet_and_archived_raw_do_not_mislabel(self):
        packet=P.encode(F.load_profile('gold200',models.GR3X.id),8)
        ext=E.build_fragments(self.raw,{8:packet})
        m=self.Machine(self.raw,ext)
        _,base=m.output(capture=False)
        # Direct admission tests leave all original descriptors and bytes intact.
        def snapshot():
            return bytes(m.u.mem_read(m.outer,0x78)),bytes(m.u.mem_read(m.workspace,0x50000))
        before=snapshot()
        cat=0x70001000;bad=bytearray(packet);bad[-1]^=1
        m.u.mem_write(0x70020000,bytes(bad));m.put(cat,0x70020000);m.put(cat+4,len(bad))
        self.assertEqual(m.call(m.jpeg_symbols['ds_jpeg_append'],m.outer,m.photo,cat),0)
        self.assertEqual(snapshot(),before)
        for offset,value in ((0x50,0xffffffff),(0x1c,0xffffffff),(0x64,0),(0x5c,1),(0x54,1)):
            saved=m.get(m.outer+offset);m.put(m.outer+offset,value);before_bad=snapshot()
            self.assertEqual(m.call(m.jpeg_symbols['ds_jpeg_append'],m.outer,m.photo,ext['catalog']),0)
            self.assertEqual(snapshot(),before_bad);m.put(m.outer+offset,saved)
        ok,other=m.output(9);self.assertEqual(ok,1)
        with self.assertRaisesRegex(ValueError,'未保存'):J.extract(other)
        # A context with failed packet allocation retains numeric core only. Do not stamp today's full
        # catalog provenance on an image rendered from a historical recipe.
        _,base=m.output(capture=False)
        pool=m.allocate(E.POOL_EXTENDED);photo=m.allocate(E.PHOTO_EXTENDED)
        m.u.mem_write(photo,bytes(m.u.mem_read(m.photo,0x74270)))
        m.put(pool+0x20,E.PHOTO_EXTENDED);m.put(pool+0x88,photo)
        m.u.mem_write(photo+0x74270,struct.pack('<4I',photo,1,1,8)+packet[24:1596])
        m.put(0x55344d7c+0x5ac,pool)
        before=snapshot()
        self.assertEqual(m.call(m.jpeg_symbols['ds_jpeg_append'],m.outer,photo,ext['catalog']),0)
        self.assertEqual(snapshot(),before);m.canaries()
        print('JPEG_NATIVE_CLOSED_FAILURES_AND_ARCHIVED_GUARD',flush=True)

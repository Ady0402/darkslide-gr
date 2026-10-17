"""Complete native Make and RAW queue bindings with explicit service substitutes."""
import json, os
from pathlib import Path
import unittest

try:
    import unicorn
except ImportError:
    unicorn=None


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD'), 'IIIx payload and Unicorn required')
class MergedMake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gr3x_recipe_machine as M
        cls.M=M;cls.raw=Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        cls.selection={8:'5219',9:'portra400',10:'gold200',11:'pro400h'}

    def values(self,r):
        return {k:r[k] for k in ('base','rgb','post','registers')}

    def test_all_legacy_recipes_slots_use_owned_full_values(self):
        M=self.M
        for path in sorted((Path(__file__).parent/"fixtures/film_legacy_v1/camera").glob("*.json")):
            film = path.stem
            for slot in range(8,12):
                with self.subTest(film=film,slot=slot):
                    m=M.Machine(self.raw,self.selection)
                    profile=json.loads(path.read_text())
                    profile.update(model=M.models.GR3X.name,firmware=M.models.GR3X.firmware)
                    packet=M.P.encode(profile,slot)
                    m.restore(packet);p=m.submit(slot);r=m.make(p)
                    checks=M.validate_consumption(m,p,packet,r)
                    self.assertTrue(checks['post_verified'])
                    m.u.mem_write(0x5536dab8,b'\xff'*16)
                    m.u.mem_write(0x55037604,b'\xff'*48)
                    again=m.make(p)
                    self.assertEqual((r['rgb'],r['post']),(again['rgb'],again['post']))

    def test_current_knots_and_saved_expansion_restore_identically(self):
        M=self.M
        for slot in range(8,12):
            with self.subTest(slot=slot):
                current=M.Machine(self.raw,self.selection)
                p=current.submit(slot,selector={8:9,9:10,10:11,11:12}[slot])
                a=current.make(p)
                restored=M.Machine(self.raw,self.selection)
                packet=restored.packets[slot]
                restored.restore(packet);q=restored.submit(slot);b=restored.make(q)
                M.validate_consumption(restored,q,packet,b)
                self.assertEqual(self.values(a),self.values(b))

    def test_ordinary_current_and_uninstalled_equal_curve_only(self):
        M=self.M
        for selection in ({},{10:'gold200'},self.selection):
            for tone in (11,18,19,20,21,22):
                with self.subTest(slots=list(selection),tone=tone):
                    values=[]
                    for recipe in (False,True):
                        m=M.Machine(self.raw,selection,recipe=recipe);p=m.photos[0]
                        for off,value in M.DEFAULTS.items():m.putbyte(p+off,value)
                        m.putbyte(p+0x77c,tone)
                        values.append(self.values(m.make(p)))
                        self.assertFalse(m.core_reads)
                    self.assertEqual(values[0],values[1])

    def test_old_recipe_survives_new_catalog_and_interleaved_photos(self):
        M=self.M
        a=M.P.encode(M.F.load_profile('gold200',M.models.GR3X.id),8)
        b=M.P.encode(M.F.load_profile('5219',M.models.GR3X.id),8)
        reference=None
        for selection in ({},{10:'pro400h'},self.selection):
            m=M.Machine(self.raw,selection)
            m.restore(a);p=m.submit(8,photo=0);ra=m.make(p)
            if reference is None:reference=self.values(ra)
            else:self.assertEqual(reference,self.values(ra))
            m.restore(b);q=m.submit(8,photo=1);rb=m.make(q);again=m.make(p)
            self.assertNotEqual(ra['rgb'],rb['rgb'])
            self.assertEqual(self.values(ra),self.values(again))
            M.validate_consumption(m,p,a,again)
            m.call('ds_pool_return',m.pool,p)
            self.assertEqual(m.word(p+M.E.PHOTO_BYTES+8),0)
            m.putbyte(m.pool+0x24,0);m.restore(a)
            p=m.submit(8,selector=9)
            self.assertEqual(m.word(p+M.E.PHOTO_BYTES+8),0)

    def test_full_make_cache_exit_and_return_match_fresh_objects(self):
        M=self.M
        selection={8:'gold200',10:'5219'}
        m=M.Machine(self.raw,selection);p=m.photos[0]
        for off,value in M.DEFAULTS.items():m.putbyte(p+off,value)
        expected={}
        for tone in (18,11,20,19,21,22,18,20,11):
            m.putbyte(p+0x77c,tone);actual=self.values(m.make(p))
            if tone not in expected:
                fresh=M.Machine(self.raw,selection);q=fresh.photos[0]
                for off,value in M.DEFAULTS.items():fresh.putbyte(q+off,value)
                fresh.putbyte(q+0x77c,tone);expected[tone]=self.values(fresh.make(q))
            self.assertEqual(actual,expected[tone],tone)

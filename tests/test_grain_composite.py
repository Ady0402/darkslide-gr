"""Real stock end-to-end grain generation; memory-only outputs."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from darkslide import compositor, composite_verify, edit_core, fwread, generate, grain_menu, rescue_gate, template, verify
from darkslide.store import Store
STOCK = Path(os.environ.get('DARKSLIDE_OFFICIAL_BIN', '/nonexistent'))

class GrainRequest(unittest.TestCase):
    def test_reject_bad_contracts_before_decode(self):
        good = dict(kind='grain_menu', slot=12, mode=22)
        for bad in (dict(good, slot=True), dict(good, slot=12.0), dict(good, mode=22.0),
                    dict(good, mode=True), dict(good, slot=7), dict(good, slot=13),
                    dict(good, bank=1), dict(kind='grain_menu',slot=12)):
            with self.subTest(bad=bad), self.assertRaises(edit_core.BuildError):
                grain_menu.validate_request(bad)
        with self.assertRaises(compositor.CompositeError):
            compositor.build_composite(b'', [good, good], template.load())

@unittest.skipUnless(STOCK.exists(), 'official fixture unavailable')
class GrainComposite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = STOCK.read_bytes()
        cls.base = fwread.unpack(cls.raw)
        cls.t = template.load()
        cls.grain = dict(kind='grain_menu', slot=12, mode=22)
        cls.jpeg = (Path(__file__).parent/'fixtures/shutdown_gradient.jpg').read_bytes()
        p = fwread.Payload(cls.base)
        _, native = p.icon_pixels(23)
        px = bytearray(fwread.icon_to_rgba(native)); px[(2*40+1)*4] ^= 128
        cls.mixed = [dict(kind='icon', slot=12, icon_id=23, pixels=bytes(px)),
                     dict(kind='name', slot=12, string_id=273, text='Color Neg'), cls.grain]
        cls.results = []
        for request, image in (([cls.grain],None),(cls.mixed,cls.jpeg)):
            with patch.object(edit_core, '_pack_payload', wraps=edit_core._pack_payload) as pack:
                result = compositor.build_composite(cls.raw,request,cls.t,image)
                if pack.call_count != 1: raise ValueError('must pack once')
            cls.results.append((result, request, image))

    def test_full_readback_and_rescue(self):
        for result, request, jpeg in self.results:
            checks=composite_verify.verify(self.raw,result,request,self.t,jpeg)
            self.assertTrue(composite_verify.all_ok(checks),checks)
            self.assertTrue(rescue_gate.all_ok(rescue_gate.gate(self.raw,result['output'])))
            p=fwread.Payload(fwread.unpack(result['output']),pinned=False)
            self.assertEqual(verify.grain_menu_state(p),'opened')

    def test_only_three_grain_bytes_plus_checksum(self):
        actual=fwread.unpack(self.results[0][0]['output'])
        # Explicit independent file offsets from pinned RTOS layout, not writer declarations.
        row=0xB45130; tail=0xB4588E
        want=bytearray(self.base)
        want[row:row+4]=(10).to_bytes(4,'little');want[tail:tail+2]=bytes((2,15))
        import struct
        checksum=(-sum(x[0] for x in struct.iter_unpack('<I',want[:-4]))) & 0xffffffff
        want[-4:]=checksum.to_bytes(4,'little')
        self.assertEqual(actual,bytes(want))

    def test_stock_identity_and_windows_rejected(self):
        for at in (0xB45130,0xB4587C,0xB4588E,0xB45890):
            altered=bytearray(self.base);altered[at]^=1
            with self.subTest(at=at),self.assertRaises(edit_core.BuildError):
                grain_menu.apply(bytes(altered))

    def test_request_omission_wrong_mode_and_duplicate_refused(self):
        result=self.results[0][0]
        for request in ([],[dict(self.grain,mode=21)],[self.grain,self.grain]):
            with self.subTest(request=request):
                self.assertFalse(composite_verify.all_ok(composite_verify.verify(self.raw,result,request,self.t)))

    def test_saved_project_reaches_verified_output(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);identity=store.put_input(self.raw)
            project=store.create_project('grain integration',identity,self.t)
            pid=project['id']
            store.put_draft(pid,{'12':{'grain':True,'name':'Color Neg'}},self.t)
            store.save(pid,self.t)
            output,manifest=generate.run(store,store.get_project(pid),self.t,self.raw)
            self.assertEqual(manifest['skipped'],[])
            self.assertEqual(manifest['features'],['grain_menu','name'])
            self.assertTrue(all(c['ok'] for c in manifest['checks']))
            self.assertEqual(verify.grain_menu_state(fwread.Payload(fwread.unpack(output),pinned=False)),'opened')

if __name__=='__main__':unittest.main()

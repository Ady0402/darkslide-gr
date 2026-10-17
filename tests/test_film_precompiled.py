"""No compiler, no firmware generation: pure ARM-fragment and integrity checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from darkslide import film_precompiled as bundle
from darkslide import film_inplace_cache, gr3x_inplace


class BundledArm(unittest.TestCase):
    def test_all_nonempty_masks_without_compiler(self):
        with patch('darkslide.film_arm_assemble.assemble', side_effect=AssertionError('compiler forbidden')), \
             patch('subprocess.run', side_effect=AssertionError('process forbidden')):
            for module in (film_inplace_cache, gr3x_inplace):
                for mask in range(1,16):
                    with self.subTest(module=module.__name__, mask=mask):
                        addresses, code = module.build_code(mask)
                        self.assertEqual(len(code),10)
                        self.assertLessEqual(sum(map(len,code.values())),sum(end-start for start,end in module.CODE))
                        for role,blob in code.items():
                            self.assertTrue(any(start <= addresses[role] and addresses[role]+len(blob) <= end for start,end in module.CODE))
                        self.assertEqual(set(addresses),set(code))

    def test_unknown_source_address_family_rejected(self):
        source = film_inplace_cache.code_sources(15,film_inplace_cache.CODE[0][0],film_inplace_cache.CODE[0][0])['point']
        for text,base,family in [(source+'\n',film_inplace_cache.CODE[0][0],bundle.FAMILIES[0]),
                                 (source,0,bundle.FAMILIES[0]),(source,film_inplace_cache.CODE[0][0],'unknown')]:
            with self.subTest(family=family,base=base,text=text[-4:]):
                with self.assertRaises(ValueError):bundle.assemble_bundled(text,base,family)

    def test_missing_and_corrupt_resources_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'arm.json'
            with patch.object(bundle,'BUNDLE',path):
                with self.assertRaises(ValueError):bundle.assemble_bundled('mov r0,r0',0,bundle.FAMILIES[0])
                path.write_bytes(b'{}')
                with self.assertRaises(ValueError):bundle.assemble_bundled('mov r0,r0',0,bundle.FAMILIES[0])

    def test_entry_validation_even_with_updated_outer_hash(self):
        original=json.loads(bundle.BUNDLE.read_bytes())
        family=bundle.FAMILIES[0]
        source=film_inplace_cache.code_sources(1,film_inplace_cache.CODE[0][0],film_inplace_cache.CODE[0][0])['point']
        base=film_inplace_cache.CODE[0][0];key=bundle.source_key(source,base)
        for failure in ('missing','size','sha256','hex'):
            data=json.loads(json.dumps(original))
            if failure=='missing':del data['families'][family]['entries'][key]
            else:data['families'][family]['entries'][key][failure] = 0 if failure=='size' else '00'
            raw=json.dumps(data).encode()
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'arm.json';path.write_bytes(raw)
                with patch.object(bundle,'BUNDLE',path),patch.object(bundle,'BUNDLE_SHA256',hashlib.sha256(raw).hexdigest()):
                    with self.assertRaises(ValueError):bundle.assemble_bundled(source,base,family)

    def test_pure_build_rejects_empty_and_invalid_masks(self):
        for module in (film_inplace_cache,gr3x_inplace):
            for mask in (0,16,-1,True,'1'):
                with self.assertRaises(ValueError):module.build_code(mask)

if __name__=='__main__':unittest.main()

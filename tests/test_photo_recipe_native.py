"""Compilation boundary only. ARM execution is a separately recorded probe."""
import unittest
from pathlib import Path
from darkslide import photo_recipe_native as N

class NativeModuleTests(unittest.TestCase):
    def test_bad_objects_fail_closed(self):
        for b in (b'',b'\x7fELF',bytes(100),b'\x7fELF\x01\x01\x01'+bytes(100)):
            with self.subTest(length=len(b)),self.assertRaises(ValueError):N.link_lab_object(b)
        for base in (0x53d36400,0x71000001,True):
            with self.subTest(base=base),self.assertRaises(ValueError):N.link_lab_object(b'',base)

    def test_lab_compile_is_not_firmware_export(self):
        try:N.resolve_clang()
        except ValueError as exc:self.skipTest(str(exc))
        r=N.compile_lab()
        self.assertFalse(r['firmware_installed'])
        self.assertFalse(r['object_ownership_verified'])
        self.assertGreater(len(r['code']),1000)
        self.assertLess(len(r['code']),65536)
        self.assertIn('ds_prepare',r['symbols'])
        self.assertTrue(N.INTEGRATION_ENTRIES <= set(r['symbols']))
        self.assertEqual(r['raw_job_extended_bytes'],1692)
        for name,at in r['symbols'].items():
            self.assertTrue(N.LAB_BASE<=at<N.LAB_BASE+len(r['code']),name)
        # All relocations are relative: moving the lab mapping changes symbols,
        # while instruction bytes remain identical (absolute firmware calls stay fixed).
        moved=N.compile_lab(N.LAB_BASE+0x10000)
        self.assertEqual(r['code'],moved['code'])
        self.assertEqual({k:v+0x10000 for k,v in r['symbols'].items()},moved['symbols'])

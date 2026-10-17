import base64
import copy
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from darkslide import models, film_profiles, film_writer, film_verify
from darkslide import photo_recipe as R, photo_recipe_dng as D


def fixture(endian='<', model=b'RICOH GR IIIx\0'):
    """Structural DNG, not a sensor image: root, subIFD and opaque private data."""
    # All indirect regions are deliberately away from the original IFD.
    raw = bytearray(1024)
    raw[:8] = (b'II' if endian == '<' else b'MM') + struct.pack(endian+'HI', 42, 8)
    entries = [(272, 2, len(model), 128), (330, 4, 1, 256),
               (50706, 1, 4, int.from_bytes(b'\1\4\0\0', 'little' if endian=='<' else 'big')),
               (50740, 1, 80, 384)]
    struct.pack_into(endian+'H', raw, 8, len(entries))
    for i, row in enumerate(entries): struct.pack_into(endian+'HHII', raw, 10+12*i, *row)
    raw[128:128+len(model)] = model
    # Empty private IFD; opaque trailing bytes must be preserved by XMP writing.
    raw[384:464] = b'RICOH\0II' + bytes(6) + bytes(range(66))
    raw[512:] = bytes(range(256))*2
    return bytes(raw)


def repair_crc(raw):
    return bytes(raw[:-4]) + struct.pack('<I', zlib.crc32(raw[:-4]))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.p = film_profiles.load_profile('gold200', models.GR3X.id)
        self.b = R.encode(self.p, 8)

    def test_all_profiles_exact_and_provenance_retained(self):
        for ident in film_profiles.ready_profile_ids():
            p = film_profiles.load_profile(ident, models.GR3X.id)
            for slot in (8,9,10,11):
                packet = R.encode(p, slot)
                decoded=R.decode(packet)['profile']
                for key, value in p.items():self.assertEqual(decoded[key], value)
                self.assertIn('SPEKTRAFILM_LICENSE.txt',decoded['data_notices'])
                restored = R.restored_profile(packet)
                for key in R.FIELDS: self.assertEqual(restored[key], p[key])
                self.assertEqual(restored.get('provenance'), p.get('provenance'))
                self.assertFalse(restored['photo_snapshot']['refitted'])

    def test_restore_does_not_read_changed_or_missing_catalog(self):
        with patch.object(film_profiles, 'load_profile', side_effect=AssertionError('catalog read')):
            old = R.restored_profile(self.b)
            edit = dict(kind='film', slot=11, film=old['id'])
            resolved = film_writer.resolve_profiles([edit], {old['id']: old}, models.GR3X.id)
            self.assertEqual(resolved[old['id']]['curves_u14'], self.p['curves_u14'])
        newer = copy.deepcopy(self.p); newer['curves_u14'][0][10] += 1
        self.assertNotEqual(R.decode(R.encode(newer, 8))['numeric_sha256'], R.decode(self.b)['numeric_sha256'])

    def test_every_truncation_and_every_byte_corruption(self):
        for n in range(len(self.b)):
            with self.assertRaises(ValueError): R.decode(self.b[:n])
        for n in range(len(self.b)):
            bad=bytearray(self.b);bad[n]^=1
            with self.assertRaises(ValueError): R.decode(bytes(bad))
        with self.assertRaises(ValueError): R.decode(self.b+b'\0')

    def test_recomputed_checksum_cannot_bypass_bounds_or_numeric_validation(self):
        for at, value in [(8,2),(10,2),(12,7),(14,1),(16,0),(20,255),
                          (24,0),(43,255),(1578,0)]:
            bad = bytearray(self.b);bad[at] = value
            with self.subTest(at=at), self.assertRaises(ValueError): R.decode(repair_crc(bad))
        wrong=copy.deepcopy(self.p);wrong['model']='GR III'
        with self.assertRaises(ValueError):R.encode(wrong,8)

    def test_unknown_metadata_duplicate_fields_and_wrong_model(self):
        start=R.HEADER.size+R.CORE.size
        meta=json.loads(self.b[start:-4])
        for mutate in [lambda m:m.update(abi='future'), lambda m:m.update(official_sha256='0'*64),
                       lambda m:m['profile'].update(firmware='2.10')]:
            badmeta=copy.deepcopy(meta);mutate(badmeta)
            blob=json.dumps(badmeta).encode();head=bytearray(self.b[:24]);struct.pack_into('<I',head,20,len(blob))
            bad=bytes(head)+self.b[24:start]+blob+b'\0'*4
            with self.assertRaises(ValueError):R.decode(repair_crc(bad))
        blob=self.b[start:-4].replace(b'{',b'{"abi":"duplicate",',1)
        head=bytearray(self.b[:24]);struct.pack_into('<I',head,20,len(blob))
        with self.assertRaises(ValueError):R.decode(repair_crc(bytes(head)+self.b[24:start]+blob+b'\0'*4))

    def test_dng_both_endians_preserve_every_original_byte_except_root_pointer(self):
        for endian in ('<','>'):
            before=fixture(endian);after=D.embed(before,self.b)
            self.assertEqual(D.extract(after),self.b)
            self.assertEqual(after[:4],before[:4]);self.assertEqual(after[8:len(before)],before[8:])
            self.assertEqual(D._ifd0(after)[1][50740][0],D._ifd0(before)[1][50740][0])
            with self.assertRaisesRegex(ValueError,'已有 XMP'):D.embed(after,self.b)

    def test_dng_missing_recipe_wrong_model_and_unsafe_structures_rejected(self):
        with self.assertRaisesRegex(ValueError,'未保存'):D.extract(fixture())
        with self.assertRaisesRegex(ValueError,'IIIx'):D.embed(fixture(model=b'RICOH GR III\0'),self.b)
        for data in (b'II',b'II+\0'+bytes(100),fixture()[:200]):
            with self.assertRaises(ValueError):D.embed(data,self.b)
        bad=bytearray(fixture());struct.pack_into('<H',bad,8,65535)
        with self.assertRaises(ValueError):D.embed(bytes(bad),self.b)
        bad=bytearray(fixture());bad[22:34]=bad[10:22]
        with self.assertRaises(ValueError):D.embed(bytes(bad),self.b)
        bad=bytearray(fixture());struct.pack_into('<I',bad,54,0xffffffff)
        with self.assertRaises(ValueError):D.embed(bytes(bad),self.b)

    def test_xmp_conflicts_entities_and_corruption_rejected(self):
        good=D._xmp(self.b)
        self.assertEqual(D._from_xmp(good),self.b)
        bads=[b'<!DOCTYPE x [<!ENTITY y "z">]>'+good,
              good.replace(b'<ds:FilmRecipe>',b'<ds:FilmRecipe>!'),
              good.replace(b'</rdf:Description>',b'<ds:FilmRecipe>AA==</ds:FilmRecipe></rdf:Description>'),
              good.replace(b'<ds:FilmRecipe>',b'<ds:FilmRecipe rdf:parseType="Resource">')]
        for bad in bads:
            with self.assertRaises(ValueError):D._from_xmp(bad)








if __name__ == '__main__':unittest.main()

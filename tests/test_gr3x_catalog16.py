"""Catalog migration, immutable historic recipes and sparse IIIx admission."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from darkslide import film_profiles as F, models, photo_recipe as R, photo_recipe_dng as D
from darkslide import gr3x_inplace as W, gr3x_factory_envelope as E
from darkslide import gr3x_camera_preview as P
from test_photo_recipe import fixture

ROOT = Path(__file__).resolve().parents[1] / 'film_curves'
LEGACY = Path(__file__).parent / 'fixtures/film_legacy_v1'
IDS = {'portra400','gold200','ektar100','pro400h','ultramax400','5207','5219',
       'xtra400_portraendura','portra160','portra800','portra800push1',
       'portra800push2','c200','5203','5213','verita200d'}
NOTICES = ('README.md','SPEKTRAFILM_LICENSE.txt','CHANGELOG.txt')


def legacy(ident):
    p = json.loads((LEGACY/'camera'/(ident+'.json')).read_text())
    p.update(model=models.GR3X.name, firmware=models.GR3X.firmware)
    p['data_notices'] = {n:(LEGACY/n).read_text() for n in NOTICES}
    return p


class CatalogMigration(unittest.TestCase):
    def test_pinned_data_and_exact_catalog(self):
        manifest = json.loads((Path(__file__).parent/'fixtures/film_catalog16_manifest.json').read_text())
        self.assertEqual(manifest['source_commit'], '8bcfd030551a87f82d1610f6b63974597ca8aaa0')
        self.assertEqual(set(F.ready_profile_ids()), IDS)
        catalog = json.loads((ROOT/'catalog.json').read_text())
        self.assertEqual({r['id'] for r in catalog['films']}, IDS)
        self.assertEqual(len(catalog['films']), 16)
        self.assertEqual(set(manifest['files']), {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()})
        for name, sha in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), sha, name)
        for row in catalog['films']:
            self.assertTrue((ROOT/row['preview']).is_file())
            p = F.load_profile(row['id'], models.GR3X.id)
            self.assertEqual(p['provenance']['project'], 'andreavolpato/spektrafilm')
            self.assertTrue(p['provenance']['base_model_id'].startswith('gr3-210-'))
            self.assertFalse(p['native_effect_verified'])
            self.assertFalse(p['compatibility']['native_effect_verified'])

    def test_every_new_recipe_keeps_license_and_full_numeric_values(self):
        for ident in sorted(IDS):
            for slot in range(8,12):
                with self.subTest(film=ident, slot=slot):
                    p = F.load_profile(ident, models.GR3X.id)
                    before = copy.deepcopy(p)
                    packet = R.encode(p, slot)
                    got = R.decode(packet)
                    self.assertLessEqual(len(packet), R.MAX_PACKET)
                    self.assertEqual(got['slot'], slot)
                    for key in R.FIELDS:
                        self.assertEqual(got['profile'][key], p[key])
                    self.assertEqual(got['profile']['data_notices'], {n:(ROOT/n).read_text() for n in NOTICES})
                    self.assertEqual(D.extract(D.embed(fixture(), packet)), packet)
                    self.assertEqual(p, before)

    def test_old_eight_same_ids_restore_exact_old_values_and_notices(self):
        for path in sorted((LEGACY/'camera').glob('*.json')):
            with self.subTest(film=path.stem):
                old = legacy(path.stem)
                old_packet = R.encode(old, 8)
                new_packet = R.encode(F.load_profile(path.stem, models.GR3X.id), 8)
                self.assertNotEqual(R.decode(old_packet)['numeric_sha256'], R.decode(new_packet)['numeric_sha256'])
                with patch.object(F, 'load_profile', side_effect=AssertionError('restore looked up current catalog')):
                    restored = R.restored_profile(D.extract(D.embed(fixture(), old_packet)))
                    for key in R.FIELDS:
                        self.assertEqual(restored[key], old[key])
                    self.assertEqual(restored['data_notices'], old['data_notices'])
                    self.assertEqual(R.decode(R.encode(restored, 11))['profile']['data_notices'], old['data_notices'])


@unittest.skipUnless(os.environ.get('DARKSLIDE_GR3X_PAYLOAD'), 'IIIx original required')
class LegacyAdmission(unittest.TestCase):
    def test_old_rejected_values_still_rejected_after_catalog_update(self):
        raw = Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        limits = E.factory_envelope_from_payload(raw)
        for name in ('ektar100','xtra400_portraendura'):
            old = legacy(name)
            self.assertFalse(P.readiness(old, limits)['numeric_installable'])
            self.assertTrue(P.readiness(F.load_profile(name, models.GR3X.id), limits)['numeric_installable'])
            for slot in range(8,12):
                with self.subTest(film=name,slot=slot), self.assertRaisesRegex(ValueError,'矩阵超出'):
                    W.plan_offline(raw,[dict(kind='film',slot=slot,film=name)],{name:old})

try:
    import unicorn
except ImportError:
    unicorn = None


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD'), 'IIIx original and Unicorn required')
class RuntimeCatalog(unittest.TestCase):
    def test_all_sixteen_current_slots_equal_saved_recipe_runtime(self):
        import gr3x_recipe_machine as M
        from darkslide.gr3x_inplace_readback import nodes
        raw = Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        for name in sorted(IDS):
            machine = M.Machine(raw, {slot:name for slot in range(8,12)})
            source = F.load_profile(name, models.GR3X.id)
            for slot in range(8,12):
                with self.subTest(film=name, slot=slot):
                    packet = machine.packets[slot]
                    applied = R.decode(packet)['profile']
                    for source_curve, saved in zip(source['curves_u14'], applied['curves_u14']):
                        k = nodes(tuple(source_curve))
                        self.assertEqual(saved, [k[x//8]+(k[x//8+1]-k[x//8])*(x%8)//8 for x in range(256)])
                    photo = machine.submit(slot, photo=0, selector=slot+1)
                    current = machine.make(photo)
                    machine.restore(packet)
                    restored_photo = machine.submit(slot, photo=1)
                    restored = machine.make(restored_photo)
                    M.validate_consumption(machine, restored_photo, packet, restored)
                    for field in ('base','rgb','post','registers'):
                        self.assertEqual(current[field], restored[field])
                    machine.canaries()

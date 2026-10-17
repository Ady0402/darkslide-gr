"""Source plumbing tests, not evidence of numerical LUT-fit quality or camera operation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from darkslide import film_profiles, fwread, server, template
from darkslide.store import Store, StoreError, write_json
from test_film_picker import cube

class PersistedSources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.project = self.store.create_project('test', self.store.put_input(b'fixture'), template.load())
        self.pid = self.project['id']
        project_path = self.store._dir(self.pid) / 'project.json'
        saved = json.loads(project_path.read_text())
        saved['input_sha256'] = fwread.V210_INPUT_SHA256
        write_json(project_path, saved)
        self.entry = self.store.put_film_lut(self.pid, cube(), 'mine.cube')
        self.ident = self.entry['id']
        # Synthetic metadata plus valid numeric fixture: proves bindings, not fitting correctness.
        profile = copy.deepcopy(film_profiles.load_profile('gold200'))
        profile.update(id=self.ident, provenance=dict(kind='user_lut', fitter='darkslide-film-fit-v2',
            source_sha256=self.entry['sha256'], official_sha256=fwread.V210_INPUT_SHA256,
            base_model_id='gr3-210-upstream-neutral-stubbed-v2', base_values_sha256='0'*64,
            target_ev=0, target_input_encoding='srgb', mid_index=7.8))
        report = dict(fitter='darkslide-film-fit-v2', layout='four_curve_v1',
                      base_model_id=profile['provenance']['base_model_id'])
        self.store.set_film_lut_fit(self.pid, self.ident, profile, report, cube())
        self.path = self.store._dir(self.pid) / 'film_luts.json'

    def test_reopen_preserves_source_and_rejects_tampered_cube(self):
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.film_lut_profiles(self.pid, [self.ident])[self.ident]['id'], self.ident)
        reopened.film_lut_path(self.pid, self.ident).write_bytes(cube(title='changed'))
        with self.assertRaises(StoreError): reopened.film_lut_profiles(self.pid, [self.ident])

    def test_source_identity_fields_are_required(self):
        original = self.store.film_luts(self.pid)
        for field, value in [('source_sha256','f'*64), ('official_sha256','f'*64),
                             ('fitter','unknown'), ('base_model_id','unknown'), ('target_ev',1)]:
            with self.subTest(field=field):
                record = copy.deepcopy(original)
                record[self.ident]['profile']['provenance'][field] = value
                write_json(self.path, record)
                with self.assertRaises(StoreError): self.store.film_lut_profiles(self.pid,[self.ident])
        write_json(self.path, original)

    def test_malformed_records_are_store_errors(self):
        original = self.store.film_luts(self.pid)
        for field in ('profile', 'fit', 'bake'):
            record = copy.deepcopy(original); record[self.ident][field] = [1]
            write_json(self.path,record)
            with self.assertRaises(StoreError): self.store.film_lut_profiles(self.pid,[self.ident])
        record = copy.deepcopy(original); record[self.ident]['profile']['provenance'] = [1]
        write_json(self.path, record)
        with self.assertRaises(StoreError): self.store.film_lut_profiles(self.pid,[self.ident])

    def test_bake_resolves_only_matching_slot_without_touching_other_edits(self):
        record=self.store.film_luts(self.pid)
        record[self.ident]['bake']={'film':'gold200','grade':{'temp':5}}
        write_json(self.path,record)
        changes={'8':{'film':'gold200','grade':{'temp':5}},'9':{'film':'portra400'},'2':{'name':'name'}}
        result=self.store.film_changes_for_generate(self.pid,changes)
        self.assertEqual(result['8']['film'],self.ident)
        self.assertEqual(result['9'],changes['9']); self.assertEqual(result['2'],changes['2'])
        self.assertEqual(changes['8']['film'],'gold200')
        changes['8']['grade']={'temp':6}
        with self.assertRaises(StoreError): self.store.film_changes_for_generate(self.pid,changes)

    def test_prepare_requires_saved_expected_snapshot_before_unpack(self):
        req=SimpleNamespace(store=self.store,app=SimpleNamespace(template=template.load()),
                            read_json=lambda: {'expected_changes':{'8':{'film':'gold200'}},'request_id':'a'})
        with mock.patch.object(fwread,'unpack',side_effect=AssertionError('must not decode')) as unpack:
            with self.assertRaises(server.ApiError) as raised:server.api_film_prepare(req,self.pid)
            self.assertEqual(raised.exception.status,409)
            unpack.assert_not_called()

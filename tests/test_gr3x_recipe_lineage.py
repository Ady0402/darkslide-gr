"""Grading provenance plumbing; numeric fitting and native execution are separate tests."""
import copy
import hashlib
import io
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from darkslide import server, models, film_profiles as F, photo_recipe as R
from darkslide import gr3x_recipe_lineage as L, gr3x_camera_preview as P
from darkslide import photo_recipe_export
from darkslide.store import Store, StoreError, write_json
from test_iiix_desktop import request, CUBE
from test_gr3x_catalog16 import legacy


class RecipeLineage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = server.App(self.tmp.name)
        self.store = self.app.store
        with patch.object(self.store, 'has_input', return_value=True):
            self.pid = self.store.create_project('lineage', models.GR3X.input_sha,
                models.template_for(models.GR3X), camera_variant='GR IIIx')['id']
        self.addCleanup(patch.stopall)
        patch.object(server, '_camera_model', return_value={'values': []}).start()
        patch.object(server, '_factory_envelope', return_value={}).start()
        self.fit = patch.object(server.film_fit, 'fit_cube', side_effect=self.fake_fit).start()
        patch.object(P, 'installed_fit_report', side_effect=lambda d,c,p,r,e:r).start()
        patch.object(P, 'preview', return_value=CUBE).start()

    def fake_fit(self, data, ident, *args, **kwargs):
        p = F.load_profile('gold200', models.GR3X.id)
        base = 'gr3x-160-upstream-neutral-stubbed-v2'
        p.update(id=ident, official_sha256=models.GR3X.input_sha, base_model_id=base,
            provenance=dict(kind='user_lut', fitter=server.film_fit.IIIX_FITTER_ID,
                source_sha256=hashlib.sha256(data).hexdigest(), official_sha256=models.GR3X.input_sha,
                base_model_id=base, base_values_sha256='0'*64, target_ev=0,
                target_input_encoding='srgb', mid_index=7.8))
        return p, dict(fitter=server.film_fit.IIIX_FITTER_ID, layout='four_curve_v1', base_model_id=base)

    def bake(self, film='gold200', grade=None, cube=CUBE):
        return server.api_bake_grade(request(self.app, dict(cube=cube.decode(), film=film,
            grade={'exp':10} if grade is None else grade)), self.pid)

    def profile(self, ident):
        return Store(self.tmp.name).film_lut_profiles(self.pid, [ident])[ident]

    def test_all_sixteen_grades_keep_source_adjustments_and_notices_in_packet(self):
        for film in F.ready_profile_ids():
            with self.subTest(film=film):
                got = self.bake(film)
                p = self.profile(got['id'])
                for slot in range(8, 12):
                    saved = R.decode(R.encode(p, slot))['profile']
                    self.assertEqual(saved['recipe_derivation']['source']['id'], film)
                    self.assertEqual(saved['recipe_derivation']['grade'], {'exp':10})
                    original = R.decode(R.encode(F.load_profile(film, models.GR3X.id), 8))
                    self.assertEqual(saved['data_notices'], original['profile']['data_notices'])
                    self.assertEqual(saved['recipe_derivation']['source']['numeric_sha256'], original['numeric_sha256'])

    def test_history_then_same_cube_second_grade_keeps_old_notices_and_lineage(self):
        packet = R.encode(legacy('gold200'), 9)
        historical = self.store.put_photo_recipe(self.pid, packet)
        first = self.bake(historical['id'])
        p1 = self.profile(first['id'])
        # Same bytes/ID: capture the parent before put_film_lut replaces its bake.
        second = self.bake(first['id'], {'temp':5})
        self.assertEqual(second['id'], first['id'])
        p2 = self.profile(second['id'])
        self.assertEqual(p2['data_notices'], historical['data_notices'])
        self.assertEqual(p2['recipe_derivation']['source']['recipe_derivation'], p1['recipe_derivation'])
        source = p1['recipe_derivation']['source']
        self.assertEqual(source['photo_snapshot']['packet_sha256'], R.decode(packet)['packet_sha256'])
        encoded = R.encode(p2, 10)
        restored = R.restored_profile(encoded)
        third = self.store.put_photo_recipe(self.pid, encoded)
        self.assertEqual(third['recipe_derivation'], restored['recipe_derivation'])
        with zipfile.ZipFile(io.BytesIO(photo_recipe_export.export_bundle(encoded, CUBE.decode(), {}))) as z:
            for name, value in historical['data_notices'].items():
                self.assertEqual(z.read('film_data/source-notices/'+name).decode(), value)
            self.assertEqual(z.read('film_data/restored-profile.dsfr'), encoded)

    def test_changed_source_fit_failure_cannot_reuse_old_fit(self):
        first = self.bake()
        with patch.object(server.film_fit, 'fit_cube', side_effect=ValueError('fit failed')):
            with self.assertRaisesRegex(ValueError, 'fit failed'):
                self.bake('5203', {'temp':4})
        self.assertFalse(self.store.list_film_luts(self.pid)[0]['fitted'])
        self.assertIsNone(self.store.bake_for(self.pid, '5203', {'temp':4}))
        with self.assertRaises(StoreError):self.profile(first['id'])
        # A later retry reads the frozen source, without consulting today's catalog.
        original = self.fake_fit(CUBE, first['id'])
        with patch.object(F, 'load_profile', side_effect=AssertionError('catalog lookup')), \
                patch.object(server.film_fit, 'fit_cube', return_value=original):
            server._fit_and_keep(request(self.app), self.pid, first['id'])
        self.assertEqual(self.profile(first['id'])['recipe_derivation']['source']['id'], '5203')

    def test_mutation_during_fit_refuses_to_publish(self):
        def change(data, ident, *args, **kwargs):
            record = self.store.film_luts(self.pid)
            record[ident]['bake']['grade'] = {'exp':20}
            write_json(self.store._dir(self.pid)/'film_luts.json', record)
            return self.fake_fit(data, ident)
        self.fit.side_effect = change
        with self.assertRaisesRegex(server.ApiError, '来源改变'):self.bake()
        self.assertFalse(self.store.list_film_luts(self.pid)[0]['fitted'])

    def test_legacy_or_tampered_bake_refused_until_rebuilt(self):
        first = self.bake()
        path = self.store._dir(self.pid)/'film_luts.json'
        good = self.store.film_luts(self.pid)
        for mutation in ('legacy', 'wrong_grade', 'wrong_notice', 'wrong_source'):
            broken = copy.deepcopy(good)
            entry = broken[first['id']]
            if mutation == 'legacy':del entry['bake']['recipe_source']
            elif mutation == 'wrong_grade':entry['bake']['grade'] = {'exp':11}
            elif mutation == 'wrong_notice':entry['profile']['data_notices'] = {}
            else:entry['bake']['recipe_source']['source']['id'] = '5203'
            write_json(path, broken)
            with self.subTest(case=mutation), self.assertRaises(ValueError):self.profile(first['id'])
            self.assertFalse(self.store.list_film_luts(self.pid)[0]['fitted'])
            self.assertIsNone(self.store.bake_for(self.pid, entry['bake']['film'], entry['bake']['grade']))
        write_json(path, good)

    def test_oversize_notice_rejects_fit_without_losing_original_photo(self):
        p = legacy('gold200')
        p['data_notices']['CHANGELOG.txt'] = 'x'*R.MAX_META
        with self.assertRaisesRegex(ValueError, '容量'):R.encode(p, 8)
        record = self.bake()['bake']
        record['recipe_source']['data_notices']['extra.txt'] = 'x'*R.MAX_META
        with self.assertRaisesRegex(ValueError, '容量'):
            L.attach(self.fake_fit(CUBE, 'user_lut_0123456789ab')[0], record)

    def test_unfitted_user_lut_comments_and_plain_grade_have_explicit_sources(self):
        cube = b'# Author: example user\n# licence supplied by the user\n'+CUBE
        entry = self.store.put_film_lut(self.pid, cube, 'mine.cube')
        got = self.bake(entry['id'], cube=b'# derived\n'+CUBE)
        p = self.profile(got['id'])
        self.assertEqual(p['recipe_derivation']['source']['source_sha256'], hashlib.sha256(cube).hexdigest())
        self.assertIn('Author: example user', p['data_notices']['SOURCE_LUT_COMMENTS.txt'])
        plain = self.profile(self.bake(None, cube=b'# plain\n'+CUBE)['id'])
        self.assertIsNone(plain['recipe_derivation']['source'])
        self.assertEqual(plain['data_notices'], {})

    def test_lut_only_controls_are_recorded_as_omitted_not_applied(self):
        grade = {'temp':5, 'vib':20, 'hH':[10,0,0,0,0,0,0,0]}
        p = self.profile(self.bake(grade=grade)['id'])
        self.assertEqual(p['recipe_derivation']['grade'], grade)
        self.assertEqual(p['recipe_derivation']['camera_omitted_adjustments'], ['hH','vib'])

    def test_already_fitted_uploaded_lut_keeps_original_comment_notice(self):
        raw = b'# Copyright example author\n# user-supplied licence text\n'+CUBE
        entry = self.store.put_film_lut(self.pid, raw, 'source.cube')
        server._fit_and_keep(request(self.app), self.pid, entry['id'])
        result = self.bake(entry['id'], cube=b'# derived output\n'+CUBE)
        p = self.profile(result['id'])
        key = 'SOURCE_LUT_'+hashlib.sha256(raw).hexdigest()+'.txt'
        self.assertEqual(p['data_notices'][key], '# Copyright example author\n# user-supplied licence text')
        self.assertEqual(R.decode(R.encode(p,8))['profile']['data_notices'], p['data_notices'])


class OutOfRangeIIIx(unittest.TestCase):
    """User, 2026-10-17: check first, never keep a fit the camera cannot hold; the IIIx side the same as GR III."""
    setUp, fake_fit, bake = RecipeLineage.setUp, RecipeLineage.fake_fit, RecipeLineage.bake

    def test_out_of_range_is_refused_before_anything_is_kept(self):
        bad = ['曲线起点 2000 超出原厂范围（0～1920）']
        entry = self.store.put_film_lut(self.pid, CUBE, 'mine.cube')
        with patch.object(server.film_fit, 'envelope_violations', return_value=bad):
            with self.assertRaises(server.ApiError) as got:
                server._fit_and_keep(request(self.app), self.pid, entry['id'])
            self.assertEqual(got.exception.status, 422)
            self.assertIn('曲线起点 2000', str(got.exception))
            listed = self.store.list_film_luts(self.pid)[0]
            self.assertFalse(listed['fitted']); self.assertIsNone(listed['fit'])
            self.assertEqual(listed['check']['writable'], False); self.assertEqual(listed['check']['violations'], bad)
            self.assertEqual(listed['check']['model_id'], models.GR3X.id)
            with self.assertRaises(server.ApiError) as got:
                self.bake(cube=b'# a grade made in the page\n' + CUBE)
            self.assertEqual(got.exception.status, 422)
            self.assertEqual([l['id'] for l in self.store.list_film_luts(self.pid)], [entry['id']],
                             'a refused 调色 leaves nothing behind')
        # The IIIx-only 33-knot rebuild check refuses the same way.
        with patch.object(P, 'installed_fit_report', side_effect=ValueError('重建后差太多')):
            with self.assertRaises(server.ApiError) as got:
                server._fit_and_keep(request(self.app), self.pid, entry['id'])
            self.assertEqual(got.exception.status, 422)
            self.assertIn('重建后差太多', str(got.exception))
        # The IIIx rebuild names both curve ends; the user sees only the end that is out, worded as on GR III.
        ends = server.film_requests.FilmRequestError(
            '胶片重建曲线起点或终点超出原厂数值边界：起点 4970（原厂 0～1920），终点 16382（原厂 12694～16383）')
        with patch.object(server.film_fit, 'fit_cube', side_effect=ends):
            with self.assertRaises(server.ApiError) as got:
                server._fit_and_keep(request(self.app), self.pid, entry['id'])
        self.assertIn('超出了理光相机原厂的范围：曲线起点 4970 超出原厂范围（0～1920）', str(got.exception))
        self.assertNotIn('终点', str(got.exception))
        self.assertEqual(self.store.list_film_luts(self.pid)[0]['check']['violations'], ['曲线起点 4970 超出原厂范围（0～1920）'])
        fitted = server._fit_and_keep(request(self.app), self.pid, entry['id'])
        self.assertTrue(fitted['fitted']); self.assertIsNone(fitted.get('check'), 'a passing fit clears the refusal')

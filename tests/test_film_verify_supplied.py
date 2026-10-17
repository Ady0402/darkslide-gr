"""Independent Cloud-profile boundary; synthetic fixtures only, no writer import."""
import copy
import unittest
from unittest.mock import patch
from darkslide import film_verify
from tests.test_film_verify import SparseOriginal, overlay, profile


def custom(ident='user_lut_example'):
    value = profile(7)
    value['id'] = ident
    return value


def edit(slot=8, ident='user_lut_example'):
    return dict(kind='film', slot=slot, film=ident)


class SuppliedProfileReadbackTests(unittest.TestCase):
    def test_empty_boundary_without_file_read(self):
        with patch.object(film_verify, 'load_profiles', side_effect=AssertionError('unexpected file read')):
            self.assertEqual(film_verify.resolve_profiles([]), {})
            self.assertEqual(film_verify.resolve_profiles([], {}), {})
            for supplied in ([], False, {'user_lut_example': custom()}):
                with self.assertRaises(film_verify.FilmReadbackError):
                    film_verify.resolve_profiles([], supplied)

    def test_bundled_fallback_and_custom_are_separate(self):
        builtin = profile()
        supplied = custom()
        edits = [edit(9), edit(8, builtin['id']), edit(11)]
        expected_builtin = [edit(8, builtin['id'])]
        with patch.object(film_verify, 'load_profiles', return_value={builtin['id']: builtin}) as loader:
            actual = film_verify.resolve_profiles(edits, {supplied['id']: supplied})
            loader.assert_called_once_with(expected_builtin)
        self.assertEqual(actual, {builtin['id']: builtin, supplied['id']: supplied})
        self.assertIsNot(actual[builtin['id']], builtin)
        self.assertIsNot(actual[supplied['id']], supplied)

    def test_no_bundled_override_or_unselected_entry(self):
        builtin = profile()
        requests = [edit(8, builtin['id']), edit(9)]
        for supplied in ({builtin['id']: builtin}, {'user_lut_unselected': custom('user_lut_unselected')},
                         {5: custom()}, {'another_id': custom()}, [], True):
            with patch.object(film_verify, 'load_profiles', side_effect=AssertionError('read before rejection')):
                with self.assertRaises(film_verify.FilmReadbackError):
                    film_verify.resolve_profiles(requests, supplied)

    def test_custom_missing_and_id_mismatch_rejected(self):
        for supplied in (None, {}, {'user_lut_example': custom('user_lut_other')}):
            with self.assertRaises(film_verify.FilmReadbackError):
                film_verify.resolve_profiles([edit()], supplied)

    def test_numeric_snapshot_has_no_caller_alias(self):
        source = custom()
        source['ignored_extension'] = {'descriptive': ['Cloud metadata']}
        supplied = {source['id']: source}
        before = copy.deepcopy(supplied)
        result = film_verify.resolve_profiles([edit()], supplied)
        self.assertEqual(supplied, before)
        self.assertNotIn('ignored_extension', result[source['id']])
        source['look_matrix_q13'][0][0] = 0
        source['curves_u14'][2][255] = 0
        source['post_matrix_q512'][0][0] = 0
        actual = result['user_lut_example']
        self.assertEqual(actual['look_matrix_q13'], before['user_lut_example']['look_matrix_q13'])
        self.assertEqual(actual['curves_u14'], before['user_lut_example']['curves_u14'])
        self.assertEqual(actual['post_matrix_q512'], before['user_lut_example']['post_matrix_q512'])
        actual['curves_u14'][0][0] = 16383
        self.assertNotEqual(source['curves_u14'][0][0], actual['curves_u14'][0][0])

    def test_strict_schema_curve_and_accumulation_guard(self):
        good = custom()
        mutations = [
            ('schema', True), ('model', 'GR IV'), ('firmware', '1.81'),
            ('look_matrix_q13', [[8192, 0, 0], [0, 8192, 0], [0, 0, False]]),
            ('curves_u14', [[0] * 256] * 2),
            ('curves_u14', [[16384] * 256] * 3),
            ('curves_u14', [[True] * 256] * 3),
            ('post_matrix_q512', [[32767, -32768, 513]] * 3),
            ('post_matrix_q512', [[512, 0, 0], [0, 512, 0], [0, 0, float('nan')]])]
        for field, value in mutations:
            bad = copy.deepcopy(good)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(film_verify.FilmReadbackError):
                film_verify.resolve_profiles([edit()], {bad['id']: bad})

    def test_request_gate_precedes_profile_access(self):
        for edits in ([edit(True)], [edit(7)], [edit(8), edit(8)],
                      [dict(kind='film', slot=8, film='../bad')],
                      [dict(kind='film', slot=8, film='user_lut_example', extra=1)]):
            with patch.object(film_verify, 'load_profiles', side_effect=AssertionError('unexpected file read')):
                with self.assertRaises(film_verify.FilmReadbackError):
                    film_verify.resolve_profiles(edits, {'user_lut_example': custom()})

    def test_synthetic_readback_all_slots_and_same_custom(self):
        # Sparse synthetic source and independent operand fixture, no assembler
        # or writer and no full original/modified payload allocation.
        original = SparseOriginal()
        supplied = {'user_lut_example': custom()}
        for mask in range(1, 16):
            requests = [edit(slot) for slot in (8, 9, 10, 11) if mask & (1 << (slot - 8))]
            profiles = film_verify.resolve_profiles(requests, supplied)
            expected = film_verify.derive_expected(original.read, requests, profiles)
            _, read = overlay(original, expected)
            result = film_verify.readback_windows(original.read, read, expected)
            self.assertTrue(result.passed, result.checks)
            self.assertLessEqual(expected.arena_used, 4096)

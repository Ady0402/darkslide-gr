from firmware_registry_fixture import base_identity
"""Independent RPC/data boundary checks. No Unicorn import or firmware execution."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from darkslide import base_curve as actual

PAYLOAD_SHA = '53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703'


def fixture(directory):
    directory = Path(directory)
    original = directory / 'synthetic.bin'
    original.write_bytes(b'independent synthetic input; not firmware')
    origin = directory / 'unicorn' / '__init__.py'
    origin.parent.mkdir()
    origin.write_bytes(b'# independent mock package\n')
    helper = origin.with_name('helper.py')
    helper.write_bytes(b'# second independently fingerprinted file\n')
    library = origin.parent / 'lib' / 'libunicorn.2.dylib'
    library.parent.mkdir()
    library.write_bytes(b'independent mock library; never loaded')
    # Assemble the declared package fingerprint directly, not through the
    # production backend-identity function used under test.
    fingerprint = hashlib.sha256()
    for name, data in (('__init__.py', origin.read_bytes()), ('helper.py', helper.read_bytes())):
        fingerprint.update(name.encode('utf-8'))
        fingerprint.update(data)
    backend = dict(package_path=str(origin.resolve()), package_sha256=fingerprint.hexdigest(),
                   library_path=str(library.resolve()), library_sha256=hashlib.sha256(library.read_bytes()).hexdigest())
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    result = dict(schema=1, model='GR III', firmware='2.10', official_sha256=sha,
                  payload_sha256=PAYLOAD_SHA, model_id=actual.MODEL_ID,
                  emulator_version='2.1.4', backend=backend, value_range=[0, 16384],
                  output_normalization_divisor=16384, settings=dict(tone=11, stage=1, slider_neutral_encoding=4),
                  values=list(range(255)) + [16384], location_verified=True,
                  emulated_original_arm_instructions=True, physical_target_cpu_executed=False,
                  native_effect_verified=False, full_modified_firmware_created=False,
                  assumptions=dict(base_write_coverage=512, original_guest_rom_read_only=True))
    return original, origin, library, sha, backend, result


def process(result):
    return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')


class IndependentBaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        actual._CACHE.clear()
        self.identity = base_identity(hashlib.sha256(b'independent synthetic input; not firmware').hexdigest())
        self.identity.__enter__();self.addCleanup(self.identity.__exit__,None,None,None)

    def test_bad_input_never_loads_backend_or_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'not_firmware.bin'
            path.write_bytes(b'not a Ricoh firmware file')
            with patch.object(actual.importlib.util, 'find_spec', side_effect=AssertionError('backend accessed')), \
                 patch.object(actual.subprocess, 'run', side_effect=AssertionError('worker executed')):
                with self.assertRaises(actual.BaseCurveError):
                    actual.base_curve(path)

    def test_independent_package_fingerprint_and_inclusive_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            original, origin, library, sha, backend, result = fixture(directory)
            self.assertEqual(actual._backend_identity(origin, library), backend)
            actual._validate_result(result, sha, backend)
            self.assertEqual(result['values'][-1], 16384)
            self.assertEqual(len(result['values']), 256)
            self.assertEqual(result['output_normalization_divisor'], 16384)

    def test_locked_worker_bootstrap_and_optimization_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            original, origin, library, sha, backend, result = fixture(directory)
            with base_identity(sha), \
                 patch.object(actual.importlib.util, 'find_spec', return_value=SimpleNamespace(origin=str(origin))), \
                 patch.object(actual.subprocess, 'run', return_value=process(result)) as run, \
                 patch.dict(actual.os.environ, {'PYTHONPATH': '/wrong/python', 'LIBUNICORN_PATH': '/wrong/native'}):
                self.assertEqual(actual.base_curve(original)['values'], result['values'])
                argv = run.call_args.args[0]
                self.assertEqual(argv[:3], [sys.executable, '-I', '-B'])
                self.assertEqual(argv.count('-O'), sys.flags.optimize)
                self.assertEqual(argv[-6:], [str(Path(actual.__file__).resolve().parent.parent),
                                            str(origin.resolve().parent.parent), 'darkslide.base_curve',
                                            '--worker', str(original.resolve()), json.dumps(backend)])
                env = run.call_args.kwargs['env']
                self.assertNotIn('PYTHONPATH', env)
                self.assertEqual(env['LIBUNICORN_PATH'], str(library.resolve().parent))
                self.assertEqual(run.call_args.kwargs['timeout'], 60)

    def test_cache_isolated_and_source_identity_change_invalidates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            original, origin, library, sha, backend, result = fixture(directory)
            with base_identity(sha), \
                 patch.object(actual.importlib.util, 'find_spec', return_value=SimpleNamespace(origin=str(origin))), \
                 patch.object(actual.subprocess, 'run', return_value=process(result)) as run:
                first = actual.base_curve(original)
                first['values'][255] = 3
                first['assumptions']['base_write_coverage'] = 0
                second = actual.base_curve(original)
                self.assertEqual(second['values'][255], 16384)
                self.assertEqual(second['assumptions']['base_write_coverage'], 512)
                self.assertEqual(run.call_count, 1)
                library.write_bytes(b'changed synthetic native identity')
                # Old JSON backend cannot be admitted under the new binary key.
                with self.assertRaises(actual.BaseCurveError):
                    actual.base_curve(original)
                self.assertEqual(run.call_count, 2)
                original.write_bytes(b'changed input')
                with self.assertRaises(actual.BaseCurveError):
                    actual.base_curve(original)
                self.assertEqual(run.call_count, 2)

    def test_fixed_schema_model_and_scope_flags_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, sha, backend, good = fixture(directory)
            mutations = [('schema', True), ('schema', 2), ('model', 'GR IV'), ('firmware', '1.81'),
                         ('official_sha256', '0' * 64), ('payload_sha256', '0' * 64),
                         ('model_id', 'other-model'), ('emulator_version', '2.1.3'),
                         ('value_range', [False, 16384]), ('output_normalization_divisor', 16384.0),
                         ('settings', dict(tone=11, stage=True, slider_neutral_encoding=4)),
                         ('emulated_original_arm_instructions', 1), ('physical_target_cpu_executed', True),
                         ('native_effect_verified', True), ('full_modified_firmware_created', True),
                         ('location_verified', 1), ('backend', dict(backend, additional='unknown'))]
            for key, value in mutations:
                bad = copy.deepcopy(good)
                bad[key] = value
                with self.subTest(field=key), self.assertRaises(actual.BaseCurveError):
                    actual._validate_result(bad, sha, backend)
            for missing in ('schema', 'payload_sha256', 'backend', 'settings', 'location_verified'):
                bad = copy.deepcopy(good)
                bad.pop(missing)
                with self.assertRaises(actual.BaseCurveError):
                    actual._validate_result(bad, sha, backend)

    def test_values_and_write_coverage_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, sha, backend, good = fixture(directory)
            for values in ([0] * 255, [0] * 257, [True] * 256, [0.0] * 256, [-1] * 256,
                           [16385] * 256, [float('nan')] * 256, tuple(range(256))):
                bad = dict(good, values=values)
                with self.assertRaises(actual.BaseCurveError):
                    actual._validate_result(bad, sha, backend)
            for assumptions in ({}, dict(base_write_coverage=511, original_guest_rom_read_only=True),
                                dict(base_write_coverage=512.0, original_guest_rom_read_only=True),
                                dict(base_write_coverage=512, original_guest_rom_read_only=1)):
                with self.assertRaises(actual.BaseCurveError):
                    actual._validate_result(dict(good, assumptions=assumptions), sha, backend)

    def test_crash_timeout_and_malformed_stdout_never_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            original, origin, _, sha, _, good = fixture(directory)
            cases = (SimpleNamespace(returncode=-4, stdout='', stderr='synthetic SIGILL'),
                     SimpleNamespace(returncode=1, stdout='', stderr='synthetic failure'),
                     SimpleNamespace(returncode=0, stdout='not JSON', stderr=''),
                     SimpleNamespace(returncode=0, stdout='[]', stderr=''),
                     process(dict(good, schema=True)))
            with base_identity(sha), \
                 patch.object(actual.importlib.util, 'find_spec', return_value=SimpleNamespace(origin=str(origin))):
                for item in cases:
                    with patch.object(actual.subprocess, 'run', return_value=item):
                        with self.assertRaises(actual.BaseCurveError):
                            actual.base_curve(original)
                        self.assertEqual(actual._CACHE, {})
                with patch.object(actual.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic', 60)):
                    with self.assertRaises(actual.BaseCurveError):
                        actual.base_curve(original)
                    self.assertEqual(actual._CACHE, {})

    def test_missing_or_ambiguous_backend_never_executes_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            original, origin, library, sha, _, _ = fixture(directory)
            with base_identity(sha), \
                 patch.object(actual.subprocess, 'run', side_effect=AssertionError('worker executed')):
                with patch.object(actual.importlib.util, 'find_spec', return_value=None):
                    with self.assertRaises(actual.BaseCurveError):
                        actual.base_curve(original)
                second = library.with_name('other_unicorn.dylib')
                second.write_bytes(b'never loaded')
                with patch.object(actual.importlib.util, 'find_spec', return_value=SimpleNamespace(origin=str(origin))):
                    with self.assertRaises(actual.BaseCurveError):
                        actual.base_curve(original)

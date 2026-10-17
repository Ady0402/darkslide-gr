import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from darkslide import base_curve_python as adapter


class AdapterTests(unittest.TestCase):
    def setUp(self):
        adapter._CACHE.clear()
        adapter._ROM_CACHE.clear()

    def test_read_errors_have_public_error_type(self):
        self.assertIs(adapter.BaseCurveError, adapter.BaseCurvePythonError)
        with patch.object(Path, 'read_bytes', side_effect=OSError('synthetic unreadable file')):
            with self.assertRaises(adapter.BaseCurveError): adapter._source_identity()
            with self.assertRaises(adapter.BaseCurveError): adapter._original_sha(Path('/synthetic'))
            with self.assertRaises(adapter.BaseCurveError): adapter.base_curve('/synthetic')

    def test_invalid_settings_before_original_read(self):
        for value in (False, [], {'key':True}, {'shadow':0.0}, {'highlight':5}, {'unexpected':0}):
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must reject before any read')):
                with self.assertRaises(adapter.BaseCurvePythonError): adapter.base_curve('/missing', value)

    def test_source_change_refuses_cached_use(self):
        with patch.object(adapter,'_source_identity',return_value=('changed',)):
            with self.assertRaises(adapter.BaseCurvePythonError): adapter.base_curve('/missing')

    def test_original_identity_rejects_before_compute(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'own'; p.write_bytes(b'own synthetic input')
            with patch.object(adapter,'_compute',side_effect=AssertionError('must reject wrong original')):
                with self.assertRaises(adapter.BaseCurvePythonError): adapter.base_curve(p)

    def test_payload_identity_before_interpreter(self):
        with patch.object(adapter.fwread,'unpack',return_value=b'wrong decoded'), patch.object(adapter.interpreter,'CPU',side_effect=AssertionError('no interpreter')):
            with self.assertRaises(adapter.BaseCurvePythonError): adapter._decode_rom(b'synthetic')

    def test_normalized_cache_settings_and_defensive_copies(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'own'; raw = bytes(30391780); path.write_bytes(raw)
            synthetic = dict(values=[1]*256, settings=dict(key=0,contrast=0,highlight=0,shadow=0))
            with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()), patch.object(adapter,'_compute',return_value=synthetic) as compute:
                first = adapter.base_curve(path)
                first['values'][0] = 99; first['settings']['key'] = 4
                empty = adapter.base_curve(path, {'key':0})
                self.assertEqual(empty['values'][0], 1)
                self.assertEqual(empty['settings']['key'], 0)
                self.assertEqual(compute.call_count, 1)
                adapter.base_curve(path, {'contrast':1})
                self.assertEqual(compute.call_count, 2)
                self.assertEqual(compute.call_args[0][1]['contrast'], 1)

    def test_source_changes_during_original_read_refuse_warm_cache(self):
        with tempfile.TemporaryDirectory() as d:
            path = (Path(d)/'own').resolve(); raw = bytes(30391780); path.write_bytes(raw)
            synthetic = dict(values=[1]*256, settings=dict(key=0,contrast=0,highlight=0,shadow=0))
            with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()), patch.object(adapter,'_compute',return_value=synthetic):
                adapter.base_curve(path)
                state = [False]; original_read = Path.read_bytes
                def read_changes_source(p):
                    result = original_read(p)
                    if p.resolve() == path: state[0] = True
                    return result
                def source_identity():
                    return ('changed',) if state[0] else adapter._IMPORTED_SOURCE
                with patch.object(adapter,'_source_identity',side_effect=source_identity), patch.object(Path,'read_bytes',read_changes_source):
                    with self.assertRaises(adapter.BaseCurvePythonError): adapter.base_curve(path)

    def test_source_changes_during_final_original_recheck(self):
        for warm in (False, True):
            with tempfile.TemporaryDirectory() as d:
                adapter._CACHE.clear()
                path=(Path(d)/'own').resolve(); raw=bytes(30391780);path.write_bytes(raw)
                synthetic=dict(values=[1]*256)
                with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()), patch.object(adapter,'_compute',return_value=synthetic):
                    if warm: adapter.base_curve(path)
                    state=[False]; original_sha=adapter._original_sha
                    def final_read(p):
                        result=original_sha(p);state[0]=True;return result
                    def source_identity():
                        return ('changed',) if state[0] else adapter._IMPORTED_SOURCE
                    with patch.object(adapter,'_original_sha',side_effect=final_read),patch.object(adapter,'_source_identity',side_effect=source_identity):
                        with self.assertRaises(adapter.BaseCurveError):adapter.base_curve(path)

    def test_rom_cache_identity_immutable_and_failed_decode(self):
        raw=bytes(30391780); own_rom=bytes(0x10b55c0)
        with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()),patch.object(adapter,'_decode_rom',return_value=own_rom) as decode:
            first=adapter._rom(raw);second=adapter._rom(raw)
            self.assertIs(first,second);self.assertIs(type(first),bytes)
            self.assertEqual(decode.call_count,1)
            with self.assertRaises(adapter.BaseCurveError):adapter._rom(b'wrong input')
            self.assertEqual(decode.call_count,1)
        adapter._ROM_CACHE.clear()
        with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()),patch.object(adapter,'_decode_rom',return_value=bytearray(0x10b55c0)):
            with self.assertRaises(adapter.BaseCurveError):adapter._rom(raw)
            self.assertEqual(adapter._ROM_CACHE,{})

    def test_rom_decode_source_change_does_not_cache(self):
        raw=bytes(30391780)
        with patch.object(adapter.fwread,'V210_INPUT_SHA256',hashlib.sha256(raw).hexdigest()),patch.object(adapter,'_decode_rom',return_value=bytes(0x10b55c0)),patch.object(adapter,'_source_identity',return_value=('changed',)):
            with self.assertRaises(adapter.BaseCurveError):adapter._rom(raw)
            self.assertEqual(adapter._ROM_CACHE,{})

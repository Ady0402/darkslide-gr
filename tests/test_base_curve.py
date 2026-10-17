from firmware_registry_fixture import base_identity
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from darkslide import base_curve as module


class BaseCurveTests(unittest.TestCase):
    def setUp(self):module._CACHE.clear()
    def test_bad_original_rejected_without_backend(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"stock.bin";path.write_bytes(b"not firmware")
            with patch.object(module.importlib.util,"find_spec",side_effect=AssertionError("backend must not load")):
                with self.assertRaises(module.BaseCurveError):module.base_curve(path)

    def _fixture(self,d):
        d=Path(d);path=d/"input.bin";path.write_bytes(b"synthetic original")
        package=d/"unicorn";package.mkdir();file=package/"__init__.py";file.write_text("fixture")
        lib=package/"libunicorn.2.dylib";lib.write_bytes(b"synthetic library fingerprint")
        result=dict(schema=1,model="GR III",firmware="2.10",emulator_version="2.1.4",
            payload_sha256=module.fwread.V210["payload_sha256"],settings=dict(tone=11,stage=1,slider_neutral_encoding=4),backend=module._backend_identity(file,lib),value_range=[0,16384],output_normalization_divisor=16384,location_verified=True,
            emulated_original_arm_instructions=True,physical_target_cpu_executed=False,
            native_effect_verified=False,full_modified_firmware_created=False,
            assumptions=dict(base_write_coverage=512,original_guest_rom_read_only=True),values=list(range(256)),official_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),model_id=module.MODEL_ID)
        return path,file,result

    def test_cached_results_are_copies_and_input_still_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path,file,result=self._fixture(d)
            proc=SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr="")
            with base_identity(result["official_sha256"]),patch.object(module.importlib.util,"find_spec",return_value=SimpleNamespace(origin=str(file))),patch.object(module.subprocess,"run",return_value=proc) as run:
                first=module.base_curve(path);first["values"][2]=999
                self.assertEqual(module.base_curve(path)["values"][2],2);self.assertEqual(run.call_count,1)
                path.write_bytes(b"changed")
                with self.assertRaises(module.BaseCurveError):module.base_curve(path)

    def test_worker_crash_timeout_and_bad_data_close(self):
        with tempfile.TemporaryDirectory() as d:
            path,file,result=self._fixture(d)
            for process in (SimpleNamespace(returncode=-4,stdout="",stderr="SIGILL"),SimpleNamespace(returncode=0,stdout="bad",stderr=""),SimpleNamespace(returncode=0,stdout=json.dumps(dict(result,values=[True]*256)),stderr="")):
                with base_identity(result["official_sha256"]),patch.object(module.importlib.util,"find_spec",return_value=SimpleNamespace(origin=str(file))),patch.object(module.subprocess,"run",return_value=process):
                    with self.assertRaises(module.BaseCurveError):module.base_curve(path)
            with base_identity(result["official_sha256"]),patch.object(module.importlib.util,"find_spec",return_value=SimpleNamespace(origin=str(file))),patch.object(module.subprocess,"run",side_effect=subprocess.TimeoutExpired("test",60)):
                with self.assertRaises(module.BaseCurveError):module.base_curve(path)

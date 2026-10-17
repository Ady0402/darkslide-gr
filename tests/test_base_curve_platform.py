from firmware_registry_fixture import base_identity
"""Platform contract checks without loading DLLs or reading camera firmware."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from darkslide import base_curve as module


class BaseCurvePlatformTests(unittest.TestCase):
    def setUp(self):module._CACHE.clear()

    def _package(self,d):
        package=Path(d)/"组件目录"/"unicorn";package.mkdir(parents=True)
        origin=package/"__init__.py";origin.write_text("synthetic binding",encoding="utf-8")
        libdir=package/"lib";libdir.mkdir()
        return origin,libdir

    def test_mac_cpu_families_use_binding_library_name(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d)
            lib=libdir/"libunicorn.2.dylib";lib.write_bytes(b"synthetic Mac library")
            with patch.object(module.sys,"platform","darwin"):
                self.assertEqual(module._backend_library(origin),lib.resolve())

    def test_windows_dll_found_and_mac_library_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d)
            lib=libdir/"unicorn.dll";lib.write_bytes(b"synthetic Windows library")
            (libdir/"libunicorn.2.dylib").write_bytes(b"wrong platform")
            with patch.object(module.sys,"platform","win32"):
                self.assertEqual(module._backend_library(origin),lib.resolve())

    def test_missing_and_ambiguous_windows_libraries_close(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d)
            with patch.object(module.sys,"platform","win32"):
                with self.assertRaises(module.BaseCurveError):module._backend_library(origin)
                (libdir/"unicorn.dll").write_bytes(b"first")
                (origin.parent/"unicorn.dll").write_bytes(b"second")
                with self.assertRaises(module.BaseCurveError):module._backend_library(origin)

    def test_directory_is_not_a_library(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d);(libdir/"unicorn.dll").mkdir()
            with patch.object(module.sys,"platform","win32"):
                with self.assertRaises(module.BaseCurveError):module._backend_library(origin)

    def test_noncanonical_library_names_close(self):
        for platform,name in (("darwin","other_unicorn.dylib"),("win32","other_unicorn.dll")):
            with tempfile.TemporaryDirectory() as d:
                origin,libdir=self._package(d);(libdir/name).write_bytes(b"not binding's canonical filename")
                with patch.object(module.sys,"platform",platform):
                    with self.assertRaises(module.BaseCurveError):module._backend_library(origin)

    def test_extra_native_candidates_keep_conservative_rejection(self):
        for platform,name,other in (("darwin","libunicorn.2.dylib","other_unicorn.dylib"),("win32","unicorn.dll","other_unicorn.dll")):
            with tempfile.TemporaryDirectory() as d:
                origin,libdir=self._package(d)
                (libdir/name).write_bytes(b"canonical");(libdir/other).write_bytes(b"extra candidate")
                with patch.object(module.sys,"platform",platform):
                    with self.assertRaises(module.BaseCurveError):module._backend_library(origin)

    def test_unsupported_platform_closes(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d)
            with patch.object(module.sys,"platform","linux"):
                with self.assertRaises(module.BaseCurveError):module._backend_library(origin)

    def test_windows_worker_keeps_isolation_and_unicode_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            origin,libdir=self._package(d)
            lib=libdir/"unicorn.dll";lib.write_bytes(b"synthetic Windows library")
            path=Path(d)/"用户原件 带空格.bin";path.write_bytes(b"synthetic original")
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            result=dict(schema=1,model="GR III",firmware="2.10",emulator_version="2.1.4",
                payload_sha256=module.fwread.V210["payload_sha256"],settings=dict(tone=11,stage=1,slider_neutral_encoding=4),
                backend=module._backend_identity(origin,lib),value_range=[0,16384],output_normalization_divisor=16384,
                location_verified=True,emulated_original_arm_instructions=True,physical_target_cpu_executed=False,
                native_effect_verified=False,full_modified_firmware_created=False,
                assumptions=dict(base_write_coverage=512,original_guest_rom_read_only=True),values=list(range(256)),
                official_sha256=sha,model_id=module.MODEL_ID)
            proc=SimpleNamespace(returncode=0,stdout=json.dumps(result,ensure_ascii=False),stderr="")
            with patch.object(module.sys,"platform","win32"),base_identity(sha),\
                 patch.object(module.importlib.util,"find_spec",return_value=SimpleNamespace(origin=str(origin))),\
                 patch.dict(module.os.environ,{"PYTHONPATH":"untrusted override","LIBUNICORN_PATH":"untrusted library"}),\
                 patch.object(module.subprocess,"run",return_value=proc) as run:
                self.assertEqual(module.base_curve(path),result)
                args,kwargs=run.call_args;argv=args[0]
                self.assertIn("-I",argv);self.assertIn("-B",argv)
                self.assertEqual(argv[argv.index("-X")+1],"utf8")
                self.assertEqual(argv.count("-O"),module.sys.flags.optimize)
                self.assertIn(str(path.resolve()),argv)
                self.assertNotIn("PYTHONPATH",kwargs["env"])
                self.assertEqual(kwargs["env"]["LIBUNICORN_PATH"],str(libdir.resolve()))
                self.assertEqual(kwargs["encoding"],"utf-8")
                self.assertEqual(kwargs["timeout"],60)
                self.assertNotIn("shell",kwargs)


if __name__=="__main__":unittest.main()

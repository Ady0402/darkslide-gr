"""Portable discovery/argv tests. Simulated Windows discovery is not an OS run."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from darkslide import arm_compiler as A, film_arm_assemble as S, photo_recipe_native as N


class Discovery(unittest.TestCase):
    def test_explicit_path_with_spaces_is_one_executable(self):
        path = 'C:\\Program Files\\LLVM\\bin\\clang.exe'
        with patch.dict(os.environ, {'DARKSLIDE_CLANG':path}, clear=True), \
                patch.object(A.shutil,'which',return_value=path) as which:
            self.assertEqual(A.resolve_clang(),path)
            which.assert_called_once_with(path)

    def test_bad_override_never_falls_back(self):
        for value in ('', ' ', 'clang --unwanted-flag', '/missing/clang'):
            with self.subTest(value=value), patch.dict(os.environ,{'DARKSLIDE_CLANG':value},clear=True), \
                    patch.object(A.shutil,'which',return_value=None) as which:
                with self.assertRaisesRegex(ValueError,'DARKSLIDE_CLANG'):A.resolve_clang()
                self.assertLessEqual(which.call_count,1)

    def test_host_search_order(self):
        for platform, available, expected in (
                ('darwin', A.MAC_CLANG, [A.MAC_CLANG]),
                ('darwin', 'clang', [A.MAC_CLANG,'clang']),
                ('linux', 'clang', ['clang']),
                ('win32', 'clang', ['clang']),
                ('win32', '/Program Files/LLVM/bin/clang.exe',
                 ['clang','/Program Files/LLVM/bin/clang.exe'])):
            with self.subTest(platform=platform,available=available), \
                    patch.dict(os.environ,{'ProgramFiles':'/Program Files'},clear=True), \
                    patch.object(A.sys,'platform',platform), \
                    patch.object(A.shutil,'which',side_effect=lambda p:p if p==available else None) as which:
                self.assertEqual(A.resolve_clang(),available)
                self.assertEqual([c.args[0] for c in which.call_args_list],expected)

    def test_missing_compiler_is_actionable(self):
        with patch.dict(os.environ,{},clear=True), patch.object(A.shutil,'which',return_value=None):
            with self.assertRaisesRegex(ValueError,'armv7a-none-eabi'):A.resolve_clang()

    def test_non_arm_compiler_failure_has_no_object_fallback(self):
        result = subprocess.CompletedProcess([],1,'','unsupported target')
        with patch.object(A.shutil,'which',return_value='/clang'), \
                patch.object(subprocess,'run',return_value=result) as run:
            with self.assertRaisesRegex(ValueError,'unsupported target'):S.assemble('mov r0,#1',0x1000)
            with self.assertRaisesRegex(ValueError,'unsupported target'):N.compile_extension()
            for call in run.call_args_list:
                argv = call.args[0]
                self.assertEqual(argv[0],'/clang')
                self.assertIn('armv7a-none-eabi',argv)
                self.assertFalse(call.kwargs.get('shell',False))

    def test_installed_compiler_at_override_path_matches_default(self):
        try:compiler=A.resolve_clang()
        except ValueError as exc:self.skipTest(str(exc))
        if os.name=='nt':self.skipTest('symlink fixture needs no Windows privilege; real host test separate')
        expected=S.assemble('mov r0,#1\nbl abs(0x2000)',0x1000)
        native=N.compile_extension()
        with tempfile.TemporaryDirectory(prefix='LLVM 路径 ') as folder:
            executable=Path(folder)/'clang with spaces'
            executable.symlink_to(compiler)
            with patch.dict(os.environ,{'DARKSLIDE_CLANG':str(executable)}):
                self.assertEqual(S.assemble('mov r0,#1\nbl abs(0x2000)',0x1000),expected)
                actual=N.compile_extension()
        self.assertEqual(actual['code'],native['code'])
        self.assertEqual(actual['symbols'],native['symbols'])

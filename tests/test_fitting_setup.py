import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from darkslide import fitting_setup as fs


def fake_wheel(extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("unicorn/__init__.py", "")
        z.writestr("unicorn/lib/libunicorn.2.dylib", b"\0" * 10)
        z.writestr("unicorn-2.1.4.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        z.writestr("other/ignored.txt", "x")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def with_wheel(self, data, size=None, sha=None):
        w = dict(file="x.whl", path="aa/", size=len(data) if size is None else size,
                 sha256=sha or hashlib.sha256(data).hexdigest())
        return mock.patch.object(fs, "wheel", return_value=w)

    def test_status_states(self):
        with mock.patch.object(fs, "wheel", return_value=None):
            self.assertEqual(fs.status(self.root)["state"], "unsupported")
        with self.with_wheel(b"abc"):
            self.assertEqual(fs.status(self.root)["state"], "missing")
            (fs.deps_dir(self.root) / "unicorn").mkdir(parents=True)
            self.assertEqual(fs.status(self.root)["state"], "installed")
            fs._check_file(self.root).write_text(json.dumps({"ok": False}))
            self.assertEqual(fs.status(self.root)["state"], "failed")
            fs._check_file(self.root).write_text(json.dumps({"ok": True}))
            self.assertEqual(fs.status(self.root)["state"], "ready")

    def test_install_checks_fingerprint_and_unpacks_only_the_package(self):
        data = fake_wheel()
        with self.with_wheel(data), mock.patch.object(fs, "activate"):
            got = fs.install(self.root, fetch=lambda url: Response(data))
        self.assertEqual(got["state"], "installed")
        folder = fs.deps_dir(self.root)
        self.assertTrue((folder / "unicorn" / "__init__.py").is_file())
        self.assertFalse((folder / "other").exists())
        self.assertEqual([p.name for p in folder.parent.iterdir()], [folder.name], "no leftovers")

    def test_install_refuses_wrong_bytes_and_bad_paths(self):
        data = fake_wheel()
        for size, sha in ((None, "0" * 64), (len(data) - 1, None)):
            with self.with_wheel(data, size, sha), mock.patch.object(fs, "activate"):
                with self.assertRaises(fs.SetupError):
                    fs.install(self.root, fetch=lambda url: Response(data))
            self.assertFalse(fs.deps_dir(self.root).exists())
        evil = fake_wheel({"unicorn/../../escape.py": "x"})
        with self.with_wheel(evil), mock.patch.object(fs, "activate"):
            with self.assertRaises(fs.SetupError):
                fs.install(self.root, fetch=lambda url: Response(evil))
        self.assertFalse((self.root / "escape.py").exists())
        with mock.patch.object(fs, "wheel", return_value=None):
            with self.assertRaises(fs.SetupError):
                fs.install(self.root)

    def test_self_check_remembers_the_result(self):
        (fs.deps_dir(self.root) / "unicorn").mkdir(parents=True)
        good = {"values": "placeholder", "model_id": "m"}
        with mock.patch.object(fs, "activate"), mock.patch.object(fs, "REFERENCE_VALUES_SHA256",
                                                                   hashlib.sha256(b'"placeholder"').hexdigest()):
            self.assertTrue(fs.self_check("fw.bin", good, self.root)["ok"])
            self.assertTrue(fs.checked(self.root)["ok"])
            with self.assertRaises(fs.SetupError):
                fs.self_check("fw.bin", {"values": [1], "model_id": "m"}, self.root)
            self.assertFalse(fs.checked(self.root)["ok"])

    def test_known_platforms_are_mac_and_windows(self):
        self.assertEqual(sorted(fs.WHEELS), [("darwin", "arm64"), ("darwin", "x86_64"), ("win32", "amd64")])
        for w in fs.WHEELS.values():
            self.assertTrue(w["file"].startswith("unicorn-2.1.4-cp37-abi3-"))
            self.assertRegex(w["sha256"], "^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

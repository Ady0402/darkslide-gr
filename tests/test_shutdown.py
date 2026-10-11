import json
import os
import tempfile
import unittest
from pathlib import Path

from darkslide import a_shutdown, build, composite_verify, compositor, generate, shared_shutdown, shutdown_verify, template as tpl
from darkslide.identify import digest_of as sha256
from darkslide.store import SHUTDOWN_BUDGET, Store, StoreError

FIXTURE = Path(__file__).parent / "fixtures" / "shutdown_gradient.jpg"
# Set DARKSLIDE_OFFICIAL_BIN to your own GR III 2.10 fwdc239b.bin to run the build test.
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
FAKE_OFFICIAL = b"official-firmware-bytes"


def with_marker(jpeg, marker, payload):
    """Insert one segment right after SOI (for rejection tests)."""
    seg = b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + seg + jpeg[2:]


class JpegContract(unittest.TestCase):
    def setUp(self):
        self.jpeg = FIXTURE.read_bytes()

    def test_fixture_matches_camera_format(self):
        info = shared_shutdown.jpeg_contract(self.jpeg)
        self.assertEqual((info["width"], info["height"], info["sampling"]), (720, 480, "4:2:0"))

    def test_budget_leaves_room_for_padding(self):
        self.assertEqual(SHUTDOWN_BUDGET, shared_shutdown.CAPACITY - 4)
        padded = shared_shutdown.pad_jpeg(self.jpeg)
        self.assertEqual(len(padded), shared_shutdown.CAPACITY)
        self.assertEqual(shutdown_verify.strip_com(padded), self.jpeg)

    def test_strip_com_keeps_other_segments(self):
        self.assertEqual(shutdown_verify.strip_com(self.jpeg), self.jpeg)
        self.assertIsNone(shutdown_verify.strip_com(b"\xff\xd8junk"))


class ShutdownStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.t = json.loads(json.dumps(tpl.load()))
        self.t["official_inputs"] = [dict(filename="fwdc239b.bin", size=len(FAKE_OFFICIAL), sha256=sha256(FAKE_OFFICIAL))]
        sha = self.store.put_input(FAKE_OFFICIAL)
        self.pid = self.store.create_project("关机", sha, self.t)["id"]
        self.jpeg = FIXTURE.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_and_serves(self):
        r = self.store.put_shutdown_jpeg(self.pid, self.jpeg)
        self.assertEqual(r["bytes"], len(self.jpeg))
        path = self.store.asset_path(self.pid, r["asset"])
        self.assertEqual(path.suffix, ".jpg")
        self.assertEqual(path.read_bytes(), self.jpeg)

    def test_rejects(self):
        bad = {
            "png": b"\x89PNG\r\n\x1a\n" + bytes(40),
            "exif": with_marker(self.jpeg, 0xE1, b"Exif\x00\x00" + bytes(20)),
            "icc": with_marker(self.jpeg, 0xE2, b"ICC_PROFILE\x00" + bytes(20)),
            "too_big": self.jpeg[:-2] + bytes(SHUTDOWN_BUDGET) + b"\xff\xd9",
            "progressive": self.jpeg.replace(b"\xff\xc0", b"\xff\xc2", 1),
            "size": self.jpeg.replace(b"\x01\xe0\x02\xd0", b"\x01\xe0\x02\xc0", 1),
        }
        for name, data in bad.items():
            with self.assertRaises(StoreError, msg=name):
                self.store.put_shutdown_jpeg(self.pid, data)

    def test_changes_validation(self):
        a = self.store.put_shutdown_jpeg(self.pid, self.jpeg)["asset"]
        p = self.store.put_draft(self.pid, {"shutdown": dict(asset=a, quality=60, bytes=len(self.jpeg))}, self.t)
        self.assertEqual(p["draft"]["changes"]["shutdown"]["asset"], a)
        with self.assertRaises(StoreError):
            self.store.put_draft(self.pid, {"shutdown": dict(asset="0" * 64)}, self.t)

    def test_png_asset_cannot_pose_as_shutdown(self):
        import struct
        import zlib

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        raw = b"".join(b"\x00" + bytes(4 * 8) for _ in range(8))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        a = self.store.put_asset(self.pid, png)["asset"]
        with self.assertRaises(StoreError):
            self.store.put_draft(self.pid, {"shutdown": dict(asset=a)}, self.t)

    def test_mixed_generation_reaches_composite_core(self):
        a = self.store.put_shutdown_jpeg(self.pid, self.jpeg)["asset"]
        self.store.put_draft(self.pid, {"shutdown": dict(asset=a), "7": dict(name="Posi Warm")}, self.t)
        project = self.store.save(self.pid, self.t)
        with self.assertRaises(generate.GenerateError) as ctx:
            generate.run(self.store, project, self.t, FAKE_OFFICIAL)
        # no longer refused as "either/or"; the fake input stops at the core's official-file check
        self.assertNotIn("暂时不能", str(ctx.exception))
        self.assertIn("无法生成", str(ctx.exception))


@unittest.skipUnless(STOCK.exists(), "needs the official GR III 2.10 fwdc239b.bin")
class ShutdownBuild(unittest.TestCase):
    """End to end with the real official file: build in memory, then independent read-back."""

    @classmethod
    def setUpClass(cls):
        cls.official = STOCK.read_bytes()
        cls.jpeg = FIXTURE.read_bytes()
        cls.result = a_shutdown.build_a_shutdown(cls.official, cls.jpeg)

    def test_all_checks_pass(self):
        checks = shutdown_verify.verify(self.official, self.result["output"], self.jpeg)
        self.assertTrue(shutdown_verify.all_ok(checks), [c for c in checks if not c["ok"]])
        self.assertEqual(len(checks), 13)
        self.assertEqual(self.result["shared_path"], "A:\\Resource\\Jpeg\\GB_Diary.jpg")

    def test_tampering_is_caught(self):
        out = bytearray(self.result["output"])
        out[300] ^= 1
        self.assertFalse(shutdown_verify.all_ok(shutdown_verify.verify(self.official, bytes(out), self.jpeg)))
        other = self.jpeg[:-3] + b"\x00\xff\xd9"
        self.assertFalse(shutdown_verify.all_ok(shutdown_verify.verify(self.official, self.result["output"], other)))


@unittest.skipUnless(STOCK.exists(), "needs the official GR III 2.10 fwdc239b.bin")
class CompositeBuild(unittest.TestCase):
    """Icons/names and the shutdown image in one build, read back independently."""

    @classmethod
    def setUpClass(cls):
        cls.official = STOCK.read_bytes()
        cls.jpeg = FIXTURE.read_bytes()
        cls.t = tpl.load()
        slot = tpl.slot(cls.t, 7)
        cls.edits = [dict(kind="name", slot=7, string_id=slot["string_id"], text="Posi Warm")]

    def test_single_features_match_existing_cores(self):
        names_only = compositor.build_composite(self.official, self.edits, self.t, None)
        self.assertEqual(names_only["output"], build.build(self.official, self.edits, self.t)["output"])
        shutdown_only = compositor.build_composite(self.official, [], self.t, self.jpeg)
        self.assertEqual(shutdown_only["output"], a_shutdown.build_a_shutdown(self.official, self.jpeg)["output"])

    def test_mixed_build_reads_back(self):
        result = compositor.build_composite(self.official, self.edits, self.t, self.jpeg)
        checks = composite_verify.verify(self.official, result, self.edits, self.t, self.jpeg)
        self.assertTrue(composite_verify.all_ok(checks), [c for c in checks if not c["ok"]])
        self.assertEqual(sorted(result["features"]), ["name", "shutdown"])
        bad = bytearray(result["output"])
        bad[400] ^= 1
        tampered = dict(result, output=bytes(bad))
        self.assertFalse(composite_verify.all_ok(composite_verify.verify(self.official, tampered, self.edits, self.t, self.jpeg)))


if __name__ == "__main__":
    unittest.main()

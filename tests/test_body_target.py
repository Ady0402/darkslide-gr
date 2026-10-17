"""Target body (GR III / GR III HDF): project field, family checks, protected HDF windows."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from darkslide import body_target, compositor, film_patch_plan, fwread, generate, hdf_guard, server, template as tpl
from darkslide.identify import digest_of as sha256
from darkslide.store import Store, StoreError

FIXTURE = Path(__file__).parent / "fixtures" / "shutdown_gradient.jpg"
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
FAKE_OFFICIAL = b"official-firmware-bytes"


class Values(unittest.TestCase):
    def test_only_four_exact_bodies(self):
        for body in body_target.BODIES:
            self.assertEqual(body_target.validate(body), body)
        self.assertIsNone(body_target.validate(None))
        for bad in ("", "GR3 HDF", "gr iii hdf", "GR III HDF ", "HDF", True, 1, ["GR III"]):
            with self.assertRaises(body_target.BodyTargetError, msg=repr(bad)):
                body_target.validate(bad)

    def test_unspecified_is_neither_ordinary_nor_hdf(self):
        self.assertEqual(body_target.label(None), "机身版本未指定")
        self.assertFalse(body_target.is_hdf(None))
        self.assertTrue(body_target.is_hdf("GR III HDF"))
        self.assertFalse(body_target.is_hdf("GR III"))
        self.assertIsNone(body_target.require_family(None, "GR III", "2.10"))

    def test_family_must_match_template(self):
        for body in ("GR III", "GR III HDF"):
            self.assertEqual(body_target.require_family(body, "GR III", "2.10"), body)
        for body in ("GR IIIx", "GR IIIx HDF"):
            with self.assertRaises(body_target.BodyTargetError):
                body_target.require_family(body, "GR III", "2.10")
        with self.assertRaises(body_target.BodyTargetError):
            body_target.require_family("GR III HDF", "GR III", "1.80")

    def test_shutdown_report_never_guesses_collabo_mode(self):
        for body in ("GR III", "GR III HDF"):
            r = body_target.shutdown_report(body)
            self.assertEqual(r["status"], "all_factory_routes_covered")
            self.assertEqual(r["missing_requests"], [])
            self.assertIsNone(r["collabo_mode_observed"])
            self.assertFalse(r["camera_verified"])
        with self.assertRaises(ValueError):
            body_target.shutdown_report(None)

    def test_sparse_needs_a_declared_body(self):
        with self.assertRaises(body_target.BodyTargetError):
            body_target.sparse_report(b"x", None, ())

    def test_sparse_rejects_wrong_original(self):
        with self.assertRaises(body_target.BodyTargetError):
            body_target.sparse_report(b"not the official payload", "GR III HDF", ())


class ProjectField(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.t = json.loads(json.dumps(tpl.load()))
        self.t["official_inputs"] = [dict(filename="fwdc239b.bin", size=len(FAKE_OFFICIAL), sha256=sha256(FAKE_OFFICIAL))]
        self.sha = self.store.put_input(FAKE_OFFICIAL)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_projects_have_no_default(self):
        p = self.store.create_project("旧工程", self.sha, self.t)
        self.assertNotIn("target_body", json.loads((self.store._dir(p["id"]) / "project.json").read_text()))
        self.assertEqual(p["target_body_label"], "机身版本未指定")
        self.assertIsNone(self.store.list_projects()[0]["target_body"])

    def test_create_set_and_clear(self):
        p = self.store.create_project("HDF", self.sha, self.t, "GR III HDF")
        self.assertEqual((p["target_body"], p["target_body_label"]), ("GR III HDF", "GR III HDF"))
        p = self.store.set_target_body(p["id"], "GR III", self.t)
        self.assertEqual(p["target_body"], "GR III")
        p = self.store.set_target_body(p["id"], None, self.t)
        self.assertNotIn("target_body", p)
        self.assertEqual(Store(self.tmp.name).get_project(p["id"])["target_body_label"], "机身版本未指定")

    def test_saving_keeps_the_body(self):
        pid = self.store.create_project("HDF", self.sha, self.t, "GR III HDF")["id"]
        self.store.put_draft(pid, {"7": {"name": "Posi"}}, self.t)
        self.assertEqual(self.store.save(pid, self.t)["target_body"], "GR III HDF")

    def test_bad_or_wrong_family_rejected(self):
        for bad in ("GR IIIx", "GR IIIx HDF", "HDF", 1):
            with self.assertRaises(StoreError, msg=repr(bad)):
                self.store.create_project("x", self.sha, self.t, bad)
        pid = self.store.create_project("x", self.sha, self.t)["id"]
        with self.assertRaises(StoreError):
            self.store.set_target_body(pid, "GR IIIx HDF", self.t)
        self.assertNotIn("target_body", self.store.get_project(pid))

    def test_endpoint_accepts_only_the_one_field(self):
        with mock.patch.object(self.store, "has_input", return_value=True):
            pid = self.store.create_project("x", fwread.V210_INPUT_SHA256, tpl.load())["id"]
        for body in ({}, {"target_body": "GR III", "x": 1}, ["GR III"]):
            req = SimpleNamespace(store=self.store, app=SimpleNamespace(template=self.t), read_json=lambda body=body: body)
            with self.assertRaises(server.ApiError):
                server.api_set_target_body(req, pid)
        req = SimpleNamespace(store=self.store, app=SimpleNamespace(template=self.t), read_json=lambda: {"target_body": "GR III HDF"})
        self.assertEqual(server.api_set_target_body(req, pid)["target_body"], "GR III HDF")

    def test_generate_refuses_wrong_family_before_building(self):
        project = dict(self.store.create_project("x", self.sha, self.t), changes={"7": {"name": "Posi"}},
                       unsaved=False, target_body="GR IIIx HDF")
        with mock.patch.object(generate.compositor, "build_composite", side_effect=AssertionError("built")):
            with self.assertRaisesRegex(generate.GenerateError, "不是同一家族"):
                generate.run(self.store, project, self.t, FAKE_OFFICIAL)

    def test_film_prepare_requires_a_body_before_decoding(self):
        t = tpl.load()
        with mock.patch.object(self.store, "has_input", return_value=True):
            pid = self.store.create_project("x", fwread.V210_INPUT_SHA256, t)["id"]
        req = SimpleNamespace(store=self.store, app=SimpleNamespace(template=t),
                              read_json=lambda: {"expected_changes": {}, "request_id": "a"})
        with mock.patch.object(fwread, "unpack", side_effect=AssertionError("decoded")):
            with self.assertRaisesRegex(server.ApiError, "先选机身版本") as raised:
                server.api_film_prepare(req, pid)
        self.assertEqual(raised.exception.status, 409)


@unittest.skipUnless(STOCK.exists(), "needs the official GR III 2.10 fwdc239b.bin")
class RealFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.official = STOCK.read_bytes()
        cls.decoded = bytes(fwread.unpack(cls.official))
        cls.jpeg = FIXTURE.read_bytes()
        cls.t = tpl.load()
        slot = tpl.slot(cls.t, 7)
        edits = [dict(kind="name", slot=7, string_id=slot["string_id"], text="Posi Warm")]
        cls.build = compositor.build_composite(cls.official, edits, cls.t, cls.jpeg)

    def _word(self, va):
        o = va - hdf_guard.BASE + hdf_guard.OFFSET
        return self.decoded[o:o + 4]

    def test_names_and_shutdown_leave_hdf_windows_alone(self):
        for body in ("GR III", "GR III HDF"):
            checks, info = generate.body_check(self.official, self.build["output"], body, self.t, True)
            self.assertTrue(all(c["ok"] for c in checks), checks)
            self.assertEqual(info["status"], "protected_windows_unchanged")
            self.assertEqual(info["filter_type"], 1 if body.endswith("HDF") else 0)
            self.assertEqual(info["shutdown_routes"]["missing_requests"], [])
            for flag in ("compatibility_approved", "device_tested", "body_detected"):
                self.assertIs(info[flag], False)

    def test_unspecified_body_adds_no_check(self):
        self.assertEqual(generate.body_check(self.official, self.build["output"], None, self.t, True),
                         ([], dict(target_body=None, label="机身版本未指定")))

    def test_change_in_protected_window_needs_review(self):
        candidate = bytearray(self.decoded)
        o = 0x537097b4 - hdf_guard.BASE + hdf_guard.OFFSET
        candidate[o] ^= 1
        report = body_target.build_report(self.decoded, "GR III HDF", bytes(candidate))
        self.assertEqual(report["status"], "review_required")
        self.assertIn("white_balance_factory", report["changed_windows"])
        self.assertIn("需要专项复核", body_target.summary(report))

    def test_sparse_windows_inside_and_outside(self):
        same = film_patch_plan.Window(0x537097b4, self._word(0x537097b4), self._word(0x537097b4))
        r = body_target.sparse_report(self.decoded, "GR III HDF", (same,))
        self.assertEqual(r["status"], "protected_windows_unchanged")
        self.assertFalse(r["complete_candidate_created"])
        hit = film_patch_plan.Window(0x537097b4, self._word(0x537097b4), bytes(b ^ 1 for b in self._word(0x537097b4)))
        self.assertEqual(body_target.sparse_report(self.decoded, "GR III HDF", (hit,))["status"], "review_required")

    def test_ordinary_family_payload_is_not_iiix(self):
        with self.assertRaises(body_target.BodyTargetError):
            body_target.build_report(self.decoded, "GR IIIx HDF", self.decoded)


@unittest.skipUnless(STOCK.exists(), "needs the official GR III 2.10 fwdc239b.bin")
class RealGenerate(unittest.TestCase):
    """Saved HDF project through generate.run: manifest records the body and its limits."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.t = tpl.load()
        self.official = STOCK.read_bytes()
        sha = self.store.put_input(self.official)
        self.pid = self.store.create_project("HDF", sha, self.t, "GR III HDF")["id"]
        asset = self.store.put_shutdown_jpeg(self.pid, FIXTURE.read_bytes())
        self.store.put_draft(self.pid, {"7": {"name": "Posi"}, "shutdown": asset}, self.t)
        self.store.save(self.pid, self.t)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_and_note(self):
        _, manifest = generate.run(self.store, self.store.get_project(self.pid), self.t, self.official)
        body = manifest["body"]
        self.assertEqual((body["target_body"], body["status"]), ("GR III HDF", "protected_windows_unchanged"))
        self.assertEqual(body["shutdown_routes"]["status"], "all_factory_routes_covered")
        self.assertIn("body_protected_windows", [c["id"] for c in manifest["checks"]])
        self.assertIn("HDF 机身还没有实测", manifest["verification"])
        self.assertIn("新增 Street 路线尚未实机验证", manifest["verification"])

    def test_protected_window_change_blocks_output(self):
        real = body_target.build_report
        def touched(decoded, body, candidate):
            bad = bytearray(candidate)
            bad[0x537097b4 - hdf_guard.BASE + hdf_guard.OFFSET] ^= 1
            return real(decoded, body, bytes(bad))
        with mock.patch.object(body_target, "build_report", side_effect=touched):
            with self.assertRaisesRegex(generate.GenerateError, "专项复核") as raised:
                generate.run(self.store, self.store.get_project(self.pid), self.t, self.official)
        self.assertFalse([c for c in raised.exception.checks if c["id"] == "body_protected_windows"][0]["ok"])


if __name__ == "__main__":
    unittest.main()

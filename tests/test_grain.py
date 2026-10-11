import json
import os
import tempfile
import unittest
from pathlib import Path

from darkslide import generate, template as tpl, verify
from darkslide.identify import sha256
from darkslide.store import Store, StoreError

# Set DARKSLIDE_OFFICIAL_BIN to your own GR III 2.10 fwdc239b.bin to run the read-back test.
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
FAKE_OFFICIAL = b"official-firmware-bytes"
NEGATIVE, MONO, POSITIVE = 12, 3, 7


class GrainTemplate(unittest.TestCase):
    def test_stages(self):
        t = tpl.load()
        self.assertEqual(tpl.grain_stage(t, NEGATIVE), "menu")
        self.assertEqual(tpl.grain_stage(t, MONO), "factory")
        self.assertEqual(tpl.grain_stage(t, POSITIVE), "closed")

    def test_sidecar_matches_template(self):
        t = tpl.load()
        d = tpl.load_detail(t)
        self.assertEqual(d["template_id"], t["id"])
        self.assertEqual(d["grain"]["12"], "menu")
        self.assertNotIn("grain", t["slots"][11], "main template must keep only core-whitelisted fields")


class GrainChanges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.t = json.loads(json.dumps(tpl.load()))
        self.t["official_inputs"] = [dict(filename="fwdc239b.bin", size=len(FAKE_OFFICIAL), sha256=sha256(FAKE_OFFICIAL))]
        sha = self.store.put_input(FAKE_OFFICIAL)
        self.pid = self.store.create_project("颗粒", sha, self.t)["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_negative_grain_accepted(self):
        clean = self.store.validate_changes(self.pid, {str(NEGATIVE): {"grain": True}}, self.t, strict=True)
        self.assertEqual(clean, {str(NEGATIVE): {"grain": True}})

    def test_other_slots_rejected(self):
        for no in (MONO, POSITIVE):
            with self.assertRaises(StoreError):
                self.store.validate_changes(self.pid, {str(no): {"grain": True}}, self.t, strict=False)

    def test_only_true_accepted(self):
        with self.assertRaises(StoreError):
            self.store.validate_changes(self.pid, {str(NEGATIVE): {"grain": "high"}}, self.t, strict=False)

    def test_edits_and_summary(self):
        changes = {str(NEGATIVE): {"grain": True, "name": "My Film"}}
        edits = generate.edits_from_changes(self.store, self.pid, changes, self.t)
        self.assertEqual([e["kind"] for e in edits], ["name", "grain_menu"])
        self.assertEqual(edits[1], dict(kind="grain_menu", slot=NEGATIVE, mode=22))
        what = [x["what"] for x in generate.summarize(changes, self.t)]
        self.assertEqual(what, ["预设名", "颗粒项"])

    def test_grain_alone_is_not_generated(self):
        self.store.put_draft(self.pid, {str(NEGATIVE): {"grain": True}}, self.t)
        self.store.save(self.pid, self.t)
        project = self.store.get_project(self.pid)
        with self.assertRaises(generate.GenerateError) as cm:
            generate.run(self.store, project, self.t, FAKE_OFFICIAL)
        self.assertIn("暂不参与生成", str(cm.exception))

    def test_grain_is_skipped_next_to_other_changes(self):
        self.store.put_draft(self.pid, {str(NEGATIVE): {"grain": True, "name": "Nega Warm"}}, self.t)
        self.store.save(self.pid, self.t)
        project = self.store.get_project(self.pid)
        with self.assertRaises(generate.GenerateError) as cm:
            generate.run(self.store, project, self.t, FAKE_OFFICIAL)
        # past the grain step: the fake input is stopped by the core's official-file check
        self.assertIn("无法生成", str(cm.exception))


@unittest.skipUnless(STOCK.exists(), "official firmware not available")
class GrainReadBack(unittest.TestCase):
    def test_factory_menu_state(self):
        from darkslide import fwread
        payload = fwread.Payload(fwread.unpack(STOCK.read_bytes()))
        self.assertEqual(verify.grain_menu_state(payload), "factory")

    def test_opened_state_recognised(self):
        from darkslide import fwread
        raw = bytearray(fwread.unpack(STOCK.read_bytes()))
        p = fwread.Payload(bytes(raw))
        row = verify.GRAIN_MENU["table"] + 6 * 8
        raw[p.off(row + 4):p.off(row + 4) + 4] = (10).to_bytes(4, "little")
        tail = p.off(verify.GRAIN_MENU["list_va"]) + 18
        raw[tail:tail + 2] = b"\x02\x0f"
        self.assertEqual(verify.grain_menu_state(fwread.Payload(bytes(raw), pinned=False)), "opened")
        raw[tail:tail + 2] = b"\x02\x0c"
        self.assertNotIn(verify.grain_menu_state(fwread.Payload(bytes(raw), pinned=False)), ("factory", "opened"))


if __name__ == "__main__":
    unittest.main()

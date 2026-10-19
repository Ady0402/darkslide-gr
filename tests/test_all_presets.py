"""Opening every built-in preset (not Custom 1/2): icon for 1-12, preset name for 2-12.

With the real official 2.10 file each newly opened preset is changed on its own, then
everything at once (all icons, all names, grain, shutdown image); every build must pass
the independent checker and read back with only the requested presets changed."""

import copy
import os
import unittest
from pathlib import Path

from darkslide import composite_verify, compositor, edit_core, fwread, rescue_gate, template

OFFICIAL = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
NEW = (2, 3, 4, 5, 6, 8, 9, 10)
JPEG = Path(__file__).parent / "fixtures" / "shutdown_gradient.jpg"


class Scope(unittest.TestCase):
    def setUp(self):
        self.t = template.load()

    def test_template_opens_all_but_custom(self):
        for s in self.t["slots"]:
            self.assertEqual(s["icon"] in ("test", "open"), s["no"] <= 12, s["name"])
            self.assertEqual(s["rename"] in ("test", "open"), 2 <= s["no"] <= 12, s["name"])

    def test_custom_and_standard_name_stay_closed(self):
        for no, field in ((13, "icon"), (14, "icon"), (13, "rename"), (14, "rename"), (1, "rename")):
            t = copy.deepcopy(self.t)
            t["slots"][no - 1][field] = "test"
            with self.assertRaises(ValueError):
                edit_core._template(t)

    def test_edit_count_limit(self):
        # at most 12 icons + 11 names; one more is refused before anything else is looked at
        edits = [dict(kind="name", slot=7, string_id=274, text="A")] * 24
        with self.assertRaises(ValueError) as cm:
            edit_core._validate_edits(edits, self.t)
        self.assertIn("1 to 23", str(cm.exception))


def icon_edit(p, slot, flip):
    _, native = p.icon_pixels(slot["icon_id"])
    px = bytearray(fwread.icon_to_rgba(native))
    px[(20 * 40 + 20) * 4] ^= flip  # one visible pixel, alpha untouched
    return dict(kind="icon", slot=slot["no"], icon_id=slot["icon_id"], pixels=bytes(px))


def name_edit(slot):
    text = ("T%d " % slot["no"] + "X" * 16)[:len(slot["factory_en"])].rstrip()
    return dict(kind="name", slot=slot["no"], string_id=slot["string_id"], text=text)


@unittest.skipUnless(OFFICIAL.exists(), "official firmware not available on this machine")
class RealFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = OFFICIAL.read_bytes()
        cls.t = template.load()
        cls.stock = fwread.Payload(fwread.unpack(cls.raw))

    def check(self, edits, jpeg=None):
        result = compositor.build_composite(self.raw, edits, self.t, jpeg)
        checks = composite_verify.verify(self.raw, result, edits, self.t, jpeg)
        self.assertTrue(composite_verify.all_ok(checks), [c for c in checks if not c["ok"]])
        after = fwread.Payload(fwread.unpack(result["output"]), pinned=False)
        icons = {e["slot"]: e["pixels"] for e in edits if e["kind"] == "icon"}
        names = {e["slot"]: e["text"] for e in edits if e["kind"] == "name"}
        for s in self.t["slots"]:
            got = bytes(fwread.icon_to_rgba(after.icon_pixels(s["icon_id"])[1]))
            want = icons.get(s["no"], bytes(fwread.icon_to_rgba(self.stock.icon_pixels(s["icon_id"])[1])))
            self.assertEqual(got, want, "icon of %s" % s["name"])
            for lang in ("en", "zh-CN", "zh-TW"):
                text = after.string(s["string_id"], lang)["text"]
                want = names.get(s["no"], self.stock.string(s["string_id"], lang)["text"])
                self.assertEqual(text, want, "%s name of %s" % (lang, s["name"]))
            self.assertEqual(after.string(s["string_id"], "ja")["text"],
                             self.stock.string(s["string_id"], "ja")["text"])
        return result

    def test_each_new_preset_alone(self):
        for no in NEW:
            slot = self.t["slots"][no - 1]
            with self.subTest(preset=slot["name"]):
                self.check([icon_edit(self.stock, slot, 0x55), name_edit(slot)])

    def test_everything_at_once(self):
        slots = self.t["slots"]
        edits = [icon_edit(self.stock, s, 0x33) for s in slots[:12]]
        edits += [name_edit(s) for s in slots[1:12]]
        edits.append(dict(kind="grain_menu", slot=12, mode=22))
        result = self.check(edits, JPEG.read_bytes())
        self.assertEqual(set(result["features"]), {"icon", "name", "grain_menu", "shutdown"})
        gate = rescue_gate.gate(self.raw, result["output"])
        self.assertTrue(rescue_gate.all_ok(gate), [c for c in gate if not c["ok"]])



class VerificationNote(unittest.TestCase):
    def test_open_presets_are_device_tested(self):
        from darkslide import generate
        t = template.load()
        edits = [dict(kind="icon", slot=n) for n in range(1, 13)] + [dict(kind="name", slot=n) for n in range(2, 13)]
        self.assertNotIn("还没在相机上实测", generate.verification_note(edits, t))

    def test_untested_presets_are_named(self):
        from unittest import mock
        from darkslide import generate
        t = template.load()
        with mock.patch.object(generate, "DEVICE_TESTED", {"icon": {1, 7}, "name": {7}}):
            new = generate.verification_note([dict(kind="icon", slot=2), dict(kind="name", slot=9), dict(kind="name", slot=7)], t)
        self.assertIn("鲜艳、怀旧 是新开放的预设，还没在相机上实测", new)
        self.assertNotIn("正片 是新开放", new)

if __name__ == "__main__":
    unittest.main()

"""Preset names longer than the original English name.

A longer name goes into the longest storage that only this string uses, in a language
other than ja/en/zh-TW/zh-CN; English and Simplified Chinese then point there. Names that
fit the English original keep the earlier byte-for-byte behaviour."""

import hashlib
import os
import unittest
from pathlib import Path

from darkslide import composite_verify, compositor, edit_core, fwread, rescue_gate, template

OFFICIAL = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
# User rule (2026-10-12): longer names up to 12 (Retro up to 8); presets whose original English name
# is already 12 or longer keep the original length and never borrow storage.
LIMITS = {2: 12, 3: 12, 9: 8, 10: 12}


class Limits(unittest.TestCase):
    def test_template_limits(self):
        t = template.load()
        for s in t["slots"]:
            self.assertEqual(s.get("name_max"), LIMITS.get(s["no"]), s["name"])  # others: original length
            if "name_max" in s:
                self.assertGreaterEqual(s["name_max"], len(s["factory_en"]))

    def test_over_limit_refused(self):
        t = template.load()
        for no, limit in LIMITS.items():
            s = t["slots"][no - 1]
            edit = dict(kind="name", slot=no, string_id=s["string_id"], text="N" * (limit + 1))
            with self.assertRaises(ValueError):
                edit_core._validate_edits([edit], t)


def long_name(no, length):
    return ("Long %d " % no + "abcdefghijklmnopqrstuvwxyz")[:length].rstrip()


@unittest.skipUnless(OFFICIAL.exists(), "official firmware not available on this machine")
class RealFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = OFFICIAL.read_bytes()
        cls.t = template.load()
        cls.stock = fwread.Payload(fwread.unpack(cls.raw))

    def build(self, edits):
        result = compositor.build_composite(self.raw, edits, self.t)
        checks = composite_verify.verify(self.raw, result, edits, self.t)
        self.assertTrue(composite_verify.all_ok(checks), [c for c in checks if not c["ok"]])
        gate = rescue_gate.gate(self.raw, result["output"])
        self.assertTrue(rescue_gate.all_ok(gate), [c for c in gate if not c["ok"]])
        return result, fwread.Payload(fwread.unpack(result["output"]), pinned=False)

    def test_each_preset_at_its_limit(self):
        for no, limit in LIMITS.items():
            s = self.t["slots"][no - 1]
            text = long_name(no, limit)
            if len(text) <= len(s["factory_en"]):
                continue
            with self.subTest(preset=s["name"], length=len(text)):
                _, after = self.build([dict(kind="name", slot=no, string_id=s["string_id"], text=text)])
                for lang in ("en", "zh-CN"):
                    self.assertEqual(after.string(s["string_id"], lang)["text"], text)
                for lang in ("ja", "zh-TW"):
                    self.assertEqual(after.string(s["string_id"], lang)["text"],
                                     self.stock.string(s["string_id"], lang)["text"])
                for other in self.t["slots"]:
                    if other["no"] != no:
                        self.assertEqual(after.string(other["string_id"], "en")["text"],
                                         self.stock.string(other["string_id"], "en")["text"])

    def test_all_long_names_together(self):
        edits = [dict(kind="name", slot=no, string_id=self.t["slots"][no - 1]["string_id"],
                      text=long_name(no, limit)) for no, limit in LIMITS.items()]
        _, after = self.build(edits)
        for e in edits:
            self.assertEqual(after.string(e["string_id"], "en")["text"], e["text"])
            self.assertEqual(after.string(e["string_id"], "zh-CN")["text"], e["text"])

    def test_short_names_unchanged_behaviour(self):
        # Names that fit the English original write exactly the bytes they always did.
        s = self.t["slots"][6]
        result, _ = self.build([dict(kind="name", slot=7, string_id=274, text="Posi Warm")])
        changed = {c.get("what") for c in result.get("payload_changes", []) if isinstance(c, dict)}
        self.assertNotIn("name_lent_text", changed)


if __name__ == "__main__":
    unittest.main()

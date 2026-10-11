"""Independent read-back checks (verify.py) against the real official fixture.
Everything stays in memory; no modified BIN is written."""
import copy
import json
import os
import unittest
from pathlib import Path

from darkslide import build as builder, fwread, verify

APP = Path(__file__).resolve().parents[1]
# Set DARKSLIDE_OFFICIAL_BIN to your own GR III 2.10 fwdc239b.bin to run these.
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))


class Verify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STOCK.exists():
            raise unittest.SkipTest("official GR III 2.10 fixture absent")
        cls.raw = STOCK.read_bytes()
        cls.template = json.loads((APP / "templates/gr3_v210.json").read_text())
        stock = fwread.Payload(fwread.unpack(cls.raw))
        _, native = stock.icon_pixels(232)
        pixels = bytearray(fwread.icon_to_rgba(native))
        for i in range(0, 6400, 4):
            if pixels[i + 3]:
                pixels[i:i + 3] = b"\xe9\xb7\x2e"
        cls.edits = [dict(kind="icon", slot=7, icon_id=232, pixels=bytes(pixels)),
                     dict(kind="name", slot=7, string_id=274, text="Posi Warm")]
        cls.result = builder.build(cls.raw, cls.edits, cls.template)

    def test_all_checks_pass(self):
        checks = verify.verify(self.raw, self.result, self.edits, self.template)
        self.assertTrue(verify.all_ok(checks), [c for c in checks if not c["ok"]])
        self.assertEqual(len(checks), 10)   # 9 icon/name checks + negative-film menu read-back
        self.assertIn("grain_menu", {c["id"] for c in checks})

    def test_flipped_output_byte_fails(self):
        bad = dict(self.result, output=self.result["output"][:-8] + b"\x00" + self.result["output"][-7:])
        failed = {c["id"] for c in verify.verify(self.raw, bad, self.edits, self.template) if not c["ok"]}
        self.assertIn("sha", failed)

    def test_undeclared_change_fails(self):
        bad = copy.deepcopy(self.result)
        bad["payload_changes"] = [c for c in bad["payload_changes"] if c["what"] != "name_zh_CN_record"]
        failed = {c["id"] for c in verify.verify(self.raw, bad, self.edits, self.template) if not c["ok"]}
        self.assertEqual(failed, {"only_declared"})

    def test_wrong_expectation_fails(self):
        edits = copy.deepcopy(self.edits)
        edits[1]["text"] = "Posi Cool"
        failed = {c["id"] for c in verify.verify(self.raw, self.result, edits, self.template) if not c["ok"]}
        self.assertEqual(failed, {"names"})


if __name__ == "__main__":
    unittest.main()

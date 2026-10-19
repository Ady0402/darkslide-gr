"""The camera menu language chosen before generating.

English always shows the new name (its text holds it); the chosen language's record
points at that text too; every other language keeps the factory name. A name edit
without a choice keeps the 1.0.1 languages (Simplified and Traditional Chinese)."""

import os
import tempfile
import unittest
from pathlib import Path

from darkslide import (composite_verify, compositor, fwread, menu_language, rescue_gate,
                       store as store_mod, template)

OFFICIAL = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
ALL = tuple(menu_language.CHOICES)  # all 21 firmware menu languages


class Rules(unittest.TestCase):
    def test_repointed(self):
        self.assertEqual(menu_language.repointed({}), ("zh-CN", "zh-TW"))
        self.assertEqual(menu_language.repointed({"menu_language": "en"}), ())
        for code in ("zh-CN", "zh-TW", "ja", "ko", "th", "fr"):
            self.assertEqual(menu_language.repointed({"menu_language": code}), (code,))
        self.assertEqual(len(menu_language.CHOICES), 21)
        self.assertEqual(sorted(i for i, _ in menu_language.CHOICES.values()), list(range(21)))

    def test_unknown_language_refused(self):
        for bad in (None, "", "kr", "zh", "EN"):
            with self.assertRaises(menu_language.MenuLanguageError):
                menu_language.validate(bad)

    def test_store_keeps_the_choice(self):
        with tempfile.TemporaryDirectory() as root:
            store = store_mod.Store(Path(root))
            sha = store.put_input(b"fixture")
            pid = store.create_project("t", sha, template.load())["id"]
            self.assertNotIn("menu_language", store.get_project(pid))
            self.assertEqual(store.set_menu_language(pid, "zh-TW")["menu_language"], "zh-TW")
            with self.assertRaises(store_mod.StoreError):
                store.set_menu_language(pid, "kr")
            self.assertEqual(store.get_project(pid)["menu_language"], "zh-TW")


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

    def test_each_language_short_and_long(self):
        slot = self.t["slots"][1]  # 鲜艳 / Vivid: name_max 12, factory English 5
        for code in ("zh-TW", "zh-CN", "en", "ja", "ko", "th", "ru"):
            for text in ("Vv", "Fuji Classic"):  # fits the English text / borrows storage
                with self.subTest(language=code, text=text):
                    edit = dict(kind="name", slot=slot["no"], string_id=slot["string_id"], text=text,
                                menu_language=code)
                    result, after = self.build([edit])
                    lent = {c["what"] for c in result["payload_changes"]} & {"name_lent_text"}
                    for lang in ALL:
                        at = menu_language.index(lang)
                        got = after.string(slot["string_id"], at)["text"]
                        if lang in ("en", code):
                            self.assertEqual(got, text, lang)
                        elif got != self.stock.string(slot["string_id"], at)["text"]:
                            # only the one language whose storage a longer name borrowed may change
                            self.assertTrue(lent and got == text, lang)
                    records = {c["what"] for c in result["payload_changes"] if c["what"].endswith("_record")}
                    others = {"name_%s_record" % c.replace("-", "_") for c in ALL if c not in ("en", code)}
                    self.assertFalse(records & others, records)


if __name__ == "__main__":
    unittest.main()

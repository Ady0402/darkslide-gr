"""The read-back checks keep their own menu-language table (verify_languages.py),
separate from the writer's (menu_language.py). Both must agree, and the checker's
table is pinned to the factory preset names in the official files."""

import os
import unittest
from pathlib import Path

from darkslide import fwread, menu_language, models, template, verify_languages as VL

GR3 = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
GR3X = Path(os.environ.get("DARKSLIDE_IIIX_BIN", "/nonexistent/fwdc243b.bin"))


# Factory "Positive Film" name per index, to pin the table to the firmware.
SAMPLES = {
    0: "ポジフィルム調", 1: "Positive Film", 2: "Film positif", 3: "Positivfilm",
    4: "Película positiva", 5: "Película Positiva", 6: "Pellicola positiva",
    7: "Positieffilm", 8: "Positiv film", 9: "Positiv film", 10: "Positiivinen filmi",
    11: "Film pozytywowy", 12: "Pozitivní film", 13: "Pozitív film", 14: "Pozitif Film",
    15: "Θετικό φιλμ", 16: "Позитивная пленка", 17: "포지티브 필름", 18: "正片",
    19: "正片", 20: "ฟิล์มโพสิทีฟ",
}


class Rules(unittest.TestCase):
    def test_writer_and_checker_tables_agree(self):
        self.assertEqual(VL.INDEX, {code: i for code, (i, _) in menu_language.CHOICES.items()})
        self.assertEqual(tuple(VL.NEVER_LENT), tuple(menu_language.KEEP))

    def test_policy(self):
        self.assertEqual(VL.chosen({}), ("zh-CN",))  # no choice: the 1.0.0 behaviour
        self.assertEqual(VL.chosen({"menu_language": "en"}), ())
        for code in ("ja", "ko", "zh-TW", "zh-CN", "th"):
            self.assertEqual(VL.chosen({"menu_language": code}), (code,))
        for bad in ("kr", "", None, [], {}, 1):
            with self.assertRaises(ValueError):
                VL.chosen({"menu_language": bad})
        self.assertTrue(VL.shows_new_name({"menu_language": "ko"}, "en"))
        self.assertFalse(VL.shows_new_name({"menu_language": "ko"}, "zh-CN"))


class Pinned(unittest.TestCase):
    def check(self, path, model):
        if not path.exists():
            self.skipTest("official firmware not available on this machine")
        layout = () if model == models.GR3 else (models.layout(model),)
        p = fwread.Payload(fwread.unpack(path.read_bytes()), *layout)
        string = next(s for s in template.load()["slots"] if s["no"] == 7)["string_id"]  # Positive Film
        for index, text in SAMPLES.items():
            self.assertEqual(p.string(string, index)["text"], text, index)

    def test_gr3_210(self):
        self.check(GR3, models.GR3)

    def test_gr3x_160(self):
        self.check(GR3X, models.GR3X)


if __name__ == "__main__":
    unittest.main()

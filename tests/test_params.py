import json
import tempfile
import unittest
from pathlib import Path

from darkslide import template as tpl

POSITIVE, NEGATIVE, STANDARD = 7, 12, 1


class FactoryParams(unittest.TestCase):
    def setUp(self):
        self.t = tpl.load()
        self.params = tpl.load_detail(self.t)["factory_params"]

    def values(self, no):
        return dict(self.params["slots"][str(no)]["items"])

    def test_every_preset_has_defaults(self):
        self.assertEqual(sorted(self.params["slots"], key=int), [str(s["no"]) for s in self.t["slots"]])

    def test_defaults_are_not_all_zero(self):
        self.assertTrue(all(v == 0 for v in self.values(STANDARD).values()))
        pos = self.values(POSITIVE)
        self.assertEqual((pos["高/低调"], pos["对比度"], pos["高光对比"], pos["阴影对比"]), (-1, 3, -1, -2))
        neg = self.values(NEGATIVE)
        self.assertEqual((neg["高/低调"], neg["对比度"], neg["阴影对比"]), (1, 1, -1))
        self.assertNotIn("颗粒", neg, "Negative Film has no grain item in the factory menu")

    def test_rejects_out_of_range(self):
        detail = tpl.load_detail(self.t)
        detail["factory_params"]["slots"]["1"]["items"][0][1] = 5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.detail.json"
            path.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
            old = tpl.TEMPLATE_ROOT
            tpl.TEMPLATE_ROOT = Path(tmp)
            try:
                with self.assertRaises(tpl.TemplateError):
                    tpl.load_detail(self.t, "bad.detail.json")
            finally:
                tpl.TEMPLATE_ROOT = old


if __name__ == "__main__":
    unittest.main()

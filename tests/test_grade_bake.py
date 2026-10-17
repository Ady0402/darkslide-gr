"""darkslide/grade_bake.py must bake exactly like the page (web/adjust.js combine camera=true, 33)."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from darkslide import film_luts, grade_bake

APP = Path(__file__).resolve().parents[1]
GRADES = [
    {}, {"exp": 34}, {"exp": -60}, {"temp": 40, "tint": -25}, {"con": 70, "hi": -30, "sh": 45},
    {"white": -50, "black": 38}, {"fade": 26, "sat": -99}, {"splitHi": 60, "splitSh": -44},
    {"curve": {"all": [[0, 0.05], [0.5, 0.55], [1, 0.95]], "b": [[0, 0], [0.4, 0.35], [1, 1]]}},
    {"vib": 30}, {"hH": [10, 0, 0, 0, 0, 0, 0, 0], "sat": 20},
]


def node_bake(base, grades):
    out = subprocess.run(["node", str(APP / "tools" / "grade_bake.cjs")], check=True, capture_output=True,
                         input=json.dumps(dict(adjust=str(APP / "web" / "adjust.js"), base=base, grades=grades)).encode())
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "needs node to run web/adjust.js")
class SameAsThePage(unittest.TestCase):
    def test_built_in_films_and_grades_are_byte_identical(self):
        for fid in ("gold200", "portra400", "5219"):
            base = film_luts.preview_path(fid).read_text(encoding="utf-8")
            for grade, page in zip(GRADES, node_bake(base, GRADES)):
                self.assertEqual(grade_bake.bake(base, grade), page, (fid, grade))

    def test_a_user_lut_of_another_size_with_windows_line_ends(self):
        size, data = grade_bake.parse_cube(film_luts.preview_path("gold200").read_text(encoding="utf-8"))
        small = [grade_bake._sample(size, data, [r / 16, g / 16, b / 16]) for b in range(17) for g in range(17) for r in range(17)]
        text = 'TITLE "mine"\r\n# comment\r\nLUT_3D_SIZE 17\r\n' + "".join("%.6f %.6f %.6f\r\n" % tuple(v) for v in small)
        grades = [{}, {"exp": 20, "fade": 10}]
        for grade, page in zip(grades, node_bake(text, grades)):
            self.assertEqual(grade_bake.bake(text, grade), page, grade)


class Basics(unittest.TestCase):
    def test_empty_grade_semantics_follow_the_page(self):
        self.assertTrue(grade_bake.is_empty({}))
        self.assertTrue(grade_bake.is_empty({"curve": {"all": [[0, 0], [1, 1]]}}))
        self.assertFalse(grade_bake.is_empty({"vib": 5}))
        self.assertTrue(grade_bake.is_empty_camera({"vib": 5}))
        self.assertFalse(grade_bake.is_empty_camera({"exp": 1}))

    def test_only_the_bake_block_is_fingerprinted(self):
        import tempfile
        text = grade_bake.WEB_ADJUST.read_text(encoding="utf-8")
        self.assertIn("function combine", text[text.index(grade_bake.BAKE_BEGIN):text.index(grade_bake.BAKE_END)])
        with tempfile.TemporaryDirectory() as d:
            ui = Path(d) / "ui.js"
            ui.write_text(text.replace("这个预设只能预览和导出 LUT", "改过的说明文字"), encoding="utf-8")
            self.assertEqual(grade_bake.page_bake_sha(ui), grade_bake.page_bake_sha())  # page wording: same table
            bake = Path(d) / "bake.js"
            bake.write_text(text.replace("const ev = Math.pow(2, val(g, \"exp\") / 50)", "const ev = Math.pow(2, val(g, \"exp\") / 40)"), encoding="utf-8")
            if bake.read_text(encoding="utf-8") != text:
                self.assertNotEqual(grade_bake.page_bake_sha(bake), grade_bake.page_bake_sha())  # colour math: table stale

    def test_rounding_matches_js_to_fixed(self):
        self.assertEqual(grade_bake._fixed(-0.0), "0.000000")
        self.assertEqual(grade_bake._fixed(0.0078125), "0.007813")  # exact tie: JS rounds up, "%.6f" would give 0.007812


if __name__ == "__main__":
    unittest.main()

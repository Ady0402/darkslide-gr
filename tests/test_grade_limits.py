"""Per-film slider ranges (darkslide/grade_limits.json) and the live write-range check."""
import copy
import json
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from darkslide import film_luts, models, server

APP = Path(__file__).resolve().parents[1]
TABLE = APP / "darkslide" / "grade_limits.json"
GR3_BIN = os.environ.get("DARKSLIDE_OFFICIAL_BIN")


def req(project, body=None):
    store = SimpleNamespace(get_project=lambda pid: copy.deepcopy(project), input_path=lambda sha: Path("/nonexistent") / sha)
    return SimpleNamespace(store=store, read_json=lambda: body)


GR3_PROJECT = dict(input_sha256=models.GR3.input_sha, template_id=models.GR3.id)
GR3X_PROJECT = dict(input_sha256=models.GR3X.input_sha, template_id=models.GR3X.id)


@unittest.skipUnless(TABLE.exists(), "grade limits not generated yet")
class Table(unittest.TestCase):
    def setUp(self):
        self.table = json.loads(TABLE.read_text(encoding="utf-8"))

    def test_table_is_fresh_for_the_current_page_code_and_film_data(self):
        # Changing web/adjust.js, the camera data or a preview LUT needs tools/build_grade_limits.py again.
        films = sorted(self.table["fingerprint"]["previews"])
        self.assertEqual(self.table["fingerprint"], server._grade_limits_fingerprint(films))

    def test_every_ready_film_both_models_every_slider(self):
        from darkslide import film_profiles
        ready = set(film_profiles.ready_profile_ids())
        for model in (models.GR3, models.GR3X):
            films = self.table["models"][model.id]
            self.assertEqual(set(films), ready, model.id)
            for fid, sliders in films.items():
                if sliders.get("_film_writable") is False:
                    continue
                for key in self.table["sliders"]:
                    lo, hi = sliders[key]
                    self.assertTrue(-100 <= lo <= 0 <= hi <= 100, (model.id, fid, key, lo, hi))

    def test_endpoint_serves_the_project_model_and_refuses_a_stale_table(self):
        out = server.api_grade_limits(req(GR3X_PROJECT), "p")
        self.assertTrue(out["valid"]); self.assertEqual(out["model_id"], models.GR3X.id)
        self.assertEqual(out["limits"], self.table["models"][models.GR3X.id])
        self.assertIsNone(out["curve_ends"])  # no original here: the drag hint is simply left out
        with patch.object(server, "_grade_limits_fingerprint", return_value={"adjust_js_sha256": "0" * 64}):
            stale = server.api_grade_limits(req(GR3_PROJECT), "p")
        self.assertFalse(stale["valid"]); self.assertEqual(stale["limits"], {})


class Check(unittest.TestCase):
    def test_bad_requests_are_refused_before_fitting(self):
        for body in (None, {}, {"cube": 1}, {"cube": ""}, {"cube": "x" * (8 * 1024 * 1024 + 1)}):
            with patch.object(server, "_camera_model", side_effect=AssertionError("fit")):
                with self.assertRaises(server.ApiError):
                    server.api_film_grade_check(req(GR3_PROJECT, body), "p")

    def test_missing_table_is_reported_as_not_available(self):
        with patch.object(server, "GRADE_LIMITS", APP / "darkslide" / "no_such_table.json"):
            out = server.api_grade_limits(req(GR3_PROJECT), "p")
        self.assertFalse(out["valid"])


@unittest.skipUnless(TABLE.exists() and GR3_BIN, "needs the table, the GR III original and the fitting component")
class TableAgreesWithRealFits(unittest.TestCase):
    """Spot check: a slider exactly at its tabled limit fits into the camera, one step past does not."""

    def test_a_few_limits_on_gr3(self):
        from darkslide import fitting_setup
        fitting_setup.activate()
        try:
            import unicorn  # noqa: F401
        except ImportError:
            self.skipTest("fitting component not installed")
        from darkslide import base_curve, factory_envelope
        from darkslide.film_fit_check import check_cube
        contract = base_curve.base_curve(Path(GR3_BIN))
        env = factory_envelope.factory_envelope(Path(GR3_BIN))
        table = json.loads(TABLE.read_text(encoding="utf-8"))["models"][models.GR3.id]
        cases = [(f, k, i) for f in ("gold200", "portra400") for k in ("exp", "fade") for i in (0, 1)]
        for fid, key, side in cases:
            limit = table[fid][key][side]
            if abs(limit) == 100:
                continue
            sign = -1 if side == 0 else 1
            base = film_luts.preview_path(fid).read_text(encoding="utf-8")
            out = subprocess.run(["node", str(APP / "tools" / "grade_bake.cjs")], check=True, capture_output=True,
                                 input=json.dumps(dict(adjust=str(APP / "web" / "adjust.js"), base=base,
                                                       grades=[{key: limit} if limit else {}, {key: limit + sign}])).encode())
            at, past = json.loads(out.stdout)
            self.assertTrue(check_cube(at.encode(), models.GR3, contract, env)["writable"], (fid, key, limit))
            self.assertFalse(check_cube(past.encode(), models.GR3, contract, env)["writable"], (fid, key, limit + sign))


if __name__ == "__main__":
    unittest.main()

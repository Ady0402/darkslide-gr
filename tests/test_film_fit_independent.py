"""Independent scalar expectations for admitted fits; no firmware generation.

The expected quantizer uses exact rational distances, never the importer or
vendor quantizer. Development fitting is checked at nodal samples where the
regularized solution has a closed form, without running another optimizer.
"""
import copy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from darkslide import film_fit_import, film_profiles, film_requests
from darkslide._vendor import gr3_fit_numeric

ROOT = Path(__file__).resolve().parents[1] / "film_curves"
IDS = {"portra400", "gold200", "ektar100", "pro400h", "ultramax400",
       "5207", "5219", "xtra400_portraendura"}
COMMIT = "04d5d5dd6e85d80089c6200bd0f0de5fff2d658f"


def nearest_even(value):
    """Nearest integer by comparing rational distances, including negatives."""
    value = value if isinstance(value, Fraction) else Fraction.from_float(value)
    lower = value.numerator // value.denominator
    remainder = value - lower
    if remainder < Fraction(1, 2):
        return lower
    if remainder > Fraction(1, 2):
        return lower + 1
    return lower if lower % 2 == 0 else lower + 1


def expected_q13(matrix):
    # Scaling a binary float by a power of two is exact in this admitted range.
    result = [[nearest_even(Fraction.from_float(float(v)) * 8192)
               for v in row] for row in matrix]
    for diagonal, row in enumerate(result):
        row[diagonal] = 8192 - sum(row[j] for j in range(3) if j != diagonal)
    return result


def archive():
    return json.loads((ROOT / "camera_profiles_manifest.json").read_text("utf-8"))


def source(entry):
    path = ROOT / entry["source_file"]
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


class IndependentFitTests(unittest.TestCase):
    def test_rational_oracle_only(self):
        # Preflight: no fit file, camera profile or firmware is accessed.
        for fraction, expected in ((Fraction(1, 2), 0), (Fraction(3, 2), 2),
                                   (Fraction(-1, 2), 0), (Fraction(-3, 2), -2),
                                   (Fraction(5, 2), 2), (Fraction(-5, 2), -2),
                                   (Fraction(7, 4), 2), (Fraction(-7, 4), -2)):
            self.assertEqual(nearest_even(fraction), expected)

    def test_half_ties_and_signed_scalar_quantization(self):
        for half in (-2.5, -1.5, -.5, .5, 1.5, 2.5):
            matrix = [[1 - half / 8192, half / 8192, 0],
                      [0, 1, 0], [half / 8192, 0, 1 - half / 8192]]
            self.assertEqual(gr3_fit_numeric.q13_matrix(matrix), expected_q13(matrix))
        # This specific half differentiates ties-even from ties-away.
        self.assertEqual(expected_q13([[1 - .5 / 8192, .5 / 8192, 0],
                                     [0, 1, 0], [0, 0, 1]])[0], [8192, 0, 0])
        for matrix in ([[True, 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[float("inf"), 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[.9, 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[4 - .25 / 8192, -3 + .25 / 8192, 0], [0, 1, 0], [0, 0, 1]]):
            with self.assertRaises(ValueError):
                gr3_fit_numeric.q13_matrix(matrix)

    def test_eight_saved_profiles_against_raw_scalar_expected(self):
        manifest = archive()
        self.assertEqual({e["id"] for e in manifest["profiles"]}, IDS)
        self.assertEqual(len(manifest["profiles"]), 8)
        self.assertEqual(manifest["commit"], COMMIT)
        for entry in manifest["profiles"]:
            with self.subTest(film=entry["id"]):
                fit, sha = source(entry)
                self.assertEqual(sha, entry["source_sha256"])
                original = copy.deepcopy(fit)
                preset = fit["presets"][0]
                actual = film_fit_import.convert_fit(fit, entry["id"], entry["source_path"], sha)
                # Archived upstream fits that went beyond the factory range are no longer the camera
                # file (replaced by Darkslide's in-range fit); the archive itself is still checked.
                in_use = entry.get("in_use", True)
                candidates = (actual,)
                if in_use:
                    profile = json.loads((ROOT / entry["camera_file"]).read_text("utf-8"))
                    self.assertEqual(hashlib.sha256((ROOT / entry["camera_file"]).read_bytes()).hexdigest(), entry["camera_sha256"])
                    candidates = (profile, actual)
                for candidate in candidates:
                    self.assertEqual(candidate["look_matrix_q13"], expected_q13(fit["matrix"]))
                    self.assertEqual(candidate["curves_u14"], preset["curves"])
                    post = fit["post_q512"] if "post_q512" in fit else fit["cca1_q512"]
                    self.assertEqual(candidate["post_matrix_q512"], post)
                    self.assertEqual(len(candidate["curves_u14"]), 3)
                    for row in candidate["curves_u14"]:
                        self.assertEqual(len(row), 256)
                        self.assertTrue(all(type(n) is int and 0 <= n <= 16383 for n in row))
                    for row in post:
                        self.assertEqual(sum(row), 512)
                        self.assertTrue(all(type(n) is int and -32768 <= n <= 32767 for n in row))
                    self.assertTrue(all(sum(abs(post[r][c]) for r in range(3)) <= 8191 for c in range(3)))
                    self.assertEqual(candidate["schema"], 1)
                    self.assertEqual(candidate["model"], "GR III")
                    self.assertEqual(candidate["firmware"], "2.10")
                    self.assertIs(candidate["native_effect_verified"], False)
                    p = candidate["provenance"]
                    self.assertEqual(p["source_sha256"], sha)
                    self.assertEqual(p["source_path"], entry["source_path"])
                    self.assertEqual(p["commit"], COMMIT)
                    self.assertEqual(p["target_spec"], preset["spec"])
                    self.assertEqual(p["target_input_encoding"], preset.get("in_cs", "vlog"))
                    self.assertEqual(p["target_ev"], preset.get("ev", 0.0))
                    for key, field in (("target_input_encoding_source", "in_cs"), ("target_ev_source", "ev")):
                        self.assertEqual(p[key], "explicit" if field in preset else "upstream target_of default")
                    self.assertEqual(p["source_mid_index"], 7.8)
                    self.assertIs(p["absolute_exposure_calibrated"], False)
                    self.assertEqual(p["license"], "CC-BY-SA-4.0")
                    self.assertEqual(p["authors"], ["Andrea Volpato", "idontknownihil"])
                    self.assertEqual(p["modified_by"], "LiorMoment")
                self.assertEqual(fit, original)
        own = {x["id"] for x in json.loads((ROOT / "camera_profiles_darkslide_fits.json").read_text("utf-8"))["profiles"]}
        in_use = {e["id"] for e in manifest["profiles"] if e.get("in_use", True)}
        self.assertFalse(own & in_use)
        self.assertEqual(set(film_profiles.ready_profile_ids()), in_use | own)
        # The writer status follows the dedicated v29 gate (opened for 1.0, 7fe9e46); data loading does not change it.
        from darkslide.inplace_generation import production_available
        self.assertIs(film_requests.status()["available"], production_available() is True)

    def test_format_rejects_hue_at_any_depth_and_v16_path(self):
        entry = archive()["profiles"][0]
        good, sha = source(entry)
        for key in ("hue_q10", "hue_sectors", "v16"):
            for location in ("top", "preset", "nested"):
                bad = copy.deepcopy(good)
                container = bad if location == "top" else bad["presets"][0]
                if location == "nested":
                    container["unsupported_extension"] = {key: []}
                else:
                    container[key] = []
                with self.subTest(key=key, location=location), self.assertRaises(film_requests.FilmRequestError):
                    film_fit_import.convert_fit(bad, entry["id"], entry["source_path"], sha)
        with self.assertRaises(film_requests.FilmRequestError):
            film_fit_import.convert_fit(good, entry["id"], "work/films_v16/fits/portra.json", sha)

    def test_post_legacy_mapping_conflict_and_overflow_rejection(self):
        entries = archive()["profiles"]
        legacy = [e for e in entries if "/films_v10/" in e["source_path"]]
        self.assertEqual({e["id"] for e in legacy}, {"ultramax400", "xtra400_portraendura"})
        for entry in legacy:
            fit, sha = source(entry)
            self.assertNotIn("post_q512", fit)
            actual = film_fit_import.convert_fit(fit, entry["id"], entry["source_path"], sha)
            self.assertEqual(actual["post_matrix_q512"], fit["cca1_q512"])
            fit["post_q512"] = [[512, 0, 0], [0, 512, 0], [0, 0, 512]]
            with self.assertRaises(film_requests.FilmRequestError):
                film_fit_import.convert_fit(fit, entry["id"], entry["source_path"], sha)
        entry = entries[0]
        good, sha = source(entry)
        for post in ([[32767, -32768, 513]] * 3, [[True, 0, 0]] * 3, [[512, 0, 0]]):
            bad = copy.deepcopy(good)
            bad.pop("cca1_q512", None)
            bad["post_q512"] = post
            with self.assertRaises(film_requests.FilmRequestError):
                film_fit_import.convert_fit(bad, entry["id"], entry["source_path"], sha)

    def test_fit_json_duplicate_nonfinite_and_overflow_float_rejected(self):
        for text in ('{"matrix":[],"matrix":[]}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "fit.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(film_requests.FilmRequestError):
                    film_fit_import.read_fit(path)

    def test_license_separation_and_attribution_archive(self):
        manifest = archive()
        self.assertEqual(manifest["license"], "CC-BY-SA-4.0")
        self.assertEqual(manifest["authors"], ["Andrea Volpato", "idontknownihil"])
        self.assertEqual(manifest["modified_by"], "LiorMoment")
        text = (ROOT / "README.md").read_text("utf-8")
        for required in ("Andrea Volpato", "https://github.com/andreavolpato/spektrafilm", "CC BY-SA 4.0", "idontknownihil", "LiorMoment"):
            self.assertIn(required, text)
        self.assertIn("Attribution-ShareAlike 4.0 International Public License", (ROOT / "SPEKTRAFILM_LICENSE.txt").read_text("utf-8"))
        changes = (ROOT / "CHANGELOG.txt").read_text("utf-8")
        for required in (COMMIT, "Andrea Volpato", "idontknownihil", "LiorMoment", "Curves/post values unchanged"):
            self.assertIn(required, changes)
        vendor = ROOT.parent / "darkslide" / "_vendor"
        license_text = (vendor / "GR3_FILM_MODS_LICENSE.txt").read_text("utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 idontknownihil", license_text)
        declaration = json.loads((vendor / "gr3_fit_numeric_source.json").read_text("utf-8"))
        self.assertEqual(declaration["commit"], COMMIT)
        self.assertEqual(declaration["license"], "MIT")


@unittest.skipUnless(importlib.util.find_spec("numpy"), "development NumPy unavailable")
class IndependentNodalFitTests(unittest.TestCase):
    def test_nodal_closed_form_without_second_fit(self):
        # At exact knots with lam=0 the normal matrix is diagonal. Include a
        # duplicate final clipped sample at g=16384 to test the endpoint.
        g = [64 * i for i in range(256)] + [16384]
        t = [((i * 37) % 257) / 256 for i in range(256)] + [1.0]
        weights = [1 + i % 5 for i in range(256)] + [2]
        expected = []
        maximum = 0.0
        for i in range(256):
            w = weights[i] + (2 if i == 255 else 0)
            numerator = weights[i] * t[i] * 16384 + (32768 if i == 255 else 0)
            c = numerator / (w + 1e-6)
            maximum = max(maximum, min(16383.0, c))
            expected.append(nearest_even(float(maximum)))
        self.assertEqual(gr3_fit_numeric.fit_curve(g, t, weights, lam=0), expected)

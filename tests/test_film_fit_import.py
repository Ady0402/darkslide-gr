import copy
import json
from pathlib import Path
import unittest
from darkslide import film_profiles,film_requests,film_fit_import
from darkslide._vendor.gr3_fit_numeric import q13_matrix

ROOT=Path(__file__).resolve().parents[1]/"film_curves"


class FilmFitImportTests(unittest.TestCase):
    def test_all_actual_profiles_load_and_preserve_curve_post(self):
        manifest=json.loads((ROOT/"camera_profiles_manifest.json").read_text())
        self.assertEqual(len(manifest["profiles"]),8)
        own=[x["id"] for x in json.loads((ROOT/"camera_profiles_darkslide_fits.json").read_text())["profiles"]]
        # The camera folder holds these 8 upstream fits plus the fits Darkslide made itself.
        in_use=[x for x in manifest["profiles"] if x.get("in_use",True)]
        self.assertEqual(sorted([x["id"] for x in in_use]+own),film_profiles.ready_profile_ids())
        for entry in in_use:
            fit,sha=film_fit_import.read_fit(ROOT/entry["source_file"])
            self.assertEqual(sha,entry["source_sha256"])
            profile=film_profiles.load_profile(entry["id"])
            self.assertEqual(profile["curves_u14"],fit["presets"][0]["curves"])
            self.assertEqual(profile["post_matrix_q512"],fit.get("post_q512",fit.get("cca1_q512")))
            self.assertFalse(profile["native_effect_verified"])
            converted=film_fit_import.convert_file(ROOT/entry["source_file"],entry["id"],entry["source_path"])
            for key in ("look_matrix_q13","curves_u14","post_matrix_q512"):
                self.assertEqual(profile[key],converted[key])
        self.assertIn("xtra400_portraendura",film_profiles.ready_profile_ids())
        self.assertNotIn("xtra400",film_profiles.ready_profile_ids())
        # The writer status follows the dedicated v29 gate (opened for 1.0, 7fe9e46), not the profile data.
        from darkslide.inplace_generation import production_available
        self.assertEqual(film_requests.status()["available"], production_available() is True)

    def test_quantization_matches_source_ties_even_and_guards(self):
        matrix=[[1,0,0],[0.5/8192,1-0.5/8192,0],[0,1.5/8192,1-1.5/8192]]
        self.assertEqual(q13_matrix(matrix),[[8192,0,0],[0,8192,0],[0,2,8190]])
        for row in ([True,0,0],[float("nan"),0,1],[4,-3,0],[.9,0,0]):
            with self.assertRaises(ValueError):q13_matrix([row,[0,1,0],[0,0,1]])

    def test_unsupported_or_ambiguous_fit_rejected(self):
        manifest=json.loads((ROOT/"camera_profiles_manifest.json").read_text());entry=manifest["profiles"][0]
        good,sha=film_fit_import.read_fit(ROOT/entry["source_file"])
        for field,value in (("hue_q10",[]),("mid_index",8),("post_q512",[[512,0,0]]*3),("matrix",[[True,0,0]]*3)):
            bad=copy.deepcopy(good);bad[field]=value
            if field=="post_q512":bad["cca1_q512"]=[[0,512,0]]*3
            with self.assertRaises(film_requests.FilmRequestError):film_fit_import.convert_fit(bad,entry["id"],entry["source_path"],sha)
        for field,value in (("in_cs","unknown"),("ev",True),("spec","private_adobe.cube"),("curves",[[16384]*256]*3)):
            bad=copy.deepcopy(good);bad["presets"][0][field]=value
            with self.assertRaises(film_requests.FilmRequestError):film_fit_import.convert_fit(bad,entry["id"],entry["source_path"],sha)

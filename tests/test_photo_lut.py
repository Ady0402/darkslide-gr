import base64
import math
import unittest

from darkslide import photo_lut as pl


def scene(w=160, h=120):
    """A synthetic photo: sky, ground, grey ramp, colour and skin patches, a dark corner."""
    px = bytearray()
    for y in range(h):
        for x in range(w):
            if y < h * 0.4:
                t = y / (h * 0.4)
                c = (int(90 + 120 * t), int(140 + 90 * t), int(210 + 30 * t))
            elif y > h * 0.85:
                v = int(10 + 235 * x / (w - 1))
                c = (v, v, v)
            else:
                c = (int(60 + 40 * math.sin(x / 7)), int(110 + 30 * math.cos(y / 5)), 50)
            if 20 <= x < 45 and 55 <= y < 80:
                c = (200, 40, 35)
            if 55 <= x < 80 and 55 <= y < 80:
                c = (225, 190, 40)
            if 90 <= x < 115 and 55 <= y < 80:
                c = (215, 165, 135)
            if 125 <= x < 150 and 55 <= y < 80:
                c = (35, 70, 150)
            if x < 18 and y > h * 0.55:
                c = (12, 14, 16)
            px += bytes(c)
    return {"w": w, "h": h, "rgb": base64.b64encode(bytes(px)).decode("ascii")}


TRUE_MODEL = {"version": 1,
              "tone": [round(min(1.0, 0.08 + 0.92 * (k / 32) ** 1.1), 6) for k in range(33)],
              "zones": [{"scale": 0.85, "da": -0.012, "db": -0.018},
                        {"scale": 0.8, "da": 0.004, "db": 0.006},
                        {"scale": 0.9, "da": 0.015, "db": 0.025}]}
PLAIN = dict(pl.PARAMS, protect_skin=False)


def graded(image, model, params=PLAIN):
    m, p = pl._model(model), pl._params(params)
    raw = base64.b64decode(image["rgb"])
    out = bytearray()
    for i in range(0, len(raw), 3):
        rgb = pl.apply(m, p, tuple(v / 255.0 for v in raw[i:i + 3]))
        out += bytes(int(round(v * 255)) for v in rgb)
    return dict(image, rgb=base64.b64encode(bytes(out)).decode("ascii"))


def grid_distance(model_a, model_b, params=PLAIN, n=9):
    """Mean Oklab distance x100 (roughly dE) between two looks over an n^3 grid."""
    a, b, p = pl._model(model_a), pl._model(model_b), pl._params(params)
    total = 0.0
    for i in range(n ** 3):
        rgb = (i % n / (n - 1), i // n % n / (n - 1), i // (n * n) / (n - 1))
        la = pl._oklab(*(pl._dec(c) for c in pl.apply(a, p, rgb)))
        lb = pl._oklab(*(pl._dec(c) for c in pl.apply(b, p, rgb)))
        total += math.dist(la, lb) * 100
    return total / n ** 3


class Learn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = scene()
        cls.ref = graded(cls.src, TRUE_MODEL)

    def test_same_photo_learns_nothing(self):
        res = pl.learn(self.src, [self.src])
        tone = res["model"]["tone"]
        self.assertLess(max(abs(v - k / 32) for k, v in enumerate(tone)), 0.03)
        for z in res["model"]["zones"]:
            self.assertAlmostEqual(z["scale"], 1.0, delta=0.02)
            self.assertLess(math.hypot(z["da"], z["db"]), 0.003)
        self.assertEqual(res["warnings"], [])

    def test_recovers_a_known_look(self):
        res = pl.learn(self.ref, [self.src])
        d = grid_distance(res["model"], TRUE_MODEL)
        self.assertLess(d, 2.5, "mean grid distance %.2f" % d)
        base = grid_distance({"version": 1, "tone": [k / 32 for k in range(33)],
                              "zones": [{"scale": 1.0, "da": 0.0, "db": 0.0}] * 3}, TRUE_MODEL)
        self.assertLess(d, base / 3, "learning must beat doing nothing by far")

    def test_tone_curve_monotone_and_bounded(self):
        tone = pl.learn(self.ref, [self.src])["model"]["tone"]
        self.assertEqual(tone, sorted(tone))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in tone))
        self.assertGreater(tone[0], 0.03, "lifted blacks are learned")

    def test_single_colour_reference_warns_and_lowers_tint(self):
        orange = {"w": 64, "h": 48, "rgb": base64.b64encode(bytes((230, 120, 40)) * 64 * 48).decode()}
        res = pl.learn(orange, [self.src])
        self.assertTrue(any("颜色太集中" in w for w in res["warnings"]))
        self.assertEqual(res["defaults"]["tint"], 0.5)
        for z in res["model"]["zones"]:
            self.assertLessEqual(math.hypot(z["da"], z["db"]), pl.MAX_SHIFT + 1e-9)

    def test_sunset_gradient_counts_as_one_colour_but_a_normal_scene_does_not(self):
        px = bytearray()
        for y in range(60):
            t = y / 59
            px += bytes((int(242 - 120 * t), int(160 - 106 * t), int(60 - 42 * t))) * 80
        sunset = {"w": 80, "h": 60, "rgb": base64.b64encode(bytes(px)).decode()}
        self.assertTrue(any("颜色太集中" in w for w in pl.learn(sunset, [self.src])["warnings"]))
        self.assertFalse(any("颜色太集中" in w for w in pl.learn(self.ref, [self.src])["warnings"]))

    def test_brightness_mismatch_warns(self):
        dark = graded(self.src, {"version": 1, "tone": [0.4 * k / 32 for k in range(33)],
                                 "zones": [{"scale": 1.0, "da": 0.0, "db": 0.0}] * 3})
        res = pl.learn(dark, [self.src])
        self.assertTrue(any("明暗差别很大" in w for w in res["warnings"]))

    def test_rejects_bad_input(self):
        good = self.src
        bad = [({"w": 0, "h": 1, "rgb": ""}, [good]), ({"w": 641, "h": 1, "rgb": ""}, [good]),
               (dict(good, rgb="@@@"), [good]), (dict(good, rgb=base64.b64encode(b"abc").decode()), [good]),
               (good, []), (good, [good] * 5), (dict(good, extra=1), [good]), (good, "x")]
        for ref, srcs in bad:
            with self.assertRaises(pl.PhotoLutError):
                pl.learn(ref, srcs)
        clipped = {"w": 16, "h": 16, "rgb": base64.b64encode(b"\xff" * 768).decode()}
        with self.assertRaises(pl.PhotoLutError):
            pl.learn(clipped, [good])


class Bake(unittest.TestCase):
    def test_strength_zero_is_identity(self):
        cube = pl.bake(TRUE_MODEL, {"strength": 0.0}, size=5)
        rows = [tuple(map(float, l.split())) for l in cube.splitlines()[5:]]
        self.assertEqual(len(rows), 125)
        for i, row in enumerate(rows):
            want = (i % 5 / 4, i // 5 % 5 / 4, i // 25 / 4)
            for x, y in zip(row, want):
                self.assertAlmostEqual(x, y, places=4)

    def test_keep_neutral_keeps_grey(self):
        m, p = pl._model(TRUE_MODEL), pl._params({"keep_neutral": True})
        for v in (0.1, 0.4, 0.8):
            r, g, b = pl.apply(m, p, (v, v, v))
            self.assertLess(max(r, g, b) - min(r, g, b), 0.004)
        r, g, b = pl.apply(m, pl._params({}), (0.1, 0.1, 0.1))
        self.assertGreater(abs(r - b), 0.004, "without it the shadows take the tint")

    def test_header_title_and_range(self):
        cube = pl.bake(TRUE_MODEL, None, name='My "look"\n1', size=3)
        lines = cube.splitlines()
        self.assertEqual(lines[0], 'TITLE "My look1"')
        self.assertIn("LUT_3D_SIZE 3", lines)
        self.assertTrue(all(0.0 <= float(v) <= 1.0 for l in lines[5:] for v in l.split()))

    def test_rejects_tampered_model_and_params(self):
        bad_models = [dict(TRUE_MODEL, version=2), dict(TRUE_MODEL, extra=1),
                      dict(TRUE_MODEL, tone=list(reversed(TRUE_MODEL["tone"]))),
                      dict(TRUE_MODEL, tone=TRUE_MODEL["tone"][:-1]),
                      dict(TRUE_MODEL, zones=[{"scale": 3.0, "da": 0, "db": 0}] * 3),
                      dict(TRUE_MODEL, zones=[{"scale": 1.0, "da": 0.5, "db": 0}] * 3),
                      dict(TRUE_MODEL, zones=[{"scale": float("nan"), "da": 0, "db": 0}] * 3)]
        for m in bad_models:
            with self.assertRaises(pl.PhotoLutError):
                pl.bake(m, size=2)
        for p in ({"strength": 2}, {"protect_skin": 1}, {"unknown": 0.5}, {"tint": "x"}, [1]):
            with self.assertRaises(pl.PhotoLutError):
                pl.bake(TRUE_MODEL, p, size=2)
        with self.assertRaises(pl.PhotoLutError):
            pl.bake(TRUE_MODEL, size=99)


try:
    from tests.test_http import Served
except ImportError:  # run through "discover -s tests"
    from test_http import Served


class Http(Served):
    def test_learn_then_bake(self):
        src = scene(80, 60)
        ref = graded(src, TRUE_MODEL)
        res = self.call("POST", "/api/photo-lut/learn", {"reference": ref, "sources": [src]})
        learned = self.assertJson(res, 200)
        self.assertEqual(set(learned), {"model", "warnings", "defaults"})
        res = self.call("POST", "/api/photo-lut/bake", {"model": learned["model"], "params": {"strength": 0.5},
                                                         "name": "Test", "size": 5})
        cube = self.assertJson(res, 200)["cube"]
        self.assertTrue(cube.startswith('TITLE "Test"'))
        self.assertEqual(len(cube.splitlines()), 5 + 125)

    def test_errors_are_readable(self):
        res = self.call("POST", "/api/photo-lut/learn", {"reference": {"w": 0, "h": 1, "rgb": ""}, "sources": []})
        self.assertEqual(res.status, 422)
        self.assertIn("参考照片", res.json()["error"])
        res = self.call("POST", "/api/photo-lut/bake", {"model": {"version": 9}})
        self.assertError(res, 422, "模型格式错误")
        res = self.call("POST", "/api/photo-lut/bake", b"not json")
        self.assertError(res, 400, "请求格式错误")
        res = self.call("GET", "/api/photo-lut/learn")
        self.assertEqual(res.status, 404)


if __name__ == "__main__":
    unittest.main()

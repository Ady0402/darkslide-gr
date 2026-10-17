"""User LUT slider ranges and 「收进相机范围」 (darkslide/lut_ranges.py and its endpoints).

The search logic runs here with a stand-in for the real fit (a simple rule on the baked LUT),
so it needs no fitting component; the slow real run is behind DARKSLIDE_SLOW_TESTS."""
import copy
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from darkslide import film_luts, fwread, grade_bake, lut_ranges, models, server
from darkslide import template as tpl
from darkslide.store import Store

APP = Path(__file__).resolve().parents[1]
GOLD = film_luts.preview_path("gold200").read_text(encoding="utf-8")


class InlinePool:
    """Runs each task at once, in this process, like a pool of one."""

    def submit(self, fn, *args):
        f = Future()
        f.set_result(fn(*args))
        return f


class Api:
    def __init__(self, first=()):
        self.seen, self.first, self.parts = [], list(first), []

    def progress(self, done, total=None):
        self.seen.append((done, total))

    def check(self):
        pass

    def priority(self):
        return list(self.first)

    def partial(self, done):
        self.parts.append(dict(done))

    def close_if(self, finished):
        return all(x in finished for x in self.first)


def black_white(text):
    _, d = grade_bake.parse_cube(text)
    return max(d[0:3]), min(d[-3:])


def rule_ends(text):
    """Stand-in camera: the curve start follows black, the end follows white."""
    black, white = black_white(text)
    bad = []
    if black > 0.10:
        bad.append("曲线起点 %d 超出原厂范围（0～1920）" % round(black * 16383))
    if white < 0.80:
        bad.append("曲线终点 %d 超出原厂范围（12694～16383）" % round(white * 16383))
    return dict(writable=not bad, violations=bad, reason=None, level="中", de_mean=2.0)


def rule_colour(text):
    """Stand-in camera: colours may not move further than 0.25 from no change at all."""
    _, d = grade_bake.parse_cube(text)
    m, worst, i = 32, 0.0, 0
    for b in range(33):
        for g in range(33):
            for r in range(33):
                worst = max(worst, abs(d[i] - r / m), abs(d[i + 1] - g / m), abs(d[i + 2] - b / m))
                i += 3
    if worst > 0.25:
        return dict(writable=False, violations=[], reason="颜色变化太大，相机的颜色矩阵装不下", level=None, de_mean=None)
    return dict(writable=True, violations=[], reason=None, level="高", de_mean=1.0)


def inline(rule):
    def pool(initargs):
        lut_ranges._W.update(base=initargs[3])
        return InlinePool()
    return [patch.object(lut_ranges.JOBS, "pool", side_effect=pool), patch.object(lut_ranges.JOBS, "release"),
            patch.object(lut_ranges, "_check", side_effect=rule)]


class Search(unittest.TestCase):
    def run_with(self, rule, fn, *args, api=None, **kw):
        ps = inline(rule)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        return fn(api or Api(), models.GR3.id, {}, {}, *args, **kw)

    def test_only_the_sliders_asked_for_are_worked_out_and_more_can_join(self):
        calls, saved = [], {}

        def rule(text):
            calls.append(text)
            return rule_ends(text)
        api = Api(first=["fade"])
        real_partial = api.partial

        def partial(done):  # the user drags exposure once fade is known
            real_partial(done)
            if "fade" in done and "exp" not in api.first:
                api.first.insert(0, "exp")
        api.partial = partial
        out = self.run_with(rule, lut_ranges.compute_ranges, GOLD, api=api, save=saved.update)
        self.assertEqual(set(out), {"_film_writable", "fade", "exp"})  # nothing else was computed
        self.assertEqual(saved, out)  # each saved as it finished
        self.assertEqual([list(p) for p in api.parts], [["fade"], ["exp"]])
        everything = self.run_with(rule_ends, lut_ranges.compute_ranges, GOLD, api=Api(first=["exp", "fade", "black"]))
        self.assertEqual(out["fade"], everything["fade"]); self.assertEqual(out["exp"], everything["exp"])
        # The LUT's own check and several of fade's values go out together (nothing for other sliders).
        fade = {grade_bake.bake(GOLD, {"fade": v}) for v in range(-100, 101)}  # negative fade changes nothing
        self.assertEqual(calls[0], grade_bake.bake(GOLD, {}))
        self.assertTrue(all(c in fade for c in calls[1:lut_ranges.worker_count()]))
        self.assertIn(grade_bake.bake(GOLD, {"fade": 100}), calls[1:lut_ranges.worker_count()])
        # Known not to fit: nothing is tried at all.
        calls.clear()
        self.assertEqual(self.run_with(rule, lut_ranges.compute_ranges, GOLD, api=Api(first=["exp"]), writable=False),
                         {"_film_writable": False})
        self.assertEqual(calls, [])

    def test_a_jagged_edge_gives_the_conservative_limit(self):
        # Like portra400 Blacks + on the real camera: fits up to 37, then 41-43 and 50 again.
        bad = set(range(38, 41)) | set(range(44, 50))
        jagged = lambda grade: grade.get("fade", 0) <= 50 and grade.get("fade", 0) not in bad
        saved = {}
        with patch.object(lut_ranges, "_grade_task", side_effect=jagged):
            out = self.run_with(rule_ends, lut_ranges.compute_ranges, GOLD, api=Api(first=["fade"]), save=saved.update)
        self.assertEqual(out["fade"], [-100, 37])
        self.assertEqual(saved["fade"], [-100, 37])
        self.assertEqual(lut_ranges._window(37), [37, 36, 35, 34, 33, 32, 31])

    def test_points_and_settling(self):
        self.assertEqual(lut_ranges._points(0, None, 1), [100])
        self.assertEqual(lut_ranges._points(0, 100, 1), [50])
        self.assertEqual(lut_ranges._points(34, 36, 4), [35])
        self.assertEqual(lut_ranges._settle([0, None], {25: True, 50: False, 75: False, 100: False}), [25, 50])
        self.assertEqual(lut_ranges._settle([0, None], {100: True}), [100, None])

    def test_ranges_are_the_largest_writable_whole_values(self):
        out = self.run_with(rule_ends, lut_ranges.compute_ranges, GOLD, api=Api(first=["exp", "fade"]))
        self.assertTrue(out["_film_writable"])
        ok = lambda k, v: rule_ends(grade_bake.bake(GOLD, {k: v} if v else {}))["writable"]
        for key in ("exp", "fade"):
            lo, hi = out[key]
            self.assertTrue(-100 <= lo <= 0 <= hi <= 100)
            for limit, step in ((lo, -1), (hi, 1)):
                self.assertTrue(ok(key, limit), (key, limit))
                if abs(limit) < 100:
                    self.assertFalse(ok(key, limit + step), (key, limit + step))
        self.assertLess(out["exp"][1], 100)  # exposure lifts the film's black: there is a limit

    def test_a_lut_that_is_not_writable_by_itself_has_no_ranges(self):
        faded = grade_bake.bake(GOLD, {"fade": 90})
        saved = {}
        out = self.run_with(rule_ends, lut_ranges.compute_ranges, faded, api=Api(first=["exp"]), save=saved.update)
        self.assertEqual(out, {"_film_writable": False}); self.assertEqual(saved, {"_film_writable": False})

    def test_curve_ends_are_fixed_by_pulling_black_and_white_in(self):
        faded = grade_bake.bake(GOLD, {"fade": 80})
        out = self.run_with(rule_ends, lut_ranges.fit_into, faded)
        self.assertFalse(out["already"])
        self.assertTrue(out["check"]["writable"])
        self.assertTrue(rule_ends(out["cube"])["writable"])
        self.assertGreater(out["levels"], 0); self.assertEqual(out["blend"], 0)
        self.assertIn("曲线起点", out["was"])
        self.assertGreater(out["change_de"], 0)
        # The smallest step that works: 1/64 less is not writable.
        self.assertFalse(rule_ends(lut_ranges.derive(faded, out["levels"] - 1 / 64, 0))["writable"])

    def test_colour_problems_move_towards_no_change(self):
        inverted = grade_bake.cube_text(33, [v for b in range(33) for g in range(33) for r in range(33)
                                             for v in (1 - r / 32, 1 - g / 32, 1 - b / 32)])
        out = self.run_with(rule_colour, lut_ranges.fit_into, inverted)
        self.assertTrue(rule_colour(out["cube"])["writable"])
        self.assertEqual(out["levels"], 0); self.assertGreater(out["blend"], 0.5)

    def test_already_writable_and_impossible_cases(self):
        self.assertTrue(self.run_with(rule_ends, lut_ranges.fit_into, GOLD)["already"])
        never = lambda text: dict(writable=False, violations=[], reason="不行", level=None, de_mean=None)
        with self.assertRaisesRegex(ValueError, "没法收进相机范围"):
            self.run_with(never, lut_ranges.fit_into, GOLD)

    def test_derive_keeps_black_and_white_tint_and_stays_in_0_1(self):
        faded = grade_bake.bake(GOLD, {"fade": 80})
        _, a = grade_bake.parse_cube(faded)
        _, b = grade_bake.parse_cube(lut_ranges.derive(faded, 1, 0))
        self.assertAlmostEqual(max(b[0:3]), lut_ranges.BLACK_TARGET, places=5)
        self.assertGreater(b[2] - b[0], 0)  # gold200's blue-ish black stays blue-ish
        self.assertTrue(all(0 <= v <= 1 for v in b))
        self.assertEqual(lut_ranges.derive(faded, 0, 0), grade_bake.cube_text(33, lut_ranges._grid(faded)))


class Lanes(unittest.TestCase):
    def test_a_pull_the_user_waits_for_does_not_queue_behind_slider_ranges(self):
        import threading
        jobs, gate = lut_ranges.Jobs(), threading.Event()
        jobs.submit("ranges-1", lambda api: gate.wait(5) and {}, 1)
        jobs.submit("ranges-2", lambda api: {}, 1)
        jobs.submit("pull", lambda api: {"ok": True}, 1, lane="now")
        for _ in range(200):
            if (jobs.status("pull") or {}).get("state") == "done":
                break
            time.sleep(0.01)
        self.assertEqual(jobs.status("pull")["result"], {"ok": True})
        self.assertEqual(jobs.status("ranges-1")["state"], "running")
        self.assertEqual(jobs.status("ranges-2")["state"], "queued")
        self.assertEqual(jobs.status("ranges-2")["ahead"], 0)
        gate.set()


def req(store, body=None):
    return SimpleNamespace(store=store, read_json=lambda: copy.deepcopy(body))


def wait_done(key):
    for _ in range(200):
        s = lut_ranges.JOBS.status(key)
        if s and s["state"] in ("done", "failed"):
            return s
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class Endpoints(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        with patch.object(self.store, "has_input", return_value=True):
            self.pid = self.store.create_project("ranges", fwread.V210_INPUT_SHA256, tpl.load())["id"]
        self.lid = self.store.put_film_lut(self.pid, GOLD.encode(), "mine.cube")["id"]
        for p in (patch.object(lut_ranges, "JOBS", lut_ranges.Jobs()),  # its own runner: other tests may stop the shared one
                  patch.object(server, "_camera_model", return_value={"values": []}),
                  patch.object(server, "_factory_envelope", return_value={"model_id": models.GR3.id})):
            p.start()
            self.addCleanup(p.stop)

    def compute(self, values):
        def run(api, *args, save=None, writable=None):
            self.writable_seen.append(writable)
            for slider in api.priority():
                save({"_film_writable": True, slider: values[slider]})
            return {}
        self.writable_seen = []
        return patch.object(lut_ranges, "compute_ranges", side_effect=run)

    def ask(self, slider):
        out = server.api_start_lut_ranges(req(self.store, {"slider": slider}), self.pid, self.lid)
        _, _, _, key = server._ranges_source(req(self.store), self.pid, self.lid)
        if lut_ranges.JOBS.status(key):
            wait_done(key)
        return out

    def test_a_slider_is_worked_out_when_asked_then_served_from_the_cache(self):
        self.assertEqual(server.api_lut_ranges(req(self.store), self.pid, self.lid), {"state": "idle", "limits": {}})  # picking starts nothing
        with self.compute({"exp": [-30, 25], "fade": [-100, 20]}) as compute:
            self.ask("exp")
            self.assertEqual(server.api_lut_ranges(req(self.store), self.pid, self.lid)["limits"], {"_film_writable": True, "exp": [-30, 25]})
            self.ask("exp")
            self.assertEqual(compute.call_count, 1)  # known: not again
            self.ask("fade")
            self.assertEqual(compute.call_count, 2)
            self.assertEqual(self.writable_seen, [None, True])  # the LUT's own check is not repeated
        out = server.api_lut_ranges(req(self.store), self.pid, self.lid)
        self.assertEqual(out["limits"], {"_film_writable": True, "exp": [-30, 25], "fade": [-100, 20]})
        record = json.loads((self.store._dir(self.pid) / "luts" / (self.lid + ".ranges.json")).read_text())
        self.assertEqual(record["fingerprint"]["cube_sha256"], self.store.list_film_luts(self.pid)[0]["sha256"])
        self.assertEqual(record["fingerprint"]["model_id"], models.GR3.id)
        for body in (None, {}, {"slider": "vib"}, {"slider": 1}):  # HSL/vibrance never go into the camera
            with self.assertRaises(server.ApiError):
                server.api_start_lut_ranges(req(self.store, body), self.pid, self.lid)

    def test_a_second_slider_joins_the_running_job(self):
        import threading
        gate, seen = threading.Event(), {}

        def run(api, *args, save=None, writable=None):
            gate.wait(5)
            seen["asked"] = api.priority()
            return {}
        with patch.object(lut_ranges, "compute_ranges", side_effect=run) as compute:
            server.api_start_lut_ranges(req(self.store, {"slider": "fade"}), self.pid, self.lid)
            server.api_start_lut_ranges(req(self.store, {"slider": "exp"}), self.pid, self.lid)
            gate.set()
            _, _, _, key = server._ranges_source(req(self.store), self.pid, self.lid)
            wait_done(key)
        self.assertEqual(compute.call_count, 1)
        self.assertEqual(seen["asked"], ["exp", "fade"])

    def test_a_cache_from_other_page_code_is_not_used(self):
        _, _, fp, _ = server._ranges_source(req(self.store), self.pid, self.lid)
        self.store.set_film_lut_ranges(self.pid, self.lid, dict(fingerprint=dict(fp, adjust_js_sha256="0" * 64), limits={"exp": [0, 0]}))
        self.assertEqual(server.api_lut_ranges(req(self.store), self.pid, self.lid)["limits"], {})

    def test_grade_bakes_are_not_ranged_and_deleting_removes_the_cache(self):
        bake = self.store.put_film_lut(self.pid, grade_bake.bake(GOLD, {"exp": 5}).encode(), "调色", bake={"film": "gold200", "grade": {"exp": 5}})
        with self.assertRaises(server.ApiError):
            server.api_lut_ranges(req(self.store), self.pid, bake["id"])
        self.store.set_film_lut_ranges(self.pid, self.lid, {"fingerprint": {}, "limits": {}})
        self.store.delete_film_lut(self.pid, self.lid)
        self.assertFalse((self.store._dir(self.pid) / "luts" / (self.lid + ".ranges.json")).exists())

    def test_fit_into_refuses_bad_requests_before_fitting_and_stores_nothing(self):
        with patch.object(server, "_camera_model", side_effect=AssertionError("fit")):
            for body in (None, {}, {"cube": 1}, {"cube": ""}, {"cube": "not a cube"}):
                with self.assertRaises((server.ApiError, film_luts.FilmLutError)):
                    server.api_start_fit_into(req(self.store, body), self.pid)
        before = sorted(p.name for p in (self.store._dir(self.pid) / "luts").iterdir())
        result = {"already": False, "cube": GOLD, "check": {"writable": True}}
        with patch.object(lut_ranges, "fit_into", return_value=result):
            out = server.api_start_fit_into(req(self.store, {"cube": GOLD}), self.pid)
            done = wait_done(("fit-into", self.pid, out["job"]))
        self.assertEqual(done["result"], result)
        self.assertEqual(server.api_fit_into_status(req(self.store), self.pid, out["job"])["result"], result)
        self.assertEqual(sorted(p.name for p in (self.store._dir(self.pid) / "luts").iterdir()), before)
        self.assertEqual(len(self.store.list_film_luts(self.pid)), 1)

    def test_routes_exist(self):
        paths = {(m, p.pattern) for m, p, _ in server.ROUTES}
        for method, url in (("GET", "/api/projects/p_000000000000/film-luts/user_lut_000000000000/ranges"),
                            ("POST", "/api/projects/p_000000000000/film-luts/user_lut_000000000000/ranges"),
                            ("POST", "/api/projects/p_000000000000/film-fit-into"),
                            ("GET", "/api/projects/p_000000000000/film-fit-into/0123456789abcdef")):
            self.assertTrue(any(m == method and p.fullmatch(url) for m, p, _ in server.ROUTES), url)


GR3_BIN = os.environ.get("DARKSLIDE_OFFICIAL_BIN")


@unittest.skipUnless(GR3_BIN and os.environ.get("DARKSLIDE_SLOW_TESTS"), "slow: real fits on the GR III original (about 1–2 minutes)")
class RealFits(unittest.TestCase):
    def test_gold200_as_a_user_lut_gets_the_same_ranges_as_the_built_in_table(self):
        from darkslide import base_curve, factory_envelope, fitting_setup
        fitting_setup.activate()
        contract = base_curve.base_curve(Path(GR3_BIN))
        env = factory_envelope.factory_envelope(Path(GR3_BIN))
        out = lut_ranges.compute_ranges(Api(first=lut_ranges.SLIDERS), models.GR3.id, contract, env, GOLD)
        table = json.loads((APP / "darkslide" / "grade_limits.json").read_text(encoding="utf-8"))
        self.assertEqual(out, table["models"][models.GR3.id]["gold200"])


if __name__ == "__main__":
    unittest.main()

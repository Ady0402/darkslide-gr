"""Precompute, per built-in film and camera model, how far each grading slider can go
on its own before the result no longer fits into the camera (darkslide/grade_limits.json).

For every (model, film, slider, direction) the grade is baked exactly as the page does
(tools/grade_bake.cjs runs web/adjust.js), fitted for real and checked with
film_fit_check.check_cube; the largest whole value that is still writable is found by
bisection (0 must be writable, 100 is tried first). Several sliders together can still
exceed the range: the page checks the actual combination after grading.

Development tool; needs node and the fitting component. Reads the official originals,
writes no firmware. Usage:
  python3 tools/build_grade_limits.py --gr3 <fwdc239b.bin> --gr3x <fwdc243b.bin> [--workers 8] [--films id,id]
"""
import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from darkslide import film_luts, film_profiles, models  # noqa: E402

SLIDERS = ("temp", "tint", "exp", "con", "hi", "sh", "white", "black", "fade", "sat", "splitHi", "splitSh")
OUT = APP / "darkslide" / "grade_limits.json"
ADJUST = APP / "web" / "adjust.js"
_CACHE = {}


def fingerprint(films):
    from darkslide.grade_bake import page_bake_sha
    return dict(adjust_bake_sha256=page_bake_sha(ADJUST),
                film_data_revision=film_profiles.data_revision(),
                previews={f: hashlib.sha256(film_luts.preview_path(f).read_bytes()).hexdigest() for f in films})


def _camera(model_id, path):
    if model_id not in _CACHE:
        from darkslide import fitting_setup
        fitting_setup.activate()  # the installed Unicorn component, as the server does
        from darkslide import base_curve, factory_envelope, gr3x_factory_envelope, film_fit
        model = models.get(model_id)
        contract = base_curve.base_curve(Path(path))
        if model == models.GR3X:
            film_fit.contract_model(contract, model.id)
            env = gr3x_factory_envelope.factory_envelope(Path(path))
        else:
            env = factory_envelope.factory_envelope(Path(path))
        _CACHE[model_id] = (model, contract, env)
    return _CACHE[model_id]


def bake(base_text, grades):
    out = subprocess.run(["node", str(APP / "tools" / "grade_bake.cjs")], check=True, capture_output=True,
                         input=json.dumps(dict(adjust=str(ADJUST), base=base_text, grades=grades)).encode())
    return json.loads(out.stdout)


def writable(model_id, path, base_text, grade):
    from darkslide.film_fit_check import check_cube
    model, contract, env = _camera(model_id, path)
    return check_cube(bake(base_text, [grade])[0].encode(), model, contract, env)["writable"]


def task(args):
    model_id, path, film, slider, sign = args
    base_text = film_luts.preview_path(film).read_text(encoding="utf-8")
    ok = lambda v: writable(model_id, path, base_text, {slider: sign * v} if v else {})
    if not ok(0):
        return model_id, film, slider, sign, None
    if ok(100):
        return model_id, film, slider, sign, 100
    lo, hi = 0, 100  # lo writable, hi not
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return model_id, film, slider, sign, lo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gr3", required=True)
    ap.add_argument("--gr3x", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--films", default="")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    films = [f for f in (a.films.split(",") if a.films else film_profiles.ready_profile_ids())]
    paths = {models.GR3.id: a.gr3, models.GR3X.id: a.gr3x}
    jobs = [(m, paths[m], f, s, sign) for m in paths for f in films for s in SLIDERS for sign in (-1, 1)]
    table = {m: {f: {} for f in films} for m in paths}
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for i, (m, f, s, sign, limit) in enumerate(pool.map(task, jobs), 1):
            if limit is None:
                table[m][f]["_film_writable"] = False
            else:
                table[m][f].setdefault("_film_writable", True)
                pair = table[m][f].setdefault(s, [0, 0])
                pair[0 if sign < 0 else 1] = sign * limit
            print("%d/%d %s %s %s %+d -> %s" % (i, len(jobs), m, f, s, sign, limit), flush=True)
    result = dict(schema=1, generated=datetime.date.today().isoformat(), fingerprint=fingerprint(films),
                  sliders=list(SLIDERS),
                  method="per slider alone, baked like the page (adjust.js combine camera=true, 33), real fit, "
                         "film_fit_check.check_cube; bisection to the largest writable whole value",
                  models=table)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()

"""Re-check every limit in darkslide/grade_limits.json step by step, a few steps inward.

Whether a grade fits into the camera is not always continuous near the edge (seen on
portra400, Shadows +69 fits, +70 does not, +71..+73 fit again), so a bisection can land
outside a gap it never tried. Here, for every (model, film, slider, side) the limit and the
WINDOW whole values just inside it are fitted for real; if any of them does not fit, the
limit moves to just inside the innermost failure and the new window is checked, until WINDOW
clean steps in a row. Limits only ever move towards 0 (conservative).

Baked with darkslide/grade_bake.py (byte-identical to web/adjust.js, tests/test_grade_bake.py),
fitted and judged with film_fit_check.check_cube, like the page's live check. Development tool;
needs the fitting component; reads the official originals, writes no firmware. Usage:
  python3 tools/audit_grade_limits.py --gr3 <fwdc239b.bin> --gr3x <fwdc243b.bin> [--workers 8] [--window 6] [--out <json>]
"""
import argparse
import datetime
import json
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from darkslide import models  # noqa: E402

TABLE = APP / "darkslide" / "grade_limits.json"
_W = {}


def _init(paths):
    _W["paths"] = paths


def _camera(model_id):
    if model_id not in _W:
        from darkslide import base_curve, factory_envelope, film_fit, fitting_setup, gr3x_factory_envelope
        fitting_setup.activate()
        path = Path(_W["paths"][model_id])
        model = models.get(model_id)
        contract = base_curve.base_curve(path)
        if model == models.GR3X:
            film_fit.contract_model(contract, model.id)
            env = gr3x_factory_envelope.factory_envelope(path)
        else:
            env = factory_envelope.factory_envelope(path)
        _W[model_id] = (model, contract, env)
    return _W[model_id]


def _base(film):
    key = "film:" + film
    if key not in _W:
        from darkslide import film_luts
        _W[key] = film_luts.preview_path(film).read_text(encoding="utf-8")
    return _W[key]


def fits(model_id, film, slider, value):
    from darkslide import grade_bake
    from darkslide.film_fit_check import check_cube
    model, contract, env = _camera(model_id)
    cube = grade_bake.bake(_base(film), {slider: value} if value else {})
    return check_cube(cube.encode("utf-8"), model, contract, env)["writable"]


def window(limit, sign, size):
    """The limit and `size` whole values just inside it (never 0: the film itself is known to fit)."""
    return [sign * v for v in range(abs(limit), max(0, abs(limit) - size - 1), -1) if v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gr3", required=True)
    ap.add_argument("--gr3x", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--window", type=int, default=6)
    ap.add_argument("--table", default=str(TABLE))
    ap.add_argument("--films", default="", help="comma-separated, for a quick partial run")
    ap.add_argument("--out", default=str(TABLE))
    a = ap.parse_args()
    table = json.loads(Path(a.table).read_text(encoding="utf-8"))
    paths = {models.GR3.id: a.gr3, models.GR3X.id: a.gr3x}
    entries = {}  # (model, film, slider, sign) -> current limit
    for model_id, films in table["models"].items():
        for film, sliders in films.items():
            if sliders.get("_film_writable") is False or (a.films and film not in a.films.split(",")):
                continue
            for slider in table["sliders"]:
                for i, sign in enumerate((-1, 1)):
                    entries[(model_id, film, slider, sign)] = sliders[slider][i]
    original = dict(entries)
    tried = {}  # (model, film, slider, value) -> fits
    done = 0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(paths,)) as pool:
        running, pending = {}, set()

        def submit(key):
            model_id, film, slider, sign = key
            for v in window(entries[key], sign, a.window):
                probe = (model_id, film, slider, v)
                if probe not in tried and probe not in pending:
                    pending.add(probe)
                    running[pool.submit(fits, model_id, film, slider, v)] = probe
        for key in entries:
            submit(key)
        while running:
            ready, _ = wait(running, return_when=FIRST_COMPLETED)
            touched = set()
            for future in ready:
                probe = running.pop(future)
                pending.discard(probe)
                tried[probe] = future.result()
                done += 1
                touched.update(k for k in entries if k[:3] == probe[:3])
            for key in touched:
                model_id, film, slider, sign = key
                values = window(entries[key], sign, a.window)
                failed = [v for v in values if tried.get((model_id, film, slider, v)) is False]
                if failed:
                    inner = min(failed, key=abs)
                    entries[key] = inner - sign  # just inside the innermost failure
                    print("moved %s %s %s %+d: %d -> %d" % (model_id, film, slider, sign, original[key], entries[key]), flush=True)
                if any((model_id, film, slider, v) not in tried for v in window(entries[key], sign, a.window)):
                    submit(key)
            if done % 100 < len(ready):
                print("%d fits, %d waiting" % (done, len(running)), flush=True)
    changes = []
    for key, limit in entries.items():
        model_id, film, slider, sign = key
        table["models"][model_id][film][slider][0 if sign < 0 else 1] = limit
        if limit != original[key]:
            changes.append(dict(model=model_id, film=film, slider=slider, side="-" if sign < 0 else "+", was=original[key], now=limit))
    table["audit"] = dict(date=datetime.date.today().isoformat(), window=a.window, fits=done, changes=changes,
                          method="each limit and the %d whole values inside it fitted for real (grade_bake + "
                                 "film_fit_check); a failure moves the limit just inside it, repeated until clean" % a.window)
    Path(a.out).write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("fits %d, changed %d, wrote %s" % (done, len(changes), a.out))


if __name__ == "__main__":
    main()

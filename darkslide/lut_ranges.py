"""Background work on a user's own colours: a user LUT's slider ranges, and a version of a
look pulled into the camera's range ("收进相机范围").

Both are calculations only: every candidate is baked like the page (grade_bake, the Python
twin of web/adjust.js), fitted for real and judged by film_fit_check.check_cube, the same
rules the write path enforces. Nothing here writes firmware or changes a stored LUT; the
write path checks again on its own. A pulled-in version is only offered: the page shows it
next to the original, and only the user's choice imports it as a new LUT (the original stays).

One fit takes a few seconds, so the work runs in a process pool, one fit per task (a stop
never waits for more than one fit); see Jobs for the order.
"""
import atexit
import hashlib
import math
import os
import threading
import time
from array import array
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from . import VERSION, grade_bake, models

SCHEMA = 1
HERE = Path(__file__).resolve().parent
WEB_ADJUST = HERE.parent / "web" / "adjust.js"
SLIDERS = grade_bake.CAMERA_SLIDERS[:]
SIZE = 33


def worker_count():
    return max(1, min(8, (os.cpu_count() or 2) - 2))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(model_id, official_sha, cube_sha):
    """What a user LUT's slider ranges depend on; any change means they are computed again."""
    return dict(schema=SCHEMA, version=VERSION, model_id=model_id, official_sha256=official_sha, cube_sha256=cube_sha,
                adjust_bake_sha256=grade_bake.page_bake_sha(WEB_ADJUST), grade_bake_sha256=_sha(HERE / "grade_bake.py"),
                film_fit_sha256=_sha(HERE / "film_fit.py"), film_fit_check_sha256=_sha(HERE / "film_fit_check.py"))


# ---------------------------------------------------------------- worker side
_W = {}


def _init(model_id, contract, envelope, base_text, root=None):
    from . import fitting_setup
    fitting_setup.activate(root)  # the server's own data folder
    _W.update(model=models.get(model_id), contract=contract, envelope=envelope, base=base_text)


def _check(cube_text):
    from .film_fit_check import check_cube
    return check_cube(cube_text.encode("utf-8"), _W["model"], _W["contract"], _W["envelope"])


def _grade_task(grade):
    """Is the base LUT plus this grade writable?"""
    return _check(grade_bake.bake(_W["base"], grade))["writable"]


def _derive_task(levels, blend):
    """A pulled-in candidate and its check result."""
    text = derive(_W["base"], levels, blend)
    return text, _check(text)


# ---------------------------------------------------------------- the pulled-in look
BLACK_TARGET, WHITE_TARGET = 0.06, 0.96


def _grid(base_text):
    """The base LUT on the 33-point grid, as the page samples it."""
    size, data = grade_bake.parse_cube(base_text)
    m = SIZE - 1
    out = array("f")
    for b in range(SIZE):
        for g in range(SIZE):
            for r in range(SIZE):
                out.extend(grade_bake._sample(size, data, [r / m, g / m, b / m]))
    return out


def derive(base_text, levels, blend):
    """levels: how far (0..1) black is pulled down to BLACK_TARGET and white up to WHITE_TARGET
    (one straight line for all three channels, so the tint of black and white is kept);
    blend: how far (0..1) the colours move towards no change at all (the camera's own look)."""
    data = _grid(base_text)
    black, white = max(data[0:3]), min(data[-3:])
    lo, hi = min(black, BLACK_TARGET), max(white, WHITE_TARGET)
    scale = (hi - lo) / (white - black) if white - black > 1e-6 else 1.0
    m = SIZE - 1
    out = array("f")
    i = 0
    for b in range(SIZE):
        for g in range(SIZE):
            for r in range(SIZE):
                for c, ident in enumerate((r / m, g / m, b / m)):
                    y = data[i + c]
                    y += levels * (lo + (y - black) * scale - y)
                    y += blend * (ident - y)
                    out.append(min(1.0, max(0.0, y)))
                i += 3
    return grade_bake.cube_text(SIZE, out)


def change_of(base_text, derived_text, step=4):
    """Mean CIEDE2000 between the original and the pulled-in look, over the LUT grid."""
    from ._vendor import gr3_lut_fit as fitlib
    a, (_, b) = _grid(base_text), grade_bake.parse_cube(derived_text)
    n, total, count = SIZE, 0.0, 0
    for bi in range(0, n, step):
        for gi in range(0, n, step):
            for ri in range(0, n, step):
                k = ((bi * n + gi) * n + ri) * 3
                total += fitlib.de2000(a[k:k + 3], b[k:k + 3])
                count += 1
    return round(total / count, 2)


# ---------------------------------------------------------------- jobs
class Cancelled(Exception):
    pass


class Jobs:
    """Background jobs in two lanes: slider ranges wait in line one after another; a
    「收进相机范围」 the user is waiting for has its own lane and never waits behind them.
    Results stay in memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs, self._queues, self._threads = {}, {}, {}
        self._pools, self._stopping = set(), False

    def status(self, key):
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                return None
            out = {k: v for k, v in job.items() if k not in ("run", "lane")}
            if job["state"] == "queued":
                out["ahead"] = self._queues[job["lane"]].index(key)
            return out

    def submit(self, key, run, total, lane="background", priority=()):
        """run(job_api) -> result dict. A finished or failed job with the same key is replaced."""
        with self._lock:
            job = self._jobs.get(key)
            if job and job["state"] in ("queued", "running"):
                return
            self._jobs[key] = dict(state="queued", done=0, total=total, started=time.time(), run=run, lane=lane,
                                   priority=list(priority))
            self._queues.setdefault(lane, []).append(key)
            thread = self._threads.get(lane)
            if thread is None or not thread.is_alive():
                thread = self._threads[lane] = threading.Thread(target=self._loop, args=(lane,), name="darkslide-lut-" + lane, daemon=True)
                thread.start()

    def prioritize(self, key, slider):
        """Add this slider to a running job, first in line (the one being dragged).
        False when no such job is queued or running: then a new one has to be started."""
        with self._lock:
            job = self._jobs.get(key)
            if not job or job["state"] not in ("queued", "running") or job.get("closing"):
                return False
            job["priority"] = [slider] + [x for x in job.get("priority", []) if x != slider]
            return True

    def forget(self, key):
        with self._lock:
            job = self._jobs.get(key)
            if job and job["state"] not in ("queued", "running"):
                del self._jobs[key]

    def _loop(self, lane):
        while True:
            with self._lock:
                queue = self._queues[lane]
                if not queue or self._stopping:
                    self._threads.pop(lane, None)
                    return
                key = queue.pop(0)
                job = self._jobs[key]
                job["state"] = "running"
            try:
                result = job["run"](_Api(self, job))
                update = dict(state="done", result=result)
            except Cancelled:
                update = dict(state="failed", error="已停止")
            except Exception as exc:  # reported to the page; the server keeps running
                update = dict(state="failed", error=str(exc) or exc.__class__.__name__)
            with self._lock:
                job.update(update, finished=time.time())
                job.pop("run", None)

    def pool(self, initargs):
        pool = ProcessPoolExecutor(max_workers=worker_count(), initializer=_init, initargs=initargs)
        with self._lock:
            if self._stopping:
                pool.shutdown(wait=False, cancel_futures=True)
                raise Cancelled()
            self._pools.add(pool)
        return pool

    def release(self, pool):
        with self._lock:
            self._pools.discard(pool)
        pool.shutdown(wait=False, cancel_futures=True)

    def stop(self):
        with self._lock:
            self._stopping = True
            pools = list(self._pools)
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)

    @property
    def stopping(self):
        return self._stopping


class _Api:
    def __init__(self, jobs, job):
        self.jobs, self.job = jobs, job

    def progress(self, done, total=None):
        with self.jobs._lock:
            self.job["done"] = done
            if total is not None:
                self.job["total"] = total

    def check(self):
        if self.jobs.stopping:
            raise Cancelled()

    def priority(self):
        """Sliders asked for, most recent first."""
        with self.jobs._lock:
            return list(self.job.get("priority", ()))

    def close_if(self, finished):
        """End the job unless a slider not in `finished` was asked for meanwhile (checked and
        closed under one lock, so a request never lands in a job that is already ending)."""
        with self.jobs._lock:
            if any(x not in finished for x in self.job.get("priority", ())):
                return False
            self.job["closing"] = True
            return True

    def partial(self, done):
        """Sliders already worked out, shown before the whole job ends."""
        with self.jobs._lock:
            self.job.setdefault("partial", {}).update(done)


JOBS = Jobs()
atexit.register(JOBS.stop)  # the launcher also stops it on quit (concurrent.futures' own exit hook runs before atexit)


def _left(lo, hi):
    """Fits still to come for one bisection (the probe at 100 first, then halving)."""
    if hi is None:
        return 1 + math.ceil(math.log2(100 - lo)) if lo < 100 else 0
    if lo >= 100:
        return 0
    return math.ceil(math.log2(hi - lo)) if hi - lo > 1 else 0


def _points(lo, hi, n):
    """n values to try between lo (writable) and hi (not writable; None: 100 not tried yet).
    One value is plain bisection; several split the gap evenly, so fewer rounds are needed."""
    if hi is None:
        return sorted({lo + math.ceil((100 - lo) * i / n) for i in range(1, n + 1)})
    return sorted({v for v in (lo + round((hi - lo) * i / (n + 1)) for i in range(1, n + 1)) if lo < v < hi})


def _settle(state, tried):
    """New (lo, hi) after a round: the first failing value caps it, the best success below it is lo."""
    lo, hi = state
    for v in sorted(tried):
        if not tried[v]:
            hi = v if hi is None else min(hi, v)
            break
    lo = max([lo] + [v for v, ok in tried.items() if ok and (hi is None or v < hi)])
    return [lo, hi]


def _finished(lo, hi):
    return lo >= 100 or (hi is not None and hi - lo <= 1)


WINDOW = 6  # whole values checked just inside every limit (tools/audit_grade_limits.py does the same)


def _window(lo):
    """The limit and the WINDOW whole values just inside it (0 is the LUT itself, known to fit)."""
    return [v for v in range(lo, max(0, lo - WINDOW) - 1, -1) if v > 0]


def compute_ranges(api, model_id, contract, envelope, base_text, root=None, save=None, writable=None):
    """Only the sliders asked for (api.priority, which can grow while this runs: the user's
    drags), each side the largest whole value that is still writable on its own: 0 must be
    writable, 100 is tried first, then the gap is narrowed with up to four values at a time.
    Near the edge, fitting is not always continuous (a value can fit with failures just inside
    it), so the limit and the WINDOW values inside it must all fit; a failure there moves the
    limit just inside it and the window is checked again (conservative).
    Each finished slider goes to save({slider: [lo, hi]}) and api.partial at once.
    writable: whether the LUT itself fits, if already known; otherwise checked alongside, and
    nothing is handed over before that check has passed."""
    pool = JOBS.pool((model_id, contract, envelope, base_text, root))
    try:
        if writable is False:
            return {"_film_writable": False}
        done, workers, out = 0, worker_count(), {}
        state, rounds, running = {}, {}, {}  # (slider, sign) -> [lo, hi]; key -> {value: ok}; future -> (key, value)
        tried = {}  # (slider, sign) -> {value: ok}

        def todo(key):
            """Values to try next for this side; [] when it is settled."""
            lo, hi = state[key]
            if not _finished(lo, hi):
                return None
            return [v for v in _window(lo) if v not in tried[key]]

        def side_done(key):
            return key in state and key not in rounds and todo(key) == []
        settled, waiting = set(), []  # sliders with both sides done; done before the LUT's own check
        known = writable is True
        if not known:
            running[pool.submit(_grade_task, {})] = (None, 0)

        def hand_over(slider):
            out[slider] = [-state[(slider, -1)][0], state[(slider, 1)][0]]
            if save:
                save({slider: out[slider]})
            api.partial({slider: out[slider]})

        def keys():
            return [(x, sign) for x in api.priority() if x in SLIDERS and x not in settled for sign in (-1, 1)]

        def fill():
            free = workers - len(running)
            for key in keys():
                state.setdefault(key, [0, None])
                tried.setdefault(key, {})
                if free <= 0 or key in rounds:
                    continue
                values = todo(key)
                if values is None:
                    values = _points(*state[key], min(free, 4))
                values = values[:free]
                if not values:
                    continue
                rounds[key] = dict.fromkeys(values)
                for v in values:
                    running[pool.submit(_grade_task, {key[0]: key[1] * v})] = (key, v)
                free -= len(values)

        while True:
            fill()
            if not running:
                if api.close_if(settled | (set(api.priority()) - set(SLIDERS))):
                    return out
                continue  # a slider was asked for just now: fill() takes it on the next pass
            ready, _ = wait(running, return_when=FIRST_COMPLETED)
            api.check()
            for future in ready:
                key, value = running.pop(future)
                ok = future.result()
                done += 1
                if key is None:  # the LUT itself
                    if not ok:
                        if save:
                            save({"_film_writable": False})
                        return {"_film_writable": False}
                    known, out["_film_writable"] = True, True
                    if save:
                        save({"_film_writable": True})
                    for slider in waiting:
                        hand_over(slider)
                    waiting.clear()
                    continue
                rounds[key][value] = ok
                if any(v is None for v in rounds[key].values()):
                    continue
                results = rounds.pop(key)
                tried[key].update(results)
                if not _finished(*state[key]):
                    state[key] = _settle(state[key], results)
                while _finished(*state[key]):
                    bad = [v for v in _window(state[key][0]) if tried[key].get(v) is False]
                    if not bad:
                        break
                    inner = min(bad)
                    state[key] = [inner - 1, inner]  # just inside the innermost failure; its window comes next
                slider = key[0]
                sides = [(slider, -1), (slider, 1)]
                if slider not in settled and all(side_done(k) for k in sides):
                    settled.add(slider)
                    if known:
                        hand_over(slider)
                    else:
                        waiting.append(slider)
            api.progress(done, done + len(running) + sum(_left(*state[k]) + WINDOW for k in keys() if k in state and k not in rounds and not side_done(k)))
    finally:
        JOBS.release(pool)


def fit_into(api, model_id, contract, envelope, base_text, root=None):
    """The smallest change that brings this look into the camera's range, or why there is none.
    First black/white are pulled in (when the curve ends are the problem), then the colours are
    moved towards no change in steps of 1/8, then refined between the last two steps."""
    pool = JOBS.pool((model_id, contract, envelope, base_text, root))
    try:
        steps = [0]

        def batch(pairs):
            futures = [pool.submit(_derive_task, lv, bl) for lv, bl in pairs]
            out = []
            for f in futures:
                out.append(f.result())
                api.check()
                steps[0] += 1
                api.progress(steps[0])
            return out

        (_, start), = batch([(0, 0)])
        if start["writable"]:
            return dict(already=True, check=start)
        reasons = start["violations"] or [start["reason"] or ""]
        ends = any("起点" in v or "终点" in v for v in reasons)

        def search(make):
            grid = [i / 8 for i in range(1, 9)]
            results = batch([make(t) for t in grid])
            hit = next((i for i, (_, c) in enumerate(results) if c["writable"]), None)
            if hit is None:
                return None
            lo = grid[hit] - 1 / 8
            fine = [lo + (grid[hit] - lo) * i / 8 for i in range(1, 8)]
            for t, (text, check) in zip(fine, batch([make(t) for t in fine])):
                if check["writable"]:
                    return t, text, check
            return grid[hit], results[hit][0], results[hit][1]

        levels, blend, found = 0.0, 0.0, None
        if ends:
            found = search(lambda t: (t, 0.0))
            if found:
                levels = found[0]
        if not found:
            levels = 1.0 if ends else 0.0
            found = search(lambda t: (levels, t))
            if not found:
                raise ValueError("这组颜色没法收进相机范围：" + reasons[0])
            blend = found[0]
        _, text, check = found
        return dict(already=False, cube=text, check=check, levels=round(levels, 3), blend=round(blend, 3),
                    change_de=change_of(base_text, text), was=reasons[0])
    finally:
        JOBS.release(pool)

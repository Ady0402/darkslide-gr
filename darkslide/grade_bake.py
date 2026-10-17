"""Python twin of the page's camera grade bake (web/adjust.js combine(base, grade, camera=true, 33)).

The page bakes "film + grade" into a LUT before fitting. Range checks that run without a
browser (a user LUT's slider ranges, the "fit into the camera" helper) need the very same
bake, so the camera-writable part of adjust.js is mirrored here: same formulas, same order,
values stored as 32-bit floats like the page's Float32Array, same .cube text. HSL and
vibrance are LUT-only and are left out, exactly as camera=true does.
tests/test_grade_bake.py compares this file with adjust.js run by node, and the slider-range
caches carry the hash of adjust.js's camera-bake block (page_bake_sha), so a change on one
side cannot go unnoticed.
"""
import hashlib
import math
from array import array
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

WEB_ADJUST = Path(__file__).resolve().parents[1] / "web" / "adjust.js"
BAKE_BEGIN, BAKE_END = "// ---- camera bake begin", "// ---- camera bake end"


def page_bake_sha(path=WEB_ADJUST):
    """SHA-256 of the camera-bake block of web/adjust.js (between its markers): what the slider
    ranges depend on. Page wording and layout outside the block do not change it."""
    text = Path(path).read_text(encoding="utf-8")
    start = text.index(BAKE_BEGIN)
    end = text.index(BAKE_END, start)
    return hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()

CAMERA_SLIDERS = ("temp", "tint", "exp", "con", "hi", "sh", "white", "black", "fade", "sat", "splitHi", "splitSh")


def parse_cube(text):
    """film.js parseCube: (size, float32 data in r-fastest order)."""
    lines = text.split("\n")
    size = int(next(l for l in lines if l.startswith("LUT_3D_SIZE")).split()[1])
    data = array("f")
    for line in lines:
        t = line.strip()
        if t and (t[0].isdigit() or t[0] in ".-+"):
            v = t.split()
            data.extend((float(v[0]), float(v[1]), float(v[2])))
    if len(data) != size ** 3 * 3:
        raise ValueError("cube data length")
    return size, data


def cube_text(size, data):
    """grade_bake.cjs cubeText (no title/credit lines: they do not change the fit)."""
    lines = ["LUT_3D_SIZE %d" % size, "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    for i in range(0, len(data), 3):
        lines.append("%s %s %s" % (_fixed(data[i]), _fixed(data[i + 1]), _fixed(data[i + 2])))
    return "\n".join(lines) + "\n"


_STEP = Decimal("0.000001")


def _fixed(v):
    # JS toFixed(6): on the exact binary value, an exact tie goes to the larger magnitude
    # (Python's "%.6f" would round it to even, which differs on dyadic float32 values).
    return str(Decimal(v if v != 0 else 0.0).quantize(_STEP, rounding=ROUND_HALF_UP))  # JS: (-0).toFixed -> "0.000000"


def _val(g, k):
    v = (g or {}).get(k)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _curve_pts(g, ch):
    return ((g or {}).get("curve") or {}).get(ch) or [[0, 0], [1, 1]]


def is_empty_camera(g):
    """No camera-writable change (sliders or curves); HSL/vibrance alone count as empty here."""
    if any(_val(g, k) for k in CAMERA_SLIDERS):
        return False
    curves = (g or {}).get("curve") or {}
    return not any(len(p) > 2 or p[0][1] != 0 or p[1][1] != 1 for p in curves.values())


def is_empty(g):
    """adjust.js isEmpty: also HSL/vibrance count (the page then runs the camera transform with
    them dropped, which is not bit-identical to skipping it)."""
    if not is_empty_camera(g):
        return False
    if _val(g, "vib"):
        return False
    return not any(any((g or {}).get(k) or []) for k in ("hH", "hS", "hL"))


def _dec(c):
    return c / 12.92 if c <= 0.04045 else math.pow((c + 0.055) / 1.055, 2.4)


def _enc(c):
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * math.pow(c, 1 / 2.4) - 0.055


def _cbrt(x):
    return math.copysign(math.pow(abs(x), 1 / 3), x) if x else 0.0


def _oklab(r, g, b):
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s)


def _linear(L, a, b):
    l = math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3)
    m = math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3)
    s = math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3)
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)


def _smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _spline(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    n = len(xs)
    m = [0.0] * n
    if n > 2:
        h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        a, b, c, d = [0.0], [1.0], [0.0], [0.0]
        for i in range(1, n - 1):
            a.append(h[i - 1]); b.append(2 * (h[i - 1] + h[i])); c.append(h[i])
            d.append(6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1]))
        a.append(0.0); b.append(1.0); c.append(0.0); d.append(0.0)
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        m[n - 1] = d[n - 1] / b[n - 1]
        for i in range(n - 2, -1, -1):
            m[i] = (d[i] - c[i] * m[i + 1]) / b[i]

    def f(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[n - 1]:
            return ys[n - 1]
        i = 0
        while i < n - 2 and xs[i + 1] < x:
            i += 1
        hh, t0, t1 = xs[i + 1] - xs[i], xs[i + 1] - x, x - xs[i]
        return (m[i] * t0 ** 3 + m[i + 1] * t1 ** 3) / (6 * hh) + (ys[i] / hh - m[i] * hh / 6) * t0 + (ys[i + 1] / hh - m[i + 1] * hh / 6) * t1
    return f


def _transform(g):
    t, ti, ev = _val(g, "temp") / 100, _val(g, "tint") / 100, math.pow(2, _val(g, "exp") / 50)
    gr, gg, gb = math.pow(2, 0.3 * t), math.pow(2, -0.2 * ti), math.pow(2, -0.3 * t)
    gn = 0.2126 * gr + 0.7152 * gg + 0.0722 * gb
    c, hi, sh = _val(g, "con") / 100, _val(g, "hi") / 100, _val(g, "sh") / 100
    wh, bk, fade = _val(g, "white") / 100, _val(g, "black") / 100, _val(g, "fade") / 100

    def tone(x):
        y = x + 0.22 * c * 4 * x * (1 - x) * (2 * x - 1)
        if x > 0.4:
            y += 0.15 * hi * math.sin(math.pi * (x - 0.4) / 0.6) ** 2
        if x < 0.6:
            y += 0.15 * sh * math.sin(math.pi * x / 0.6) ** 2
        y += 0.12 * wh * x ** 4 + 0.12 * bk * (1 - x) ** 4
        return min(1.0, max(0.0, 0.15 * fade + y * (1 - 0.15 * fade) if fade > 0 else y))

    master = _spline(_curve_pts(g, "all"))
    chan = [_spline(_curve_pts(g, k)) for k in ("r", "g", "b")]
    sat = 1 + _val(g, "sat") / 100
    s_hi, s_sh = _val(g, "splitHi") / 100, _val(g, "splitSh") / 100

    def fn(rgb):
        r, g2, b = (_dec(v) for v in rgb)
        r *= gr / gn * ev; g2 *= gg / gn * ev; b *= gb / gn * ev
        y = 0.2126 * r + 0.7152 * g2 + 0.0722 * b
        y2 = _dec(tone(_enc(y)))
        if y > 1e-6:
            r *= y2 / y; g2 *= y2 / y; b *= y2 / y
        else:
            r = g2 = b = y2
        L, A, B = _oklab(max(0.0, r), max(0.0, g2), max(0.0, b))
        A *= sat; B *= sat
        w_hi, w_sh = _smooth(0.55, 0.85, L), 1 - _smooth(0.25, 0.5, L)
        A += 0.04 * (s_hi * w_hi + s_sh * w_sh) * 0.45
        B += 0.04 * (s_hi * w_hi + s_sh * w_sh)
        out = [_enc(v) for v in _linear(L, A, B)]
        out = [master(v) for v in out]
        out = [chan[i](v) for i, v in enumerate(out)]
        return [min(1.0, max(0.0, v)) for v in out]
    return fn


def _sample(size, data, rgb):
    n, m = size, size - 1
    f = [min(1.0, max(0.0, v)) * m for v in rgb]
    i0 = [min(m - 1, int(math.floor(v))) for v in f]
    t = [v - i for v, i in zip(f, i0)]

    def at(r, g, b, c):
        return data[((b * n + g) * n + r) * 3 + c]
    out = [0.0, 0.0, 0.0]
    for c in range(3):
        c00 = at(i0[0], i0[1], i0[2], c) * (1 - t[0]) + at(i0[0] + 1, i0[1], i0[2], c) * t[0]
        c10 = at(i0[0], i0[1] + 1, i0[2], c) * (1 - t[0]) + at(i0[0] + 1, i0[1] + 1, i0[2], c) * t[0]
        c01 = at(i0[0], i0[1], i0[2] + 1, c) * (1 - t[0]) + at(i0[0] + 1, i0[1], i0[2] + 1, c) * t[0]
        c11 = at(i0[0], i0[1] + 1, i0[2] + 1, c) * (1 - t[0]) + at(i0[0] + 1, i0[1] + 1, i0[2] + 1, c) * t[0]
        out[c] = (c00 * (1 - t[1]) + c10 * t[1]) * (1 - t[2]) + (c01 * (1 - t[1]) + c11 * t[1]) * t[2]
    return out


def bake(base_text, grade, size=33):
    """.cube text of (base LUT or identity) followed by the camera-writable grade, like the page."""
    base = parse_cube(base_text) if base_text else None
    fn = None if is_empty(grade) else _transform(grade)
    m = size - 1
    data = array("f")
    for b in range(size):
        for g in range(size):
            for r in range(size):
                v = [r / m, g / m, b / m]
                if base:
                    v = _sample(base[0], base[1], v)
                if fn:
                    v = fn(v)
                data.extend(v)
    return cube_text(size, data)

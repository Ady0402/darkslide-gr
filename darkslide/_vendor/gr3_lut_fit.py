"""Fit a .cube to what the GR III film path can express, ported from gr3-film-mods (MIT).

Copyright (c) 2026 idontknownihil. License: GR3_FILM_MODS_LICENSE.txt.
Ported and modified by LiorMoment from cube_fit.py (camera model, M_from, the
alternating matrix/curve fit, fit_curve), cca1_fit.py (neutral-preserving
post-curve matrix) and lab_fit.py (perceptual CIEDE2000 refit). Changes: standard library only (banded Cholesky for the
curve solve, a small Levenberg-Marquardt for the six matrix terms instead of
NumPy/SciPy); sRGB-encoded .cube targets only; procedural samples (grey ramp,
hue wheel, skin tones, random colours) instead of the ColorChecker table; the
base gamma is passed in by the caller and never loaded from a foreign dump.
See gr3_lut_fit_source.json for the pinned sources.

Camera model (per channel c):
    code_c = Post( Curve_c( Base( K * (M @ L)_c ) ) / 16384 )
L is scene-linear sRGB-primaries RGB with mid grey at 0.18; K puts that grey at
base-gamma index 7.8 (an upstream assumption, not a calibrated exposure).
"""
import colorsys
import math
import random

MID_INDEX = 7.8
K = MID_INDEX / 0.18


# ------------------------------------------------------------------ colour helpers
def srgb_encode(c):
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def srgb_decode(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lab(rgb):
    r, g, b = (srgb_decode(min(1.0, max(0.0, v))) for v in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def de2000(a, b):
    """CIEDE2000 between two sRGB-encoded colours."""
    L1, a1, b1 = _lab(a)
    L2, a2, b2 = _lab(b)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dl, dc = L2 - L1, c2p - c1p
    if not c1p * c2p:
        dh = 0.0
    else:
        dh = h2p - h1p
        dh = dh - 360 if dh > 180 else dh + 360 if dh < -180 else dh
    dH = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    lm, cmp_ = (L1 + L2) / 2, (c1p + c2p) / 2
    if not c1p * c2p:
        hm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hm = (h1p + h2p) / 2
    else:
        hm = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63)))
    sl = 1 + 0.015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cmp_, 1 + 0.015 * cmp_ * t
    rt = -2 * math.sqrt(cmp_ ** 7 / (cmp_ ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh))


# ------------------------------------------------------------------ target LUT
class Cube:
    """Sampled 3D LUT (red runs fastest), tetrahedral interpolation on 0..1 input."""

    def __init__(self, size, rows):
        self.n, self.rows = size, rows

    def apply(self, rgb):
        n1 = self.n - 1
        pos = [min(1.0, max(0.0, v)) * n1 for v in rgb]
        base = [min(int(p), n1 - 1) for p in pos]
        fr, fg, fb = (p - i for p, i in zip(pos, base))
        r0, g0, b0 = base
        at = lambda dr, dg, db: self.rows[(r0 + dr) + (g0 + dg) * self.n + (b0 + db) * self.n * self.n]
        c000, c111 = at(0, 0, 0), at(1, 1, 1)
        if fr >= fg >= fb:
            p1, p2, w = at(1, 0, 0), at(1, 1, 0), (fr, fg, fb)
        elif fr >= fb >= fg:
            p1, p2, w = at(1, 0, 0), at(1, 0, 1), (fr, fb, fg)
        elif fb >= fr >= fg:
            p1, p2, w = at(0, 0, 1), at(1, 0, 1), (fb, fr, fg)
        elif fg >= fr >= fb:
            p1, p2, w = at(0, 1, 0), at(1, 1, 0), (fg, fr, fb)
        elif fg >= fb >= fr:
            p1, p2, w = at(0, 1, 0), at(0, 1, 1), (fg, fb, fr)
        else:
            p1, p2, w = at(0, 0, 1), at(0, 1, 1), (fb, fg, fr)
        a, b, c = w
        return tuple(min(1.0, max(0.0, (1 - a) * c000[k] + (a - b) * p1[k] + (b - c) * p2[k] + c * c111[k]))
                     for k in range(3))


def target_of(cube, ev=0.0):
    """sRGB-encoded linear image (clipped at 1) through the cube, as cube_fit's 'srgb' input."""
    scale = 2.0 ** ev
    return lambda lin: cube.apply([srgb_encode(v * scale) for v in lin])


# ------------------------------------------------------------------ samples
SKIN = ((0.93, 0.78, 0.69), (0.85, 0.67, 0.56), (0.76, 0.57, 0.45), (0.58, 0.40, 0.30))


def _luma(lin):
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def samples(seed=1, randoms=1500):
    """Scene-linear samples and weights: neutrals dominate so greys stay grey."""
    rng = random.Random(seed)
    L, w = [], []
    for i in range(200):
        v = 0.18 * 2.0 ** (-7 + 11.5 * i / 199)
        L.append((v, v, v)); w.append(450.0)
    for h in range(24):
        for s in (0.3, 0.6, 0.9):
            lin = [srgb_decode(c) for c in colorsys.hsv_to_rgb(h / 24, s, 1.0)]
            y = _luma(lin)
            for ev in (-2, -1, 0, 1, 2):
                k = 0.15 * 2.0 ** ev / y
                L.append(tuple(c * k for c in lin)); w.append(8.0)
    for tone in SKIN:
        lin = [srgb_decode(c) for c in tone]
        y = _luma(lin)
        for ev in (-2, -1, 0, 1, 2):
            k = 0.18 * 2.0 ** ev / y
            L.append(tuple(c * k for c in lin)); w.append(30.0)
    for _ in range(randoms):
        k = 2.0 ** rng.uniform(-4, 2) * 0.6
        L.append(tuple(rng.random() ** 2.2 * k for _ in range(3))); w.append(4.0)
    return L, w


# ------------------------------------------------------------------ camera model
def interp256(table, x):
    if x <= 0:
        return table[0]
    if x >= 255:
        return table[255]
    i = int(x)
    return table[i] + (table[i + 1] - table[i]) * (x - i)


def M_from(p):
    """Six off-diagonal terms -> 3x3 with rows summing to 1 (white preserved)."""
    M = [[0.0] * 3 for _ in range(3)]
    for r in range(3):
        o = [j for j in range(3) if j != r]
        M[r][o[0]], M[r][o[1]] = p[2 * r], p[2 * r + 1]
        M[r][r] = 1 - p[2 * r] - p[2 * r + 1]
    return M


def base_index(base, M, lin):
    """Base-gamma output of M @ lin per channel (0..16384)."""
    return [interp256(base, min(255.0, max(0.0, K * (M[c][0] * lin[0] + M[c][1] * lin[1] + M[c][2] * lin[2]))))
            for c in range(3)]


def model(base, M, curves, lin, post=None):
    g = base_index(base, M, lin)
    out = [interp256(curves[c], g[c] / 64.0) / 16384 for c in range(3)]
    if post is None:
        return out
    return [min(1.0, max(0.0, post[c][0] * out[0] + post[c][1] * out[1] + post[c][2] * out[2])) for c in range(3)]


# ------------------------------------------------------------------ curve solve
def _solve_banded_spd(bands, rhs):
    """Cholesky solve of a symmetric positive definite matrix given by bands[d][i] = A[i][i+d]."""
    n, p = len(rhs), len(bands) - 1
    Lb = [[0.0] * (p + 1) for _ in range(n)]
    for i in range(n):
        for d in range(p, 0, -1):
            j = i - d
            if j < 0:
                continue
            s = bands[d][j]
            for k in range(max(0, i - p), j):
                s -= Lb[i][i - k] * Lb[j][j - k]
            Lb[i][d] = s / Lb[j][0]
        s = bands[0][i]
        for k in range(max(0, i - p), i):
            s -= Lb[i][i - k] ** 2
        Lb[i][0] = math.sqrt(s)
    y = [0.0] * n
    for i in range(n):
        s = rhs[i]
        for k in range(max(0, i - p), i):
            s -= Lb[i][i - k] * y[k]
        y[i] = s / Lb[i][0]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = y[i]
        for k in range(i + 1, min(n, i + p + 1)):
            s -= Lb[k][k - i] * x[k]
        x[i] = s / Lb[i][0]
    return x


def fit_curve(g, t, w, lam=3000.0):
    """Weighted least squares for a 256-knot piecewise-linear curve over g/64,
    second-difference smoothing; monotone, clipped to 0..16383 (cube_fit.fit_curve)."""
    bands = [[1e-6] * 256, [0.0] * 256, [0.0] * 256]
    b = [0.0] * 256
    for gi, ti, wi in zip(g, t, w):
        x = min(255.0, max(0.0, gi / 64.0))
        i0 = min(int(x), 254)
        f = x - i0
        a0, a1 = 1 - f, f
        bands[0][i0] += wi * a0 * a0
        bands[0][i0 + 1] += wi * a1 * a1
        bands[1][i0] += wi * a0 * a1
        b[i0] += wi * a0 * ti * 16384
        b[i0 + 1] += wi * a1 * ti * 16384
    for k in range(254):
        coef = ((k, 1.0), (k + 1, -2.0), (k + 2, 1.0))
        for i, ci in coef:
            for j, cj in coef:
                if j >= i:
                    bands[j - i][i] += lam * ci * cj
    c = _solve_banded_spd(bands, b)
    out, top = [], 0.0
    for v in c:
        top = max(top, min(16383.0, max(0.0, v)))
        out.append(int(round(top)))
    return out


# ------------------------------------------------------------------ 6-term least squares
def _solve6(A, b):
    n = len(b)
    A = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(A[r][i]))
        A[i], A[piv] = A[piv], A[i]
        if abs(A[i][i]) < 1e-18:
            return None
        for r in range(i + 1, n):
            f = A[r][i] / A[i][i]
            for c in range(i, n + 1):
                A[r][c] -= f * A[i][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (A[i][n] - sum(A[i][c] * x[c] for c in range(i + 1, n))) / A[i][i]
    return x


def least_squares6(res, p, iters=10, step=1e-4, tol=1e-9, tries=6, project=None):
    """Levenberg-Marquardt with forward differences, for the six matrix terms."""
    p = list(p)
    r = res(p)
    cost = sum(v * v for v in r)
    lam = 1e-3
    for _ in range(iters):
        J = []
        steps = step if isinstance(step, (list, tuple)) else [step] * len(p)
        for k in range(len(p)):
            q = p[:]
            q[k] += steps[k]
            J.append([(a - b) / steps[k] for a, b in zip(res(q), r)])
        n = len(p)
        JTJ = [[sum(x * y for x, y in zip(J[i], J[j])) for j in range(n)] for i in range(n)]
        JTr = [sum(x * y for x, y in zip(J[i], r)) for i in range(n)]
        improved = False
        for _ in range(tries):
            # a small floor keeps parameters the samples cannot see (zero rows) from making A singular
            floor = 1e-9 * max(max(JTJ[i][i] for i in range(n)), 1e-30)
            A = [[JTJ[i][j] + (lam * JTJ[i][i] + floor if i == j else 0.0) for j in range(n)] for i in range(n)]
            d = _solve6(A, [-v for v in JTr])
            if d is None:
                lam *= 10
                continue
            q = [a + b for a, b in zip(p, d)]
            if project:
                q = project(q)
            rq = res(q)
            cq = sum(v * v for v in rq)
            if cq < cost:
                improved = cost - cq > tol * cost
                p, r, cost = q, rq, cq
                lam = max(lam / 3, 1e-7)
                break
            lam *= 4
        if not improved:
            break
    return p


# ------------------------------------------------------------------ bounds (Darkslide)
# Fitting inside RICOH's own factory range (user, 2026-10-14): the look matrix and the
# curve steps are kept within bounds measured from the user's firmware while fitting, so
# the result never needs clamping afterwards. bounds keys: look_min, look_max,
# look_row_abs_max (Q13), curve_step_max, curve_step_min (u14 per curve index).
LOOK_MARGIN = 6 / 8192  # room for Q13 rounding and the diagonal repair


def project_look(p, bounds):
    """Move the six off-diagonal terms so every row of M_from(p) stays inside the bounds."""
    if not bounds:
        return p
    lo = bounds.get("look_min", -32768) / 8192 + LOOK_MARGIN
    hi = bounds.get("look_max", 32767) / 8192 - LOOK_MARGIN
    rmax = bounds.get("look_row_abs_max", 10 ** 9) / 8192 - 3 * LOOK_MARGIN
    out = list(p)
    for r in range(3):
        o = [out[2 * r], out[2 * r + 1]]
        for _ in range(40):
            o = [min(hi, max(lo, v)) for v in o]
            d = 1 - o[0] - o[1]
            if d > hi:
                o = [v + (d - hi) / 2 for v in o]
                continue
            if d < lo:
                o = [v - (lo - d) / 2 for v in o]
                continue
            total = abs(d) + abs(o[0]) + abs(o[1])
            if total > rmax:
                o = [v * 0.97 for v in o]
                continue
            break
        out[2 * r], out[2 * r + 1] = o
    return out


def limit_steps(curve, smax=None, smin=None):
    """Keep each step of a 256-point curve within [smin, smax] (forward pass)."""
    if smax is None and smin is None:
        return list(curve)
    out = [curve[0]]
    for v in curve[1:]:
        prev = out[-1]
        v = min(v, prev + smax) if smax is not None else v
        v = max(v, prev + smin) if smin is not None else v
        out.append(int(round(min(16383, max(0, v)))))
    return out


# ------------------------------------------------------------------ the fit
def fit(base, target, outer=4, seed=1, bounds=None):
    """Alternate per-channel curves and the look matrix, then a post-curve matrix
    (cube_fit.fit + cca1_fit). Returns float matrix M, integer curves, float post C."""
    L, w = samples(seed)
    T = [target(lin) for lin in L]
    sw = [math.sqrt(v) for v in w]
    p = [0.0] * 6

    def curves_for(M):
        g = [base_index(base, M, lin) for lin in L]
        return [fit_curve([gi[c] for gi in g], [ti[c] for ti in T], w) for c in range(3)]

    for _ in range(outer):
        curves = curves_for(M_from(p))

        def res(q, curves=curves):
            Mq, out = M_from(q), []
            for lin, t, s in zip(L, T, sw):
                m = model(base, Mq, curves, lin)
                out.extend((s * (m[0] - t[0]), s * (m[1] - t[1]), s * (m[2] - t[2])))
            return out
        p = least_squares6(res, project_look(p, bounds), project=(lambda q: project_look(q, bounds)) if bounds else None)
    M = M_from(p)
    curves = curves_for(M)
    m_all = [model(base, M, curves, lin) for lin in L]

    def res_post(q):
        C, out = M_from(q), []
        for m, t, s in zip(m_all, T, sw):
            for c in range(3):
                v = min(1.0, max(0.0, C[c][0] * m[0] + C[c][1] * m[1] + C[c][2] * m[2]))
                out.append(s * (v - t[c]))
        return out
    C = M_from(least_squares6(res_post, [0.0] * 6))
    return M, curves, C


# ------------------------------------------------------------------ perceptual refit (lab_fit.py)
NK = 17


def _offdiag(A):
    return [A[r][j] for r in range(3) for j in range(3) if j != r]


def _corrected(curves, kn):
    """Each curve plus a piecewise-linear correction on NK knots, clipped and kept rising."""
    out = []
    for c in range(3):
        row, top = [], 0.0
        for i in range(256):
            x = i * (NK - 1) / 255
            j = min(int(x), NK - 2)
            v = curves[c][i] + kn[c * NK + j] + (kn[c * NK + j + 1] - kn[c * NK + j]) * (x - j)
            top = max(top, min(16383.0, max(0.0, v)))
            row.append(top)
        out.append(row)
    return out


def refine_perceptual(base, target, M, curves, C, iters=8, seed=5, randoms=500, bounds=None):
    """lab_fit.lab_fit: refit look matrix, post matrix and a 17-knot correction of each
    curve so the per-sample CIEDE2000 (not the RGB difference) is small. Plain LM on
    6+6+51 parameters over a smaller sample set; returns (M, curves, C)."""
    L, w = samples(seed, randoms=randoms)
    mean = sum(w) / len(w)
    sw = [math.sqrt(v / mean) for v in w]
    T = [target(lin) for lin in L]
    M0, P0 = _offdiag(M), _offdiag(C)

    def unpack(p):
        return M_from([a + b for a, b in zip(M0, p[:6])]), M_from([a + b for a, b in zip(P0, p[6:12])]), _corrected(curves, p[12:])

    def res(p):
        Mq, Pq, cv = unpack(p)
        return [s * de2000(model(base, Mq, cv, lin, Pq), t) for lin, t, s in zip(L, T, sw)]

    # per-parameter steps, like lab_fit's x_scale: matrix terms are ~0.01, curve knots ~100 u14
    def keep_in(p):
        look = project_look([a + b for a, b in zip(M0, p[:6])], bounds)
        return [a - b for a, b in zip(look, M0)] + list(p[6:])

    p = least_squares6(res, [0.0] * (12 + 3 * NK), iters=iters, step=[1e-4] * 12 + [4.0] * (3 * NK), tol=0.0, tries=14,
                       project=keep_in if bounds else None)
    Mq, Pq, cv = unpack(p)
    return Mq, [[int(round(v)) for v in row] for row in cv], Pq


def quantize_post_q512(C):
    """Round to Q512 and repair each diagonal so rows sum to exactly 512 (cca1_fit)."""
    Q = [[int(round(v * 512)) for v in row] for row in C]
    for r in range(3):
        Q[r][r] += 512 - sum(Q[r])
    if any(abs(v) >= 2048 for row in Q for v in row):
        raise ValueError("post-curve matrix too large")
    return Q


def evaluate(base, M, curves, C, target, seed=7):
    """CIEDE2000 between the (quantized) camera model and the target on fresh samples."""
    L, _ = samples(seed, randoms=800)
    des = sorted(de2000(model(base, M, curves, lin, C), target(lin)) for lin in L)
    grey = [de2000(model(base, M, curves, (v, v, v), C), target((v, v, v)))
            for v in (0.18 * 2.0 ** (e / 2) for e in range(-10, 6))]
    return dict(de_mean=sum(des) / len(des), de_p95=des[int(0.95 * (len(des) - 1))], de_max=des[-1],
                grey_de_mean=sum(grey) / len(grey), samples=len(des))

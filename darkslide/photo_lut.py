"""Learn the tone and colour leaning of a reference photo and bake it into a .cube LUT.

Approximate by design: a LUT cannot carry light, scene or lens, and the reference's
ungraded original is unknown. Method (all public, written from our own plan):
lightness is matched by quantiles in Oklab; colour is matched per tonal zone
(shadows / midtones / highlights) by mean and spread of a/b, Reinhard-style.
Both images arrive already decoded and downscaled by the browser as RGB8 bytes.
"""
import base64
import math
import re

SIZE = 33
MAX_SIDE = 640
MAX_SOURCES = 4
SAMPLE_LIMIT = 120000
TONE_POINTS = 33
SLOPE = (0.4, 2.5)
MAX_SHIFT = 0.05          # Oklab a/b offset per zone
SCALE = (0.5, 1.6)        # chroma scale per zone
ZONES = ("shadows", "midtones", "highlights")
PARAMS = {"strength": 1.0, "tone": 1.0, "tint": 1.0, "saturation": 1.0,
          "protect_skin": True, "keep_neutral": False}


class PhotoLutError(ValueError):
    pass


def _need(ok, message):
    if not ok:
        raise PhotoLutError(message)


# --- colour --------------------------------------------------------------------

def _dec(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _enc(c):
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


DEC8 = [_dec(i / 255.0) for i in range(256)]


def _cbrt(x):
    return math.copysign(abs(x) ** (1 / 3), x)


def _oklab(r, g, b):
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _linear(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _zone_weights(L):
    shadows = 1.0 - _smooth(0.30, 0.55, L)
    highlights = _smooth(0.55, 0.85, L)
    return shadows, max(0.0, 1.0 - shadows - highlights), highlights


SKIN_HUE = math.atan2(*reversed(_oklab(_dec(224 / 255), _dec(172 / 255), _dec(140 / 255))[1:]))


def _skin(a, b):
    c = math.hypot(a, b)
    if c < 0.02 or c > 0.18:
        return 0.0
    d = abs((math.atan2(b, a) - SKIN_HUE + math.pi) % (2 * math.pi) - math.pi)
    return max(0.0, math.cos(min(math.pi / 2, d * 3.0))) ** 2


# --- input ---------------------------------------------------------------------

def _image(item, label):
    _need(type(item) is dict and set(item) == {"w", "h", "rgb"}, label + "：格式错误")
    w, h = item["w"], item["h"]
    _need(type(w) is int and type(h) is int and 1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE,
          label + "：尺寸必须在 1–%d 像素之间" % MAX_SIDE)
    _need(type(item["rgb"]) is str and len(item["rgb"]) <= 4 * (w * h * 3 + 2) // 3 + 4, label + "：像素数据过长")
    try:
        raw = base64.b64decode(item["rgb"], validate=True)
    except ValueError:
        raise PhotoLutError(label + "：像素数据不是 base64") from None
    _need(len(raw) == w * h * 3, label + "：像素数量与尺寸不符")
    return raw


def _samples(raws):
    """Usable pixels of all images as Oklab triples, at most SAMPLE_LIMIT in total."""
    total = sum(len(r) // 3 for r in raws)
    step = max(1, -(-total // SAMPLE_LIMIT))
    out = []
    for raw in raws:
        for i in range(0, len(raw) // 3, step):
            r, g, b = raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]
            if max(r, g, b) >= 252 or max(r, g, b) <= 3:
                continue  # clipped: tells nothing about the look
            out.append(_oklab(DEC8[r], DEC8[g], DEC8[b]))
    return out


def _quantile(sorted_values, p):
    x = p * (len(sorted_values) - 1)
    i = int(x)
    j = min(i + 1, len(sorted_values) - 1)
    return sorted_values[i] + (sorted_values[j] - sorted_values[i]) * (x - i)


def _tone_curve(src_L, ref_L):
    """Monotone 33-point curve mapping source lightness to reference lightness."""
    s, r = sorted(src_L), sorted(ref_L)
    ps = [0.005 + 0.99 * k / 64 for k in range(65)]
    xs = [_quantile(s, p) for p in ps]
    ys = [_quantile(r, p) for p in ps]
    pairs = [(xs[0], ys[0])]
    for x, y in zip(xs[1:], ys[1:]):
        if x > pairs[-1][0] + 1e-4:
            pairs.append((x, max(y, pairs[-1][1])))
    lo_slope = hi_slope = 1.0
    if len(pairs) >= 3:
        lo_slope = (pairs[2][1] - pairs[0][1]) / (pairs[2][0] - pairs[0][0])
        hi_slope = (pairs[-1][1] - pairs[-3][1]) / (pairs[-1][0] - pairs[-3][0])
    clamp = lambda v: min(SLOPE[1], max(SLOPE[0], v))
    lo_slope, hi_slope = clamp(lo_slope), clamp(hi_slope)

    def f(x):
        if x <= pairs[0][0]:
            return pairs[0][1] - lo_slope * (pairs[0][0] - x)
        if x >= pairs[-1][0]:
            return pairs[-1][1] + hi_slope * (x - pairs[-1][0])
        for (x0, y0), (x1, y1) in zip(pairs, pairs[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pairs[-1][1]

    n = TONE_POINTS - 1
    raw = [f(k / n) for k in range(TONE_POINTS)]
    half = [min(2, k, n - k) for k in range(TONE_POINTS)]  # symmetric window, shrinking at the ends
    smooth = [sum(raw[k - r:k + r + 1]) / (2 * r + 1) for k, r in enumerate(half)]
    curve, step = [min(1.0, max(0.0, smooth[0]))], 1.0 / n
    for v in smooth[1:]:
        prev = curve[-1]
        curve.append(min(1.0, max(prev + SLOPE[0] * step if prev < 1.0 else 1.0, min(prev + SLOPE[1] * step, v))))
    return [round(v, 6) for v in curve]


def _tone(curve, L):
    x = min(1.0, max(0.0, L)) * (TONE_POINTS - 1)
    i = min(TONE_POINTS - 2, int(x))
    return curve[i] + (curve[i + 1] - curve[i]) * (x - i)


def _zone_stats(pixels, use_curve=None):
    """Per zone: weight, mean a, mean b, spread (RMS distance from the mean in a/b)."""
    acc = [[0.0, 0.0, 0.0, 0.0] for _ in ZONES]
    for L, a, b in pixels:
        if use_curve is not None:
            L = _tone(use_curve, L)
        for z, w in enumerate(_zone_weights(L)):
            if w:
                s = acc[z]
                s[0] += w
                s[1] += w * a
                s[2] += w * b
                s[3] += w * (a * a + b * b)
    out = []
    for w, sa, sb, sq in acc:
        if w < 1.0:
            out.append(None)
            continue
        ma, mb = sa / w, sb / w
        out.append((w, ma, mb, math.sqrt(max(0.0, sq / w - ma * ma - mb * mb))))
    return out


def _hue_concentration(pixels):
    """How much the coloured pixels agree on one hue: length of the chroma-weighted mean
    hue direction, 0 (all around the wheel) .. 1 (a single hue). No bin edges involved."""
    sx = sy = total = 0.0
    for _, a, b in pixels:
        c = math.hypot(a, b)
        if c > 0.03:
            sx, sy, total = sx + a, sy + b, total + c
    return math.hypot(sx, sy) / total if total > 0 else 0.0


def learn(reference, sources):
    """Return {model, warnings, defaults} from one reference and 1–4 source images."""
    ref_raw = _image(reference, "参考照片")
    _need(type(sources) is list and 1 <= len(sources) <= MAX_SOURCES, "起点照片需要 1–%d 张" % MAX_SOURCES)
    src_raws = [_image(s, "起点照片 %d" % (i + 1)) for i, s in enumerate(sources)]
    ref, src = _samples([ref_raw]), _samples(src_raws)
    _need(len(ref) >= 64 and len(src) >= 64, "照片里可用的像素太少（几乎全是过曝或死黑）")
    curve = _tone_curve([p[0] for p in src], [p[0] for p in ref])
    ref_z, src_z = _zone_stats(ref), _zone_stats(src, curve)
    zones = []
    for r, s in zip(ref_z, src_z):
        if r is None or s is None:
            zones.append({"scale": 1.0, "da": 0.0, "db": 0.0})
            continue
        k = r[3] / s[3] if s[3] > 0.005 else 1.0
        k = min(SCALE[1], max(SCALE[0], k))
        da, db = r[1] - k * s[1], r[2] - k * s[2]
        n = math.hypot(da, db)
        if n > MAX_SHIFT - 2e-6:  # margin so rounding below stays inside the limit
            da, db = da * (MAX_SHIFT - 2e-6) / n, db * (MAX_SHIFT - 2e-6) / n
        zones.append({"scale": round(k, 5), "da": round(da, 6), "db": round(db, 6)})
    warnings, defaults = [], dict(PARAMS)
    if _hue_concentration(ref) > 0.85:
        warnings.append("参考照片的颜色太集中，可能把你的照片整体染色；偏色已减半，可以再用右边栏微调")
        defaults["tint"] = 0.5
    ref_mid = _quantile(sorted(p[0] for p in ref), 0.5)
    src_mid = _quantile(sorted(p[0] for p in src), 0.5)
    if abs(ref_mid - src_mid) > 0.3:
        warnings.append("两张照片明暗差别很大（比如一张夜景、一张白天），建议换一张场景相近的起点照片")
    model = {"version": 1, "tone": curve, "zones": zones}
    return {"model": model, "warnings": warnings, "defaults": defaults}


# --- bake ----------------------------------------------------------------------

def _model(model):
    _need(type(model) is dict and set(model) == {"version", "tone", "zones"} and model["version"] == 1,
          "模型格式错误")
    tone, zones = model["tone"], model["zones"]
    _need(type(tone) is list and len(tone) == TONE_POINTS and
          all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in tone) and
          all(b >= a for a, b in zip(tone, tone[1:])), "影调曲线错误")
    _need(type(zones) is list and len(zones) == 3, "分区数据错误")
    out = []
    for z in zones:
        _need(type(z) is dict and set(z) == {"scale", "da", "db"} and
              all(type(z[k]) in (int, float) and math.isfinite(z[k]) for k in z), "分区数据错误")
        _need(SCALE[0] <= z["scale"] <= SCALE[1] and math.hypot(z["da"], z["db"]) <= MAX_SHIFT + 1e-6, "分区数值越界")
        out.append((float(z["scale"]), float(z["da"]), float(z["db"])))
    return [float(v) for v in tone], out


def _params(params):
    p = dict(PARAMS)
    _need(params is None or type(params) is dict, "参数格式错误")
    for key, value in (params or {}).items():
        _need(key in PARAMS, "未知参数：%s" % str(key)[:20])
        if type(PARAMS[key]) is bool:
            _need(type(value) is bool, "%s 应为开关" % key)
        else:
            _need(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, "%s 应在 0–1 之间" % key)
        p[key] = value
    return p


def apply(model, params, rgb):
    """Map one sRGB-encoded colour (0–1) through the learned look."""
    tone, zones = model
    p = params
    L, a, b = _oklab(*(_dec(c) for c in rgb))
    L1 = L + p["tone"] * (_tone(tone, L) - L)
    w = _zone_weights(L1)
    k = sum(wz * z[0] for wz, z in zip(w, zones))
    da = sum(wz * z[1] for wz, z in zip(w, zones)) * p["tint"]
    db = sum(wz * z[2] for wz, z in zip(w, zones)) * p["tint"]
    k = 1.0 + p["saturation"] * (k - 1.0)
    guard = 1.0 - 0.7 * _skin(a, b) if p["protect_skin"] else 1.0
    k = 1.0 + guard * (k - 1.0)
    shift = guard * (min(1.0, math.hypot(a, b) / 0.04) if p["keep_neutral"] else 1.0)
    a1, b1 = a * k + da * shift, b * k + db * shift
    s = p["strength"]
    out = _linear(L + s * (L1 - L), a + s * (a1 - a), b + s * (b1 - b))
    return tuple(_enc(c) for c in out)


def bake(model, params=None, name="Reference look", size=SIZE):
    """Return the .cube text for a learned model and the user's adjustments."""
    _need(type(size) is int and 2 <= size <= 65, "LUT 网格必须在 2–65 之间")
    m, p = _model(model), _params(params)
    title = re.sub(r'["\\\x00-\x1f\x7f]', "", str(name)).strip()[:80] or "Reference look"
    lines = ['TITLE "%s"' % title,
             "# Approximate look learned from a reference photo by Darkslide",
             "LUT_3D_SIZE %d" % size, "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    n = size - 1
    for bi in range(size):
        for gi in range(size):
            for ri in range(size):
                lines.append("%.6f %.6f %.6f" % apply(m, p, (ri / n, gi / n, bi / n)))
    return "\n".join(lines) + "\n"

"""Bake the colour settings of a Lightroom / Camera Raw XMP preset into a .cube LUT.

Each slider is approximated with Darkslide's own model; Adobe's renderer is not
public, so results are close but never identical. Non-colour settings (grain,
vignette, sharpening, clarity, masks, profile tables) are skipped and listed.
The input is an untrusted file: size-limited, DTD and entities refused.
"""
import colorsys
import math
import re
import sys
import xml.etree.ElementTree as ET

CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
MAX_BYTES = 4 << 20
SIZE = 33
BANDS = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")
CENTERS = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0)
TABLE = 1024

USED = (
    ("白平衡", ("IncrementalTemperature", "IncrementalTint", "Temperature", "Tint")),
    ("曝光", ("Exposure2012",)), ("对比度", ("Contrast2012",)),
    ("高光", ("Highlights2012",)), ("阴影", ("Shadows2012",)),
    ("白色", ("Whites2012",)), ("黑色", ("Blacks2012",)),
    ("饱和度", ("Saturation",)), ("自然饱和度", ("Vibrance",)),
    ("参数曲线", ("ParametricShadows", "ParametricDarks", "ParametricLights", "ParametricHighlights")),
    ("点曲线", ("ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green", "ToneCurvePV2012Blue")),
    ("HSL", tuple(p + b for p in ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment") for b in BANDS)),
    ("颜色分级", ("SplitToningShadowSaturation", "SplitToningHighlightSaturation", "ColorGradeMidtoneSat",
              "ColorGradeGlobalSat", "ColorGradeShadowLum", "ColorGradeMidtoneLum",
              "ColorGradeHighlightLum", "ColorGradeGlobalLum")),
    ("校准", ("RedHue", "RedSaturation", "GreenHue", "GreenSaturation", "BlueHue", "BlueSaturation", "ShadowTint")),
    ("黑白混色", ("ConvertToGrayscale",)),
)
SKIPPED = {
    "Sharpness": "锐化", "LuminanceSmoothing": "降噪", "ColorNoiseReduction": "降噪",
    "Clarity2012": "清晰度", "Clarity": "清晰度", "Texture": "纹理", "Dehaze": "去朦胧",
    "GrainAmount": "颗粒", "PostCropVignetteAmount": "暗角", "VignetteAmount": "镜头暗角",
    "LensProfileEnable": "镜头校正", "AutoLateralCA": "色差校正", "HasCrop": "裁剪",
    "RGBTable": "配置文件颜色表", "LookTable": "配置文件颜色表", "Look": "配置文件（Look）",
    "MaskGroupBasedCorrections": "蒙版与局部调整", "GradientBasedCorrections": "蒙版与局部调整",
    "CircularGradientBasedCorrections": "蒙版与局部调整", "PaintBasedCorrections": "蒙版与局部调整",
    "RetouchInfo": "污点去除", "AutoTone": "自动调整", "AutoWhiteVersion": "自动调整",
}
NEUTRAL_PROFILES = ("", "Embedded", "Adobe Standard", "Adobe Color")


class XmpError(ValueError):
    pass


def _need(ok, message):
    if not ok:
        raise XmpError(message)


def parse(raw):
    """Return {key: str | list} for every crs setting; nested Looks are only noted."""
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "XMP 文件为空或超过 4 MB")
    _need(not re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.I), "XMP 含有 DOCTYPE/ENTITY，拒绝读取")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise XmpError("不是有效的 XMP：%s" % exc) from exc
    out = {}

    def walk(el):
        if el.tag == RDF + "Description":
            for key, value in el.attrib.items():
                if key.startswith(CRS):
                    out[key[len(CRS):]] = value
        elif el.tag.startswith(CRS):
            name = el.tag[len(CRS):]
            if name in ("Look", "Parameters"):
                out["Look"] = "True"
                return
            seq = el.find(RDF + "Seq")
            if seq is None:
                seq = el.find(RDF + "Bag")
            alt = el.find(RDF + "Alt")
            if seq is not None:
                out[name] = [(li.text or "").strip() for li in seq.findall(RDF + "li")]
            elif alt is not None:
                li = alt.find(RDF + "li")
                out[name] = (li.text or "").strip() if li is not None else ""
            elif len(el):
                out[name] = "True"
            else:
                out[name] = (el.text or "").strip()
            return
        for child in el:
            walk(child)

    walk(root)
    _need(out, "没有找到 Lightroom / Camera Raw 设置")
    return out


def _num(s, key, lo, hi, default=0.0):
    value = s.get(key)
    if value is None or value == "":
        return default
    _need(type(value) is str, "%s 应为数值" % key)
    try:
        x = float(value)
    except ValueError:
        raise XmpError("%s 不是数值：%s" % (key, value[:20])) from None
    _need(math.isfinite(x), "%s 不是有限数值" % key)
    return min(hi, max(lo, x))


def _curve(s, key):
    pts = s.get(key)
    if pts is None:
        return None
    _need(type(pts) is list and 2 <= len(pts) <= 64, "%s 曲线点数错误" % key)
    xs, ys, last = [], [], -1
    for item in pts:
        m = re.fullmatch(r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*", item)
        _need(m is not None, "%s 曲线点格式错误" % key)
        x, y = int(m.group(1)), int(m.group(2))
        _need(x <= 255 and y <= 255 and x > last, "%s 曲线点越界或未递增" % key)
        last = x
        xs.append(x / 255.0)
        ys.append(y / 255.0)
    if len(xs) == 2 and xs == ys == [0.0, 1.0]:
        return None
    return xs, ys


def _spline(xs, ys):
    """Natural cubic spline (C2, zero second derivative at both ends); flat outside."""
    n = len(xs)
    m = [0.0] * n
    if n > 2:
        h = [xs[i + 1] - xs[i] for i in range(n - 1)]
        a, b, c, d = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            d[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
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
        if x >= xs[-1]:
            return ys[-1]
        i = max(k for k in range(n - 1) if xs[k] <= x)
        h = xs[i + 1] - xs[i]
        t0, t1 = xs[i + 1] - x, x - xs[i]
        return (m[i] * t0 ** 3 + m[i + 1] * t1 ** 3) / (6 * h) + \
            (ys[i] / h - m[i] * h / 6) * t0 + (ys[i + 1] / h - m[i + 1] * h / 6) * t1
    return f


def _table(f, monotone=False):
    out, top = [], 0.0
    for i in range(TABLE + 1):
        y = min(1.0, max(0.0, f(i / TABLE)))
        if monotone:
            top = y = max(top, y)
        out.append(y)
    return out


def _look(t, x):
    x = min(1.0, max(0.0, x)) * TABLE
    i = min(TABLE - 1, int(x))
    return t[i] + (t[i + 1] - t[i]) * (x - i)


def _dec(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _enc(c):
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


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


def _bands(hue):
    """Two neighbouring HSL bands and their raised-cosine weights for a hue in degrees."""
    for i in range(8):
        lo, hi = CENTERS[i], CENTERS[i + 1] if i < 7 else 360.0
        if lo <= hue < hi:
            t = (hue - lo) / (hi - lo)
            w = 0.5 - 0.5 * math.cos(math.pi * t)
            return ((i, 1.0 - w), ((i + 1) % 8, w))
    return ((0, 1.0), (1, 0.0))


def _gap(i, step):
    j = (i + step) % 8
    return (CENTERS[j] - CENTERS[i]) % 360 if step > 0 else (CENTERS[i] - CENTERS[j]) % 360


def _direction(hue):
    """Unit Oklab a/b direction of the fully saturated sRGB colour at an HSV hue."""
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, 1.0, 1.0)
    _, a, bb = _oklab(_dec(r), _dec(g), _dec(b))
    n = math.hypot(a, bb) or 1.0
    return a / n, bb / n


def _settings(s):
    p = {"notes": ["近似：按 Darkslide 自己的模型换算，与 Lightroom 的结果不完全一样"]}
    # calibration: rotate and rescale each primary in Oklab, then keep white neutral
    cal = [(_num(s, c + "Hue", -100, 100), _num(s, c + "Saturation", -100, 100)) for c in ("Red", "Green", "Blue")]
    if any(h or sat for h, sat in cal):
        cols = []
        for k, (h, sat) in enumerate(cal):
            L, a, b = _oklab(*[1.0 if j == k else 0.0 for j in range(3)])
            ang = math.atan2(b, a) + math.radians(20) * h / 100
            c = math.hypot(a, b) * max(0.0, 1 + 0.6 * sat / 100)
            cols.append(_linear(L, c * math.cos(ang), c * math.sin(ang)))
        m = [[cols[j][i] for j in range(3)] for i in range(3)]
        p["matrix"] = [[v / (sum(row) or 1.0) for v in row] for row in m]
    p["shadow_tint"] = _num(s, "ShadowTint", -100, 100) / 100
    # white balance: relative shifts; absolute RAW values are read against 5500 K
    warm, tint = _num(s, "IncrementalTemperature", -100, 100) / 100, _num(s, "IncrementalTint", -100, 100) / 100
    if "IncrementalTemperature" not in s and "IncrementalTint" not in s and ("Temperature" in s or "Tint" in s):
        if "Temperature" in s:
            warm = max(-1.0, min(1.0, math.log2(_num(s, "Temperature", 2000, 50000, 5500) / 5500) / 0.6))
        tint = _num(s, "Tint", -150, 150) / 150
        p["notes"].append("RAW 白平衡按 5500 K 基准近似换算")
    if warm or tint:
        g = (2 ** (0.3 * warm), 2 ** (-0.2 * tint), 2 ** (-0.3 * warm))
        n = 0.2126 * g[0] + 0.7152 * g[1] + 0.0722 * g[2]
        p["gains"] = tuple(v / n for v in g)
    p["exposure"] = 2 ** _num(s, "Exposure2012", -5, 5)
    # basic tone on perceptual luminance, applied as a hue-keeping ratio
    c, hl, sh, wh, bk = (_num(s, k, -100, 100) / 100 for k in
                         ("Contrast2012", "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012"))
    if c or hl or sh or wh or bk:
        def tone(x):
            y = x + 0.22 * c * 4 * x * (1 - x) * (2 * x - 1)
            if x > 0.4:
                y += 0.15 * hl * math.sin(math.pi * (x - 0.4) / 0.6) ** 2
            if x < 0.6:
                y += 0.15 * sh * math.sin(math.pi * x / 0.6) ** 2
            return y + 0.12 * wh * x ** 4 + 0.12 * bk * (1 - x) ** 4
        p["tone"] = _table(tone, monotone=True)
    p["sat"] = _num(s, "Saturation", -100, 100) / 100
    p["vib"] = _num(s, "Vibrance", -100, 100) / 100
    # parametric curve then point curve, per channel on encoded values
    amounts = [_num(s, "Parametric" + k, -100, 100) / 100 for k in ("Shadows", "Darks", "Lights", "Highlights")]
    s1, s2, s3 = (_num(s, "Parametric%sSplit" % k, 5, 95, d) / 100 for k, d in
                  (("Shadow", 25), ("Midtone", 50), ("Highlight", 75)))
    _need(s1 < s2 < s3, "参数曲线分割点必须递增")
    master = _curve(s, "ToneCurvePV2012")
    if any(amounts) or master:
        centers = [s1 / 2, (s1 + s2) / 2, (s2 + s3) / 2, (s3 + 1) / 2]
        edges = [0.0] + centers + [1.0]
        spline = _spline(*master) if master else None

        def curve(x):
            y = x
            for i, amt in enumerate(amounts):
                if amt:
                    hw = max(centers[i] - edges[i], edges[i + 2] - centers[i])
                    d = (x - centers[i]) / hw
                    if abs(d) < 1:
                        y += 0.2 * amt * math.cos(math.pi / 2 * d) ** 2 * min(1.0, x * 20, (1 - x) * 20)
            return spline(y) if spline else y
        p["curve"] = _table(curve, monotone=not master)
    for k, ch in enumerate(("Red", "Green", "Blue")):
        pts = _curve(s, "ToneCurvePV2012" + ch)
        if pts:
            p.setdefault("rgb", [None, None, None])[k] = _table(_spline(*pts))
    hsl = [[_num(s, pre + b, -100, 100) / 100 for b in BANDS] for pre in
           ("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")]
    p["gray"] = s.get("ConvertToGrayscale", "False") == "True"
    if p["gray"]:
        p["mix"] = [_num(s, "GrayMixer" + b, -100, 100) / 100 for b in BANDS]
    elif any(any(row) for row in hsl):
        p["hsl"] = hsl
    # colour grading (split-toning keys hold the shadow/highlight wheels)
    wheels = []
    for hue_key, sat_key, lum_key, strength in (
            ("SplitToningShadowHue", "SplitToningShadowSaturation", "ColorGradeShadowLum", 0.10),
            ("ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeMidtoneLum", 0.08),
            ("SplitToningHighlightHue", "SplitToningHighlightSaturation", "ColorGradeHighlightLum", 0.10),
            ("ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum", 0.06)):
        sat = _num(s, sat_key, 0, 100) / 100
        da, db = _direction(_num(s, hue_key, 0, 360))
        wheels.append((strength * sat * da, strength * sat * db, 0.08 * _num(s, lum_key, -100, 100) / 100))
    if any(any(w) for w in wheels) or p["shadow_tint"]:
        p["wheels"] = wheels
        p["pivot"] = 0.5 - 0.25 * _num(s, "SplitToningBalance", -100, 100) / 100
        p["blend"] = 0.15 + 0.35 * _num(s, "ColorGradeBlending", 0, 100, 50) / 100
    return p


def _pixel(r, g, b, p):
    r, g, b = _dec(r), _dec(g), _dec(b)
    if "matrix" in p:
        m = p["matrix"]
        r, g, b = (m[i][0] * r + m[i][1] * g + m[i][2] * b for i in range(3))
    if "gains" in p:
        r, g, b = r * p["gains"][0], g * p["gains"][1], b * p["gains"][2]
    e = p["exposure"]
    r, g, b = r * e, g * e, b * e
    if "tone" in p:
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        y2 = _dec(_look(p["tone"], _enc(y)))
        r, g, b = (r * y2 / y, g * y2 / y, b * y2 / y) if y > 1e-6 else (y2, y2, y2)
    r, g, b = (min(1.0, max(0.0, v)) for v in (r, g, b))
    if p["sat"] or p["vib"]:
        L, a, bb = _oklab(r, g, b)
        c = math.hypot(a, bb)
        f = max(0.0, 1 + p["sat"])
        if p["vib"]:
            skin = max(0.0, math.cos(math.atan2(bb, a) - 1.0)) ** 4
            f *= max(0.0, 1 + p["vib"] * (1 - min(1.0, c / 0.2)) * (1 - 0.5 * skin))
        r, g, b = (min(1.0, max(0.0, v)) for v in _linear(L, a * f, bb * f))
    r, g, b = _enc(r), _enc(g), _enc(b)
    if "curve" in p:
        r, g, b = (_look(p["curve"], v) for v in (r, g, b))
    if "rgb" in p:
        r, g, b = (_look(t, v) if t else v for t, v in zip(p["rgb"], (r, g, b)))
    if "hsl" in p or p["gray"]:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        bands = _bands(h * 360)
        if p["gray"]:
            y = 0.2126 * _dec(r) + 0.7152 * _dec(g) + 0.0722 * _dec(b)
            y *= max(0.0, 1 + 0.5 * s * sum(w * p["mix"][i] for i, w in bands))
            r = g = b = _enc(y)
        else:
            hue, sat, lum = p["hsl"]
            dh = sum(w * hue[i] * 0.6 * _gap(i, 1 if hue[i] > 0 else -1) for i, w in bands)
            r, g, b = colorsys.hsv_to_rgb(((h * 360 + dh) % 360) / 360,
                                          min(1.0, s * max(0.0, 1 + sum(w * sat[i] for i, w in bands))), v)
            f = 2 ** (0.6 * s * sum(w * lum[i] for i, w in bands))
            r, g, b = (_enc(_dec(c) * f) for c in (r, g, b))
    if "wheels" in p:
        L, a, bb = _oklab(_dec(r), _dec(g), _dec(b))
        piv, half = p["pivot"], p["blend"] / 2
        ws = 1 - _smooth(piv - 0.2 - half, piv - 0.2 + half, L)
        wh = _smooth(piv + 0.2 - half, piv + 0.2 + half, L)
        weights = (ws, max(0.0, 1 - ws - wh), wh, 1.0)
        for w, (da, db, dl) in zip(weights, p["wheels"]):
            a, bb, L = a + w * da, bb + w * db, L + w * dl
        a += 0.03 * p["shadow_tint"] * (1 - _smooth(0.0, 0.5, L))
        r, g, b = (_enc(v) for v in _linear(max(0.0, L), a, bb))
    return r, g, b


def convert(raw, name=None, size=SIZE):
    """Return dict(cube, name, size, used, skipped, notes, approximate=True)."""
    _need(type(size) is int and 2 <= size <= 65, "LUT 网格必须在 2–65 之间")
    s = parse(raw)
    p = _settings(s)
    used = [label for label, keys in USED if any(_active(s, k) for k in keys)]
    skipped = []
    for key, value in s.items():
        label = "配置文件颜色表" if key.startswith("Table_") else SKIPPED.get(key)
        if key == "CameraProfile" and value not in NEUTRAL_PROFILES:
            label = "相机配置文件（按普通图片处理）"
        if label and (key.startswith("Table_") or key == "CameraProfile" or _active(s, key)) and label not in skipped:
            skipped.append(label)
    if "配置文件颜色表" in skipped or "配置文件（Look）" in skipped:
        p["notes"].append("配置文件里的颜色表没有解码，已跳过")
    title = name or s.get("Name") or "XMP preset"
    title = re.sub(r'["\\\x00-\x1f\x7f]', "", str(title)).strip()[:80] or "XMP preset"
    lines = ['TITLE "%s"' % title,
             "# Approximate conversion of a Lightroom / Camera Raw XMP preset (colour settings only) by Darkslide",
             "LUT_3D_SIZE %d" % size, "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    n = size - 1
    for bi in range(size):
        for gi in range(size):
            for ri in range(size):
                lines.append("%.6f %.6f %.6f" % _pixel(ri / n, gi / n, bi / n, p))
    return dict(cube="\n".join(lines) + "\n", name=title, size=size, used=used,
                skipped=skipped, notes=p["notes"], approximate=True)


def _active(s, key):
    value = s.get(key)
    if value is None or value == "":
        return False
    if type(value) is list:
        return bool(value) if not key.startswith("ToneCurvePV2012") else _curve(s, key) is not None
    if value in ("True", "False"):
        return value == "True"
    try:
        return float(value) != 0
    except ValueError:
        return False


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("用法：python3 -m darkslide.xmp_lut 预设.xmp 输出.cube")
        return 2
    import os
    if os.path.exists(args[1]):
        print("输出文件已存在，不覆盖：%s" % args[1])
        return 1
    with open(args[0], "rb") as f:
        raw = f.read(MAX_BYTES + 1)
    try:
        result = convert(raw)
    except XmpError as exc:
        print("无法转换：%s" % exc)
        return 1
    with open(args[1], "x", encoding="utf-8") as f:
        f.write(result["cube"])
    print("已生成：%s（%s）" % (args[1], result["name"]))
    print("带进来的：" + ("、".join(result["used"]) or "无"))
    print("跳过的：" + ("、".join(result["skipped"]) or "无"))
    for note in result["notes"]:
        print("说明：" + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())

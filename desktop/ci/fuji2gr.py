"""Convert FUJIFILM F-Log2 / F-Gamut film-simulation LUTs into sRGB-input .cube
files that DARKSLIDE GR can fit into a RICOH GR III preset.

DARKSLIDE feeds its target cube with sRGB-encoded scene light (mid grey = linear
0.18). Each output grid point here goes:

    sRGB code -> linear BT.709 -> linear F-Gamut (BT.2020 primaries)
              -> highlight knee -> F-Log2 code -> FUJIFILM LUT (tetrahedral)
              -> BT.709 output

The FUJIFILM LUTs are for video and keep detail up to about +6 EV over mid
grey, while a photo's white (sRGB 1.0) sits at +2.47 EV, where they only reach
~0.84. The knee leaves everything at or below mid grey alone and stretches the
EV above it smoothly (EV' = EV + c*EV^2, one gain on all three channels from
luminance, so hues stay put) until sRGB white lands on the LUT's own white.
--video skips the knee and keeps the LUT's video tone curve.

--input cineon handles DaVinci Resolve's film-look LUTs (e.g. "Rec709 Fujifilm
3513DI D65"): Cineon log in (ref white 685, black 95, 300 codes per decade),
Rec.709 primaries kept as they are, Rec.709 gamma 2.4 out.

    python3 fuji2gr.py <fuji .cube> <out .cube> [--size 33] [--title NAME]
    python3 fuji2gr.py --probe <fuji .cube>     # grey-ramp report only
"""
import argparse
import math
import sys

# F-Log2 encoding, FUJIFILM F-Log2 data sheet (scene-linear reflectance in).
A, B, C, D, E, F = 5.555556, 0.064829, 0.245281, 0.384316, 8.799461, 0.092864
CUT1 = 0.000889

# Linear BT.709 -> linear BT.2020 (F-Gamut), D65, ITU-R BT.2087.
M709_2020 = (
    (0.6274040, 0.3292820, 0.0433136),
    (0.0690970, 0.9195400, 0.0113612),
    (0.0163916, 0.0880132, 0.8955950),
)


def flog2(x):
    return C * math.log10(A * x + B) + D if x >= CUT1 else E * x + F


CINEON_OFFSET = 10 ** ((95 - 685) / 300)


def cineon(x):
    return (685 + 300 * math.log10(max(x * (1 - CINEON_OFFSET) + CINEON_OFFSET, 1e-6))) / 1023


INPUTS = {  # name -> (log encoding, linear BT.709 -> LUT gamut)
    "flog2": (None, None),  # filled below, after the functions exist
    "cineon": (cineon, ((1, 0, 0), (0, 1, 0), (0, 0, 1))),
}
ENCODE = flog2
GAMUT = M709_2020

MID = 0.18
PHOTO_WHITE_EV = math.log2(1.0 / MID)
LUMA_2020 = (0.2627, 0.6780, 0.0593)


def white_ev(size, rows):
    """EV over mid grey where the LUT's grey ramp gets within 0.005 of its top."""
    evs = [x / 8 for x in range(0, 81)]
    outs = [sample(size, rows, *(ENCODE(MID * 2 ** ev),) * 3)[1] for ev in evs]
    top = max(outs)
    return next(ev for ev, o in zip(evs, outs) if o >= top - 0.005)


def knee(rgb, target_ev):
    y = sum(w * v for w, v in zip(LUMA_2020, rgb))
    if target_ev is None or y <= MID:
        return rgb
    ev = math.log2(y / MID)
    c = (target_ev - PHOTO_WHITE_EV) / PHOTO_WHITE_EV ** 2
    gain = 2 ** (ev + c * ev * ev) / (y / MID)
    return [v * gain for v in rgb]


def srgb_decode(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def read_cube(path):
    size, rows = None, []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("LUT_3D_SIZE"):
                size = int(s.split()[1])
            elif s[0] in "-.0123456789":
                rows.append(tuple(float(t) for t in s.split()[:3]))
            elif s.startswith(("DOMAIN_MIN", "DOMAIN_MAX", "TITLE")):
                parts = s.split()
                if parts[0] == "DOMAIN_MIN" and any(float(t) != 0 for t in parts[1:]):
                    sys.exit("unsupported DOMAIN_MIN")
                if parts[0] == "DOMAIN_MAX" and any(float(t) != 1 for t in parts[1:]):
                    sys.exit("unsupported DOMAIN_MAX")
    if size is None or len(rows) != size ** 3:
        sys.exit("not a 3D cube: %s" % path)
    return size, rows  # red varies fastest


def sample(size, rows, r, g, b):
    """Tetrahedral interpolation, inputs clamped to 0..1."""
    n = size - 1
    p = [min(max(c, 0.0), 1.0) * n for c in (r, g, b)]
    i = [min(int(c), n - 1) for c in p]
    f = [p[k] - i[k] for k in range(3)]

    def at(dr, dg, db):
        return rows[(i[0] + dr) + (i[1] + dg) * size + (i[2] + db) * size * size]

    fr, fg, fb = f
    c000, c111 = at(0, 0, 0), at(1, 1, 1)
    if fr >= fg >= fb:
        w, a, b_ = (1 - fr, fr - fg, fg - fb, fb), at(1, 0, 0), at(1, 1, 0)
    elif fr >= fb >= fg:
        w, a, b_ = (1 - fr, fr - fb, fb - fg, fg), at(1, 0, 0), at(1, 0, 1)
    elif fb >= fr >= fg:
        w, a, b_ = (1 - fb, fb - fr, fr - fg, fg), at(0, 0, 1), at(1, 0, 1)
    elif fg >= fr >= fb:
        w, a, b_ = (1 - fg, fg - fr, fr - fb, fb), at(0, 1, 0), at(1, 1, 0)
    elif fg >= fb >= fr:
        w, a, b_ = (1 - fg, fg - fb, fb - fr, fr), at(0, 1, 0), at(0, 1, 1)
    else:
        w, a, b_ = (1 - fb, fb - fg, fg - fr, fr), at(0, 0, 1), at(0, 1, 1)
    return tuple(w[0] * c000[k] + w[1] * a[k] + w[2] * b_[k] + w[3] * c111[k] for k in range(3))


def convert_point(size, rows, rgb, target_ev=None):
    lin = [srgb_decode(v) for v in rgb]
    wide = knee([sum(GAMUT[r][k] * lin[k] for k in range(3)) for r in range(3)], target_ev)
    return sample(size, rows, *(ENCODE(max(v, 0.0)) for v in wide))


def probe(path):
    size, rows = read_cube(path)
    print("%-6s %-8s %-8s %s" % ("EV", "linear", "log in", "LUT out (R G B)"))
    for ev in (-6, -4, -2, -1, 0, 1, 2, 2.5, 3, 4):
        x = 0.18 * 2 ** ev
        out = sample(size, rows, *(ENCODE(x),) * 3)
        print("%-6s %-8.4f %-8.4f %.4f %.4f %.4f" % (ev, x, ENCODE(x), *out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--size", type=int, default=33)
    ap.add_argument("--title")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--video", action="store_true", help="no highlight knee")
    ap.add_argument("--input", choices=sorted(INPUTS), default="flog2")
    args = ap.parse_args(argv)
    global ENCODE, GAMUT
    INPUTS["flog2"] = (flog2, M709_2020)
    ENCODE, GAMUT = INPUTS[args.input]
    if args.probe:
        return probe(args.src)
    if not args.dst:
        ap.error("dst is required")
    size, rows = read_cube(args.src)
    target = None if args.video else white_ev(size, rows)
    if target is not None:
        print("highlight knee: sRGB white -> +%.3f EV" % target, file=sys.stderr)
    n = args.size - 1
    with open(args.dst, "w", encoding="ascii", newline="\n") as out:
        if args.title:
            out.write('TITLE "%s"\n' % args.title)
        out.write("LUT_3D_SIZE %d\nDOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n" % args.size)
        for bi in range(args.size):
            for gi in range(args.size):
                for ri in range(args.size):
                    o = convert_point(size, rows, (ri / n, gi / n, bi / n), target)
                    out.write("%.6f %.6f %.6f\n" % tuple(min(max(v, 0.0), 1.0) for v in o))


if __name__ == "__main__":
    main()

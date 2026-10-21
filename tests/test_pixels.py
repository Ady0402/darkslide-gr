"""web/pixels.js: the icon and shutdown picture come out of plain arithmetic, the same in
every browser. Run with node on the page's own file."""
import json
import shutil
import struct
import subprocess
import unittest
import zlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

# Loads web/pixels.js into a bare context and runs `body`, which prints JSON.
HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const ctx = { window: {}, Uint8ClampedArray, Uint8Array, Uint32Array, Math, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const P = ctx.window.DarkslidePixels;
const run = new Function("P", "orient", %s);
console.log(JSON.stringify(run(P)));
"""


def page(body):
    script = HARNESS % json.dumps(body)
    out = subprocess.run(["node", "-e", script, str(APP / "web" / "pixels.js")], check=True, capture_output=True)
    return json.loads(out.stdout)


def unpng(data):
    """(w, h, RGBA bytes) of an 8-bit RGBA PNG, read with the standard library."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", None, None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body, crc = data[pos + 8:pos + 8 + n], struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert zlib.crc32(kind + body) == crc, kind
        if kind == b"IHDR":
            w, h, depth, colour = struct.unpack(">IIBB", body[:10])
            assert (depth, colour) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = [raw[y * (w * 4 + 1):(y + 1) * (w * 4 + 1)] for y in range(h)]
    assert all(r[0] == 0 for r in rows)
    return w, h, b"".join(r[1:] for r in rows)


@unittest.skipUnless(shutil.which("node"), "needs node to run web/pixels.js")
class Pixels(unittest.TestCase):
    def test_shrinking_averages_the_area_each_pixel_covers(self):
        # 4×2 picture -> 2×1: each output pixel is the mean of a 2×2 block.
        got = page("""
          const d = new Uint8ClampedArray([0,0,0,255, 100,0,0,255, 10,20,30,255, 30,40,50,255,
                                           50,0,0,255, 150,0,0,255, 50,60,70,255, 70,80,90,255]);
          return Array.from(P.resample({w: 4, h: 2, data: d}, {sx: 0, sy: 0, sw: 4, sh: 2}, 2, 1));
        """)
        self.assertEqual(got, [75, 0, 0, 255, 40, 50, 60, 255])

    def test_transparent_parts_turn_black_and_the_result_is_opaque(self):
        got = page("""
          const d = new Uint8ClampedArray([200,100,50,0, 200,100,50,255]);
          return Array.from(P.resample({w: 2, h: 1, data: d}, {sx: 0, sy: 0, sw: 2, sh: 1}, 1, 1));
        """)
        self.assertEqual(got, [100, 50, 25, 255])

    def test_a_fractional_crop_and_enlarging_stay_in_range(self):
        got = page("""
          const d = new Uint8ClampedArray(3 * 3 * 4).map((_, i) => i % 4 === 3 ? 255 : (i * 37) % 256);
          const a = P.resample({w: 3, h: 3, data: d}, {sx: 0.25, sy: 0.5, sw: 2.5, sh: 2.25}, 7, 5);
          const b = P.resample({w: 3, h: 3, data: d}, {sx: 0.25, sy: 0.5, sw: 2.5, sh: 2.25}, 7, 5);
          return {same: a.every((v, i) => v === b[i]), n: a.length, opaque: a.filter((_, i) => i % 4 === 3).every((v) => v === 255)};
        """)
        self.assertEqual(got, {"same": True, "n": 7 * 5 * 4, "opaque": True})

    def test_exif_orientations_turn_the_picture_upright(self):
        # A 3×2 picture whose pixels are numbered 0..5 in the red channel, row by row:
        #   0 1 2
        #   3 4 5
        got = page("""
          const d = new Uint8ClampedArray(6 * 4).map((_, i) => i % 4 === 0 ? i / 4 : 255);
          const out = {};
          for (let o = 1; o <= 8; o++) {
            const r = P.orient({w: 3, h: 2, data: d}, o);
            out[o] = [r.w, r.h, Array.from(r.data).filter((_, i) => i % 4 === 0)];
          }
          return out;
        """)
        self.assertEqual(got["1"], [3, 2, [0, 1, 2, 3, 4, 5]])
        self.assertEqual(got["2"], [3, 2, [2, 1, 0, 5, 4, 3]])   # mirrored
        self.assertEqual(got["3"], [3, 2, [5, 4, 3, 2, 1, 0]])   # upside down
        self.assertEqual(got["4"], [3, 2, [3, 4, 5, 0, 1, 2]])   # mirrored upside down
        self.assertEqual(got["5"], [2, 3, [0, 3, 1, 4, 2, 5]])   # transposed
        self.assertEqual(got["6"], [2, 3, [3, 0, 4, 1, 5, 2]])   # turned 90° clockwise
        self.assertEqual(got["7"], [2, 3, [5, 2, 4, 1, 3, 0]])   # transversed
        self.assertEqual(got["8"], [2, 3, [2, 5, 1, 4, 0, 3]])   # turned 90° counter-clockwise

    def test_the_icon_png_reads_back_as_the_same_pixels(self):
        got = page("""
          const d = new Uint8ClampedArray(40 * 40 * 4).map((_, i) => (i * 7919) % 256);
          return {png: Array.from(P.png(40, 40, d)), px: Array.from(d)};
        """)
        w, h, rgba = unpng(bytes(got["png"]))
        self.assertEqual((w, h), (40, 40))
        self.assertEqual(rgba, bytes(got["px"]))

    def test_a_big_picture_spans_several_stored_blocks(self):
        got = page("""
          const d = new Uint8ClampedArray(200 * 120 * 4).map((_, i) => i % 251);
          return {png: Array.from(P.png(200, 120, d)), px: Array.from(d)};
        """)
        self.assertEqual(unpng(bytes(got["png"]))[2], bytes(got["px"]))


if __name__ == "__main__":
    unittest.main()

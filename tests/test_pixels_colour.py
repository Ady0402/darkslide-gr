"""web/pixels.js reads a JPEG itself only when its numbers are already sRGB; a Display P3
(iPhone) or Adobe RGB JPEG goes to the browser, which converts it as the page shows it."""
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const ctx = { window: {}, Uint8ClampedArray, Uint8Array, Uint32Array, Math, String, Object, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
console.log(JSON.stringify(process.argv.slice(2).map((f) => ctx.window.DarkslidePixels.srgbJpeg(new Uint8Array(fs.readFileSync(f))))));
"""

SRGB = [(0.4361, 0.2225, 0.0139), (0.3851, 0.7169, 0.0971), (0.1431, 0.0606, 0.7141)]
P3 = [(0.5151, 0.2412, -0.0011), (0.2920, 0.6922, 0.0419), (0.1571, 0.0666, 0.7841)]
ADOBE = [(0.6097, 0.3111, 0.0195), (0.2053, 0.6257, 0.0609), (0.1492, 0.0632, 0.7446)]


def icc(space, primaries=None):
    """A minimal ICC profile: the header's colour space and, for RGB, the three primaries."""
    tags = list(zip((b"rXYZ", b"gXYZ", b"bXYZ"), primaries or []))
    table, data = b"", b""
    base = 128 + 4 + 12 * len(tags)
    for sig, xyz in tags:
        body = b"XYZ \0\0\0\0" + b"".join(struct.pack(">i", round(v * 65536)) for v in xyz)
        table += sig + struct.pack(">II", base + len(data), len(body))
        data += body
    head = bytearray(128)
    head[12:16], head[16:20], head[36:40] = b"mntr", space, b"acsp"
    out = bytes(head) + struct.pack(">I", len(tags)) + table + data
    return struct.pack(">I", len(out)) + out[4:]


def jpeg(profile=None, chunks=1):
    """SOI, the profile in APP2 ICC_PROFILE segments (split in `chunks`), then a scan."""
    out = b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    if profile:
        step = -(-len(profile) // chunks)
        pieces = [profile[i:i + step] for i in range(0, len(profile), step)]
        for n, piece in reversed(list(enumerate(pieces, 1))):  # out of order on purpose
            body = b"ICC_PROFILE\0" + bytes([n, len(pieces)]) + piece
            out += b"\xff\xe2" + struct.pack(">H", len(body) + 2) + body
    return out + b"\xff\xda\x00\x02\xff\xd9"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SrgbJpeg(unittest.TestCase):
    def check(self, cases):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, data in enumerate(cases.values()):
                p = Path(tmp) / ("%d.jpg" % i)
                p.write_bytes(data)
                paths.append(str(p))
            out = subprocess.run(["node", "-e", HARNESS, str(APP / "web" / "pixels.js"), *paths],
                                 check=True, capture_output=True, text=True)
        return dict(zip(cases, json.loads(out.stdout)))

    def test_which_jpegs_are_read_here(self):
        got = self.check({
            "no profile": jpeg(),
            "sRGB": jpeg(icc(b"RGB ", SRGB)),
            "sRGB in 3 segments": jpeg(icc(b"RGB ", SRGB), chunks=3),
            "grey": jpeg(icc(b"GRAY")),
            "Display P3": jpeg(icc(b"RGB ", P3)),
            "Adobe RGB": jpeg(icc(b"RGB ", ADOBE)),
            "RGB without primaries": jpeg(icc(b"RGB ")),
            "CMYK": jpeg(icc(b"CMYK")),
        })
        self.assertEqual(got, {
            "no profile": True, "sRGB": True, "sRGB in 3 segments": True, "grey": True,
            "Display P3": False, "Adobe RGB": False, "RGB without primaries": False, "CMYK": False,
        })


if __name__ == "__main__":
    unittest.main()

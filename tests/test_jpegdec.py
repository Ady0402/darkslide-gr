"""web/jpegdec.js decodes JPEG with integer arithmetic only, so a picture's pixels, and the
icon and shutdown picture made from them, are the same in every browser. Run with node."""
import hashlib
import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
PICTURE = APP / "tests" / "fixtures" / "shutdown_gradient.jpg"
# SHA-256 of PICTURE's RGBA as jpegdec.js decodes it. A change here changes the icon and the
# shutdown picture made from every JPEG, and so the firmware: only on purpose.
PICTURE_RGBA_SHA256 = "5a1c816c02b6c789f525062579e2e3f0c05d170342bfb8d2d93e72fe431e1742"

HARNESS = r"""
const fs = require("fs"), vm = require("vm"), crypto = require("crypto");
const ctx = { window: {}, Uint8Array, Uint8ClampedArray, Int16Array, Int32Array, Uint16Array, Uint32Array };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const out = [];
for (const file of process.argv.slice(2)) {
  try {
    const r = ctx.window.DarkslideJpegDecode.decode(new Uint8Array(fs.readFileSync(file)));
    out.push({ w: r.w, h: r.h, orientation: r.orientation,
               sha256: crypto.createHash("sha256").update(Buffer.from(r.data.buffer, r.data.byteOffset, r.data.length)).digest("hex") });
  } catch (e) { out.push({ error: String(e.message) }); }
}
console.log(JSON.stringify(out));
"""


def decode(*paths):
    out = subprocess.run(["node", "-e", HARNESS, str(APP / "web" / "jpegdec.js")] + [str(p) for p in paths],
                         check=True, capture_output=True)
    return json.loads(out.stdout)


def with_exif_orientation(jpeg, value, big_endian):
    """The JPEG with an APP1 Exif segment holding only the orientation tag."""
    e = ">" if big_endian else "<"
    tiff = (b"MM" if big_endian else b"II") + struct.pack(e + "HI", 42, 8)
    tiff += struct.pack(e + "H", 1) + struct.pack(e + "HHI", 0x0112, 3, 1) + struct.pack(e + "HH", value, 0) + struct.pack(e + "I", 0)
    body = b"Exif\0\0" + tiff
    return jpeg[:2] + b"\xFF\xE1" + struct.pack(">H", len(body) + 2) + body + jpeg[2:]


@unittest.skipUnless(shutil.which("node"), "needs node to run web/jpegdec.js")
class JpegDecode(unittest.TestCase):
    def test_the_fixture_decodes_to_the_pinned_pixels(self):
        got = decode(PICTURE, PICTURE)
        self.assertEqual(got[0], {"w": 720, "h": 480, "orientation": 1, "sha256": PICTURE_RGBA_SHA256})
        self.assertEqual(got[0], got[1])

    def test_exif_orientation_is_read_not_applied(self):
        import tempfile
        raw = PICTURE.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for value, big in ((6, True), (8, False), (3, False)):
                path = Path(tmp) / ("o%d.jpg" % value)
                path.write_bytes(with_exif_orientation(raw, value, big))
                files.append(path)
            got = decode(*files)
        self.assertEqual([g["orientation"] for g in got], [6, 8, 3])
        self.assertTrue(all(g["sha256"] == PICTURE_RGBA_SHA256 and (g["w"], g["h"]) == (720, 480) for g in got))

    def test_what_it_cannot_read_throws_so_the_page_falls_back(self):
        import tempfile
        raw = PICTURE.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            cut = Path(tmp) / "cut.jpg"
            cut.write_bytes(raw[:len(raw) // 2])
            png = Path(tmp) / "not.jpg"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
            got = decode(cut, png)
        self.assertTrue(all("error" in g and g["error"].startswith("JPEG decode") for g in got), got)


if __name__ == "__main__":
    unittest.main()

import io
import os
import unittest
import zipfile
from pathlib import Path

from darkslide import fwzip


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


class Unwrap(unittest.TestCase):
    def test_plain_bin_passes_through(self):
        self.assertEqual(fwzip.unwrap(b"firmware", "fwdc239b.bin"), (b"firmware", "fwdc239b.bin"))

    def test_takes_firmware_out_of_zip(self):
        z = make_zip([("readme.txt", b"x"), ("gr3_v210/FWDC239B.BIN", b"firmware")])
        self.assertEqual(fwzip.unwrap(z, "gr3_v210.zip"), (b"firmware", "FWDC239B.BIN"))

    def test_zip_without_firmware(self):
        with self.assertRaises(fwzip.ZipError):
            fwzip.unwrap(make_zip([("other.bin", b"x")]), "a.zip")

    def test_zip_with_two_firmwares(self):
        with self.assertRaises(fwzip.ZipError):
            fwzip.unwrap(make_zip([("a/fwdc239b.bin", b"1"), ("b/fwdc239b.bin", b"2")]), "a.zip")

    def test_broken_zip(self):
        z = make_zip([("fwdc239b.bin", b"firmware" * 100)])
        with self.assertRaises(fwzip.ZipError):
            fwzip.unwrap(z[: len(z) // 2], "a.zip")

    def test_oversized_member(self):
        old = fwzip.MAX_MEMBER
        fwzip.MAX_MEMBER = 10
        try:
            with self.assertRaises(fwzip.ZipError):
                fwzip.unwrap(make_zip([("fwdc239b.bin", b"x" * 11)]), "a.zip")
        finally:
            fwzip.MAX_MEMBER = old


OFFICIAL = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))


@unittest.skipUnless(OFFICIAL.exists(), "official firmware not available on this machine")
class RealZip(unittest.TestCase):
    def test_official_inside_zip_is_identified(self):
        from darkslide import template as tpl
        from darkslide.identify import identify
        raw = OFFICIAL.read_bytes()
        data, name = fwzip.unwrap(make_zip([("fwdc239b.bin", raw)]), "gr3_v210.zip")
        self.assertEqual(data, raw)
        t = tpl.load(Path(__file__).resolve().parents[1] / "templates" / "gr3_v210.json")
        self.assertEqual(identify(data, name, t, [])["kind"], "official")


if __name__ == "__main__":
    unittest.main()

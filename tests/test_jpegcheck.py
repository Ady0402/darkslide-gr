import unittest
from pathlib import Path

from darkslide import jpegcheck

GOOD = (Path(__file__).parent / "fixtures" / "shutdown_gradient.jpg").read_bytes()


def scan_start(data):
    i = data.index(b"\xff\xda")
    return i + 2 + int.from_bytes(data[i + 2:i + 4], "big")


class JpegDecodeCheck(unittest.TestCase):
    def test_fixture_decodes_to_the_end(self):
        self.assertEqual(jpegcheck.check(GOOD)["mcus"], 1350)

    def rejects(self, data):
        with self.assertRaises(jpegcheck.JpegCheckError):
            jpegcheck.check(data)

    def test_truncated_scan(self):
        self.rejects(GOOD[:-200] + b"\xff\xd9")

    def test_trailing_bytes_inside_scan(self):
        self.rejects(GOOD[:-2] + b"\x55" * 16 + b"\xff\xd9")

    def test_restart_marker_without_interval(self):
        s = scan_start(GOOD) + 40
        self.rejects(GOOD[:s] + b"\xff\xd0" + GOOD[s:])

    def test_restart_interval_segment(self):
        dri = b"\xff\xdd\x00\x04\x00\x10"
        i = GOOD.index(b"\xff\xda")
        self.rejects(GOOD[:i] + dri + GOOD[i:])

    def test_garbage_scan(self):
        s = scan_start(GOOD)
        self.rejects(GOOD[:s] + bytes(range(1, 255)) * 4 + b"\xff\xd9")

    def test_wrong_size(self):
        i = GOOD.index(b"\xff\xc0")
        bad = bytearray(GOOD)
        bad[i + 7:i + 9] = (640).to_bytes(2, "big")
        self.rejects(bytes(bad))


if __name__ == "__main__":
    unittest.main()

"""An installed film tone's own still checks are silenced; Standard's stay the only ones.

Camera finding (GR III HDF, 2026-10-19): the same LUT in Bleach Bypass (factory key,
contrast and highlight contrast +4) came out about one stop brighter than in Cross
Process (factory 0) because Bleach Bypass's own checks still pushed its +4 values
after Standard's. See darkslide/film_own_checks.py."""

import os
import unittest
from pathlib import Path

from darkslide import film_inplace_cache, film_own_checks, film_standard_proxy, fwread

OFFICIAL = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))


@unittest.skipUnless(OFFICIAL.exists(), "official firmware not available on this machine")
class OwnChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        u = fwread.unpack(OFFICIAL.read_bytes())
        cls.raw = bytes(u if isinstance(u, (bytes, bytearray)) else u[0])
        p = fwread.Payload(cls.raw)
        cls.read = staticmethod(lambda a, n: cls.raw[p.off(a):p.off(a) + n])
        cls.rows = film_own_checks.scan(cls.read)

    def test_standard_checks_are_the_proxy_ones(self):
        found = sorted(r["at"] - (28 if r["set"] == 0 else 40) for r in self.rows if r["tone"] == 11)
        self.assertEqual(found, sorted(film_standard_proxy.ACTIVE))

    def test_counts_per_tone_and_set(self):
        for slot, tone in film_own_checks.TONES.items():
            words = film_own_checks.changes(self.read, [slot])
            self.assertEqual(len(words), 3 * film_own_checks.EXPECTED[tone], slot)
            for at, old, new in words:
                self.assertEqual(old & 0xFFFFF000, 0xE3530000)
                self.assertEqual(new, (old & 0xFFFFF000) | (0x8FF if (old & 0xF00) else 0xFF))
        self.assertEqual(len(film_own_checks.changes(self.read, [8, 9, 10, 11])), 87)

    def test_unshared_adjustments_keep_their_checks(self):
        # Bleach Bypass toning, HDR strength, Cross Process preset: Standard has no such adjustment.
        silenced = {at for at, _, _ in film_own_checks.changes(self.read, [8, 9, 10, 11])}
        kept = [r for r in self.rows if r["tone"] in (18, 19, 20, 21) and r["at"] not in silenced]
        self.assertEqual(sorted((r["tone"], r["set"]) for r in kept),
                         sorted((t, s) for t, n in ((18, 1), (19, 1), (20, 2), (21, 1)) for s in range(3) for _ in range(n)))

    def test_plan_contains_exactly_the_installed_tones(self):
        profiles = {"portra400": __import__("darkslide.film_profiles", fromlist=["x"]).load_profile("portra400")}
        plan = film_inplace_cache.plan_offline(self.raw, [dict(kind="film", slot=8, film="portra400")], profiles)
        touched = {w.address for w in plan["windows"]}
        mine = {at for at, _, _ in film_own_checks.changes(self.read, [8])}
        others = {at for at, _, _ in film_own_checks.changes(self.read, [9, 10, 11])}
        self.assertTrue(mine <= touched)
        self.assertFalse(others & touched)


if __name__ == "__main__":
    unittest.main()

"""Pinned facts for film_own_checks on both GR III 2.10 and GR IIIx 1.60.

- The 87 silenced words (address, original, replacement) for all four film slots are
  pinned by digest, so a change to the scanner or its fingerprinting shows up here
  rather than only through the writer's own counts.
- Movie-mode checks (the same prologue with "cmp r2,#1") are never touched.
- Each film slot's plan contains its own tone's words and none of the other slots'.
"""

import hashlib
import os
import struct
import unittest
from pathlib import Path

from darkslide import (film_inplace_cache, film_own_checks as O, film_profiles, fwread,
                       gr3x_inplace, models)

GR3 = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))
GR3X = Path(os.environ.get("DARKSLIDE_IIIX_BIN", "/nonexistent/fwdc243b.bin"))

# sha256 over sorted (address, original word, replacement word) packed as <III, slots 8-11.
ALL_FOUR_SHA256 = "532d346a06aa60096f26a2778d218297c7c377f1df43345c3bb5413d8d0695d3"
ALL_FOUR_SPAN = (0x5325BB40, 0x532699DC)
PER_SLOT = {8: 27, 9: 27, 10: 6, 11: 27}
MOVIE_CHECKS = 221
FILMS = {8: "portra400", 9: "gold200", 10: "5219", 11: "c200"}


def load(path, model):
    if not path.exists():
        raise unittest.SkipTest("official firmware not available on this machine")
    raw = bytes(fwread.unpack(path.read_bytes()))
    p = fwread.Payload(raw) if model == models.GR3 else fwread.Payload(raw, models.layout(model))
    return raw, (lambda a, n: raw[p.off(a):p.off(a) + n])


class Pinned:
    model = None
    path = None

    @classmethod
    def setUpClass(cls):
        cls.raw, read = load(cls.path, cls.model)
        cls.read = staticmethod(read)

    def test_all_four_words_pinned(self):
        words = O.changes(self.read, [8, 9, 10, 11])
        self.assertEqual(len(words), 87)
        digest = hashlib.sha256(b"".join(struct.pack("<III", *w) for w in sorted(words))).hexdigest()
        self.assertEqual(digest, ALL_FOUR_SHA256)
        self.assertEqual((min(a for a, _, _ in words), max(a for a, _, _ in words)), ALL_FOUR_SPAN)
        for at, old, new in words:
            self.assertEqual(struct.unpack("<I", self.read(at, 4))[0], old)
            self.assertEqual(old & 0xFFFFF000, 0xE3530000)        # cmp r3,#imm
            self.assertEqual(new & 0xFFFFF000, 0xE3530000)
            self.assertIn(new & 0xFFF, (0xFF, 0x8FF))             # 0xFF, or 0xFF<<16 in set 0

    def test_movie_checks_untouched(self):
        start, end = O.RANGE
        words = struct.unpack("<%dI" % ((end - start) // 4), self.read(start, end - start))
        movie = [start + 4 * i for i in range(len(words) - 3)
                 if words[i:i + 3] == (0xE5903004, 0xE5D32044, 0xE3520001)]
        self.assertEqual(len(movie), MOVIE_CHECKS)
        silenced = {at for at, _, _ in O.changes(self.read, [8, 9, 10, 11])}
        for m in movie:
            self.assertFalse(silenced & set(range(m, m + 52, 4)), hex(m))

    def test_each_slot_plan_has_only_its_own_tone(self):
        everyone = {s: {at for at, _, _ in O.changes(self.read, [s])} for s in FILMS}
        for slot, film in FILMS.items():
            with self.subTest(slot=slot):
                self.assertEqual(len(everyone[slot]), PER_SLOT[slot])
                profiles = {film: film_profiles.load_profile(film, self.model.id)}
                plan = self.plan(self.raw, [dict(kind="film", slot=slot, film=film)], profiles)
                touched = {w.address + i for w in plan["windows"] for i in range(0, len(w.replacement), 4)}
                self.assertTrue(everyone[slot] <= touched)
                for other in FILMS:
                    if other != slot:
                        self.assertFalse(everyone[other] & touched, other)


class GR3_210(Pinned, unittest.TestCase):
    model = models.GR3
    path = GR3
    plan = staticmethod(film_inplace_cache.plan_offline)


class GR3X_160(Pinned, unittest.TestCase):
    model = models.GR3X
    path = GR3X
    plan = staticmethod(gr3x_inplace.plan_offline)


if __name__ == "__main__":
    unittest.main()

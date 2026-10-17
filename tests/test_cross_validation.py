"""Synthetic Cross development checks; no original camera program is executed."""
import copy
import hashlib
import struct
import sys
import unittest
from darkslide import film_cross_validation as cross
from darkslide.film_requests import FilmRequestError, available
from test_film_writer import fixture, profile, overlay


def original():
    cells, read = fixture()
    for i, b in enumerate(struct.pack('<I', cross.STD)):
        cells[cross.RECORDS + 84 + i] = b
    return cells, read


class CrossValidationTests(unittest.TestCase):
    def setUp(self):
        self.edit = dict(kind='film', slot=11, film='testfilm')
        self.profile = profile()

    def test_fixed_banks_and_same_code_page(self):
        cells, read = original()
        before = dict(cells)
        result = cross.plan(read, self.edit, self.profile)
        got = overlay(read, result['windows'])
        self.assertEqual(cells, before)
        self.assertEqual(result['selector'], 2)
        self.assertEqual((result['area_a_used'], result['area_b_used']), (24, 356))
        for key in ('record', 'matrix', 'post_table'):
            self.assertEqual(result[key] & ~4095, cross.CODE_PAGE)
        self.assertEqual(got(cross.LIB, 48), read(cross.LIB, 48))
        for c, address in enumerate(result['curve_pointers']):
            self.assertEqual(struct.unpack('<256H', got(address, 512)), tuple(self.profile['curves_u14'][c]))
        self.assertFalse(result['shared_pointer_writes'])
        self.assertFalse(result['old_private_arena_used'])
        self.assertFalse(available())

    def test_every_other_record_and_bank_preserved(self):
        _, read = original()
        result = cross.plan(read, self.edit, self.profile)
        got = overlay(read, result['windows'])
        for i in range(26):
            if i != 21:
                self.assertEqual(got(cross.RECORDS + i * 4, 4), read(cross.RECORDS + i * 4, 4))
        for i in range(12):
            if i not in (3, 4, 5):
                self.assertEqual(got(0x53EF1000 + i * 512, 512), read(0x53EF1000 + i * 512, 512))
        for address, size in ((cross.STD, 84), (0x55037634, 132), (0x536DD4B8, 88),
                              (cross.FILL + 24, 168), (cross.POST + 356, 312)):
            self.assertEqual(got(address, size), read(address, size))
        for address in range(0x53D36400, 0x53D37400, 512):
            self.assertEqual(got(address, 512), read(address, 512))

    def test_record_matrix_and_initialized_tail(self):
        _, read = original()
        p = profile(bias=7)
        result = cross.plan(read, self.edit, p)
        got = overlay(read, result['windows'])
        record = got(result['record'], 84)
        self.assertEqual(record[:4], read(cross.STD, 4))
        self.assertEqual(record[8:68], read(cross.STD + 8, 60))
        self.assertEqual(record[68:], b'abcdefghijklmnop')
        self.assertEqual(int.from_bytes(record[4:8], 'little'), result['matrix'])
        self.assertEqual(struct.unpack('<9h', got(result['matrix'], 18)), (8192, 0, 0, 0, 8192, 0, 0, 0, 8192))
        self.assertEqual(int.from_bytes(got(cross.RECORDS + 84, 4), 'little'), result['record'])

    def test_other_slots_and_invalid_profile_rejected_before_read(self):
        def forbidden(*args):
            raise AssertionError('must not read original')
        for slot in (8, 9, 10, True, 12):
            with self.assertRaises(FilmRequestError):
                cross.plan(forbidden, dict(self.edit, slot=slot), self.profile)
        bad = copy.deepcopy(self.profile)
        bad['curves_u14'][0][0] = True
        with self.assertRaises(FilmRequestError):
            cross.plan(forbidden, self.edit, bad)
        with self.assertRaises(FilmRequestError):
            cross.plan_official_payload(b'not the official image', self.edit, self.profile)

    def test_original_guards_and_short_reads_rejected(self):
        for address in (0x536EF618, 0x536DD450, 0x536DD454, 0x536E4774,
                        0x536DD464, cross.RECORDS + 84, 0x536EB214):
            cells, read = original()
            cells[address] ^= 1
            before = dict(cells)
            with self.assertRaises(ValueError):
                cross.plan(read, self.edit, self.profile)
            self.assertEqual(cells, before)
        with self.assertRaises(FilmRequestError):
            cross.plan(lambda a, n: b'', self.edit, self.profile)

    def test_independent_checker_and_every_window_mutation(self):
        from pathlib import Path
        tools = str(Path(__file__).resolve().parents[2] / 'tools')
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from verify_cross_validation import verify_plan
        except ImportError:
            self.skipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")
        _, read = original()
        result = cross.plan(read, self.edit, self.profile)
        checked = verify_plan(read, result, self.profile)
        self.assertTrue(checked['passed'])
        for i, window in enumerate(result['windows']):
            bad = copy.deepcopy(result)
            bad['windows'] = list(bad['windows'])
            replacement = bytes([window.replacement[0] ^ 1]) + window.replacement[1:]
            bad['windows'][i] = type(window)(window.address, window.expected, replacement)
            with self.assertRaises(ValueError):
                verify_plan(read, bad, self.profile)
        bad = dict(result, shared_pointer_writes=True)
        with self.assertRaises(ValueError):
            verify_plan(read, bad, self.profile)


if __name__ == '__main__':
    unittest.main()

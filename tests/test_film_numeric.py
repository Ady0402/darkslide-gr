import copy
import math
import unittest
from darkslide import film_numeric as f


class FilmNumeric(unittest.TestCase):
    def test_table_domains_are_different(self):
        self.assertEqual(f.validate_base_q([16384] * 256)[-1], 16384)
        with self.assertRaises(f.FilmNumericError):
            f.validate_film_curves([[16384] * 256 for _ in range(3)])
        self.assertEqual(f.validate_film_curves([[16383] * 256 for _ in range(3)])[2][-1], 16383)

    def test_no_missing_q_fallback(self):
        for bad in (None, [], [0] * 255, [0] * 257, tuple([0] * 256)):
            with self.subTest(value=type(bad).__name__), self.assertRaises(f.FilmNumericError):
                f.validate_base_q(bad)

    def test_strict_numeric_rejection(self):
        for bad in (True, False, 1.0, -1, 16385, math.nan, math.inf, '1'):
            row = [0] * 256
            row[128] = bad
            with self.subTest(value=bad), self.assertRaises(f.FilmNumericError):
                f.validate_base_q(row)
            with self.subTest(curve=bad), self.assertRaises(f.FilmNumericError):
                f.validate_film_curves([row, [0] * 256, [0] * 256])

    def test_curves_shape_and_snapshot(self):
        curves = [[0] * 256 for _ in range(3)]
        snapshot = f.validate_film_curves(curves)
        curves[0][0] = 12
        self.assertEqual(snapshot[0][0], 0)
        for bad in (None, curves[:2], curves + [curves[0]], [curves[0], [], curves[2]]):
            with self.assertRaises(f.FilmNumericError):
                f.validate_film_curves(bad)

    def test_q13_round_and_diagonal_repair(self):
        matrix = [[1.0, 0.5 / 8192, -0.5 / 8192],
                  [0.5 / 8192, 1.0 - 1 / 8192, 0.5 / 8192],
                  [0.0, 0.0, 1.0]]
        before = copy.deepcopy(matrix)
        self.assertEqual(f.quantize_matrix_q13(matrix),
                         ((8192, 1, -1), (1, 8190, 1), (0, 0, 8192)))
        self.assertEqual(matrix, before)

    def test_q13_white_and_storage(self):
        bads = ([[1.1, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[4, -3, 0], [0, 1, 0], [0, 0, 1]],
                [[True, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[math.nan, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[math.inf, 0, 0], [0, 1, 0], [0, 0, 1]],
                [[3.99999, -2.99999, 0], [0, 1, 0], [0, 0, 1]])
        for matrix in bads:
            with self.subTest(matrix=matrix), self.assertRaises(f.FilmNumericError):
                f.quantize_matrix_q13(matrix)
        for matrix in ([[8192, 0, 0], [0, 8192, 0], [0, 0, 8191]],
                       [[8192, False, 0], [0, 8192, 0], [0, 0, 8192]],
                       [[32768, -24576, 0], [0, 8192, 0], [0, 0, 8192]]):
            with self.assertRaises(f.FilmNumericError):
                f.validate_matrix_q13(matrix)

    def test_u10_transition_and_domain(self):
        for x, expected in ((0, 0), (15, 0), (16, 1), (31, 1), (16368, 1023), (16383, 1023)):
            self.assertEqual(f.quantize_srgb_output(x), expected)
        for bad in (True, 16.0, -1, 16384, math.nan):
            with self.assertRaises(f.FilmNumericError):
                f.quantize_srgb_output(bad)

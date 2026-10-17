"""Development NumPy fitter checks; skipped in stdlib-only App environments."""
import importlib.util
import unittest
from darkslide._vendor.gr3_fit_numeric import fit_curve


@unittest.skipUnless(importlib.util.find_spec("numpy"),"development NumPy unavailable")
class CurveFitTests(unittest.TestCase):
    def test_complete_monotone_identity_fit_and_determinism(self):
        g=list(range(0,16384,64));t=[v/16384 for v in g];w=[100]*256
        first=fit_curve(g,t,w)
        self.assertEqual(len(first),256)
        self.assertEqual(first,fit_curve(g,t,w))
        self.assertTrue(all(type(v) is int and 0<=v<=16383 for v in first))
        self.assertTrue(all(b>=a for a,b in zip(first,first[1:])))
        self.assertLessEqual(max(abs(a-b) for a,b in zip(first,g)),1)

    def test_invalid_samples_fail_before_solver(self):
        for args in (([True],[0],[1]),([0],[float("nan")],[1]),([0],[0],[-1]),([0],[2],[1]),([0,1],[0],[1]),([0],[0],[0])):
            with self.assertRaises(ValueError):fit_curve(*args)

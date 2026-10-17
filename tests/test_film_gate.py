"""The factory-range gate in front of every film write."""
import os
import unittest
from pathlib import Path
from unittest import mock

from darkslide import factory_envelope, film_four_apply, film_gate, film_profiles, film_requests, film_writer, fwread

OFFICIAL = os.environ.get("DARKSLIDE_OFFICIAL_BIN")
GOOD = dict(model_id=factory_envelope.MODEL_ID, look_min=-5792, look_max=9578, look_row_abs_max=19776,
            post_min=-8191, post_max=8191, post_col_abs_max=8191, curve_step_max=194, curve_step_min=-58,
            curve_first_min=0, curve_first_max=1920, curve_last_min=12694, curve_last_max=16383)


def env_with(**change):
    env = dict(GOOD)
    env.update(change)
    return {k: v for k, v in env.items() if v is not None}


class EnvelopeShape(unittest.TestCase):
    def check(self, env):
        with mock.patch.object(factory_envelope, "factory_envelope_from_payload", return_value=env):
            return film_gate.checked_envelope(b"payload")

    def test_a_well_formed_range_passes(self):
        self.assertEqual(self.check(env_with())["look_max"], 9578)

    def test_missing_or_odd_bounds_are_refused(self):
        for bad in (dict(look_max=None), dict(curve_step_min=None), dict(post_col_abs_max=True),
                    dict(curve_first_max=None), dict(curve_last_min=None),
                    dict(look_min=-5792.0), dict(look_max="9578"), dict(model_id="other")):
            with self.assertRaises(film_requests.FilmRequestError, msg=bad):
                self.check(env_with(**bad))
        for empty in ({}, None, []):
            with self.assertRaises(film_requests.FilmRequestError):
                self.check(empty)

    def test_bounds_in_the_wrong_order_are_refused(self):
        for bad in (dict(look_min=9578, look_max=-5792), dict(curve_step_min=194, curve_step_max=-58),
                    dict(post_min=8191, post_max=-8191), dict(look_row_abs_max=0),
                    dict(curve_first_max=13000), dict(curve_last_min=12694, curve_last_max=12000)):
            with self.assertRaises(film_requests.FilmRequestError, msg=bad):
                self.check(env_with(**bad))

    def test_a_payload_that_is_not_the_official_one_is_refused(self):
        for raw in (b"", b"\0" * 64, "text", None):
            with self.assertRaises(film_requests.FilmRequestError):
                film_gate.checked_envelope(raw)


class Profiles(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(factory_envelope, "factory_envelope_from_payload", return_value=env_with())
        patch.start()
        self.addCleanup(patch.stop)
        self.profile = film_profiles.load_profile("portra400")

    def test_bundled_film_inside_the_range_passes(self):
        film_gate.require_inside(b"payload", {"portra400": self.profile})

    def test_a_profile_outside_the_range_stops_the_write(self):
        bad = dict(self.profile, look_matrix_q13=[[9999, 0, 0], [0, 8192, 0], [0, 0, 8192]])
        with self.assertRaises(film_requests.FilmRequestError) as ctx:
            film_gate.require_inside(b"payload", {"user_lut_000000000000": bad})
        self.assertIn("超出", str(ctx.exception))

    def test_curve_start_or_end_outside_the_range_stops_the_write(self):
        # Curves are judged as the camera stores them (33-knot rebuild); linear ramps rebuild exactly.
        ramp = lambda first, last: [round(first + (last - first) * i / 255) for i in range(256)]
        for first, last, ok in ((1920, 16383, True), (1921, 16383, False), (0, 12694, True), (0, 12693, False)):
            prof = dict(self.profile, curves_u14=[ramp(first, last)] * 3)
            if ok:
                film_gate.require_inside(b"payload", {"user_lut_000000000001": prof})
            else:
                with self.assertRaises(film_requests.FilmRequestError, msg=(first, last)) as ctx:
                    film_gate.require_inside(b"payload", {"user_lut_000000000001": prof})
                self.assertIn("曲线", str(ctx.exception))

    def test_incomplete_profile_or_nothing_to_check_is_refused(self):
        with self.assertRaises(film_requests.FilmRequestError):
            film_gate.require_inside(b"payload", {"x": {"look_matrix_q13": [[8192, 0, 0]]}})
        for nothing in ({}, None, []):
            with self.assertRaises(film_requests.FilmRequestError):
                film_gate.require_inside(b"payload", nothing)


class BothWritersUseTheGate(unittest.TestCase):
    FOUR = [dict(kind="film", slot=s, film="gold200") for s in (8, 9, 10, 11)]

    def setUp(self):
        # Only synthetic helper tests: never reopen the App generation route.
        for module in (film_writer, film_four_apply):
            on = mock.patch.object(module, "available", return_value=True)
            on.start()
            self.addCleanup(on.stop)

    def test_four_layout_stops_before_planning(self):
        with mock.patch.object(film_four_apply, "require_inside", side_effect=film_requests.FilmRequestError("gate")) as gate, \
                mock.patch.object(film_four_apply.four, "plan_official_payload") as plan:
            with self.assertRaises(film_requests.FilmRequestError):
                film_four_apply.apply(b"\0" * 64, self.FOUR)
            gate.assert_called_once()
            plan.assert_not_called()

    def test_legacy_layout_stops_before_planning(self):
        with mock.patch.object(film_gate, "require_inside", side_effect=film_requests.FilmRequestError("gate")) as gate, \
                mock.patch.object(film_writer, "_plan_resolved") as plan:
            with self.assertRaises(film_requests.FilmRequestError):
                film_writer.apply(b"\0" * 64, self.FOUR[:1])
            gate.assert_called_once()
            plan.assert_not_called()


class OneSnapshot(unittest.TestCase):
    """The profiles the gate checked are the very ones planned: read once, copied once."""
    FOUR = [dict(kind="film", slot=s, film="gold200") for s in (8, 9, 10, 11)]

    def setUp(self):
        # Only synthetic helper tests: never reopen the App generation route.
        for module in (film_writer, film_four_apply):
            on = mock.patch.object(module, "available", return_value=True)
            on.start()
            self.addCleanup(on.stop)
        good = film_profiles.load_profile("gold200")
        self.good = {"gold200": good}
        self.bad = {"gold200": dict(good, look_matrix_q13=[[99999, 0, 0], [0, 8192, 0], [0, 0, 8192]])}

    def run_case(self, module, plan_name, films):
        seen = {}
        reads = mock.Mock(side_effect=[self.good, self.bad])

        def gate(payload, profiles):
            seen["gate"] = profiles

        def plan(raw, requests, profiles):
            seen["plan"] = profiles
            raise film_requests.FilmRequestError("stop after planning")

        with mock.patch.object(module, "resolve_profiles", reads), \
                mock.patch.object(film_gate if module is film_writer else module, "require_inside", side_effect=gate), \
                mock.patch.object(*plan_name, side_effect=plan):
            with self.assertRaises(film_requests.FilmRequestError):
                module.apply(b"\0" * 64, films)
        self.assertEqual(reads.call_count, 1, "profiles are read once")
        self.assertIs(seen["gate"], seen["plan"], "gate and plan get the same snapshot")
        self.assertEqual(seen["plan"]["gold200"]["look_matrix_q13"], self.good["gold200"]["look_matrix_q13"])
        self.assertIsNot(seen["plan"]["gold200"], self.good["gold200"], "a defensive copy, not the caller's dict")

    def test_legacy_writer(self):
        self.run_case(film_writer, (film_writer, "_plan_resolved"), self.FOUR[:1])

    def test_four_film_layout(self):
        seen = {}
        reads = mock.Mock(side_effect=[self.good, self.bad])

        def gate(payload, profiles):
            seen["gate"] = profiles

        def plan(raw, requests, profiles):
            seen["plan"] = profiles
            raise ValueError("stop after planning")

        with mock.patch.object(film_four_apply, "resolve_profiles", reads), \
                mock.patch.object(film_four_apply, "require_inside", side_effect=gate), \
                mock.patch.object(film_four_apply.four, "plan_official_payload", side_effect=plan):
            with self.assertRaises(film_requests.FilmRequestError):
                film_four_apply.apply(b"\0" * 64, self.FOUR)
        self.assertEqual(reads.call_count, 1)
        self.assertIs(seen["gate"], seen["plan"])
        self.assertIsNot(seen["plan"]["gold200"], self.good["gold200"])


@unittest.skipUnless(OFFICIAL, "needs DARKSLIDE_OFFICIAL_BIN")
class RealPayload(unittest.TestCase):
    def test_range_from_the_payload_matches_the_range_from_the_file(self):
        raw = Path(OFFICIAL).read_bytes()
        payload = fwread.unpack(raw)
        from_payload = film_gate.checked_envelope(payload)
        from_file = factory_envelope.factory_envelope(OFFICIAL)
        for name in film_gate.FIELDS:
            self.assertEqual(from_payload[name], from_file[name], name)

    def test_all_bundled_films_pass_on_the_real_payload(self):
        payload = fwread.unpack(Path(OFFICIAL).read_bytes())
        for ident in film_profiles.ready_profile_ids():
            film_gate.require_inside(payload, {ident: film_profiles.load_profile(ident)})


if __name__ == "__main__":
    unittest.main()

"""Generation wiring of the four-film layout (four_curve_v1).

Synthetic only: no official firmware is decoded and no modified firmware is built
here; the real-firmware plan and readback are covered by the four-film tests.
"""
import unittest
from collections import namedtuple
from unittest import mock

from darkslide import compositor, composite_verify, film_four_apply, film_requests, film_writer, generate, rescue_gate
from darkslide import template as tpl

Window = namedtuple("Window", "address expected replacement")
FOUR = [dict(kind="film", slot=s, film="gold200") for s in (8, 9, 10, 11)]


class StubPayload:
    BASE = 0x1000

    def __init__(self, raw, *args, **kwargs):
        self.raw = raw

    def off(self, va):
        return va - self.BASE


class FourApply(unittest.TestCase):
    def setUp(self):
        on = mock.patch.object(film_four_apply, "available", return_value=True)
        on.start()
        self.addCleanup(on.stop)
        # synthetic payloads: the factory-range gate itself is covered in test_film_gate
        gate = mock.patch.object(film_four_apply, "require_inside")
        gate.start()
        self.addCleanup(gate.stop)

    def test_all_four_are_required_before_any_planning(self):
        with mock.patch.object(film_four_apply.four, "plan_official_payload") as plan:
            for films in (FOUR[:3], FOUR[1:], FOUR[:1]):
                with self.assertRaises(film_requests.FilmRequestError) as ctx:
                    film_four_apply.apply(b"\0" * 64, films)
                self.assertIn("四个位置", str(ctx.exception))
            plan.assert_not_called()
        self.assertEqual(film_four_apply.apply(b"x", []), (b"x", []))

    def test_closed_when_writing_is_off(self):
        with mock.patch.object(film_four_apply, "available", return_value=False):
            with self.assertRaises(film_requests.FilmRequestError):
                film_four_apply.apply(b"\0" * 64, FOUR)

    def _apply(self, windows, raw=None):
        raw = raw or bytes(range(64)) * 2
        with mock.patch.object(film_four_apply.four, "plan_official_payload", return_value=dict(windows=windows)) as plan, \
                mock.patch("darkslide.fwread.Payload", StubPayload):
            out = film_four_apply.apply(raw, FOUR)
        return raw, out, plan

    def test_windows_become_payload_offsets(self):
        raw = bytes(range(64)) * 2
        w = [Window(0x1004, raw[4:8], b"ABCD"), Window(0x1010, raw[16:18], b"xy")]
        _, (changed, changes), plan = self._apply(w, raw)
        self.assertEqual(changed[4:8], b"ABCD")
        self.assertEqual(changed[16:18], b"xy")
        self.assertEqual(changed[:4] + changed[8:16] + changed[18:], raw[:4] + raw[8:16] + raw[18:])
        self.assertEqual(changes, [dict(offset=4, length=4, kind="film"), dict(offset=16, length=2, kind="film")])
        profiles = plan.call_args[0][2]
        self.assertEqual(set(profiles), {"gold200"}, "built-in data is loaded by the writer itself")

    def test_bad_windows_are_refused(self):
        raw = bytes(range(64)) * 2
        cases = {
            "原字变化": [Window(0x1004, b"????", b"ABCD")],
            "别名冲突": [Window(0x1004, raw[4:8], b"ABCD"), Window(0x1006, raw[6:8], b"zz")],
            "越界": [Window(0x1000 + len(raw) - 2, raw[-2:], b"zz")],
        }
        for word, windows in cases.items():
            with self.assertRaises(film_requests.FilmRequestError) as ctx:
                self._apply(windows, raw)
            self.assertIn(word, str(ctx.exception))

    def test_supplied_data_only_for_selected_user_luts(self):
        with mock.patch.object(film_four_apply.four, "plan_official_payload") as plan:
            with self.assertRaisesRegex(film_requests.FilmRequestError, "不能覆盖内置胶片"):
                film_four_apply.apply(b"\0" * 64, FOUR, profiles={"gold200": {}})
            plan.assert_not_called()


class LayoutSelection(unittest.TestCase):
    def test_compositor_picks_the_writer_by_layout(self):
        self.assertEqual(film_requests.FILM_LAYOUT, "four_curve_v1")
        base = b"\0" * 64
        with mock.patch.object(film_requests, "available", return_value=True), \
                mock.patch.object(compositor.builder, "_template"), \
                mock.patch.object(compositor.builder, "INPUT_SIZE", 3), mock.patch.object(compositor.builder, "INPUT_SHA", compositor.builder._sha(b"off")), \
                mock.patch.object(compositor.builder, "PAYLOAD_SHA", compositor.builder._sha(base)), \
                mock.patch.object(compositor.builder, "_decode", return_value=(base, [], 0, b"")), \
                mock.patch.object(compositor.builder, "_pack_payload", side_effect=lambda *a: dict(output=a[5])), \
                mock.patch.object(film_four_apply, "apply", return_value=(b"\1" * 4 + base[4:], [dict(offset=0, length=4, kind="film")])) as four, \
                mock.patch.object(film_writer, "apply", return_value=(b"\2" * 4 + base[4:], [dict(offset=0, length=4, kind="film")])) as legacy:
            compositor.build_composite(b"off", FOUR, {})
            self.assertEqual((four.call_count, legacy.call_count), (1, 0))
            compositor.build_composite(b"off", FOUR, {}, film_layout="legacy_arena_v1")
            self.assertEqual((four.call_count, legacy.call_count), (1, 1))
            with self.assertRaises(compositor.CompositeError):
                compositor.build_composite(b"off", FOUR, {}, film_layout="whatever")

    def test_generate_rejects_legacy_four_layout_before_build_or_check(self):
        project = dict(id="p_000000000000", title="t", changes={str(s): dict(film="gold200") for s in (8, 9, 10, 11)})
        with mock.patch.object(film_requests, "available", return_value=True), \
                mock.patch.object(compositor, "build_composite", side_effect=AssertionError("no producer")) as build, \
                mock.patch.object(composite_verify, "verify", side_effect=AssertionError("no full verifier")) as check:
            with self.assertRaisesRegex(generate.GenerateError, "尚未开放"):
                generate.run(None, project, tpl.load(), b"official")
            build.assert_not_called(); check.assert_not_called()


if __name__ == "__main__":
    unittest.main()

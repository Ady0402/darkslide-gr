import unittest
import hashlib
import json
from unittest.mock import patch
from darkslide import film_writer,film_requests
from test_film_writer import fixture,profile,overlay


class UserLutWriterTests(unittest.TestCase):
    def test_custom_data_reaches_the_same_fixed_layout(self):
        ident="user_lut_test01";p=profile(ident,5)
        edits=[dict(kind="film",slot=s,film=ident) for s in (8,9,10,11)]
        resolved=film_writer.resolve_profiles(edits,{ident:p})
        _,read=fixture()
        result=film_writer.plan(read,edits,resolved)
        got=overlay(read,result["windows"])
        self.assertEqual(result["selected_slots"],(8,9,10,11))
        for record in result["records"]:
            self.assertEqual(record["film"],ident)
            for channel,address in enumerate(record["curves"]):
                expected=b"".join(v.to_bytes(2,"little") for v in p["curves_u14"][channel])
                self.assertEqual(got(address,512),expected)
        p["curves_u14"][0][0]=999
        self.assertNotEqual(resolved[ident]["curves_u14"][0][0],999)

    def test_custom_namespace_cannot_replace_bundled_or_unused_data(self):
        edits=[dict(kind="film",slot=8,film="user_lut_test01")]
        for supplied in ([],{}, {"portra400":profile("portra400")}, {"user_lut_other":profile("user_lut_other")}):
            with self.assertRaises(film_requests.FilmRequestError):film_writer.resolve_profiles(edits,supplied)
        bad=profile("user_lut_test01");bad["curves_u14"][0][0]=16384
        with self.assertRaises(film_requests.FilmRequestError):film_writer.resolve_profiles(edits,{"user_lut_test01":bad})

    def test_mixed_bundled_and_custom_requests(self):
        ident="user_lut_test01";p=profile(ident)
        edits=[dict(kind="film",slot=8,film=ident),dict(kind="film",slot=9,film="portra400")]
        data=film_writer.resolve_profiles(edits,{ident:p})
        self.assertEqual(set(data),{ident,"portra400"})
        self.assertEqual(data["portra400"]["id"],"portra400")

    def test_off_gate_prevents_custom_full_generation(self):
        edit=dict(kind="film",slot=8,film="user_lut_test01")
        with patch.object(film_writer,"plan_official_payload",side_effect=AssertionError("must not plan full export")):
            with self.assertRaises(film_requests.FilmRequestError):film_writer.apply(b"test",[edit],profiles={edit["film"]:profile(edit["film"])})
        raw=b"unchanged"
        self.assertIs(film_writer.apply(raw,[],profiles={})[0],raw)

    def test_independent_custom_and_mixed_readback(self):
        from darkslide import film_verify
        ident="user_lut_test01";p=profile(ident,4)
        edits=[dict(kind="film",slot=8,film=ident),dict(kind="film",slot=10,film="portra400")]
        _,read=fixture()
        source=film_writer.resolve_profiles(edits,{ident:p})
        expected=film_verify.derive_expected(read,edits,film_verify.resolve_profiles(edits,{ident:p}))
        result=film_writer.plan(read,edits,source)
        checked=film_verify.readback_windows(read,overlay(read,result["windows"]),expected)
        self.assertTrue(checked.passed,checked.checks)

    def test_generation_rejects_custom_profile_before_writer_and_verifier(self):
        from darkslide import generate, compositor, composite_verify, template
        ident="user_lut_test01"; original={ident:profile(ident,3)}
        project=dict(id="unit",title="unit",changes={"8":{"film":ident}})
        with patch.object(film_requests,"available",return_value=True), \
                patch.object(compositor,"build_composite",side_effect=AssertionError("no producer")) as build, \
                patch.object(composite_verify,"verify",side_effect=AssertionError("no full verifier")) as check:
            with self.assertRaisesRegex(generate.GenerateError,"尚未开放"):
                generate.run(None,project,template.load(),b"toy",film_profiles=original)
            build.assert_not_called(); check.assert_not_called()
        self.assertEqual(original[ident]["curves_u14"][0][0],3)

    def test_readonly_prepare_freezes_profile_before_plan_and_independent_check(self):
        from darkslide import inplace_generation as prepare
        ident="user_lut_test01"; original={ident:profile(ident,3)}
        project=dict(id="unit",changes={"8":{"film":ident}})
        seen={}
        def plan(raw, requests, profiles):
            seen['planned'] = profiles
            original[ident]['curves_u14'][0][0] = 999
            self.assertEqual(profiles[ident]['curves_u14'][0][0],3)
            return dict(layout=prepare.LAYOUT,decoded_growth_bytes=0,full_image_created=False,
                        production_integration_allowed=False,storage_approved=False,windows=())
        def check(raw, windows, changes, profiles, **kwargs):
            self.assertEqual(profiles[ident]['curves_u14'][0][0],3)
            self.assertIsNot(profiles,seen['planned'])
            self.assertEqual(kwargs,dict(planned_layout=prepare.LAYOUT,checked_layout=prepare.LAYOUT))
            return dict(layout=prepare.LAYOUT,selected_slots=[8],data_verified=True,
                shared_bytes_match_reference=True,complete_window_coverage_verified=True,
                shared_code_verified=False,production_approved=False)
        with patch.object(prepare.film_inplace_cache,'plan_offline',side_effect=plan) as planner, \
                patch.object(prepare.film_inplace_integrity,'verify_project',side_effect=check) as reader:
            result=prepare.prepare(b'toy',project,film_profiles=original)
            planner.assert_called_once(); reader.assert_called_once()
        frozen=result['profiles'][ident]
        self.assertEqual(frozen['curves_u14'][0][0],3)
        digest=hashlib.sha256(json.dumps(frozen,sort_keys=True,ensure_ascii=False,
                    allow_nan=False,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(result['profile_sha256'],{ident:digest})
        self.assertFalse(result['full_image_created'])

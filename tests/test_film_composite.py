"""Composition contract with a tiny synthetic payload, no camera image."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from darkslide import compositor, edit_core, film_requests, film_writer, generate, template


class FilmComposition(unittest.TestCase):
    def test_disabled_rejected_before_decode(self):
        with patch.object(edit_core,"_decode",side_effect=AssertionError("must not decode")):
            with self.assertRaises(compositor.CompositeError):
                compositor.build_composite(b"",[dict(kind="film",slot=8,film="testfilm")],template.load())

    def _build(self, bad=False, overlap=False):
        raw=b"synthetic input";base=b"\0"*64
        film=bytearray(base);film[8:12]=b"film"
        regular=bytearray(base);regular[8 if overlap else 4:12 if overlap else 8]=b"name"
        if bad:film[20]=1
        edits=[dict(kind="film",slot=8,film="testfilm"),dict(kind="name",slot=8,string_id=275,text="Test")]
        with ExitStack() as stack:
            stack.enter_context(patch.object(film_requests,"available",return_value=True))
            stack.enter_context(patch.object(edit_core,"INPUT_SIZE",len(raw)))
            stack.enter_context(patch.object(edit_core,"INPUT_SHA",edit_core._sha(raw)))
            stack.enter_context(patch.object(edit_core,"PAYLOAD_SHA",edit_core._sha(base)))
            stack.enter_context(patch.object(edit_core,"_validate_edits"))
            stack.enter_context(patch.object(edit_core,"_decode",return_value=(base,[],0,b"")))
            stack.enter_context(patch.object(edit_core,"apply_edits",return_value=(bytes(regular),[dict(offset=8 if overlap else 4,length=4)])))
            stack.enter_context(patch.object(film_writer,"apply",return_value=(bytes(film),[dict(offset=8,length=4,kind="film")])))
            pack=stack.enter_context(patch.object(edit_core,"_pack_payload",side_effect=lambda official,before,frames,stop,footer,merged,declared:dict(output=merged)))
            result=compositor.build_composite(raw,edits,template.load(),film_layout="legacy_arena_v1")
            self.assertEqual(pack.call_count,1)
            return result

    def test_merges_independent_deltas_and_packs_once(self):
        got=self._build()
        self.assertEqual(got["output"][4:12],b"namefilm")
        self.assertEqual(got["features"],["film","name"])

    def test_overlap_and_undeclared_mutation_are_rejected(self):
        for bad,overlap in ((True,False),(False,True)):
            with self.assertRaises(compositor.CompositeError):self._build(bad,overlap)

    def test_edit_summary_helpers_keep_legacy_nonfilm_contract(self):
        t=template.load();changes={"8":{"film":"portra400","name":"New Tone"}}
        self.assertEqual([e["kind"] for e in generate.edits_from_changes(None,"synthetic",changes,t)],["name"])
        self.assertEqual([e["what"] for e in generate.summarize(changes,t)],["预设名"])
        with self.assertRaises(generate.GenerateError):
            generate.edits_from_changes(None,"synthetic",{"8":{"film":"../x"}},t)

    def test_project_gate_rejects_film_and_mixed_requests_before_production(self):
        for edit in ({"film":"portra400"},{"film":"portra400","name":"New Tone"}):
            with self.subTest(edit=edit), patch.object(compositor,"build_composite",side_effect=AssertionError("no producer")) as build, \
                    patch.object(generate,"edits_from_changes",side_effect=AssertionError("no legacy helper")) as edits:
                with self.assertRaisesRegex(generate.GenerateError,"尚未开放"):
                    generate.run(None,dict(id="synthetic",changes={"8":edit}),template.load(),b"")
                build.assert_not_called(); edits.assert_not_called()
        self.assertTrue(film_requests.status()["available"])  # v29 App route only; legacy stays closed


if __name__=="__main__":unittest.main()

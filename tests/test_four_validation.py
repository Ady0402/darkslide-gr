"""Four distinct synthetic looks and independent replacement boundaries."""
import copy
import struct
import sys
import unittest
from darkslide import film_four_validation as four
from darkslide.film_requests import FilmRequestError
from test_film_writer import fixture as legacy_fixture, profile, overlay


def fixture():
    cells, read = legacy_fixture()
    at = 0x536E87C4
    word = four._branch(at, 0x536EEDF0, link=True)
    cells.update((at+i,b) for i,b in enumerate(struct.pack('<I',word)))
    cells.update((0x536DD024+i,b) for i,b in enumerate(struct.pack("<I",0xE5C4100E)))
    cells.update((0x536E87C8+i,b) for i,b in enumerate(struct.pack("<I",0xE51B3044)))
    return cells, read


def inputs():
    edits = [dict(kind='film', slot=8+i, film='film'+str(i)) for i in range(4)]
    profiles = {e['film']: profile(e['film'], 10*i) for i,e in enumerate(edits)}
    return edits, profiles


class FourValidationTests(unittest.TestCase):
    def test_four_distinct_bindings_and_aliases(self):
        cells, read = fixture()
        before = dict(cells)
        edits, profiles = inputs()
        result = four.plan(read, edits, profiles)
        got = overlay(read, result['windows'])
        self.assertEqual(cells, before)
        self.assertEqual(result['selected_slots'], (8,9,10,11))
        self.assertEqual(len({r['record'] for r in result['records']}), 4)
        self.assertLessEqual(result['area_a_used'], 192)
        self.assertLessEqual(result['area_b_used'], 668)
        self.assertFalse(result['shared_library_pointer_writes'])
        self.assertFalse(result['old_private_arena_used'])
        for row, edit in zip(result['records'], edits):
            self.assertEqual(int.from_bytes(got(row['record']+4,4),'little'),row['matrix'])
            for index in four.SLOT_INFO[row['slot']][1]:
                self.assertEqual(int.from_bytes(got(four.PRIMARY+4*index,4),'little'),row['record'])
            for channel, at in enumerate(row['knots']):
                knots=struct.unpack('<33H',got(at,66))
                rebuilt=four.expand_knots(knots)
                source=profiles[edit['film']]['curves_u14'][channel]
                self.assertEqual(max(abs(a-b) for a,b in zip(rebuilt,source)),
                                 result['compression_errors'][row['slot']-8]['channels'][channel]['max_abs_u14'])

    def test_replace_one_preserves_other_three_data_and_code(self):
        _,read=fixture();edits,profiles=inputs()
        first=four.plan(read,edits,profiles); a=overlay(read,first['windows'])
        for changed in range(4):
            new=copy.deepcopy(profiles); ident=edits[changed]['film']
            new[ident]=profile(ident,30+changed)
            new[ident]['look_matrix_q13']=[[8191,1,0],[0,8192,0],[0,0,8192]]
            new[ident]['post_matrix_q512']=[[511,1,0],[0,512,0],[0,0,512]]
            second=four.plan(read,edits,new); b=overlay(read,second['windows'])
            self.assertEqual(first['records'],second['records'])
            for i,row in enumerate(first['records']):
                if i != changed:
                    for at,size in [(row['record'],84),(row['matrix'],18)]+[(k,66) for k in row['knots']]:
                        self.assertEqual(a(at,size),b(at,size))
                    self.assertEqual(a(first['post_table']+i*24,24),b(first['post_table']+i*24,24))
            for at,n in [(four.FILL,first['area_a_used']),(four.POST,first['area_b_used']),(first['lookup'],80)]:
                self.assertEqual(a(at,n),b(at,n))

    def test_original_library_standard_and_unused_regions_preserved(self):
        _,read=fixture();edits,profiles=inputs();result=four.plan(read,edits,profiles);got=overlay(read,result['windows'])
        for at,n in [(four.LIB,48),(four.STANDARD,84),(0x55037634,132),(0x536DD4B8,88),
                     (four.FILL+result['area_a_used'],192-result['area_a_used']),
                     (four.POST+result['area_b_used'],668-result['area_b_used'])]:
            self.assertEqual(got(at,n),read(at,n))
        for i in (0,1,2,6,7,8,9,10,11):
            self.assertEqual(got(0x53ef1000+i*512,512),read(0x53ef1000+i*512,512))
        changed={i for slot in four.SLOTS for i in four.SLOT_INFO[slot][1]}
        for i in set(range(26))-changed:
            self.assertEqual(got(four.PRIMARY+4*i,4),read(four.PRIMARY+4*i,4))
        for at in range(0x53D36400,0x53D37400,512):
            self.assertEqual(got(at,512),read(at,512))

    def test_compression_is_reported_and_non_monotone_supported(self):
        curve=[i*60 for i in range(256)]
        knots,metrics=four.fit_knots(curve)
        self.assertTrue(metrics['lossless'])
        self.assertEqual(four.expand_knots(knots),tuple(curve))
        jagged=[0 if i%2 else 16383 for i in range(256)]
        _,metrics=four.fit_knots(jagged)
        self.assertFalse(metrics['lossless'])
        self.assertGreater(metrics['max_abs_u14'],0)
        for bad in ([False]*256,[16384]*256,[0]*255):
            with self.assertRaises(FilmRequestError):four.fit_knots(bad)

    def test_request_and_original_rejections(self):
        _,read=fixture();edits,profiles=inputs()
        with self.assertRaises(FilmRequestError):four.plan(read,edits[:3],profiles)
        with self.assertRaises(FilmRequestError):four.plan(read,edits,{})
        with self.assertRaises(FilmRequestError):four.plan_official_payload(b'not official',edits,profiles)
        for at in (0x536E87C4,0x536DD450,0x536DBE98):
            cells, read=fixture()
            if at==0x536E87C4:
                original=four._branch(at,0x536EEDF0,link=True)
                cells.update((at+i,b) for i,b in enumerate(struct.pack('<I',original)))
            cells[at]^=1
            with self.assertRaises(ValueError):four.plan(read,edits,profiles)

    def test_independent_four_readback_and_window_mutations(self):
        from pathlib import Path
        tools = str(Path(__file__).resolve().parents[2] / 'tools')
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from verify_four_validation import verify_plan
        except ImportError:
            self.skipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")
        _,read=fixture();edits,profiles=inputs();result=four.plan(read,edits,profiles)
        self.assertTrue(verify_plan(read,result,edits,profiles)['passed'])
        for i,w in enumerate(result['windows']):
            bad=copy.deepcopy(result);bad['windows']=list(bad['windows'])
            value=bytes([w.replacement[0]^1])+w.replacement[1:]
            bad['windows'][i]=type(w)(w.address,w.expected,value)
            with self.assertRaises(ValueError):verify_plan(read,bad,edits,profiles)
        with self.assertRaises(ValueError):verify_plan(read,result,edits[:3],profiles)

    def test_independent_metadata_rejects_old_scratch_and_type_forgery(self):
        from pathlib import Path
        tools = str(Path(__file__).resolve().parents[2] / 'tools')
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from verify_four_validation import verify_plan
        except ImportError:
            self.skipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")
        _, read = fixture(); edits, profiles = inputs()
        result = four.plan(read, edits, profiles)
        self.assertEqual((len(result['windows']), result['area_a_used'], result['area_b_used']),
                         (49, 176, 600))
        self.assertEqual(sum(len(w.replacement) for w in result['windows']), 2276)
        for key, value in (('gamma_scratch_offset', 0xA08), ('expansion', 0x536EF884),
                           ('curve_storage', 'expanded_scratch'), ('expanded_scratch_bytes', False),
                           ('point_sampler', 0x536EF66C), ('curve_composer', 0x536EF894),
                           ('area_a_used', 76), ('area_b_used', 500),
                           ('same_gamma_concurrent_calls_verified', True)):
            bad = copy.deepcopy(result); bad[key] = value
            with self.assertRaises(ValueError, msg=key):
                verify_plan(read, bad, edits, profiles)


if __name__=='__main__':unittest.main()

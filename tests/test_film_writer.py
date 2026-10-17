"""Sparse synthetic originals only: never construct a real modified firmware."""
import struct
import unittest
from unittest.mock import patch
from darkslide import film_writer as writer, film_requests as requests
from darkslide.film_profiles import validate_profile
from darkslide.film_patch_plan import _branch


def profile(ident="testfilm", bias=0):
    return dict(schema=1,id=ident,model="GR III",firmware="2.10",
                look_matrix_q13=[[8192,0,0],[0,8192,0],[0,0,8192]],
                curves_u14=[[i*60+bias+c for i in range(256)] for c in range(3)],
                post_matrix_q512=[[512,0,0],[0,512,0],[0,0,512]])


def fixture():
    cells={}
    def put(at,value):
        cells.update((at+i,b) for i,b in enumerate(value))
    def word(at,value):put(at,struct.pack("<I",value))
    for i in range(12):
        word(0x55037604+4*i,0x53ef1000+i*512)
        put(0x53ef1000+i*512,struct.pack("<256H",*[i*256+j for j in range(256)]))
    for i in range(26):
        at=0x55018000+84*i;matrix=0x53dc3000+20*i
        word(0x55018d94+4*i,at)
        put(at,bytes(84));word(at+4,matrix)
        put(matrix,struct.pack("<9h",8192,0,0,0,8192,0,0,0,8192))
    put(0x5501900c,bytes(range(84)))
    put(0x53dc27a4,b"abcdefghijklmnop")
    guards={0x536eb0dc:0xe302c7a4,0x536eb0e0:0xe345c3dc,
            0x536eb160:0xe89c000f,0x536eb164:0xe59f6098,
            0x536eb168:0xe59f5098,0x536eb16c:0xe59f4098,
            0x536eb170:0xe59fe098,0x536eb174:0xe59f7098,
            0x536eb178:0xe887000f,0x536eb214:0x55019050,
            0x536dd464:0xe89daff8,0x536ef618:0xeddf0be0,
            0x536dd450:0x159632d0,
            0x536dd454:_branch(0x536dd454,0x536dd4b8,condition=0),
            0x536e4774:_branch(0x536e4774,0x536e4720,link=True)}
    for at,old,new in writer.HDR_FIXES+writer.RETRO_FIXES:guards[at]=old
    for at,value in guards.items():word(at,value)
    return cells,lambda at,n:bytes(cells.get(at+i,0) for i in range(n))


def overlay(read,windows):
    def result(at,n):
        data=bytearray(read(at,n))
        for w in windows:
            a=max(at,w.address);b=min(at+n,w.address+len(w.replacement))
            if a<b:data[a-at:b-at]=w.replacement[a-w.address:b-w.address]
        return bytes(data)
    return result


class SelectiveFilmTests(unittest.TestCase):
    def test_independent_readback_of_each_subset(self):
        from darkslide import film_verify
        _,read=fixture()
        for mask in range(16):
            edits=[dict(kind="film",slot=8+i,film="testfilm") for i in range(4) if mask&(1<<i)]
            expected=film_verify.derive_expected(read,edits,{"testfilm":profile()})
            result=writer.plan(read,edits,{"testfilm":profile()})
            checked=film_verify.readback_windows(read,overlay(read,result["windows"]),expected)
            self.assertTrue(checked.passed,checked.checks)

    def test_all_subsets_preserve_unselected_data(self):
        cells,read=fixture();original=dict(cells)
        for mask in range(16):
            slots=[8+i for i in range(4) if mask&(1<<i)]
            edits=[dict(kind="film",slot=s,film="testfilm") for s in slots]
            result=writer.plan(read,edits,{"testfilm":profile()})
            self.assertEqual(cells,original)
            got=overlay(read,result["windows"])
            self.assertEqual(result["selected_slots"],tuple(slots))
            self.assertFalse(result["complete_image_created"])
            selected_indices={i for s in slots for i in writer.SLOT_INFO[s][1]}
            for i in range(26):
                at=0x55018d94+4*i
                if i not in selected_indices:self.assertEqual(got(at,4),read(at,4))
            for i in range(12):
                if not (10 in slots and i<3 or 11 in slots and 3<=i<6):
                    at=0x53ef1000+512*i
                    self.assertEqual(got(at,512),read(at,512))
            for at,old,new in writer.HDR_FIXES+writer.RETRO_FIXES:
                active=10 in slots if (at,old,new) in writer.HDR_FIXES else 9 in slots
                self.assertEqual(int.from_bytes(got(at,4),"little"),new if active else old)
            for row in result["records"]:
                clone=got(row["record"],84)
                self.assertEqual(clone[:4],read(0x5501900c,4))
                self.assertEqual(clone[8:68],read(0x55019014,60))
                self.assertEqual(clone[68:],b"abcdefghijklmnop")
                self.assertEqual(int.from_bytes(clone[4:8],"little"),row["matrix"])
                for c,at in enumerate(row["curves"]):
                    self.assertEqual(struct.unpack("<256H",got(at,512)),tuple(profile()["curves_u14"][c]))
            if slots:
                self.assertLessEqual(result["arena_used"],4096)
                self.assertEqual(len(got(writer.FILL,100)),100)
            else:self.assertEqual(result["windows"],())

    def test_identity_catalogue_contract_and_duplicate_films(self):
        _,read=fixture()
        for i in range(16):
            ident="film%d"%i
            result=writer.plan(read,[dict(kind="film",slot=s,film=ident) for s in (8,9,10,11)],{ident:profile(ident,i)})
            self.assertEqual([r["film"] for r in result["records"]],[ident]*4)

    def test_fail_closed_and_source_immutable(self):
        cells,read=fixture();edit=[dict(kind="film",slot=8,film="testfilm")]
        for at in (0x53d36400,0x536dd450,0x536eb214):
            saved=dict(cells);cells[at]=255;bad=dict(cells)
            with self.assertRaises(ValueError):writer.plan(read,edit,{"testfilm":profile()})
            self.assertEqual(cells,bad);cells.clear();cells.update(saved)
        with self.assertRaises(requests.FilmRequestError):writer.plan(read,edit,{})
        with self.assertRaises(requests.FilmRequestError):writer.plan(lambda a,n:b"",edit,{"testfilm":profile()})
        for key,value in (("curves_u14",[[True]*256]*3),("look_matrix_q13",[[8192.0,0,0]]*3),("post_matrix_q512",[[513,0,0]]*3)):
            bad=profile();bad[key]=value
            with self.assertRaises(requests.FilmRequestError):validate_profile(bad,"testfilm")

    def test_off_gate_and_no_selection_are_early(self):
        self.assertFalse(requests.available())
        with patch.object(writer,"plan_official_payload",side_effect=AssertionError("must not plan")):
            with self.assertRaises(requests.FilmRequestError):writer.apply(b"synthetic",[dict(kind="film",slot=8,film="testfilm")])
            raw=b"unchanged";self.assertIs(writer.apply(raw,[])[0],raw)
        self.assertEqual(writer.plan(None,[],None)["windows"],())

    def test_post_accumulator_bound_is_rejected_without_clipping(self):
        p=profile();p["post_matrix_q512"]=[[8191,-7679,0],[0,512,0],[0,0,512]]
        self.assertEqual(validate_profile(p,"testfilm")["post_matrix_q512"],p["post_matrix_q512"])
        for matrix in ([[8192,-7680,0],[0,512,0],[0,0,512]],[[32767,-32768,513]]*3):
            p["post_matrix_q512"]=matrix
            with self.assertRaises(requests.FilmRequestError):validate_profile(p,"testfilm")

    def test_request_rejections_and_sorted_copy(self):
        edit=dict(kind="film",slot=11,film="portra400")
        self.assertEqual(requests.validate_batch([edit,dict(edit,slot=8)])[0]["slot"],8)
        for bad in (dict(edit,slot=True),dict(edit,slot=7),dict(edit,film="../a"),dict(edit,extra=1)):
            with self.assertRaises(requests.FilmRequestError):requests.validate_request(bad)
        with self.assertRaises(requests.FilmRequestError):requests.validate_batch([edit,edit])
        self.assertEqual(requests.from_changes({"8":{"film":"portra400"},"9":{"film":"portra400"}})[1]["slot"],9)
        p=profile();clean=validate_profile(p,"testfilm");clean["curves_u14"][0][0]=99
        self.assertEqual(p["curves_u14"][0][0],0)


if __name__=="__main__":unittest.main()

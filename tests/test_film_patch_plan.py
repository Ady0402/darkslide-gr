import struct
import unittest
from darkslide.film_patch_plan import PlanImage,HOOK_RANGES,plan_four_mode_hooks,LIB,_branch
from darkslide.film_arm_assemble import assemble,_text

def fixture():
    cells={}
    def word(address,value):
        cells.update({address+i:b for i,b in enumerate(struct.pack("<I",value))})
    for i in range(12):word(LIB+4*i,0x53ef1000+512*i)
    for at,value in [(0x536dd464,0xe89daff8),(0x536ef618,0xeddf0be0),
                     (0x536dd450,0x159632d0),(0x536dd454,_branch(0x536dd454,0x536dd4b8,condition=0)),
                     (0x536e4774,_branch(0x536e4774,0x536e4720,link=True))]:word(at,value)
    def read(a,n):return bytes(cells.get(a+i,0) for i in range(n))
    return cells,read

def posts():
    return {0x55019060:[[512,0,0],[0,512,0],[0,0,512]],
            0x5501939c:[[512,0,0],[0,512,0],[0,0,512]],
            0x55019108:[[512,0,0],[0,512,0],[0,0,512]],
            0x55018f94:[[512,0,0],[0,512,0],[0,0,512]]}

class FilmPatchPlanTests(unittest.TestCase):
    def test_compiler_branch_golden_and_rejections(self):
        raw=assemble("mov r0, #1\nbl abs(0x2000)",0x1000)
        self.assertEqual(raw,struct.pack("<II",0xe3a00001,_branch(0x1004,0x2000,link=True)))
        for source,base in [(".include x",0),("b abs(0xffffffff)",0),("mov r0,#0",True)]:
            with self.assertRaises(ValueError):assemble(source,base)
        with self.assertRaises(ValueError):_text(b"bad")
    def test_four_mode_partial_plan(self):
        cells,read=fixture();before=dict(cells)
        image=PlanImage(read,HOOK_RANGES)
        result=plan_four_mode_hooks(image,posts())
        self.assertEqual(cells,before)
        self.assertEqual(len(result["windows"]),8)
        self.assertEqual(result["curve_points"],256)
        self.assertNotIn("vivid",result["modes"])
        self.assertFalse(result["getter_replaced"])
        self.assertFalse(result["complete_image_created"])
        self.assertLessEqual(result["area_a_used"],192)
        self.assertLessEqual(result["area_b_used"],668)
        self.assertFalse(result["records_and_curves_written"])
        with self.assertRaises(ValueError):image.write(0x536ef61c,b"0000")
    def test_input_and_guard_failure_atomic(self):
        cells,read=fixture();cells[0x536dd450]=0
        image=PlanImage(read,HOOK_RANGES)
        with self.assertRaises(ValueError):plan_four_mode_hooks(image,posts())
        self.assertEqual(image.windows,[])
        for value in [True,1.0,32768]:
            image=PlanImage(read,HOOK_RANGES);m=posts();m[0x55019060][0][0]=value
            with self.assertRaises(ValueError):plan_four_mode_hooks(image,m)
            self.assertEqual(image.windows,[])
    def test_non_target_records_rejected(self):
        cells,read=fixture()
        for key in [0x5501900c,0x55019534,True,1.0]:
            image=PlanImage(read,HOOK_RANGES)
            with self.assertRaises(ValueError):
                plan_four_mode_hooks(image,{key:[[512,0,0],[0,512,0],[0,0,512]]})
            self.assertEqual(image.windows,[])
    def test_overlay_bounds_and_source_change(self):
        cells={100:1,101:2,102:3,103:4}
        read=lambda a,n:bytes(cells.get(a+i,0) for i in range(n))
        image=PlanImage(read,((100,104),),max_bytes=4)
        image.write(101,b"xx")
        self.assertEqual(image.read(100,4),b"\x01xx\x04")
        with self.assertRaises(ValueError):image.write(102,b"x")
        with self.assertRaises(ValueError):image.write(104,b"x")
        with self.assertRaises(ValueError):image.read(True,2)
        cells[101]=9
        with self.assertRaises(ValueError):image.seal()
if __name__=="__main__":unittest.main()

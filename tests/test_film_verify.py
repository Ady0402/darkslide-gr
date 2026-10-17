"""Synthetic independent readback cases; never invoke a film writer or compiler."""
import itertools
import json
from pathlib import Path
import struct
import tempfile
import unittest
from darkslide.film_verify import (derive_expected,readback_windows,load_profiles,FilmReadbackError,ARENA,LIB,RECORD_TABLE,STD,BOOT_TAIL,FILL,POST)


def profile(index=0):
    return dict(schema=1,id='film_'+str(index),model='GR III',firmware='2.10',
                look_matrix_q13=[[8192-index,index,0],[0,8192+index,-index],[-index,0,8192+index]],
                post_matrix_q512=[[512-index,index,0],[0,512+index,-index],[-index,0,512+index]],
                curves_u14=[[(64*k+17*c+index)%16384 for k in range(256)] for c in range(3)])


def branch(at,to,cond=14,link=False):
    return (cond<<28)|((11 if link else 10)<<24)|(((to-at-8)//4)&0xffffff)


def half_move(reg,number,high=False):
    value=(number>>16) if high else number&65535
    return (0xe3400000 if high else 0xe3000000)|(reg<<12)|((value>>12)<<16)|(value&4095)


def fixture_code(region):
    # Explicit golden A32 words from the independent shared operand contract,
    # not from a writer/template/assembler call. Pointer/branch values are holes.
    base=region.address
    if region.role=='fill':
        stock,mode,ret=region.pointers
        words=[0xe92d0080,half_move(0,LIB+36),half_move(0,LIB+36,True),half_move(2,stock),half_move(2,stock,True),0xe89200b0,0xe88000b0,half_move(2,mode),half_move(2,mode,True),0xe5924000,0xe3540000,branch(base+44,base+96,0),0xe1540001,0x02824004,branch(base+56,base+68,0),0xe2822010,branch(base+64,base+36),0xe8940320,0xe8800320,0xe283390e,0xe3a02004,0xe5c32a98,0xe8bd0080,ret,0xe8bd0080,0xe3510015,branch(base+104,0x536DD4B8,0),branch(base+108,0x536DD458)]
    else:
        table,=region.pointers
        words=[0xe92d41f3,branch(base+4,0x536E4720,link=True),0xe59d0000,0xe59d1004,0xe5913008,half_move(4,table),half_move(4,table,True),0xe594c000,0xe35c0000,branch(base+36,base+200,0),0xe15c0003,0x12844018,branch(base+48,base+28,1),0xe2844004,0xe24dd024,0xe3a0c000,0xe790e00c,0xe1a0e68e,0xe1a0e6ce,0xe78de00c,0xe28cc004,0xe35c0024,branch(base+88,base+64,1),0xe3a05000,0xe3a06000,0xe79d7005,0xe19480f6,0xe00e0897,0xe2852004,0xe79d7002,0xe2862006,0xe19480f2,0xe02ee897,0xe2852008,0xe79d7002,0xe286200c,0xe19480f2,0xe02ee897,0xe28eec01,0xe1a0e4ce,0xe1a0e68e,0xe1a0e6ae,0xe480e004,0xe2866002,0xe3560006,branch(base+180,base+100,1),0xe285500c,0xe3550024,branch(base+192,base+96,1),0xe28dd024,0xe8bd81f3]
    return b''.join(w.to_bytes(4,'little') for w in words)


class SparseOriginal:
    def __init__(self):
        self.cells={};self.max_read=0
        for index in range(12):
            pointer=0x53EF1000+512*index
            self.put(LIB+4*index,pointer.to_bytes(4,'little'))
            self.put(pointer,bytes([index+1])*512)
        addresses={2:0x5501939C,11:STD,18:0x55018F94,19:0x55019108,20:STD,21:STD,22:0x55019174,23:0x55019608,24:0x55019534}
        for number,address in enumerate(sorted(set(addresses.values()))):
            matrix=0x53DC2000+32*number
            record=bytes((7*i+number+11)%256 for i in range(84))
            self.put(address,record[:4]+matrix.to_bytes(4,'little')+record[8:])
            self.put(matrix,struct.pack('<9h',8192,0,0,0,8192,0,0,0,8192))
        for index,address in addresses.items():self.put(RECORD_TABLE+4*index,address.to_bytes(4,'little'))
        self.put(BOOT_TAIL,bytes(range(16)))
        guardpairs=[(0x536DD464,0xe89daff8),(0x536EF618,0xeddf0be0),(0x536DD450,0x159632d0),(0x536DD454,branch(0x536DD454,0x536DD4B8,0)),(0x536E4774,branch(0x536E4774,0x536E4720,link=True)),(0x536DBEB4,0xe5d39788),(0x536DC27C,branch(0x536DC27C,0x536DC818,0)),(0x536DBEBC,0xe5d32796),(0x535131FC,branch(0x535131FC,0x53513274,0)),(0x536DBE98,0xe1ce40b0),(0x536EB0DC,0xe302c7a4),(0x536EB0E0,0xe345c3dc),(0x536EB160,0xe89c000f),(0x536EB164,0xe59f6098),(0x536EB168,0xe59f5098),(0x536EB16C,0xe59f4098),(0x536EB170,0xe59fe098),(0x536EB174,0xe59f7098),(0x536EB178,0xe887000f),(0x536EB214,0x55019050)]
        for address,word in guardpairs:self.put(address,word.to_bytes(4,'little'))
        self.put(0x536DD4B8,bytes([23])*88)
        self.put(FILL+112,bytes([37])*80);self.put(POST+204,bytes([41])*464)
    def put(self,address,data):
        self.cells.update({address+i:b for i,b in enumerate(data)})
    def read(self,address,size):
        self.max_read=max(self.max_read,size)
        return bytes(self.cells.get(address+i,0) for i in range(size))


def overlay(original,expectations):
    changed={}
    for window in expectations.data_windows:
        changed.update({window.address+i:v for i,v in enumerate(window.data)})
    for region in expectations.code_regions:
        changed.update({region.address+i:v for i,v in enumerate(fixture_code(region))})
    def read(address,size):
        return bytes(changed.get(address+i,original.cells.get(address+i,0)) for i in range(size))
    return changed,read


class FilmVerifyTests(unittest.TestCase):
    def test_all_subsets_and_same_film_slots(self):
        original=SparseOriginal();catalog={p['id']:p for p in [profile(i) for i in range(16)]}
        for mask in range(16):
            edits=[dict(kind='film',slot=slot,film='film_'+str((mask+slot)%16)) for slot in (8,9,10,11) if mask&(1<<(slot-8))]
            expectations=derive_expected(original.read,edits,catalog);changes,read=overlay(original,expectations)
            result=readback_windows(original.read,read,expectations)
            self.assertTrue(result.passed,result.checks)
            self.assertEqual(result.expected_spans,expectations.expected_spans)
            self.assertEqual(sum(len(w.data) for w in result.expected_windows),sum(b-a for a,b in expectations.expected_spans))
            self.assertLessEqual(expectations.arena_used,4096)
        edits=[dict(kind='film',slot=s,film='film_0') for s in (8,9,10,11)]
        expectations=derive_expected(original.read,edits,catalog);_,read=overlay(original,expectations)
        self.assertTrue(readback_windows(original.read,read,expectations).passed)
        self.assertLessEqual(original.max_read,512)

    def test_data_and_unclaimed_mutations_fail_closed(self):
        original=SparseOriginal();p=profile();expectations=derive_expected(original.read,[dict(kind='film',slot=8,film=p['id'])],{p['id']:p})
        for address in [ARENA,ARENA+84,ARENA+expectations.arena_used,FILL+112,POST+204,RECORD_TABLE+4*25,0x536DD4B8,0x53EF1000+3*512,STD]:
            changes,read=overlay(original,expectations)
            changes[address]=(read(address,1)[0]+1)%256
            result=readback_windows(original.read,read,expectations)
            self.assertFalse(result.passed,hex(address));self.assertEqual(result.expected_windows,())

    def test_code_operand_branch_and_pointer_mutations(self):
        original=SparseOriginal();p=profile();expectations=derive_expected(original.read,[dict(kind='film',slot=11,film=p['id'])],{p['id']:p})
        for address in [FILL+3*4,FILL+11*4,FILL+20*4,FILL+26*4,POST+4,POST+5*4,POST+26*4,POST+45*4]:
            changes,read=overlay(original,expectations);changes[address]=read(address,1)[0]^1
            result=readback_windows(original.read,read,expectations)
            self.assertFalse(result.passed,hex(address));self.assertEqual(result.expected_windows,())

    def test_balanced_r7_save_restore_and_exit_targets_fail_closed(self):
        original=SparseOriginal();p=profile()
        expected=derive_expected(original.read,[dict(kind='film',slot=11,film=p['id'])],{p['id']:p})
        region=next(c for c in expected.code_regions if c.role=='fill')
        self.assertEqual(region.size,112)
        tail=next(c for c in expected.protected_regions if c.label=='unused_fill_area')
        self.assertEqual((tail.address,tail.size),(FILL+112,80))
        valid=fixture_code(region)
        self.assertEqual(len(valid),112)
        # Remove or change the save/restore, or jump directly past a required
        # restore. These are independent operand/control-contract mutations.
        replacements=[(0,0xe1a00000),(0,0xe92d0040),(22,0xe1a00000),
                      (22,0xe8bd0040),(24,0xe1a00000),(24,0xe8bd0040),
                      (11,branch(FILL+44,FILL+100,0)),
                      (14,branch(FILL+56,FILL+92,0))]
        for index,word in replacements:
            changes,read=overlay(original,expected)
            for offset,byte in enumerate(word.to_bytes(4,'little')):changes[FILL+index*4+offset]=byte
            result=readback_windows(original.read,read,expected)
            self.assertFalse(result.passed,(index,word,result.checks))
            self.assertEqual(result.expected_windows,())
            self.assertEqual(result.expected_spans,())
        changes,read=overlay(original,expected)
        changes[FILL+112]=read(FILL+112,1)[0]^1
        self.assertFalse(readback_windows(original.read,read,expected).passed)
        # Legacy 100-byte body lacks the entry save and balanced exits.
        words=list(struct.unpack('<28I',valid))
        legacy=words[1:22]+[words[23]]+words[25:]
        changes,read=overlay(original,expected)
        for offset,byte in enumerate(struct.pack('<25I',*legacy)):changes[FILL+offset]=byte
        self.assertFalse(readback_windows(original.read,read,expected).passed)

    def test_original_zero_guard_boot_and_curve_overlap(self):
        p=profile();request=[dict(kind='film',slot=9,film=p['id'])]
        for kind in ['zero','boot','overlap','adjacent_overlap','mutable']:
            original=SparseOriginal();reader=original.read
            if kind=='zero':original.put(ARENA,b'x')
            if kind=='boot':original.put(0x536EB160,bytes(4))
            if kind=='overlap':original.put(LIB+4,original.read(LIB,4))
            if kind=='adjacent_overlap':original.put(LIB+4,(0x53EF1000+510).to_bytes(4,'little'))
            if kind=='mutable':reader=lambda address,size:bytearray(original.read(address,size))
            with self.assertRaises(FilmReadbackError):derive_expected(reader,request,{p['id']:p})

    def test_profile_requests_and_JSON_fail_closed(self):
        p=profile();original=SparseOriginal();request=[dict(kind='film',slot=8,film=p['id'])]
        for field,value in [('schema',True),('model','GR IIIx'),('firmware','1.81'),('id','wrong')]:
            bad=dict(p);bad[field]=value
            with self.assertRaises(FilmReadbackError):derive_expected(original.read,request,{p['id']:bad})
        for field,value in [('look_matrix_q13',[[True,8191,0],[0,8192,0],[0,0,8192]]),('post_matrix_q512',[[8192,0,0],[0,512,0],[0,0,512]]),('curves_u14',[[16384]*256,[0]*256,[0]*256])]:
            bad=dict(p);bad[field]=value
            with self.assertRaises(FilmReadbackError):derive_expected(original.read,request,{p['id']:bad})
        bad=dict(p);bad['post_matrix_q512']=[[32767,-32768,513]]*3
        with self.assertRaises(FilmReadbackError):derive_expected(original.read,request,{p['id']:bad})
        for edits in [[dict(kind='film',slot=True,film=p['id'])],request+request,[dict(kind='film',slot=8,film='../bad')]]:
            with self.assertRaises(FilmReadbackError):derive_expected(original.read,edits,{p['id']:p})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/(p['id']+'.json');path.write_text(json.dumps(p))
            self.assertEqual(load_profiles(request,root)[p['id']],p)
            valid=json.dumps(p)
            for text in ['{"schema":1,"schema":1}',valid[:-1]+',"bad":NaN}',valid[:-1]+',"bad":1e999}']:
                path.write_text(text)
                with self.assertRaises(FilmReadbackError):load_profiles(request,root)
            path.write_bytes(b'\xff')
            with self.assertRaises(FilmReadbackError):load_profiles(request,root)
            path.unlink()
            with self.assertRaises(FilmReadbackError):load_profiles(request,root)

    def test_source_change_detected_and_empty_no_reads(self):
        original=SparseOriginal();p=profile();expectations=derive_expected(original.read,[dict(kind='film',slot=8,film=p['id'])],{p['id']:p});_,read=overlay(original,expectations)
        original.put(ARENA,b'x')
        self.assertFalse(readback_windows(original.read,read,expectations).passed)
        def forbidden(address,n):raise AssertionError('empty edit must not read')
        empty=derive_expected(forbidden,[],{})
        self.assertEqual(empty.expected_spans,());self.assertTrue(readback_windows(forbidden,forbidden,empty).passed)

if __name__=='__main__':unittest.main()

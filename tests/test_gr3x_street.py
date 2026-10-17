"""Conditional Street route: original selector + new A32, fixtures at service calls.

No camera/MMIO; consumer is a recording stub. Identity globals are explicit
fixtures, not observations of an HDF body's active collaboration setting.
"""
import os, struct, unittest, zlib
from pathlib import Path
from darkslide import photo_recipe_extension as E, photo_recipe_extension_read as R
from darkslide import photo_recipe_candidate_verify as V, gr3x_street_read as S
try:
    import unicorn
except ImportError:
    unicorn=None

@unittest.skipUnless(os.environ.get('DARKSLIDE_GR3X_PAYLOAD'),'pinned IIIx payload required')
class StreetReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        cls.ext=E.build_fragments(cls.raw,{},shutdown_hdf=True)
        cls.jpeg=(Path(__file__).parent/'fixtures/shutdown_gradient.jpg').read_bytes()
        from darkslide.a_shutdown import apply_a_shutdown
        from darkslide.models import GR3X
        after=bytearray(apply_a_shutdown(cls.raw,cls.jpeg,GR3X.id)[0])
        for w in cls.ext['windows']:
            i=0x10870+w.address-0x53000000;after[i:i+len(w.replacement)]=w.replacement
        tail=0x10870+E.STOCK_SIZE
        after[tail:tail]=cls.ext['extension']
        struct.pack_into('<I',after,0x1086c,cls.ext['new_rtos_size'])
        cls.after=bytes(after)

    def test_independent_complete_binding_and_opt_out(self):
        for enabled in (False,True):
            ext=self.ext if enabled else E.build_fragments(self.raw,{})
            expected,body,catalog=V._binding_contract(ext['native'],(),False,enabled)
            self.assertEqual({w.address:int.from_bytes(w.replacement,'little') for w in ext['windows']},expected)
            self.assertEqual(len(expected),34 if enabled else 33)
            self.assertEqual(ext['extension'][64:catalog-E.TAIL],body)
            self.assertEqual(R.inspect(ext['extension'])['shutdown_hdf'],enabled)
        self.assertTrue(S.verify(self.raw,self.after,self.jpeg)['verified'])

    def test_body_exception_requires_image_flag_and_all_other_windows(self):
        from unittest.mock import patch
        from darkslide import gr3x_generation as G, gr3x_recipe_gate, fwread, hdf_guard
        def check(after,jpeg):
            with patch.object(gr3x_recipe_gate,'gate',return_value=[dict(ok=True)]), \
                    patch.object(fwread,'unpack',side_effect=[self.raw,after]):
                return G.extension_body(b'original fixture',b'candidate fixture','GR IIIx HDF',jpeg)
        _,report=check(self.after,self.jpeg)
        self.assertEqual(report['status'],'protected_windows_with_verified_shutdown_hook')
        self.assertEqual(report['changed_windows'],['shutdown_selection'])
        self.assertEqual(sum(r['unchanged'] for r in report['protected_windows']),len(report['protected_windows'])-1)
        with self.assertRaises(ValueError):check(self.after,None)
        bad=bytearray(self.after);bad[0x10870+0x536b41d0-0x53000000]^=1
        with self.assertRaises(ValueError):check(bytes(bad),self.jpeg)
        w=next(w for w in self.ext['windows'] if w.address==S.SITE)
        generic=hdf_guard.inspect_sparse(self.raw,'GR IIIx HDF',
            (dict(address=w.address,expected=w.expected,replacement=w.replacement),))
        self.assertEqual(generic['status'],'review_required')

    def test_flag_thunk_branch_resources_and_unexpected_window_reject(self):
        at=self.ext['catalog']-144
        offsets=[0x10870+E.STOCK_SIZE+36, # feature flag (not covered by CRC)
                 0x10870+S.SITE-0x53000000, # original BL
                 0x10870+0x5319f204-0x53000000, # unrelated selector instruction
                 0x10870+0x53b2298c-0x53000000, # runtime resource path
                 59298653+len(self.ext['extension']), # installed resource path
                 59298689+len(self.ext['extension'])+100, # JPEG table bytes
                 0x10870+0x5407e0bc-0x53000000+8] # shared Street table entry
        # Recomputed CRC must not bless changed instruction, identity or padding.
        offsets += [0x10870+at-0x53000000+i for i in (0,12,16,28,32,36,44,48,56,60,64,68)]
        for offset in offsets:
            with self.subTest(offset=hex(offset)):
                bad=bytearray(self.after);bad[offset]^=1
                start=0x10870+E.STOCK_SIZE
                if start+64<=offset<start+len(self.ext['extension']):
                    struct.pack_into('<I',bad,start+32,zlib.crc32(bad[start+64:start+len(self.ext['extension'])])&0xffffffff)
                with self.assertRaises(ValueError):S.verify(self.raw,bytes(bad),self.jpeg)
        with self.assertRaises(ValueError):S.verify(self.raw,self.after,None)
        for flag in (2,3,0xffffffff):
            bad=bytearray(self.ext['extension']);struct.pack_into('<I',bad,36,flag)
            with self.assertRaises(ValueError):R.inspect(bytes(bad))

@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD'),'ARM emulator and IIIx payload required')
class StreetRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unicorn import arm_const as A
        cls.A=A;cls.raw=Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        cls.ext=E.build_fragments(cls.raw,{},shutdown_hdf=True)

    def test_original_selector_truth_table_preserves_abi_state_and_diagnostics(self):
        A=self.A;u=unicorn.Uc(unicorn.UC_ARCH_ARM,unicorn.UC_MODE_ARM)
        u.mem_map(0x53000000,0x3000000);u.mem_map(0x70000000,0x20000)
        u.mem_write(0x53000000,self.raw[0x10870:0x10870+E.STOCK_SIZE])
        u.mem_write(E.TAIL,self.ext['extension'])
        hook=next(w for w in self.ext['windows'] if w.address==S.SITE)
        u.mem_write(hook.address,hook.replacement)
        def put(a,n):u.mem_write(a,struct.pack('<I',n))
        for a,n in ((0x70000004,0x70000100),(0x7000010c,0x70000200),(0x7000021c,0x70000300)):put(a,n)
        stop=0x70010000;sp=0x7001f000;seen=[];diagnostics=[];writes=[]
        def trace(uc,addr,size,data):
            if addr==stop:uc.emu_stop();return
            if addr==0x5322e4a8:
                seen.append(tuple(uc.reg_read(r) for r in (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2,A.UC_ARM_REG_R3,A.UC_ARM_REG_SP,A.UC_ARM_REG_LR)))
            elif addr==0x536b93d0:diagnostics.append(addr)
            elif addr==0x53233fb0:uc.mem_write(uc.reg_read(A.UC_ARM_REG_R0),struct.pack('<2I',123,456))
            elif addr in (0x5320ad88,0x5320b13c,0x5320b07c,0x53525d5c):
                uc.reg_write(A.UC_ARM_REG_R0,{0x5320ad88:0x11,0x5320b13c:0x22,0x5320b07c:0x33,0x53525d5c:0x70000000}[addr])
            elif addr not in (0x536b53e0,0x536b53e8,0x536b5d1c):return
            uc.reg_write(A.UC_ARM_REG_PC,uc.reg_read(A.UC_ARM_REG_LR))
        u.hook_add(unicorn.UC_HOOK_CODE,trace)
        u.hook_add(unicorn.UC_HOOK_MEM_WRITE,lambda uc,access,address,size,value,data:writes.append((address,size)))
        regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(4,12)]
        count=0
        for family in (0,1,2,255):
            for descriptor in (0,0x53d62124,0x53d621fc,0x53d621a8,0x53d62194,0xdeadbeef):
                for mode in (0,1,2,3,4,5,0xffffffff):
                    seen.clear();diagnostics.clear();writes.clear()
                    u.mem_write(0x55018ae0,bytes([family]));put(0x5536d054,descriptor);put(0x70000348,mode)
                    for i,r in enumerate(regs):u.reg_write(r,0x123400+i)
                    u.reg_write(A.UC_ARM_REG_SP,sp);u.reg_write(A.UC_ARM_REG_LR,stop)
                    u.emu_start(0x5319f180,stop,count=300)
                    request={0:2,1:3,2:11,3:10,4:12}.get(mode,2)
                    if request==3 and family==0 and descriptor==0x53d62124:request=12
                    self.assertEqual(seen,[(0x33,request,sp-52,sp-60,sp-80,0x5319f238)])
                    self.assertEqual(u.reg_read(A.UC_ARM_REG_SP),sp)
                    self.assertEqual([u.reg_read(r) for r in regs],[0x123400+i for i in range(8)])
                    self.assertEqual(len(diagnostics),int(mode not in range(5)))
                    self.assertTrue(all(sp-96<=a and a+n<=sp for a,n in writes),writes)
                    self.assertEqual(bytes(u.mem_read(0x5536d054,4)),struct.pack('<I',descriptor))
                    self.assertEqual(bytes(u.mem_read(0x70000348,4)),struct.pack('<I',mode))
                    count+=1
        print('STREET_ORIGINAL_SELECTOR_CASES',count,flush=True)
        for request in (0,1,2,10,11,12,255,0xffffffff):
            seen.clear();writes.clear()
            for r,v in ((A.UC_ARM_REG_R0,123),(A.UC_ARM_REG_R1,request),(A.UC_ARM_REG_R2,456),
                        (A.UC_ARM_REG_R3,789),(A.UC_ARM_REG_SP,sp),(A.UC_ARM_REG_LR,stop)):
                u.reg_write(r,v)
            u.emu_start(self.ext['catalog']-144,stop,count=100)
            self.assertEqual(seen,[(123,request,456,789,sp,stop)])
            self.assertEqual(writes,[])
        print('STREET_OTHER_REQUEST_CASES',8,flush=True)

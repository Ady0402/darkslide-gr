"""Actual formatter/parser -> owned context -> native queue/Make.

Two bounded emulators are joined at the owned-context ABI, relocating only its
owner pointer. File transport and RTOS services are fixtures; no sensor pixels.
The metadata harness is the immutable local v10/v09/v08 research harness.
"""
import importlib.util
import os
from pathlib import Path
import struct
import unittest

try:
    import unicorn
except ImportError:
    unicorn=None


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD'), 'IIIx payload and Unicorn required')
class Roundtrip(unittest.TestCase):
    def test_four_slots_actual_formatter_reader_and_make(self):
        import gr3x_recipe_machine as Q
        from darkslide import gr3x_recipe_merge as M, photo_recipe_extension as E, photo_recipe_dng as D
        research=Path(os.environ.get('DARKSLIDE_RESEARCH_ROOT',
                      Path(__file__).resolve().parents[5]/'研究参考'))
        archive=research/'GRIIIx_160完整配方接入_2026-10-13_v10/formatter_probe.py'
        spec=importlib.util.spec_from_file_location('merged_formatter_fixture',archive)
        F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)
        C,V,N,P=F.C,F.V,F.N,F.P
        raw=Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        selection={8:'5219',9:'portra400',10:'gold200',11:'pro400h'}
        profiles={f:Q.F.load_profile(f,Q.models.GR3X.id) for f in selection.values()}
        merged=M.prepare(raw,[dict(kind='film',slot=s,film=f) for s,f in selection.items()],profiles)
        from gr3x_recipe_io import Machine as ProductionIo
        class Machine(F.Machine):
            new_job = ProductionIo.new_job
            def __init__(self):
                super().__init__(raw,N.compile_lab())
                self.ext=merged['extension']
                for w in merged['curve']['windows']:self.patch(w.address,w.expected,w.replacement,'current curves')
                regions=list(self.u.mem_regions());lo=E.TAIL&~65535;hi=(self.ext['end']+65535)&~65535
                for at in range(lo,hi,4096):
                    if not any(a<=at and at+4095<=b for a,b,_ in regions):self.u.mem_map(at,4096)
                self.u.mem_write(E.TAIL,self.ext['extension']);self.u.mem_protect(lo,hi-lo,C.U.UC_PROT_READ|C.U.UC_PROT_EXEC)
                for w in self.ext['windows']:
                    previous=next((p for p in reversed(self.patch_windows) if int(p['address'],16)==w.address),None)
                    self.patch(w.address,bytes.fromhex(previous['after']) if previous else w.expected,w.replacement,'merged hook')
                self.symbols=self.ext['native']['symbols']
            def block(self,u,a,n,x):
                if hasattr(self,'ext') and E.TAIL<=a and a+n<=self.ext['catalog']:return
                return super().block(u,a,n,x)
        for slot in range(8,12):
            with self.subTest(slot=slot):
                m=Machine();job,prop,photo,work=m.new_job()
                m.call(0x535f85d8,C.FORMATTER);m.call(0x535cd9ac,0x55357b70,0);m.call(0x535faf58,C.FORMATTER)
                m.put(C.SOURCE+4,0x7000b000);m.put(C.SOURCE+8,photo);m.put(C.SOURCE+12,work);m.put(C.SOURCE+16,photo)
                for i in range(12):
                    at=0x7000a000+0x100*i;m.put(C.SOURCE+24+4*i,at);m.allowed.append((at,at+0x80));m.u.mem_write(at,bytes(0x80));m.u.mem_write(at+0x2d,b'\x01')
                m.u.mem_write(photo+0x77c,bytes([slot+10]))
                data,root,tags=F.output(m);packet=merged['packets'][slot]
                self.assertEqual(D.extract(data),packet)
                fixture=C.transport_fixture();needle=bytes.fromhex('0410a0e30020a0e3')
                self.assertEqual(fixture.count(needle),1)
                m.u.mem_write(C.NEAR+0xe000,fixture.replace(needle,bytes.fromhex('0410a0e30820a0e3')))
                m.stream_base=0;m.stream_error=0;m.task_load(job,prop,work,root[50740][2])
                self.assertEqual(m.call('ds_raw_job_view',job,work,0,V.OUT),1)
                core=bytes(m.u.mem_read(m.get(V.OUT),P.CORE.size))
                self.assertEqual(core,packet[24:24+P.CORE.size])
                m.call(0x535fa6e0,C.FORMATTER);m.call(0x535fa49c,C.FORMATTER)
                self.assertEqual(m.call('ds_raw_job_view',job,work,0,V.OUT),1)
                self.assertEqual(bytes(m.u.mem_read(m.get(V.OUT),P.CORE.size)),core)
                # ABI bridge: preserve parser-produced state/epoch/slot/core.
                # Only a virtual address changes between isolated machines.
                restored=Q.Machine(raw,{})
                context=bytearray(m.u.mem_read(job+96,1588))
                struct.pack_into('<I',context,0,restored.original)
                # Deep-copy the actual parser-owned packet, not a pointer into
                # the other emulator. Preserve independently checked core/state.
                packet_at,packet_size=struct.unpack('<II',m.u.mem_read(job+96+1588,8))
                self.assertEqual(bytes(m.u.mem_read(packet_at,packet_size)),packet)
                restored.restore(bytes(m.u.mem_read(packet_at,packet_size)))
                restored.u.mem_write(restored.job+96,bytes(context))
                p=restored.submit(slot);after=restored.make(p)
                Q.validate_consumption(restored,p,packet,after)
                current=Q.Machine(raw,selection)
                before=current.make(current.submit(slot,selector=slot+1))
                for key in ('base','rgb','post','registers'):self.assertEqual(before[key],after[key])
                for selector in range(1,13):self.assertEqual(m.call('ds_raw_job_view',job,work,selector,V.OUT),0)
                m.call('ds_raw_job_release',job);m.free(job);self.assertFalse(m.allocations)
                print('MERGED_FORMATTER_ROUNDTRIP',slot,len(data),len(tags),flush=True)

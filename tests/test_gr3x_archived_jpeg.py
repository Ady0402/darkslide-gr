"""Original RAW parser/task -> request -> pool photo -> JPEG writer -> desktop.

File/RTOS services and boot pool inventory are explicit fixtures. JPEG pixels
are synthetic. All allocations have guards; freed packet reads are forbidden.
"""
import os
import struct
import unittest
from pathlib import Path
from darkslide import photo_recipe as P, photo_recipe_extension as E
from darkslide import photo_recipe_jpeg as J, film_profiles as F, models
try:
    import unicorn
except ImportError:
    unicorn = None


def packet(film, slot=8):
    return P.encode(F.load_profile(film, models.GR3X.id), slot)


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD') and
                    os.environ.get('DARKSLIDE_RESEARCH_ROOT'), 'IIIx payload and local ARM fixtures required')
class ArchivedJPEG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gr3x_jpeg_machine import Machine as JPEG, C, V
        cls.raw = Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        cls.C, cls.V = C, V

        from gr3x_recipe_queue import queue_machine
        Machine = queue_machine(JPEG)

        cls.Machine = Machine

    def test_all_sixteen_historical_packets_survive_changed_catalog(self):
        for i,film in enumerate(F.ready_profile_ids()):
            slot = 8+i%4
            with self.subTest(film=film,slot=slot):
                old=packet(film,slot)
                # Today's ROM deliberately contains another recipe at this slot.
                current=packet('5219' if film!='5219' else 'gold200',slot)
                m=self.Machine(self.raw,E.build_fragments(self.raw,{slot:current}))
                source=m.load(old);request=m.send()
                self.assertEqual(m.ref(request+24),(request+E.REQUEST_EXTENDED,len(old)))
                m.call('ds_begin',m.job+96,0,19)  # next RAW must not change queued data
                self.assertIn(source,[a for a,n in m.free_log])
                photo=m.accept(request)
                owned,n=m.ref(photo+E.PHOTO_BYTES)
                self.assertEqual(bytes(m.u.mem_read(owned,n)),old)
                _,base=m.output(slot,capture=False);ok,out=m.output(slot)
                self.assertEqual(ok,1);self.assertEqual(J.extract(out),old)
                from test_gr3x_jpeg_runtime import Runtime
                Runtime.check_image(self,base,out,old)
                m.call('ds_pool_return',m.pool,photo)
                self.assertEqual(m.ref(photo+E.PHOTO_BYTES),(0,0))
                self.assertIn(owned,[a for a,n in m.free_log]);m.canaries()

    def test_max_history_without_rom_and_cancelled_request(self):
        from test_photo_recipe_jpeg import packet_of_size
        old=packet_of_size(packet('gold200'),P.MAX_PACKET)
        m=self.Machine(self.raw,E.build_fragments(self.raw,{}))
        m.load(old);cancel=m.send()
        # Cancellation/free needs no private destructor: all bytes are inline.
        allocations=len(m.allocations);m.call(0x5382d088,m.transport,cancel)
        self.assertEqual(len(m.allocations),allocations-1)
        m.cancel_during_send=True
        cancel=m.send()  # sender may release before it returns; no tail reads
        self.assertFalse(any(a==cancel for a,b in m.allocations))
        m.cancel_during_send=False
        request=m.send();m.call('ds_begin',m.job+96,0,20);m.accept(request)
        _,out=m.output();self.assertEqual(J.extract(out),old)
        self.assertEqual(len([1 for k,p,*_ in J.markers(out) if k==0xef and p.startswith(b'DSRECIPE')]),2)

    def test_derived_recipe_metadata_survives_raw_to_jpeg_and_desktop_import(self):
        import tempfile
        from unittest.mock import patch
        from darkslide import gr3x_recipe_lineage as L, server
        from test_iiix_desktop import request
        from test_gr3x_catalog16 import legacy
        with tempfile.TemporaryDirectory() as folder:
            app=server.App(folder)
            with patch.object(app.store,'has_input',return_value=True):
                pid=app.store.create_project('derived',models.GR3X.input_sha,
                    models.template_for(models.GR3X),camera_variant='GR IIIx')['id']
            original=app.store.put_photo_recipe(pid,P.encode(legacy('gold200'),9))
            bake=dict(film=original['id'],grade={'temp':5},recipe_source=L.capture(app.store,pid,original['id']))
            # Known valid numeric fixture; the actual fitter is covered by HTTP.
            profile=F.load_profile('gold200',models.GR3X.id)
            profile.update(id='user_lut_0123456789ab',official_sha256=models.GR3X.input_sha,
                base_model_id='gr3x-160-upstream-neutral-stubbed-v2')
            derived=L.attach(profile,bake);old=P.encode(derived,8)
            m=self.Machine(self.raw,E.build_fragments(self.raw,{8:packet('5219')}))
            m.load(old);req=m.send();m.call('ds_begin',m.job+96,0,0);photo=m.accept(req)
            _,out=m.output();self.assertEqual(J.extract(out),old)
            imported=server.api_import_photo_recipe(request(app,data=out),pid)
            self.assertEqual(imported['data_notices'],original['data_notices'])
            self.assertEqual(imported['recipe_derivation'],derived['recipe_derivation'])
            self.assertEqual(app.store.photo_recipe_packet(pid,imported['id']),old)
            m.call('ds_pool_return',m.pool,photo);m.canaries()

    def test_failed_packet_allocations_never_use_current_catalog(self):
        old=packet('gold200');current=packet('5219')
        for phase in ('restore','request','accept','photo'):
            with self.subTest(phase=phase):
                m=self.Machine(self.raw,E.build_fragments(self.raw,{8:current}))
                if phase=='restore':
                    # Parsed tag payload succeeds; fail its owned archive copy.
                    m.fail_size=len(old)
                    m.call('ds_begin',m.job+96,m.get(m.prop+0x5d0),1)
                    m.u.mem_write(self.V.PACKET,old)
                    self.assertEqual(m.call('ds_restore',m.job+96,self.V.PACKET,len(old)),1)
                    m.fail_size=None
                else:m.load(old)
                m.u.mem_write(m.work+0x77c,b'\x12')
                if phase=='request':m.fail_size=E.REQUEST_EXTENDED+len(old)
                request=m.send();m.fail_size=None
                if phase in ('accept','photo'):
                    m.fail_nth=len(m.alloc_log)+(1 if phase=='accept' else 2)
                photo=m.accept(request);m.fail_nth=None
                self.assertEqual(m.get(photo+E.PHOTO_BYTES+8),1)
                self.assertEqual(m.ref(photo+E.PHOTO_BYTES),(0,0))
                _,base=m.output(capture=False);_,out=m.output()
                self.assertEqual(out,base)
                with self.assertRaisesRegex(ValueError,'未保存'):J.extract(out)
                m.call('ds_begin',m.job+96,0,0);m.call('ds_pool_return',m.pool,photo)

    def test_two_photos_duplicate_reset_and_release(self):
        a,b=packet('gold200'),packet('5219')
        m=self.Machine(self.raw,E.build_fragments(self.raw,{8:packet('portra400')}))
        originals=[]
        for i,data in enumerate((a,b)):
            m.load(data);m.accept(m.send(),i)
            originals.append(m.ref(m.photos[i]+E.PHOTO_BYTES)[0])
        for i,data in ((0,a),(1,b),(0,a)):
            m.photo=m.photos[i];m.put(self.C.SOURCE+8,m.photo)
            _,out=m.output();self.assertEqual(J.extract(out),data)
        p=m.ref(m.job+96)[0]
        m.u.mem_write(self.V.PACKET,a)
        self.assertEqual(m.call('ds_restore',m.job+96,self.V.PACKET,len(a)),0)
        self.assertEqual(m.ref(m.job+96),(0,0));self.assertIn(p,[x for x,n in m.free_log])
        m.load(a);p=m.ref(m.job+96)[0]
        # Actual newly bound job-release call, not just a direct helper call.
        m.segment(0x534bf468,0x534bf46c,{0:m.job})
        self.assertEqual(m.ref(m.job+96),(0,0));self.assertIn(p,[x for x,n in m.free_log])
        for photo in m.photos:m.call('ds_pool_return',m.pool,photo)
        self.assertTrue(set(originals)<={x for x,n in m.free_log})
        m.canaries()

    def test_selection_reenable_and_numeric_packet_mismatch(self):
        old,current=packet('gold200'),packet('5219')
        m=self.Machine(self.raw,E.build_fragments(self.raw,{8:current}))
        m.load(old);owned=m.ref(m.job+96)[0]
        # Existing UI selector uses these states; its actual call-site execution
        # is covered by test_gr3x_recipe_runtime. Exercise the downstream carrier.
        m.put(m.job+96+8,0x109)
        m.accept(m.send())
        _,out=m.output();self.assertEqual(J.extract(out),current)
        self.assertEqual(m.ref(m.job+96)[0],owned)
        m.put(m.job+96+8,1)
        photo=m.accept(m.send())
        _,out=m.output();self.assertEqual(J.extract(out),old)
        # A valid packet must still describe the numeric core that was rendered.
        at=photo+E.PHOTO_BYTES+16
        m.u.mem_write(at,bytes([m.u.mem_read(at,1)[0]^1]))
        _,base=m.output(capture=False);_,out=m.output();self.assertEqual(out,base)
        m.call('ds_pool_return',m.pool,photo);m.call('ds_begin',m.job+96,0,0)
        m.canaries()

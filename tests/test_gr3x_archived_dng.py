"""Restored owned photo -> original DNG formatter, not a camera UI claim.

Uses original parser, queue binding, parent allocation, both layout call sites,
private serializer and destruction. No evidence yet that the camera exposes a
RAW-to-DNG export command. Sensor pixel storage is a fixture.
"""
import os
import struct
import unittest
from pathlib import Path
from darkslide import photo_recipe as P, photo_recipe_extension as E, photo_recipe_dng as D
from test_gr3x_archived_jpeg import packet, unicorn


@unittest.skipUnless(unicorn and os.environ.get('DARKSLIDE_GR3X_PAYLOAD') and
                    os.environ.get('DARKSLIDE_RESEARCH_ROOT'), 'IIIx payload and local ARM fixtures required')
class ArchivedDNG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gr3x_recipe_io import Machine as Io, F, C, V
        from gr3x_recipe_queue import queue_machine
        cls.raw = Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        cls.F, cls.C, cls.V = F, C, V

        class Dng(Io):
            def __init__(self, raw, ext):
                super().__init__(raw, ext)
                self.job, self.prop, self.photo, self.work = self.new_job()
                self.call(0x535f85d8, C.FORMATTER)
                self.call(0x535cd9ac, 0x55357b70, 0)
                self.call(0x535faf58, C.FORMATTER)
                self.put(C.SOURCE+4, 0x7000b000)
                self.put(C.SOURCE+8, self.photo)
                self.put(C.SOURCE+12, self.work)
                self.put(C.SOURCE+16, self.photo)
                for i in range(12):
                    at = 0x7000a000+256*i
                    self.put(C.SOURCE+24+4*i, at)
                    self.allowed.append((at, at+128))
                    self.u.mem_write(at, bytes(128))
                    self.u.mem_write(at+0x2d, b'\1')

            def output(self):
                self.read_stream = False
                self.stream_base = 0
                self.stream_error = 0
                self.stream_limit = len(self.stream)
                return F.output(self)

            def close(self):
                self.call(0x535fa6e0, C.FORMATTER)
                self.call(0x535fa49c, C.FORMATTER)
                self.call('ds_raw_job_release', self.job)
                self.free(self.job)
                for photo in self.photos:self.call('ds_pool_return', self.pool, photo)
                self.canaries()

        cls.Machine = queue_machine(Dng)

    def machine(self, catalog):
        return self.Machine(self.raw, E.build_fragments(self.raw, catalog))

    def restore(self, m, data, index=0):
        m.load(data)
        request = m.send()
        m.call('ds_begin', m.job+96, 0, 123)  # original RAW has already gone away
        return m.accept(request, index)

    def test_four_slots_changed_catalog_and_desktop_roundtrip(self):
        from darkslide import server, models
        from test_iiix_desktop import request
        from unittest.mock import patch
        import tempfile
        for slot in range(8, 12):
            with self.subTest(slot=slot):
                old = packet('gold200', slot)
                m = self.machine({slot:packet('5219', slot)})
                photo = self.restore(m, old)
                data, root, tags = m.output()
                self.assertEqual(D.extract(data), old)
                self.assertEqual(tags[0xd534][:3], (7,len(old),old))
                self.assertEqual(root[50740][1], m.get(self.C.FORMATTER+0x290))
                with tempfile.TemporaryDirectory() as folder:
                    app = server.App(folder)
                    with patch.object(app.store,'has_input',return_value=True):
                        pid = app.store.create_project('history',models.GR3X.input_sha,
                            models.template_for(models.GR3X),camera_variant='GR IIIx')['id']
                    imported = server.api_import_photo_recipe(request(app,data=data),pid)
                    self.assertEqual(app.store.photo_recipe_packet(pid,imported['id']),old)
                m.close()
                self.assertEqual(m.ref(photo+E.PHOTO_BYTES),(0,0))

    def test_max_packet_without_catalog_both_secondary_variants(self):
        from test_photo_recipe_jpeg import packet_of_size
        old = packet_of_size(packet('gold200'), P.MAX_PACKET)
        m = self.machine({})
        photo = self.restore(m, old)
        data, root, _ = m.output()
        self.assertEqual(D.extract(data), old)
        reserved = m.get(self.C.FORMATTER+0x290)
        self.assertGreaterEqual(reserved, P.MAX_PACKET+12)
        # Original secondary pass chooses source variant 1 or 2, independently
        # of the first pass. Give both genuine owned-photo identities.
        for variant in (1, 2):
            m.put(self.C.SOURCE+8+4*variant, photo)
            m.u.mem_write(self.C.SOURCE,bytes([variant]))
            offset=(m.maxwrite+3)&~3
            m.put(self.C.FORMATTER+0x294,offset)
            self.assertEqual(m.call(0x535fad88,self.C.FORMATTER,self.V.STREAM,self.C.SOURCE),1)
            private=self.F.ifd_bytes(bytes(m.stream[:m.maxwrite]),offset)[50740][2]
            self.assertEqual(self.F.ifd_bytes(private)[0xd534][:3],(7,len(old),old))
        self.assertEqual(m.get(self.C.FORMATTER+0x290),reserved)
        m.close()

    def test_reuse_two_photos_ordinary_selection_and_invalid_history(self):
        a, b, current = packet('gold200'), packet('portra400'), packet('5219')
        m = self.machine({8:current})
        photos = [self.restore(m, p, i) for i,p in enumerate((a,b))]
        for photo, data in ((photos[0],a),(photos[1],b),(photos[0],a)):
            m.put(self.C.SOURCE+8, photo)
            self.assertEqual(D.extract(m.output()[0]),data)
        # A normal stock tone removes the private tag when formatter is reused.
        m.u.mem_write(photos[0]+0x77c,b'\x0b')
        self.assertNotIn(0xd534,m.output()[2])
        m.u.mem_write(photos[0]+0x77c,b'\x12')
        self.assertEqual(D.extract(m.output()[0]),a)
        # Active history with damaged/missing packet cannot use current ROM.
        context = photos[0]+E.PHOTO_BYTES
        at, size = m.ref(context)
        m.u.mem_write(at+size-1,bytes([m.u.mem_read(at+size-1,1)[0]^1]))
        self.assertNotIn(0xd534,m.output()[2])
        m.u.mem_write(at+size-1,bytes([m.u.mem_read(at+size-1,1)[0]^1]))
        m.u.mem_write(context+16,bytes([m.u.mem_read(context+16,1)[0]^1]))
        self.assertNotIn(0xd534,m.output()[2])
        # Explicitly new/current state uses current catalog rather than history.
        m.put(context+8,0)
        self.assertEqual(D.extract(m.output()[0]),current)
        m.close()

    def test_tag_allocation_failure_keeps_original_metadata_and_recovers(self):
        old = packet('gold200')
        m = self.machine({8:packet('5219')})
        photo = self.restore(m, old)
        expected, root, tags = m.output()
        m.fail_size = len(old)  # only the writer's tag buffer, after restoration
        failed, failed_root, failed_tags = m.output()
        self.assertNotIn(0xd534,failed_tags)
        # Factory field 4 tracks the laid-out private directory extent. It
        # changes when our entry is omitted; stable tag values must not change.
        self.assertEqual(failed_tags[4][:2],tags[4][:2])
        self.assertGreater(int.from_bytes(tags[4][2],'little'),
                           int.from_bytes(failed_tags[4][2],'little'))
        for key in tags.keys()-{0xd534,4}:
            self.assertEqual(failed_tags[key][:3],tags[key][:3])
        for key in (271,272):self.assertEqual(failed_root[key][:3],root[key][:3])
        m.fail_size = None
        self.assertEqual(m.output()[0],expected)
        m.call('ds_begin',photo+E.PHOTO_BYTES,photo,0)
        m.put(photo+E.PHOTO_BYTES+8,1)
        m.put(photo+E.PHOTO_BYTES+12,8)
        self.assertNotIn(0xd534,m.output()[2])
        m.close()

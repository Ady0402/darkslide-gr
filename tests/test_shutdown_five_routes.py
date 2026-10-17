"""Five factory routes share one user JPEG; no new code, allocation or module."""
import hashlib, json, os, struct, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from darkslide import (models, server, compositor, composite_verify, fwread,
    package, body_target, hdf_guard, gr3x_generation, generate, photo_recipe_native)
from test_iiix_desktop import request

JPEG=(Path(__file__).parent/'fixtures/shutdown_gradient.jpg').read_bytes()

def sha(b):return hashlib.sha256(b).hexdigest()
def off(a):return 0x10870+a-0x53000000

class Coverage(unittest.TestCase):
    def test_all_known_modes_without_inferring_body_setting(self):
        for body in body_target.BODIES:
            report=body_target.shutdown_report(body)
            self.assertEqual(report['missing_requests'],[])
            self.assertEqual(report['status'],'all_factory_routes_covered')
            self.assertIsNone(report['collabo_mode_observed'])
            self.assertFalse(report['camera_verified'])
            self.assertFalse(report['compatibility_approved'])
        self.assertFalse(models.IIIX_RECIPE_MODULE)

@unittest.skipUnless(os.environ.get('DARKSLIDE_OFFICIAL_BIN') and os.environ.get('DARKSLIDE_IIIX_PRODUCT_BIN'),
                     'both held official inputs required')
class ActualFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs={models.GR3:Path(os.environ['DARKSLIDE_OFFICIAL_BIN']).read_bytes(),
                    models.GR3X:Path(os.environ['DARKSLIDE_IIIX_PRODUCT_BIN']).read_bytes()}

    def test_both_families_exact_five_routes_no_code_changes_and_rejection(self):
        for model,official in self.inputs.items():
            with self.subTest(model=model.id):
                template=models.template_for(model)
                result=compositor.build_composite(official,[],template,JPEG)
                checks=composite_verify.verify(official,result,[],template,JPEG)
                self.assertTrue(composite_verify.all_ok(checks),checks)
                before,after=fwread.unpack(official),fwread.unpack(result['output'])
                self.assertEqual(len(before),len(after))
                self.assertEqual(before[0x10860:0x10870],after[0x10860:0x10870])
                # Every table entry, including the seven non-shutdown entries.
                old=struct.unpack_from('<12I',before,off(0x5407e0bc))
                new=struct.unpack_from('<12I',after,off(0x5407e0bc))
                for i in range(12):self.assertEqual(new[i],old[11] if i+1 in (2,3,10,11,12) else old[i])
                self.assertEqual(old[2],0x53b5f550);self.assertEqual(new[2],0x53b5f508)
                self.assertEqual(result['request_ids'],[2,3,10,11,12])
                for body in body_target.BODIES:
                    if body_target.family(body)==model.name:
                        r=body_target.build_report(before,body,after)
                        self.assertEqual(r['status'],'protected_windows_unchanged')
                # All executable prefix bytes unchanged; image/path/table are later.
                self.assertEqual(before[0x10870:off(0x538f0000)],after[0x10870:off(0x538f0000)])
                # Two checksum-correct malformed candidates: missing Street alias
                # and a neighboring non-shutdown pointer. Reader must reject both.
                archive=package.Package.read(result['output'],model.id)
                for index,value in ((2,old[2]),(3,old[11])):
                    a=off(0x5407e0bc+index*4);bad=bytearray(after)
                    struct.pack_into('<I',bad,a,value)
                    wire,raw,_,_=package.pack_change(result['output'],after,archive.frames,
                        archive.stream_end,archive.trailer.values(),bytes(bad),[dict(offset=a,length=4)])
                    changed=dict(result,output=wire,output_sha256=sha(wire),payload_sha256_after=sha(raw))
                    checks=composite_verify.verify(official,changed,[],template,JPEG)
                    self.assertFalse(composite_verify.all_ok(checks))
                    self.assertFalse(next(c['ok'] for c in checks if c['id']=='entire_payload_matches_independent_request'))
                print('FIVE_ROUTE_FILE',model.name,result['output_sha256'],'decoded_growth=0',flush=True)

    def test_no_shutdown_keeps_all_factory_images_and_pointers(self):
        for model,official in self.inputs.items():
            template=models.template_for(model)
            slot=template['slots'][6]
            edits=[dict(kind='name',slot=7,string_id=slot['string_id'],text='TEST')]
            result=compositor.build_composite(official,edits,template)
            self.assertTrue(composite_verify.all_ok(composite_verify.verify(official,result,edits,template,None)))
            before,after=fwread.unpack(official),fwread.unpack(result['output'])
            self.assertEqual(before[off(0x5407e0bc):off(0x5407e0bc)+48],after[off(0x5407e0bc):off(0x5407e0bc)+48])
            self.assertEqual(before[0x10870+0x10b55c0:-4],after[0x10870+0x10b55c0:-4])
            self.assertNotIn('shutdown',result['features'])

    def test_saved_product_generation_with_recipe_module_disabled(self):
        self.assertFalse(models.IIIX_RECIPE_MODULE)
        for model,official in self.inputs.items():
            with tempfile.TemporaryDirectory() as root:
                app=server.App(root);app.store.put_input(official);t=models.template_for(model)
                variant='GR III Street Edition' if model==models.GR3 else 'GR IIIx HDF'
                pid=app.store.create_project('Street no growth',model.input_sha,t,camera_variant=variant)['id']
                asset=app.store.put_shutdown_jpeg(pid,JPEG)
                changes={'shutdown':{'asset':asset['asset']}}
                if model==models.GR3X:changes['8']={'film':'gold200'}
                app.store.put_draft(pid,changes,t);app.store.save(pid,t)
                with patch.object(photo_recipe_native,'compile_extension',side_effect=AssertionError('recipe dependency')):
                    if model==models.GR3X:
                        result=server.api_iiix_candidate(request(app,dict(expected_changes=changes,recipe_extension=False)),pid)
                        self.assertNotIsInstance(result,server.Reply)
                        output=server.api_build_firmware(request(app),result['build_id']).body
                        self.assertEqual(result['decoded_growth_bytes'],0)
                        self.assertNotIn('film_recipe_archive',result)
                    else:
                        output,result=generate.run(app.store,app.store.get_project(pid),t,official)
                self.assertTrue(all(c['ok'] is True for c in result['checks']))
                self.assertEqual(result['body']['status'],'protected_windows_unchanged')
                self.assertEqual(result['body']['shutdown_routes']['missing_requests'],[])
                self.assertEqual(len(fwread.unpack(output)),len(fwread.unpack(official)))
                print('FIVE_ROUTE_PRODUCT',model.name,sha(output),'recipe_module=False',flush=True)

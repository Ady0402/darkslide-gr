"""1.0 candidate boundary and real IIIx packaging, no device operations."""
import copy, hashlib, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from darkslide import server, models, gr3x_generation as G, generate, fwread
from darkslide.store import StoreError
from test_iiix_desktop import request

class CandidateBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=server.App(self.tmp.name)
        with patch.object(self.app.store,'has_input',return_value=True):
            self.pid=self.app.store.create_project('IIIx',models.GR3X.input_sha,models.template_for(models.GR3X),camera_variant='GR IIIx')['id']
            self.other=self.app.store.create_project('III',models.GR3.input_sha,models.template_for(models.GR3),camera_variant='GR III')['id']
        self.body=dict(expected_changes={},recipe_extension=False)

    def test_route_body_model_lock_and_unsaved_reject_before_producer(self):
        with patch.object(G,'run',side_effect=AssertionError('producer')):
            for bad in ({},dict(self.body,recipe_extension=1),dict(self.body,extra=True)):
                with self.assertRaises(server.ApiError):server.api_iiix_candidate(request(self.app,bad),self.pid)
            with self.assertRaises(server.ApiError):server.api_iiix_candidate(request(self.app,self.body),self.other)
            self.app.iiix_generation_lock.acquire()
            with self.assertRaises(server.ApiError):server.api_iiix_candidate(request(self.app,self.body),self.pid)
            self.app.iiix_generation_lock.release()
            self.app.store.put_draft(self.pid,{'8':{'name':'TEST'}},models.template_for(models.GR3X))
            with self.assertRaises(server.ApiError):server.api_iiix_candidate(request(self.app,self.body),self.pid)
        self.assertEqual(self.app.store.builds(),[])

    def test_recipe_module_refused_in_1_0_before_producer(self):
        # User 2026-10-16: 1.0 offers no photo-recipe module (it grows the firmware).
        self.assertFalse(models.IIIX_RECIPE_MODULE)
        caps=models.capabilities(models.GR3X)
        self.assertFalse(caps['candidate_recipe_extension']);self.assertFalse(caps['photo_recipe_read'])
        self.assertTrue(caps['candidate_generation'])
        with patch.object(G,'run',side_effect=AssertionError('producer')):
            with self.assertRaises(server.ApiError) as caught:
                server.api_iiix_candidate(request(self.app,dict(expected_changes={},recipe_extension=True)),self.pid)
        self.assertEqual(caught.exception.status,422)
        self.assertTrue(self.app.iiix_generation_lock.acquire(blocking=False));self.app.iiix_generation_lock.release()
        self.assertEqual(self.app.store.builds(),[])

    def test_store_rejects_wrong_name_hash_or_failed_checks(self):
        good=dict(input_sha256=models.GR3X.input_sha,output_filename=models.GR3X.filename,output_sha256=G.sha(b'x'),checks=[dict(ok=True)])
        for bad in (dict(good,output_filename=models.GR3.filename),dict(good,output_sha256='0'*64),dict(good,checks=[]),dict(good,checks=[dict(ok=1)])):
            with self.assertRaises(StoreError):self.app.store.put_build(b'x',bad)
        self.assertEqual(self.app.store.builds(),[])


@unittest.skipUnless(os.environ.get('DARKSLIDE_IIIX_PRODUCT_BIN'),'IIIx product candidate integration original required')
class RealCandidate(unittest.TestCase):
    def setUp(self):
        # Module internals stay covered with the 1.0 switch turned on for this test only.
        switch=patch.object(models,'IIIX_RECIPE_MODULE',True);switch.start();self.addCleanup(switch.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=server.App(self.tmp.name);self.source=Path(os.environ['DARKSLIDE_IIIX_PRODUCT_BIN']).read_bytes()
        self.app.store.put_input(self.source);self.template=models.template_for(models.GR3X)
        self.pid=self.app.store.create_project('IIIx runtime',models.GR3X.input_sha,self.template,camera_variant='GR IIIx HDF')['id']

    def build(self,changes,extension):
        self.app.store.put_draft(self.pid,changes,self.template);self.app.store.save(self.pid,self.template)
        result=server.api_iiix_candidate(request(self.app,dict(expected_changes=changes,recipe_extension=extension)),self.pid)
        if isinstance(result,server.Reply):self.fail(str(result.body))
        self.assertEqual(result['output_filename'],models.GR3X.filename)
        self.assertTrue(all(c['ok'] is True for c in result['checks']))
        self.assertFalse(result['camera_verified']);self.assertFalse(result['production_approved'])
        self.assertEqual(result['body']['status'], 'protected_windows_with_verified_shutdown_hook' if extension and 'shutdown' in changes else 'protected_windows_unchanged')
        output=server.api_build_firmware(request(self.app),result['build_id']).body
        self.assertEqual(G.sha(output),result['output_sha256'])
        self.assertEqual(result['output_bytes'],len(output))
        self.assertEqual(result['encoded_growth_bytes'],len(output)-len(self.source))
        self.assertEqual(result['input_bytes'],len(self.source))
        self.assertEqual(len(fwread.unpack(output))-len(fwread.unpack(self.source)),result['decoded_growth_bytes'])
        reopened=server.App(self.tmp.name)
        self.assertEqual(server.api_build_firmware(request(reopened),result['build_id']).body,output)
        print('PRODUCT_CANDIDATE',json.dumps({k:result[k] for k in ('output_sha256','decoded_growth_bytes','firmware_layout','features')},ensure_ascii=False),flush=True)
        return result,output

    def test_chosen_menu_language_reaches_the_iiix_build(self):
        # The IIIx path must honour the menu language picked before generating, like GR III does.
        slot=self.template['slots'][1]
        self.app.store.set_menu_language(self.pid,'ko')
        result,output=self.build({str(slot['no']):{'name':'Vivid KO'}},False)
        self.assertEqual(result['menu_language'],'ko')
        stock=fwread.Payload(fwread.unpack(self.source),models.layout(models.GR3X))
        after=fwread.Payload(fwread.unpack(output),models.layout(models.GR3X),pinned=False)
        for lang,shows in ((1,True),(17,True),(19,False),(18,False),(0,False)):  # en, ko, zh-CN, zh-TW, ja
            want='Vivid KO' if shows else stock.string(slot['string_id'],lang)['text']
            self.assertEqual(after.string(slot['string_id'],lang)['text'],want,lang)

    def test_curves_plus_ordinary_and_extended_full_bundle(self):
        from test_http import icon_png
        icon=self.app.store.put_asset(self.pid,icon_png(),expect_icon=True)
        # Standard edits travel through the same adapter as the four film slots.
        changes={str(s):{'film':f} for s,f in zip(range(8,12),('5203','5207','5219','gold200'))}
        changes['8'].update(name='NEW FILM',icon={'asset':icon['asset'],'style':'image'})
        changes['12']={'grain':True}
        jpeg=(Path(__file__).parent/'fixtures/shutdown_gradient.jpg').read_bytes()
        shutdown=self.app.store.put_shutdown_jpeg(self.pid,jpeg)
        changes['shutdown']={'asset':shutdown['asset']}
        regular,_=self.build(changes,False)
        self.assertEqual(regular['decoded_growth_bytes'],0)
        extended,output=self.build(changes,True)
        self.assertGreater(extended['decoded_growth_bytes'],0)
        self.assertEqual(len(extended['film_recipe_archive']['snapshots']),4)
        self.assertTrue(extended['film_recipe_archive']['jpeg_capture_implemented'])
        self.assertTrue(extended['film_recipe_archive']['jpeg_archived_raw_reexport'])
        self.assertFalse(extended['film_recipe_archive']['raw_to_dng_camera_entry_implemented'])
        self.assertTrue(extended['body']['shutdown_routes']['conditional_request_3']['verified'])
        self.assertNotIn('JPEG 不含自动配方',extended['verification'])
        from darkslide import gr3x_recipe_archive
        self.assertEqual(extended['film_recipe_archive'],gr3x_recipe_archive.from_output(output))

    def test_compiler_checksum_and_body_failure_do_not_publish(self):
        from darkslide import photo_recipe_native, body_target
        with patch.object(photo_recipe_native, 'compile_extension', side_effect=OSError('compiler missing')):
            response=server.api_iiix_candidate(request(self.app,dict(expected_changes={},recipe_extension=True)),self.pid)
            self.assertIsInstance(response,server.Reply)
            self.assertIn('compiler missing',str(response.body))
        changes={'8':{'film':'gold200'}}
        self.app.store.put_draft(self.pid,changes,self.template);self.app.store.save(self.pid,self.template)
        broken=self.source[:-4]+b'BAD!'
        with patch.object(G,'curve_candidate',return_value=(broken,[dict(id='fixture',ok=True)])):
            response=server.api_iiix_candidate(request(self.app,dict(expected_changes=changes,recipe_extension=False)),self.pid)
            self.assertIsInstance(response,server.Reply)
        with patch.object(G,'curve_candidate',return_value=(self.source,[dict(id='fixture',ok=True)])), \
                patch.object(body_target,'build_report',return_value=dict(status='review_required')), \
                patch.object(body_target,'summary',return_value='protected mismatch'):
            response=server.api_iiix_candidate(request(self.app,dict(expected_changes=changes,recipe_extension=False)),self.pid)
            self.assertIsInstance(response,server.Reply)
        self.assertEqual(self.app.store.builds(),[])

    def test_restore_only_and_source_change_refuses_record(self):
        result,_=self.build({},True)
        self.assertEqual(result['film_recipe_archive']['snapshots'],[])
        before=len(self.app.store.builds())
        original=G.extension_body
        def change(*args):
            result=original(*args)
            self.app.store.rename_project(self.pid,'changed while generating')
            return result
        with patch.object(G,'extension_body',side_effect=change):
            result=server.api_iiix_candidate(request(self.app,dict(expected_changes={},recipe_extension=True)),self.pid)
            self.assertIsInstance(result,server.Reply)
        self.assertEqual(len(self.app.store.builds()),before)

@unittest.skipUnless(os.environ.get('DARKSLIDE_IIIX_HTTP_BIN'),'actual IIIx HTTP generation original required')
class RealHTTP(unittest.TestCase):
    def setUp(self):
        switch=patch.object(models,'IIIX_RECIPE_MODULE',True);switch.start();self.addCleanup(switch.stop)

    def test_fitted_and_historical_recipe_complete_candidate_download_and_rejection(self):
        import http.client, threading
        from darkslide import photo_recipe as R
        from darkslide.store import write_json,read_json
        from test_iiix_desktop import CUBE
        from test_gr3x_catalog16 import legacy
        with tempfile.TemporaryDirectory() as folder:
            app=server.App(folder);app.store.put_input(Path(os.environ['DARKSLIDE_IIIX_HTTP_BIN']).read_bytes())
            t=models.template_for(models.GR3X)
            pid=app.store.create_project('HTTP mixed',models.GR3X.input_sha,t,camera_variant='GR IIIx')['id']
            historical=app.store.put_photo_recipe(pid,R.encode(legacy('gold200'),9))
            lid=app.store.put_film_lut(pid,CUBE,'identity.cube')['id']
            # Use an already installed emulator, without invoking the installer in a temporary store.
            from darkslide import base_curve
            contract=base_curve.base_curve(app.store.input_path(models.GR3X.input_sha))
            with patch.object(server,'_camera_model',return_value=contract):
                fitted=server._fit_and_keep(request(app),pid,lid)
                # Synthetic cube isolates metadata transport; this is not a
                # claim that the fixture reproduces Gold + exposure visually.
                graded=server.api_bake_grade(request(app,dict(cube='# grading transport fixture\n'+CUBE.decode(),
                    film='gold200',grade={'exp':10})),pid)
            self.assertTrue(fitted['fit']['current_install']['numeric_installable'])
            changes={'8':{'film':'5203'},'9':{'film':historical['id']},'10':{'film':lid},'11':{'film':'gold200','grade':{'exp':10}}}
            app.store.put_draft(pid,changes,t);app.store.save(pid,t)
            httpd=server.LocalServer(('127.0.0.1',0),app)
            worker=threading.Thread(target=httpd.serve_forever,daemon=True);worker.start()
            def call(method,url,data=None):
                conn=http.client.HTTPConnection('127.0.0.1',httpd.server_address[1],timeout=300)
                try:
                    conn.request(method,url,body=json.dumps(data).encode() if data is not None else None)
                    response=conn.getresponse();return response.status,response.read()
                finally:conn.close()
            try:
                url='/api/projects/'+pid+'/iiix-candidate'
                status,body=call('POST',url,dict(expected_changes=changes,recipe_extension=True))
                self.assertEqual(status,200,body[:2000]);manifest=json.loads(body)
                self.assertEqual(manifest['model'],'GR IIIx')
                self.assertEqual(app.template['model'],'GR III') # no global model switch
                self.assertTrue(all(c['ok'] is True for c in manifest['checks']))
                snapshots=manifest['film_recipe_archive']['snapshots']
                self.assertEqual({s['film'] for s in snapshots},{'5203',historical['id'],lid,graded['id']})
                import base64
                old=R.decode(base64.b64decode(next(s for s in snapshots if s['slot']==9)['packet_base64']))['profile']
                self.assertEqual(old['data_notices'],historical['data_notices'])
                for k in ('look_matrix_q13','post_matrix_q512'):self.assertEqual(old[k],historical[k])
                baked=R.decode(base64.b64decode(next(s for s in snapshots if s['slot']==11)['packet_base64']))['profile']
                self.assertEqual(baked['recipe_derivation']['source']['id'],'gold200')
                self.assertEqual(baked['recipe_derivation']['grade'],{'exp':10})
                from darkslide import film_profiles
                source_recipe=R.decode(R.encode(film_profiles.load_profile('gold200',models.GR3X.id),11))['profile']
                self.assertEqual(baked['data_notices'],source_recipe['data_notices'])
                status,output=call('GET','/api/builds/'+manifest['build_id']+'/firmware')
                self.assertEqual(status,200);self.assertEqual(G.sha(output),manifest['output_sha256'])
                path=app.store.build_path(manifest['build_id'],'manifest.json')
                changed=copy.deepcopy(manifest);changed['checks'][0]['ok']=False;write_json(path,changed)
                status,_=call('GET','/api/builds/'+manifest['build_id']+'/firmware');self.assertGreaterEqual(status,400)
                print('HTTP_MIXED_CANDIDATE',manifest['output_sha256'],manifest['decoded_growth_bytes'],flush=True)
            finally:httpd.shutdown();httpd.server_close();worker.join()

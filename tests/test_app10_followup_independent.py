"""Port missing v07 rejection coverage to the 1.0 readonly endpoint."""
import copy,os,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_app10_independent as fixtures
from darkslide import server,fwread,inplace_generation

class EndpointRefusals(unittest.TestCase):
    setUp=fixtures.PersistedSources.setUp
    save=fixtures.PersistedSources.save
    def request(self,changes):
        # 1.0 now requires an explicit body before any readonly check (HDF guard).
        self.store.set_target_body(self.pid,'GR III',self.template);self.save(changes)
        return SimpleNamespace(store=self.store,app=SimpleNamespace(template=self.template),read_json=lambda:dict(expected_changes=copy.deepcopy(changes),request_id='followup'))
    def test_corrupt_original_refused_before_unpack_or_prepare(self):
        req=self.request({'8':{'film':'gold200'}})
        with patch.object(self.store,'input_path') as path,patch.object(fwread,'unpack',side_effect=AssertionError('decode')) as unpack,patch.object(inplace_generation,'prepare',side_effect=AssertionError('prepare')) as prepare,patch.object(self.store,'put_build',side_effect=AssertionError('output')) as output:
            path.return_value.read_bytes.return_value=b'corrupted original'
            with self.assertRaisesRegex(server.ApiError,'校验失败'):server.api_film_prepare(req,self.pid)
            unpack.assert_not_called();prepare.assert_not_called();output.assert_not_called()
    @unittest.skipUnless(os.environ.get('DARKSLIDE_API_ORIGINAL'),'official source required')
    def test_out_of_range_user_profile_refused_at_all_four_positions(self):
        bad=copy.deepcopy(self.profile)
        bad['look_matrix_q13']=[[10000,-1808,0],[0,8192,0],[0,0,8192]]
        self.store.set_film_lut_fit(self.pid,self.ident,bad,self.fit,self.cube)
        for slot in range(8,12):
            req=self.request({str(slot):{'film':self.ident}})
            with patch.object(self.store,'input_path',return_value=Path(os.environ['DARKSLIDE_API_ORIGINAL'])),patch.object(self.store,'put_build',side_effect=AssertionError('output')) as output:
                with self.assertRaisesRegex(server.ApiError,'矩阵超出原厂数值边界'):server.api_film_prepare(req,self.pid)
                output.assert_not_called()

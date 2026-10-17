from firmware_registry_fixture import base_identity
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from darkslide import base_curve as module
from darkslide._vendor.gr3_base_emulator import OriginalEmulator
import test_base_curve as fixtures


class BaseSettingsTests(unittest.TestCase):
    def setUp(self):module._CACHE.clear()

    def test_invalid_settings_rejected_before_original_or_backend(self):
        for settings in ([], 0, {"tone":11}, {1:0}, {"key":True}, {"key":1.0},
                         {"key":float("nan")}, {"contrast":-5}, {"highlight":5}):
            with patch.object(module.Path,"resolve",side_effect=AssertionError("no file read")):
                with self.assertRaises(module.BaseCurveError):module.base_curve("absent.bin",settings)

    def test_cache_separates_requests_and_normalizes_missing_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path,file,neutral=fixtures.BaseCurveTests()._fixture(d)
            responses=[]
            def worker(argv,**kwargs):
                if argv[-1]==json.dumps(neutral["backend"]):result=copy.deepcopy(neutral)
                else:
                    sliders=json.loads(argv[-1]);responses.append(sliders)
                    result=copy.deepcopy(neutral);result["model_id"]=module.SETTINGS_MODEL_ID
                    result["settings"]={"tone":11,"stage":1,"slider_neutral_encoding":4,
                        "slider_values":sliders,"slider_encodings":{k:v+4 for k,v in sliders.items()}}
                    result["values"][5]=100+sliders["contrast"]
                return SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr="")
            with base_identity(neutral["official_sha256"]), \
                 patch.object(module.importlib.util,"find_spec",return_value=SimpleNamespace(origin=str(file))), \
                 patch.object(module.subprocess,"run",side_effect=worker) as run:
                old=module.base_curve(path)
                first=module.base_curve(path,{"contrast":2});first["values"][5]=999
                same=module.base_curve(path,{"shadow":0,"contrast":2,"highlight":0,"key":0})
                self.assertEqual(same["values"][5],102)
                self.assertEqual(module.base_curve(path,{"contrast":-2})["values"][5],98)
                self.assertEqual(module.base_curve(path)["values"],old["values"])
                self.assertEqual(run.call_count,3)
                self.assertEqual(responses,[{"key":0,"contrast":2,"highlight":0,"shadow":0},
                                            {"key":0,"contrast":-2,"highlight":0,"shadow":0}])

    def test_worker_cannot_return_other_settings_or_bool_encodings(self):
        with tempfile.TemporaryDirectory() as d:
            path,file,result=fixtures.BaseCurveTests()._fixture(d)
            selected={"key":0,"contrast":2,"highlight":-1,"shadow":0}
            result["model_id"]=module.SETTINGS_MODEL_ID
            result["settings"]={"tone":11,"stage":1,"slider_neutral_encoding":4,
                "slider_values":dict(selected),"slider_encodings":{"key":4,"contrast":6,"highlight":3,"shadow":4}}
            with base_identity(result["official_sha256"]):
                module._validate_result(result,result["official_sha256"],result["backend"],selected)
            for group,key,value in (("slider_values","contrast",-2),("slider_values","key",False),
                                    ("slider_encodings","shadow",4.0),("slider_encodings","key",True)):
                bad=copy.deepcopy(result);bad["settings"][group][key]=value
                with base_identity(result["official_sha256"]), self.assertRaises(module.BaseCurveError):
                    module._validate_result(bad,result["official_sha256"],result["backend"],selected)

    def test_guest_slider_guard_before_allocation(self):
        e=OriginalEmulator.__new__(OriginalEmulator)
        for sliders in ({0x77f:4}, {float(0x77f):4,0x780:4,0x781:4,0x782:4}, {0x77f:4,0x780:4,0x781:4,0x782:9},
                        {0x77f:True,0x780:4,0x781:4,0x782:4}):
            with self.assertRaises(ValueError):e.standard_base(sliders)

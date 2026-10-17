"""Scalar envelope contract, malformed input and defensive cache ownership."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
from darkslide import factory_envelope as env


def fixture():
    cells = {}
    def put(a, raw):
        cells.update((a+i, v) for i, v in enumerate(raw))
    matrices = []
    for i in range(15):
        record, matrix = 0x5501900C+i*84, 0x53DC2000+i*20
        put(env._PRIMARY+(11+i)*4, struct.pack('<I',record))
        put(record+4, struct.pack('<I',matrix))
        values = [8192, -i, i, 0, 8192+i, 0, 0, 0, 8192]
        put(matrix,struct.pack('<9h',*values));matrices.append(values)
    curves = []
    for i in range(12):
        a = 0x53EF1000+i*512
        put(env._LIBRARY+4*i,struct.pack('<I',a))
        values = [j*60+i for j in range(256)];values[1] = i-1 if i else 0
        put(a,struct.pack('<256H',*values));curves.append(values)
    # A compact test-only mapping; no factory arrays or firmware are used.
    addresses=sorted(cells); mapped={a:i for i,a in enumerate(addresses)}
    payload=bytes(cells[a] for a in addresses)
    class Source:
        def __init__(self, value):
            if value!=payload:raise ValueError('fixture changed')
        def off(self,a):return mapped[a]
    return cells, payload, Source, matrices, curves


class EnvelopeTests(unittest.TestCase):
    def tearDown(self):env._CACHE.clear()

    def test_actual_statistics_and_explicit_nonfactory_post(self):
        _,p,source,matrices,curves=fixture()
        with mock.patch.object(env.fwread,'Payload',source):v=env._statistics(p)
        steps=[b-a for c in curves for a,b in zip(c,c[1:])]
        self.assertEqual(v['look_min'],-14)
        self.assertEqual(v['look_max'],8206)
        self.assertEqual(v['look_row_abs_max'],8220)
        self.assertEqual((v['curve_step_min'],v['curve_step_max']),(min(steps),max(steps)))
        self.assertFalse(v['provenance']['post']['factory_comparable'])
        self.assertEqual((v['post_min'],v['post_max'],v['post_col_abs_max']),(-8191,8191,8191))
        self.assertFalse(v['original_arrays_retained'])
        self.assertFalse(any(type(value) in (bytes,bytearray) for value in v.values()))

    def test_reject_input_before_decode(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input';p.write_bytes(b'x')
            with mock.patch.object(env.fwread,'unpack') as decode:
                with self.assertRaises(env.FactoryEnvelopeError):env.factory_envelope(p)
                with mock.patch.object(env,'_INPUT_BYTES',1):
                    with self.assertRaises(env.FactoryEnvelopeError):env.factory_envelope(p)
                decode.assert_not_called()
        with self.assertRaises(env.FactoryEnvelopeError):env.factory_envelope(None)

    def test_sha_cache_is_scalar_and_defensive(self):
        value=dict(look_min=-1,provenance=dict(post=dict(factory_comparable=False)))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input';p.write_bytes(b'x')
            with mock.patch.object(env,'_INPUT_BYTES',1), mock.patch.object(env.hashlib,'sha256') as digest, mock.patch.object(env.fwread,'unpack') as decode, mock.patch.object(env,'_statistics',return_value=value):
                digest.return_value.hexdigest.return_value=env.fwread.V210_INPUT_SHA256
                first=env.factory_envelope(p);first['look_min']=999;first['provenance']['post']['factory_comparable']=True
                second=env.factory_envelope(p)
                self.assertEqual(second['look_min'],-1)
                self.assertFalse(second['provenance']['post']['factory_comparable'])
                decode.assert_called_once()
                p.write_bytes(b'y');digest.return_value.hexdigest.return_value='0'*64
                with self.assertRaises(env.FactoryEnvelopeError):env.factory_envelope(p)
                decode.assert_called_once()

    def test_invalid_or_overlapping_pointer_rejected(self):
        cells,_,_,_,_=fixture()
        for value in (0,0x53EF1000,0x53EF11FE):
            bad=dict(cells);a=env._LIBRARY+4
            bad.update((a+i,v) for i,v in enumerate(struct.pack('<I',value)))
            addresses=sorted(bad);mapping={a:i for i,a in enumerate(addresses)};payload=bytes(bad[a] for a in addresses)
            class Source:
                def __init__(self,p):pass
                def off(self,a):return mapping[a]
            with mock.patch.object(env.fwread,'Payload',Source):
                with self.assertRaises(env.FactoryEnvelopeError):env._statistics(payload)


if __name__=='__main__':unittest.main()

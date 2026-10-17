"""Merged layout, full combinations and independent rejection of corrupt images."""
import copy
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
from darkslide import gr3x_recipe_candidate as C, gr3x_recipe_merge as M
from darkslide import gr3x_recipe_verify as V, photo_recipe_candidate_verify as B
from darkslide import film_profiles as F, models, package, template, photo_recipe as P, fwread


@unittest.skipUnless(os.environ.get('DARKSLIDE_GR3X_PAYLOAD'), 'IIIx original payload required')
class Bindings(unittest.TestCase):
    def test_all_masks_resolve_exact_four_conflicts(self):
        raw=Path(os.environ['DARKSLIDE_GR3X_PAYLOAD']).read_bytes()
        profiles={f:F.load_profile(f,models.GR3X.id) for f in ('5207','5219','gold200','pro400h')}
        for mask in range(16):
            edits=[dict(kind='film',slot=s,film=f) for s,f in zip(range(8,12),profiles) if mask&(1<<(s-8))]
            result=M.prepare(raw,edits,profiles);ext=result['extension']
            expected,body,catalog=B._binding_contract(ext['native'],tuple(e['slot'] for e in edits),True)
            self.assertEqual(ext['extension'][64:catalog-ext['address']],body)
            self.assertEqual({w.address:int.from_bytes(w.replacement,'little') for w in ext['windows']},expected)
            self.assertEqual(set(result['overlap']),({0x536e87c4,0x536e4774} if mask else set())|
                             ({0x536dc27c,0x535131fc} if mask&4 else set()))


@unittest.skipUnless(os.environ.get('DARKSLIDE_IIIX_BIN'), 'IIIx official BIN required')
class Candidate(unittest.TestCase):
    def test_full_combination_and_tamper_rejection(self):
        official=Path(os.environ['DARKSLIDE_IIIX_BIN']).read_bytes();t=template.load('gr3x_v160.json')
        edits=[dict(kind='film',slot=s,film=f) for s,f in zip(range(8,12),('5207','5219','gold200','pro400h'))]
        slot=next(s for s in t['slots'] if s['no']==8)
        reader=fwread.Payload(fwread.unpack(official),models.layout(models.GR3X))
        _,pixels=reader.icon_pixels(slot['icon_id'])
        rgba=bytearray(fwread.icon_to_rgba(pixels))
        for i in range(0,len(rgba),4):
            if rgba[i+3]:rgba[i]^=127
        edits += [dict(kind='name',slot=8,string_id=slot['string_id'],text='NEW FILM'),
                  dict(kind='icon',slot=8,icon_id=slot['icon_id'],pixels=bytes(rgba)),
                  dict(kind='grain_menu',slot=12,mode=22)]
        jpeg=(Path(__file__).parent/'fixtures/shutdown_gradient.jpg').read_bytes()
        captured=[];verify=V.verify
        def record(*args,**kw):
            captured.append(args);return verify(*args,**kw)
        with patch.object(V,'verify',side_effect=record):
            result=C.build(official,edits,t,shutdown_jpeg=jpeg,experimental_recipe=True)
        self.assertTrue(all(c['ok'] for c in result['checks']+result['base_checks']))
        self.assertEqual(len(result['overlap_addresses']),4)
        self.assertEqual(result['curve_growth_bytes'],0);self.assertGreater(result['recipe_extension_bytes'],0)
        self.assertFalse(result['product_download_enabled'])
        self.assertFalse(result['physical_camera_tested'])
        source=package.Package.read(official,models.GR3X.id)
        def wire(data):
            data=package.close_words(bytes(data[:-4]));frames=package.raw_frames(data)+b'\0\0'
            footer=struct.pack('<5I',source.trailer.project,source.trailer.sentinel,source.trailer.operation,len(frames),len(data))
            return package.close_words(source.header+frames+bytes((-len(frames))%4)+source.auxiliary+footer)
        for name,index,address in (('getter',1,0x536e87c4),('matrix',1,0x536e4774),
                ('JPEG',1,0x53603a78),('HDR',1,0x536dc27c),('unknown',1,0x53002000),('recovery',1,0x53620100),
                ('curve_data',2,0x53dc2bf8),('undeclared_curve',2,0x53002000)):
            args=list(captured[0]);data=bytearray(V.fwread.unpack(args[index]))
            data[0x10870+address-0x53000000]^=1;args[index]=wire(data)
            with self.subTest(name=name):self.assertFalse(all(c['ok'] for c in verify(*args)))
        args=list(captured[0]);args[7]=dict(args[7]);snap=P.decode(args[7][8])['profile']
        snap['curves_u14'][0][12]+=1;args[7][8]=P.encode(snap,8)
        self.assertFalse(all(c['ok'] for c in verify(*args)))
        args=list(captured[0]);args[1]=args[1][:-4]+b'bad!'
        self.assertFalse(all(c['ok'] for c in verify(*args)))
        print('MERGED_COMBINATION',result['output_sha256'],result['recipe_extension_bytes'])

    def test_restore_only_container_without_current_catalog(self):
        result=C.build(Path(os.environ['DARKSLIDE_IIIX_BIN']).read_bytes(),[],
                       template.load('gr3x_v160.json'),experimental_recipe=True)
        self.assertTrue(all(c['ok'] for c in result['checks']))
        self.assertEqual(result['overlap_addresses'],[])
        self.assertEqual(result['snapshot_numeric_sha256'],{})


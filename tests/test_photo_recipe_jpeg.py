import copy
import io
import struct
import unittest
import zlib
from unittest.mock import patch
try:
    from PIL import Image
except ImportError:  # Pillow is only needed by these tests, not by the program
    raise unittest.SkipTest("Pillow not installed")
from darkslide import photo_recipe_jpeg as J, photo_recipe as P, film_profiles as F, models, server
import test_iiix_desktop as desktop
request = desktop.request


def packet_of_size(packet, size):
    """Valid JSON whitespace stretches the metadata to a boundary, no fake CRC."""
    extra = size-len(packet)
    if extra < 0:
        raise ValueError('fixture size too small')
    b = bytearray(packet[:-4]+b' '*extra+b'\0'*4)
    struct.pack_into('<I', b, 20, len(b)-1600)
    struct.pack_into('<I', b, len(b)-4, zlib.crc32(b[:-4]))
    P.decode(bytes(b))
    return bytes(b)


def segments(packet, pad=0):
    parts = []
    count = (len(packet)+59999)//60000
    for i in range(count):
        chunk = packet[i*60000:(i+1)*60000]
        last = i+1 == count
        value = struct.pack('<8s4B3I', b'DSRECIPE', 1, i, count, pad if last else 0,
                            len(packet), i*60000, len(chunk))+chunk
        if last:
            value += bytes(pad)+b'\xff\xd8'
        parts.append(b'\xff\xef'+struct.pack('>H', len(value)+2)+value)
    return parts


def jpeg(packet=None, *, model='RICOH GR IIIx', pad=0, progressive=False):
    stream = io.BytesIO()
    exif = Image.Exif()
    exif[272] = model
    Image.new('RGB', (8, 8), (72, 90, 120)).save(stream, format='JPEG', exif=exif, progressive=progressive)
    original = stream.getvalue()
    return original[:2]+(b''.join(segments(packet, pad)) if packet else b'')+original[2:]


class Reader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = P.encode(F.load_profile('gold200', models.GR3X.id), 8)

    def test_one_and_two_segments_both_scan_types_and_padding(self):
        for size in (len(self.packet), 60000, 60001, P.MAX_PACKET):
            packet = packet_of_size(self.packet, size)
            for pad in (0, 1, 31):
                for progressive in (False, True):
                    data = jpeg(packet, pad=pad, progressive=progressive)
                    self.assertEqual(J.extract(data), packet)
                    Image.open(io.BytesIO(data)).load()

    def test_all_catalog_profiles_and_slots(self):
        for film in F.ready_profile_ids():
            for slot in range(8, 12):
                packet = P.encode(F.load_profile(film, models.GR3X.id), slot)
                self.assertEqual(J.extract(jpeg(packet)), packet)

    def test_chunks_missing_reordered_duplicated_conflicted_and_crc(self):
        packet = packet_of_size(self.packet, P.MAX_PACKET)
        a, b = segments(packet)
        base = jpeg()
        bads = [a, b, b+a, a+a+b, a+b+b, a+segments(self.packet)[0]]
        corrupt = bytearray(a+b);corrupt[80] ^= 1;bads.append(bytes(corrupt))
        for payload in bads:
            with self.subTest(bytes=len(payload)), self.assertRaises(ValueError):
                J.extract(base[:2]+payload+base[2:])

    def test_headers_padding_model_and_jpeg_boundaries(self):
        good = jpeg(self.packet, pad=31)
        for at, val in ((14, 2), (15, 1), (16, 0), (17, 32), (18, 0), (22, 1), (26, 0)):
            b = bytearray(good);b[at] = val
            with self.subTest(at=at), self.assertRaises(ValueError):J.extract(bytes(b))
        bad = bytearray(good);bad[2+len(segments(self.packet,31)[0])-3] = 1
        with self.assertRaises(ValueError):J.extract(bytes(bad))
        for data in (good[:-2], good+b'junk', good[:10], b'\xff\xd8\xff\xd9',
                     jpeg(self.packet, model='RICOH GR III'), jpeg()):
            with self.assertRaises(ValueError):J.extract(data)
        # Valid packet bytes hidden in entropy are never accepted as metadata.
        base = jpeg();fake = base[:-2]+self.packet+base[-2:]
        with self.assertRaises(ValueError):J.extract(fake)
        # A second EXIF, even agreeing, is ambiguous.
        exif = next(base[a:b] for mark, p, a, b, scan in J.markers(base) if mark == 0xe1)
        with self.assertRaises(ValueError):J.extract(good[:2]+exif+good[2:])
        with self.assertRaises(ValueError):J.extract(base[:-2]+b''.join(segments(self.packet))+base[-2:])


class Import(unittest.TestCase):
    setUp = desktop.Desktop.setUp
    def test_jpeg_import_exact_packet_catalog_independence_and_rejection(self):
        with patch.object(F, 'load_profile', side_effect=AssertionError('catalog lookup')):
            restored = server.api_import_photo_recipe(request(self.app, data=jpeg(self.packet)), self.pid)
        rid = restored['id']
        path = self.app.store._dir(self.pid)/'photo_recipes'/(rid+'.dsfr')
        self.assertEqual(path.read_bytes(), self.packet)
        self.assertEqual(restored['data_notices'], P.decode(self.packet)['profile']['data_notices'])
        self.assertEqual(restored['curves_u14'], self.profile['curves_u14'])
        for data in (jpeg(), jpeg(self.packet)[:-2], jpeg(self.packet, model='RICOH GR III')):
            with self.assertRaises(server.ApiError):server.api_import_photo_recipe(request(self.app, data=data), self.pid)
        with self.assertRaises(server.ApiError):server.api_import_photo_recipe(request(self.app, data=jpeg(self.packet)), self.gr3)
        self.assertEqual(len(self.app.store.list_photo_recipes(self.pid)), 1)
        self.assertFalse(self.app.store.builds())

    def test_real_http_jpeg_import_export_and_bad_input(self):
        import http.client
        import threading
        import json
        import zipfile
        httpd=server.LocalServer(('127.0.0.1',0),self.app)
        worker=threading.Thread(target=httpd.serve_forever,daemon=True);worker.start()
        def call(path,body):
            conn=http.client.HTTPConnection('127.0.0.1',httpd.server_address[1],timeout=30)
            try:
                conn.request('POST',path,body=body)
                response=conn.getresponse();return response.status,response.read()
            finally:conn.close()
        try:
            url='/api/projects/'+self.pid+'/photo-recipes'
            status,data=call(url,jpeg(self.packet));self.assertEqual(status,200,data)
            rid=__import__('json').loads(data)['id']
            status,data=call(url+'/'+rid+'/export',json.dumps({'cube':desktop.CUBE.decode(),'grade':{}}).encode())
            self.assertEqual(status,200,data[:100])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(archive.read('film_data/restored-profile.dsfr'),self.packet)
            for bad in (jpeg(),jpeg(self.packet)[:-2]):
                status,data=call(url,bad);self.assertEqual(status,422,data)
            self.assertEqual(len(self.app.store.list_photo_recipes(self.pid)),1)
        finally:httpd.shutdown();httpd.server_close();worker.join()

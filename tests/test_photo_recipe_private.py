"""Private carrier parser checks; fixtures contain no sensor or firmware data."""
import struct
import unittest
from darkslide import film_profiles, models, photo_recipe as R, photo_recipe_dng as D
from test_photo_recipe import fixture


def private_blob(packet, endian='<', duplicate=False):
    rows = [(0x4f, 3, 1, 18), (0xd534, 7, len(packet), 0)]
    if duplicate:
        rows.append(rows[-1])
    end = 14+12*len(rows)
    out = bytearray(b'RICOH\0'+(b'II' if endian=='<' else b'MM'))
    out.extend(struct.pack(endian+'H', len(rows)))
    for tag, kind, count, value in rows:
        if tag == 0xd534:
            value = end
            out.extend(struct.pack(endian+'HHII',tag,kind,count,value))
        else:
            out.extend(struct.pack(endian+'HHI',tag,kind,count)+struct.pack(endian+'H',value)+bytes(2))
    out.extend(bytes(4));out.extend(packet)
    return bytes(out)


def carrier(blob, endian='<', xmp=None):
    out=bytearray(fixture(endian));start=len(out);out.extend(blob)
    struct.pack_into(endian+'HHII',out,46,50740,1,len(blob),start)
    if xmp is not None:
        # Construct the root independently of the product's XMP embedder.
        root=out[10:58];at=len(out);out.extend(xmp);end=len(out)
        out.extend(struct.pack(endian+'H',5)+root+struct.pack(endian+'HHII',700,1,len(xmp),at)+bytes(4))
        struct.pack_into(endian+'I',out,4,end)
    return bytes(out)


class PrivateRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=R.encode(film_profiles.load_profile('gold200',models.GR3X.id),8)

    def test_outer_and_private_byte_orders_are_independent(self):
        for outer in ('<','>'):
            for inner in ('<','>'):
                with self.subTest(outer=outer,inner=inner):
                    self.assertEqual(D.extract(carrier(private_blob(self.packet,inner),outer)),self.packet)

    def test_all_profiles_and_slots(self):
        for name in film_profiles.ready_profile_ids():
            for slot in range(8,12):
                packet=R.encode(film_profiles.load_profile(name,models.GR3X.id),slot)
                self.assertEqual(D.extract(carrier(private_blob(packet))),packet)

    def test_xmp_coexistence_and_conflict(self):
        blob=private_blob(self.packet)
        self.assertEqual(D.extract(carrier(blob,xmp=D._xmp(self.packet))),self.packet)
        self.assertEqual(D.extract(carrier(blob,xmp=b'<metadata/>')),self.packet)
        other=R.encode(film_profiles.load_profile('5207',models.GR3X.id),8)
        with self.assertRaisesRegex(ValueError,'冲突'):
            D.extract(carrier(blob,xmp=D._xmp(other)))
        for bad in (b'<bad',b'<!DOCTYPE a><a/>'):
            with self.assertRaises(ValueError):D.extract(carrier(blob,xmp=bad))

    def test_private_bounds_duplicates_type_crc_and_directory_alias(self):
        good=private_blob(self.packet)
        bads=[good[:n] for n in (8,9,13,25,37,len(good)-1)]
        bads.append(private_blob(self.packet,duplicate=True))
        for at,fmt,value in [(8,'H',65535),(24,'H',1),(26,'I',0),(26,'I',0xffffffff),
                             (30,'I',0xffffffff),(30,'I',10),(34,'I',8)]:
            bad=bytearray(good);struct.pack_into('<'+fmt,bad,at,value);bads.append(bytes(bad))
        bad=bytearray(good);bad[-1]^=1;bads.append(bytes(bad))
        # Recognized malformed private data cannot be concealed by valid XMP.
        for bad in bads:
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):
                D.extract(carrier(bad,xmp=D._xmp(self.packet)))
        bad=bytearray(good)
        struct.pack_into('<HHII',bad,10,0x4f,7,8,38)
        with self.assertRaisesRegex(ValueError,'重叠'):D.extract(carrier(bytes(bad)))

    def test_missing_or_unrecognized_carrier_and_copy_only_embed(self):
        with self.assertRaisesRegex(ValueError,'未保存'):D.extract(carrier(b'Other metadata'))
        src=carrier(private_blob(self.packet));after=D.embed(src,self.packet)
        self.assertEqual(D.extract(after),self.packet)
        self.assertEqual(after[8:len(src)],src[8:])
        other=R.encode(film_profiles.load_profile('5207',models.GR3X.id),8)
        with self.assertRaisesRegex(ValueError,'冲突'):D.embed(src,other)

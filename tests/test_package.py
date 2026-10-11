"""Format boundary and fixed-image-size regression tests."""
import unittest
from pathlib import Path
from darkslide import jpeg_profile, package, shared_shutdown


class CheckWords(unittest.TestCase):
    def test_additive_completion(self):
        for data in (bytes(0), bytes(4), b'abcd', b'abcdefghijkl', b'\xff' * 16):
            result = package.close_words(data)
            self.assertEqual(result[:-4], data)
            self.assertEqual(package.word_total(result), 0)
        with self.assertRaises(package.PackageError):
            package.close_words(b'x')

    def test_literal_extent_and_terminators(self):
        block = b'x' * (24576 * 2 + 10)
        encoded = package.raw_frames(block)
        sizes, decoded, cursor = [], bytearray(), 0
        while cursor < len(encoded):
            label = int.from_bytes(encoded[cursor:cursor + 2], 'big')
            cursor += 2
            self.assertTrue(label >= 32768)
            sizes.append(label & 32767)
            decoded.extend(encoded[cursor:cursor + sizes[-1]])
            cursor += sizes[-1]
        self.assertEqual(sizes, [24576, 24576, 10])
        self.assertEqual(bytes(decoded), block)


class CommentPlan(unittest.TestCase):
    def test_extents_and_boundaries(self):
        for missing in (0, 4, 5, 65536, 65537, 65538, 65539, 65540, 65541, 112509):
            sizes = jpeg_profile.comment_sizes(missing)
            self.assertEqual(sum(sizes), missing)
            self.assertTrue(all(4 <= size <= 65537 for size in sizes))
        self.assertEqual(jpeg_profile.comment_sizes(65538), [65533, 5])
        self.assertEqual(jpeg_profile.comment_sizes(65539), [65533, 6])
        self.assertEqual(jpeg_profile.comment_sizes(65540), [65533, 7])
        for missing in (1, 2, 3, -1, True, 4.0):
            with self.assertRaises(jpeg_profile.ProfileError):
                jpeg_profile.comment_sizes(missing)

    def test_preserves_existing_nonzero_comment(self):
        image = (Path(__file__).parent / 'fixtures/shutdown_gradient.jpg').read_bytes()
        comment = bytes.fromhex('fffe0005') + b'abc'
        submitted = image[:2] + comment + image[2:]
        padded = shared_shutdown.pad_jpeg(submitted)
        cut = jpeg_profile.inspect(submitted)['sos_offset']
        new_cut = jpeg_profile.inspect(padded)['sos_offset']
        self.assertEqual(padded[:cut], submitted[:cut])
        self.assertEqual(padded[new_cut:], submitted[cut:])
        self.assertEqual(len(padded), shared_shutdown.CAPACITY)

    def test_no_header_alias_or_extra_frame(self):
        image = (Path(__file__).parent / 'fixtures/shutdown_gradient.jpg').read_bytes()
        frame = next(s for s in jpeg_profile.segments_of(image) if s.code == 192)
        duplicated = image[:2] + image[frame.start:frame.following] + image[2:]
        for value in (None, bytearray(image), duplicated):
            with self.assertRaises(shared_shutdown.SharedSlotError):
                shared_shutdown.jpeg_contract(value)


if __name__ == '__main__':
    unittest.main()

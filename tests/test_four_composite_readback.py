"""Four-look readback through the real combined verifier on artificial data.

The container/unpack and resource discovery boundaries use a synthetic reader.
Film opcodes, physical offsets, names, icons, full-payload comparison and sums
run normally. No official input or modified camera image is constructed.
"""
from contextlib import ExitStack
import copy
import hashlib
import struct
import unittest
from unittest.mock import patch

from darkslide import composite_verify as combined, film_four_validation as writer
from darkslide import film_four_verify as reader, film_requests, film_verify, template
from test_four_validation import fixture
from test_film_writer import profile


class CompositeFixture:
    def __init__(self):
        self.cells, self.read = fixture()
        self.template = template.load()
        self.edits = [dict(kind='film', slot=s, film='user_lut_' + str(s))
                      for s in (8, 9, 10, 11)]
        self.profiles = {e['film']: profile(e['film'], i * 10)
                         for i, e in enumerate(self.edits)}
        self.icons, self.strings = {}, {}
        end = max(film_verify.va_to_offset(a) for a in self.cells) + 1024
        body = bytearray((end + 3) // 4 * 4)
        for address, value in self.cells.items():
            body[film_verify.va_to_offset(address)] = value
        for no, slot in enumerate(self.template['slots'], 1):
            at = 0x20000 + no * 6400
            pixels = bytearray(6400)
            for y in range(2, 38):
                for x in range(1, 39):
                    i = (y * 40 + x) * 4
                    pixels[i:i + 4] = bytes((no, 20 + no, 30 + no, 255))
            body[at:at + 6400] = pixels
            self.icons[slot['icon_id']] = at
            for language, text in (('en', slot['factory_en']),
                                   ('zh-CN', 'Z' + str(no)), ('zh-TW', 'T' + str(no)),
                                   ('ja', 'J' + str(no))):
                index = (no - 1) * 4 + ('en', 'zh-CN', 'zh-TW', 'ja').index(language)
                rec, text_at = 0x1000 + index * 8, 0x4000 + index * 128
                value = text.encode('utf-16-le') + bytes(2)
                body[rec:rec + 8] = bytes((len(text) + 1, 1, 0, 0)) + struct.pack('<I', text_at)
                body[text_at:text_at + len(value)] = value
                self.strings[(slot['string_id'], language)] = rec
        self.before = self.finalize(body)
        self.official = bytes(128) + self.before
        owner = self

        class Payload:
            def __init__(self, value, pinned=True):
                self.p = value

            def off(self, address):
                return film_verify.va_to_offset(address)

            def icon_pixels(self, ident):
                at = owner.icons[ident]
                return dict(payload_offset=at), self.p[at:at + 6400]

            def string(self, ident, language):
                rec = owner.strings[(ident, language)]
                count = self.p[rec]
                at = struct.unpack_from('<I', self.p, rec + 4)[0]
                raw = self.p[at:at + count * 2]
                if len(raw) != count * 2 or raw[-2:] != bytes(2):
                    raise ValueError('synthetic string extent')
                return dict(text=raw[:-2].decode('utf-16-le'), length_byte=count,
                            text_offset=at, record_offset=rec)

        self.Payload = Payload
        self.regular = []
        for no in (8, 9, 10, 11):
            slot = self.template['slots'][no - 1]
            self.regular.append(dict(kind='name', slot=no, string_id=slot['string_id'],
                                     text='N' + str(no)))
            at = self.icons[slot['icon_id']]
            pixels = bytearray(self.before[at:at + 6400])
            for i in range(0, 6400, 4):
                if pixels[i + 3]:
                    pixels[i:i + 3] = bytes((200 + no, 80 + no, no))
            self.regular.append(dict(kind='icon', slot=no, icon_id=slot['icon_id'],
                                     pixels=bytes(pixels)))

    @staticmethod
    def finalize(value):
        body = bytearray(value)
        body[-4:] = ((-combined._sum32(body[:-4])) & 0xffffffff).to_bytes(4, 'little')
        return bytes(body)

    def candidate(self, profiles=None, regular=None):
        profiles = self.profiles if profiles is None else profiles
        regular = self.regular if regular is None else regular
        plan = writer.plan(self.read, self.edits, profiles)
        body = bytearray(self.before)
        for window in plan['windows']:
            at = film_verify.va_to_offset(window.address, len(window.replacement))
            body[at:at + len(window.replacement)] = window.replacement
        for edit in regular:
            if edit['kind'] == 'icon':
                at = self.icons[edit['icon_id']]
                body[at:at + 6400] = edit['pixels']
            else:
                rec = self.strings[(edit['string_id'], 'en')]
                zh = self.strings[(edit['string_id'], 'zh-CN')]
                tw = self.strings[(edit['string_id'], 'zh-TW')]
                at = struct.unpack_from('<I', body, rec + 4)[0]
                capacity = body[rec] * 2
                value = edit['text'].encode('utf-16-le') + bytes(2)
                body[at:at + capacity] = value + bytes(capacity - len(value))
                body[rec] = len(edit['text']) + 1
                body[zh:zh + 8] = bytes((len(edit['text']) + 1, 1, 0, 0)) + body[rec + 4:rec + 8]
                body[tw:tw + 8] = bytes((len(edit['text']) + 1, 1, 0, 0)) + body[rec + 4:rec + 8]
        return self.result(self.finalize(body))

    def result(self, after):
        out = bytes(128) + after
        return dict(output=out, output_sha256=hashlib.sha256(out).hexdigest(),
                    payload_sha256_after=hashlib.sha256(after).hexdigest(),
                    payload_changes=[dict(offset=0, length=len(after), kind='untrusted')],
                    film_layout='untrusted', selected_slots=[0])

    def verify(self, result, *, profiles=None, edits=None, layout='four_curve_v1'):
        profiles = self.profiles if profiles is None else profiles
        edits = self.edits + self.regular if edits is None else edits
        with ExitStack() as stack:
            stack.enter_context(patch.object(combined.fwread, 'V210_INPUT_SHA256',
                                              hashlib.sha256(self.official).hexdigest()))
            stack.enter_context(patch.object(combined.fwread, 'unpack', side_effect=lambda raw: raw[128:]))
            stack.enter_context(patch.object(combined.fwread, 'Payload', self.Payload))
            stack.enter_context(patch.object(combined, '_container',
                                              side_effect=lambda raw: ((1, 2, 3, 0, 5), (), len(raw))))
            stack.enter_context(patch.object(combined, '_resources', return_value=[]))
            return combined.verify(self.official, result, edits, self.template,
                                   film_profiles=profiles, film_layout=layout)

    @staticmethod
    def payload_reader(payload):
        def read(address, count):
            at = film_verify.va_to_offset(address, count)
            return payload[at:at + count]
        return read


class FourCombinedReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = CompositeFixture()
        cls.base = cls.f.candidate()

    def test_actual_combined_path_reads_four_films_names_icons_and_checksum(self):
        checks = self.f.verify(self.base)
        self.assertTrue(combined.all_ok(checks), checks)
        passed = {c['id'] for c in checks if c['ok']}
        self.assertTrue({'film_layout', 'entire_payload_matches_independent_request',
                         'readback_icons_names', 'payload_sum', 'file_sum'} <= passed)
        self.assertFalse(film_requests.available())

    def test_each_single_film_change_keeps_three_through_combined_path(self):
        for slot in (8, 9, 10, 11):
            with self.subTest(slot=slot):
                profiles = copy.deepcopy(self.f.profiles)
                ident = 'user_lut_' + str(slot)
                profiles[ident] = profile(ident, 150 + slot)
                profiles[ident]['look_matrix_q13'][0] = [8191, 1, 0]
                profiles[ident]['post_matrix_q512'][0] = [511, 1, 0]
                result = self.f.candidate(profiles)
                checks = self.f.verify(result, profiles=profiles)
                self.assertTrue(combined.all_ok(checks), checks)
                transition = reader.verify_transition(
                    self.f.read, self.f.payload_reader(self.base['output'][128:]),
                    self.f.payload_reader(result['output'][128:]), self.f.edits, self.f.edits,
                    self.f.profiles, profiles, changed_slots=[slot])
                self.assertTrue(transition.passed, transition.checks)
                for regular in self.f.regular:
                    if regular['kind'] == 'icon':
                        at, count = self.f.icons[regular['icon_id']], 6400
                        self.assertEqual(result['output'][128 + at:128 + at + count],
                                         self.base['output'][128 + at:128 + at + count])

    def test_other_film_or_protected_byte_cannot_hide_in_result_declarations(self):
        expectations = reader.derive_expected(self.f.read, self.f.edits, self.f.profiles)
        # These are actual data bytes, not plan metadata accepted as evidence.
        positions = [expectations.slots[1].matrix,
                     0x55037604, 0x55037634, 0x53D36400, 0x536EF900]
        for address in positions:
            with self.subTest(address=address):
                after = bytearray(self.base['output'][128:])
                after[film_verify.va_to_offset(address)] ^= 1
                result = self.f.result(self.f.finalize(after))
                self.assertFalse(combined.all_ok(self.f.verify(result)))

    def test_missing_or_swapped_four_request_refused(self):
        self.assertFalse(combined.all_ok(self.f.verify(
            self.base, edits=self.f.edits[:3] + self.f.regular)))
        swapped = copy.deepcopy(self.f.edits)
        swapped[0]['film'], swapped[1]['film'] = swapped[1]['film'], swapped[0]['film']
        self.assertFalse(combined.all_ok(self.f.verify(
            self.base, edits=swapped + self.f.regular)))

    def test_unrequested_regular_change_is_rejected_by_entire_payload_comparison(self):
        checks = self.f.verify(self.base, edits=self.f.edits)
        self.assertFalse(combined.all_ok(checks))
        self.assertTrue(any(c['id'] == 'entire_payload_matches_independent_request'
                            and c['ok'] is False for c in checks))

    def test_invalid_layout_and_incomplete_four_fail_before_unpack(self):
        for layout, edits in ((False, self.f.edits), ('unknown', self.f.edits),
                              ('four_curve_v1', []), ('four_curve_v1', self.f.edits[:3])):
            with patch.object(combined.fwread, 'V210_INPUT_SHA256',
                              hashlib.sha256(self.f.official).hexdigest()), \
                    patch.object(combined.fwread, 'unpack', side_effect=AssertionError('must not unpack')):
                checks = combined.verify(self.f.official, {}, edits, self.f.template,
                                         film_profiles=self.f.profiles, film_layout=layout)
                self.assertFalse(combined.all_ok(checks))

    def test_old_layout_cannot_accept_new_four_window_format(self):
        self.assertFalse(combined.all_ok(self.f.verify(self.base, layout='legacy_arena_v1')))


if __name__ == '__main__':
    unittest.main()

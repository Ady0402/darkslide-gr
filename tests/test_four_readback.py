"""Sparse independent App readback fixtures; no writer, compiler or ARM runs."""
import copy
from dataclasses import FrozenInstanceError, replace
import struct
import unittest
from unittest.mock import patch

from darkslide import film_four_verify as four
from darkslide import film_verify as legacy
from tests.test_film_verify import SparseOriginal, branch, half_move, profile, fixture_code as old_code


def inputs(shared=False):
    values = [profile(i + 1) for i in range(4)]
    edits = [dict(kind='film', slot=8 + i, film=values[0 if shared and i < 2 else i]['id'])
             for i in range(4)]
    return edits, {p['id']: p for p in values}


def original():
    source = SparseOriginal()
    source.put(0x536E87C4, struct.pack('<I', branch(0x536E87C4, 0x536EEDF0, link=True)))
    source.put(0x536E87C8, struct.pack('<I', 0xE51B3044))
    source.put(0x536DD024, struct.pack('<I', 0xE5C4100E))
    return source


def code(region):
    a = region.address
    if region.role == 'four_post':
        return old_code(region)
    if region.role == 'four_fill':
        words = [0xE2412012, 0xE3520004, branch(a + 8, a + 20, 3), 0xE3510015,
                 branch(a + 16, 0x536DD458), 0xE283390E, 0xE3A02002, 0xE5C32A98, 0xE89DAFF8]
    elif region.role == 'four_dirty':
        words = [0xE92D000C, 0xE10F3000, 0xE5D421A8, 0xE2422012, 0xE3520004,
                 0x33811001, 0xE128F003, 0xE8BD000C, 0xE5C4100E,
                 branch(a + 36, 0x536DD028)]
    elif region.role == 'four_getter':
        lookup, fallback = region.pointers
        words = [0xE92D41F0, 0xE1A04001, 0xE1A05002, 0xE1A06003, 0xE51BC048, 0xE59CC008,
                 half_move(2, lookup), half_move(2, lookup, True), 0xE5923000, 0xE3530000,
                 branch(a + 40, a + 100, 0), 0xE153000C, 0x02822004, branch(a + 52, a + 64, 0),
                 0xE2822010, branch(a + 60, a + 32), 0xE5923000, 0xE5843000, 0xE5923004,
                 0xE5853000, 0xE5923008, 0xE5863000, 0xE3A03000, 0xE5C03000, 0xE8BD81F0,
                 0xE1A01004, 0xE1A02005, 0xE1A03006, branch(a + 112, 0x536EEDF0, link=True),
                 half_move(7, fallback), half_move(7, fallback, True), 0xE1A00004,
                 branch(a + 128, four.REMAP, link=True), 0xE1A00005,
                 branch(a + 136, four.REMAP, link=True), 0xE1A00006,
                 branch(a + 144, four.REMAP, link=True), 0xE8BD81F0]
    elif region.role == 'four_point':
        words = [0xE52DE004, 0xE1A02320, 0xE35200FF, 0x23A020FF, 0xE200C03F,
                 0x23A0C000, 0xE1A031A2, 0xE081E083, 0xE2022007, 0xE1DE00B0,
                 0xE1DE30B2, 0xE0431000, 0xE0010192, 0xE08001C1, 0xE1DE10B0,
                 0xE0433001, 0xE2822001, 0xE0030392, 0xE08111C3, 0xE0411000,
                 0xE001019C, 0xE3510000, 0xB281103F, 0xE0800341, 0xE49DF004]
    elif region.role == 'four_composer':
        table, = region.pointers
        words = [0xE51B0048, 0xE5900008, half_move(1, table), half_move(1, table, True),
                 0xE5912000, 0xE3520000, branch(a+24,a+44,0), 0xE1500002,
                 branch(a+32,a+52,0), 0xE2811010, branch(a+40,a+16), 0xE51B3044,
                 branch(a+48,0x536E87CC), 0xE51B4044, 0xE51B703C, 0xE51B8038,
                 0xE51B9034, 0xE3A0A000]
        for reg, addword, weight in ((7,0xE2841C2A,77),(8,0xE2841B0B,150),(9,0xE2841C2E,29)):
            index=len(words)
            words += [0xE19400BA, 0xE1A01000 | reg, branch(a+(index+2)*4,four.POINT,link=True),
                      addword, 0xE2811008, 0xE18100BA, 0xE3A01000 | weight,
                      0xE0050190 if reg==7 else 0xE0255190]
        words += [0xE1A00445, 0xE2841A03, 0xE2811008, 0xE18100BA, 0xE28AA002,
                  0xE35A0C02, branch(a+192,a+72,1), branch(a+196,0x536E89CC)]
    elif region.role == 'four_remap':
        words = [0xE5901000, 0xE1A02007, 0xE3A03003, 0xE4928008, 0xE1510008,
                 0x05121004, 0x05801000, 0x012FFF1E, 0xE2533001,
                 branch(a + 36, a + 12, 1), 0xE12FFF1E]
    else:
        raise AssertionError('unknown golden role')
    result = struct.pack('<' + str(len(words)) + 'I', *words)
    if len(result) != region.size:
        raise AssertionError('golden extent differs')
    return result


def overlay(source, expected):
    cells = {}
    for w in expected.data_windows:
        cells.update({w.address + i: v for i, v in enumerate(w.data)})
    for c in expected.code_regions:
        cells.update({c.address + i: v for i, v in enumerate(code(c))})
    return cells, lambda a, n: bytes(cells.get(a + i, source.cells.get(a + i, 0)) for i in range(n))


class FourReadbackTests(unittest.TestCase):
    def setUp(self):
        self.source = original()
        self.edits, self.profiles = inputs()

    def expected(self, profiles=None, edits=None):
        return four.derive_expected(self.source.read, self.edits if edits is None else edits,
                                    self.profiles if profiles is None else profiles)

    def test_complete_readback_spans_source_and_frozen_snapshot(self):
        expected = self.expected()
        _, read = overlay(self.source, expected)
        result = four.readback_windows(self.source.read, read, expected)
        self.assertTrue(result.passed, result.checks)
        self.assertEqual(len(result.expected_windows), 49)
        self.assertEqual(sum(b - a for a, b in result.expected_spans), 2276)
        self.assertEqual(len(expected.protected_regions), 52)
        self.assertTrue(any(r.address == four.PRIMARY + 21 * 4 for r in expected.source_regions))
        self.assertLessEqual(self.source.max_read, 512)
        with self.assertRaises(FrozenInstanceError):
            expected.slots[0].record = 0
        self.profiles[self.edits[0]['film']]['curves_u14'][0][0] = 1234
        self.assertNotEqual(expected.slots[0].profile[1][0][0], 1234)
        self.assertTrue(four.readback_windows(self.source.read, read, expected).passed)

    def test_every_write_and_protected_region_mutation_fails(self):
        expected = self.expected()
        addresses = [w.address for w in expected.data_windows] + [c.address for c in expected.code_regions]
        addresses += [r.address for r in expected.protected_regions]
        for address in addresses:
            cells, read = overlay(self.source, expected)
            cells[address] = read(address, 1)[0] ^ 1
            result = four.readback_windows(self.source.read, read, expected)
            self.assertFalse(result.passed, hex(address))
            self.assertEqual((result.expected_windows, result.expected_spans), ((), ()))

    def test_every_new_instruction_is_decoded_and_layout_forgery_rejected(self):
        expected = self.expected()
        for region in expected.code_regions:
            if region.role == 'four_post':
                continue
            for offset in range(0, region.size, 4):
                cells, read = overlay(self.source, expected)
                a = region.address + offset
                cells[a] = read(a, 1)[0] ^ 1
                self.assertFalse(four.readback_windows(self.source.read, read, expected).passed, hex(a))
        _, read = overlay(self.source, expected)
        wrong = replace(expected, selected_slots=(8.0, 9, 10, 11))
        self.assertFalse(four.readback_windows(self.source.read, read, wrong).passed)
        wrong = replace(expected, data_windows=expected.data_windows[:-1])
        self.assertFalse(four.readback_windows(self.source.read, read, wrong).passed)
        configuration = list(expected.configuration)
        configuration[0] = (8.0, *configuration[0][1:])
        self.assertFalse(four.readback_windows(self.source.read, read,
                                             replace(expected, configuration=tuple(configuration))).passed)

    def test_old_seven_tone_enable_guard_is_rejected_by_both_readers(self):
        from pathlib import Path
        import sys
        tools = str(Path(__file__).resolve().parents[2] / 'tools')
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from verify_four_validation import _fill as tool_fill
        except ImportError:
            self.skipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")
        expected = self.expected()
        region = next(c for c in expected.code_regions if c.role == 'four_fill')
        corrected = code(region)
        four._fill(corrected)
        tool_fill(corrected)
        old = bytearray(corrected)
        struct.pack_into('<I', old, 4, 0xE3520007)
        for check in (four._fill, tool_fill):
            with self.assertRaises(ValueError):
                check(bytes(old))
        cells, read = overlay(self.source, expected)
        cells[region.address + 4] = 7
        rejected = four.readback_windows(self.source.read, read, expected)
        self.assertFalse(rejected.passed)
        self.assertEqual((rejected.expected_windows, rejected.expected_spans), ((), ()))

    def test_direct_point_and_composer_semantic_fields_fail_closed(self):
        expected = self.expected()
        point = next(c for c in expected.code_regions if c.role == 'four_point')
        composer = next(c for c in expected.code_regions if c.role == 'four_composer')
        # Clamp unsigned, preserve clamp flags, floor step-8, then trunc0 Q6;
        # stores and dispatch must retain the exact documented objects/targets.
        mutations = ((point, 0, 0xE52DE008), (point, 3, 0xA3A020FF),
                     (point, 4, 0xE210C03F), (point, 9, 0xE1DE00F0),
                     (point, 13, 0xE08001A1), (point, 16, 0xE2822002),
                     (point, 22, 0xE281103F), (point, 23, 0xE0800321),
                     (point, 24, 0xE49DF008), (composer, 0, 0xE51B0044),
                     (composer, 18, 0xE19400FA), (composer, 23, 0xE18100B8),
                     (composer, 24, 0xE3A0104E), (composer, 33, 0xE0050190),
                     (composer, 47, 0xE35A0C01),
                     (composer, 49, branch(composer.address+196, 0x536E89D0)))
        for region, index, word in mutations:
            cells, read = overlay(self.source, expected)
            address = region.address + 4*index
            cells.update((address+i, v) for i, v in enumerate(struct.pack('<I', word)))
            result = four.readback_windows(self.source.read, read, expected)
            self.assertFalse(result.passed, (region.role, index))
            self.assertEqual((result.expected_windows, result.expected_spans), ((), ()))
        getter = next(c for c in expected.code_regions if c.role == 'four_getter')
        with self.assertRaises(four.FilmReadbackError):
            four._getter(code(getter) + bytes(36), *getter.pointers)
        self.assertEqual([(p.address, p.size) for p in expected.protected_regions
                          if p.label in ('unused_fill', 'unused_post')],
                         [(four.FILL+176, 16), (four.POST+600, 68)])

    def test_missing_or_wrong_gamma_dirty_hook_is_rejected_by_both_readers(self):
        from pathlib import Path
        import sys
        tools = str(Path(__file__).resolve().parents[2] / 'tools')
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from verify_four_validation import _dirty as tool_dirty
        except ImportError:
            self.skipTest("开发仓库根目录 tools/ 下的独立核对工具不随发布包分发；在开发仓库里运行时这项测试照常执行")
        expected = self.expected()
        region = next(c for c in expected.code_regions if c.role == 'four_dirty')
        corrected = code(region)
        self.assertEqual((region.address, region.size), (four.FILL + 36, 40))
        tail = next(p for p in expected.protected_regions if p.label == 'unused_fill')
        self.assertEqual((tail.address, tail.size), (four.FILL + 176, 16))
        for check in (four._dirty, tool_dirty):
            check(corrected)
            with self.assertRaises(ValueError):
                check(corrected[:-4])
        wrong_fields = ((0, 0xE92D0004), (1, 0xE10F2000), (2, 0xE5D421A9),
                        (3, 0xE2522012), (4, 0xE3520007), (5, 0xE3811001),
                        (5, 0x33911001), (6, 0xE128F002), (7, 0xE8BD0004),
                        (8, 0xE5C4100F), (8, 0xE584100E), (9, branch(region.address + 36, 0x536DD02C)))
        for index, wrong in wrong_fields:
            bad = bytearray(corrected)
            struct.pack_into('<I', bad, index * 4, wrong)
            for check in (four._dirty, tool_dirty):
                with self.assertRaises(ValueError):
                    check(bytes(bad))
            cells, read = overlay(self.source, expected)
            cells.update((region.address + i, v) for i, v in enumerate(bad))
            rejected = four.readback_windows(self.source.read, read, expected)
            self.assertFalse(rejected.passed)
            self.assertEqual((rejected.expected_windows, rejected.expected_spans), ((), ()))
        wrong_source = original()
        wrong_source.put(0x536DD024, struct.pack('<I', 0xE5C4100F))
        with self.assertRaises(four.FilmReadbackError):
            four.derive_expected(wrong_source.read, self.edits, self.profiles)

    def test_request_profile_source_and_resolver_fail_closed(self):
        for edits in ([], self.edits[:3], [dict(e, slot=True) for e in self.edits], self.edits + self.edits[:1]):
            with self.assertRaises(four.FilmReadbackError):
                four.derive_expected(lambda *a: self.fail('read before rejecting edits'), edits, self.profiles)
            with self.assertRaises(four.FilmReadbackError):
                four.resolve_profiles(edits)
        for reader in (lambda a, n: b'', lambda a, n: bytearray(self.source.read(a, n))):
            with self.assertRaises(four.FilmReadbackError):
                four.derive_expected(reader, self.edits, self.profiles)
        bad = copy.deepcopy(self.profiles)
        bad[self.edits[0]['film']]['curves_u14'][0][0] = True
        with self.assertRaises(four.FilmReadbackError):
            self.expected(bad)
        with patch.object(legacy, 'load_profiles', return_value=self.profiles):
            resolved = four.resolve_profiles(self.edits)
        self.assertEqual(resolved, self.profiles)
        self.assertIsNot(resolved[self.edits[0]['film']], self.profiles[self.edits[0]['film']])
        with patch.object(legacy, 'load_profiles', side_effect=AssertionError('read before override rejection')):
            with self.assertRaises(four.FilmReadbackError):
                four.resolve_profiles(self.edits, self.profiles)
        expected = self.expected(); _, read = overlay(self.source, expected)
        self.source.put(0x536EB170, b'wrong')
        self.assertFalse(four.readback_windows(self.source.read, read, expected).passed)

    def test_one_changed_slot_keeps_other_three_and_dispatch(self):
        previous = self.expected(); _, before = overlay(self.source, previous)
        for index in range(4):
            following = copy.deepcopy(self.profiles)
            ident = self.edits[index]['film']
            following[ident]['curves_u14'][0][7] += 123
            next_expected = self.expected(following); _, after = overlay(self.source, next_expected)
            result = four.verify_transition(self.source.read, before, after, self.edits, self.edits,
                                            self.profiles, following, changed_slots=[8 + index])
            self.assertTrue(result.passed, result.checks)
            self.assertTrue(any(c['id'].startswith('previous_') for c in result.checks))
            self.assertTrue(any(c['id'].startswith('next_') for c in result.checks))
            for declared in ([], [8 + index, 8 + index], [True], [8 + ((index + 1) % 4)]):
                self.assertFalse(four.verify_transition(self.source.read, before, after, self.edits,
                    self.edits, self.profiles, following, changed_slots=declared).passed)

    def test_shared_id_change_requires_both_slots_and_bad_previous_is_distinct(self):
        edits, profiles = inputs(shared=True)
        previous = self.expected(profiles, edits); previous_cells, before = overlay(self.source, previous)
        following = copy.deepcopy(profiles)
        following[edits[0]['film']]['post_matrix_q512'] = [[511, 1, 0], [0, 512, 0], [0, 0, 512]]
        nxt = self.expected(following, edits); _, after = overlay(self.source, nxt)
        result = four.verify_transition(self.source.read, before, after, edits, edits, profiles, following,
                                        changed_slots=[8, 9])
        self.assertTrue(result.passed, result.checks)
        self.assertFalse(four.verify_transition(self.source.read, before, after, edits, edits,
                                               profiles, following, changed_slots=[8]).passed)
        previous_cells[four.GETTER + 16] ^= 1
        result = four.verify_transition(self.source.read, before, after, edits, edits, profiles, following,
                                        changed_slots=[8, 9])
        self.assertFalse(result.passed)
        self.assertTrue(any(c['id'] == 'previous_four_closed_failure' for c in result.checks))

    def test_modified_last_stability_read_mutating_original_is_rejected(self):
        expected = self.expected(); _, read = overlay(self.source, expected)
        target = expected.data_windows[0]
        counts, mutated = {}, []
        def modified(a, n):
            value = read(a, n); key = (a, n)
            counts[key] = counts.get(key, 0) + 1
            if key == (target.address, len(target.data)) and counts[key] == 2:
                self.source.cells[0x536EB170] ^= 1
                mutated.append(True)
            return value
        self.assertFalse(four.readback_windows(self.source.read, modified, expected).passed)
        self.assertEqual(mutated, [True])

    def test_original_later_dependency_mutating_earlier_dependency_is_rejected(self):
        expected = self.expected(); _, read = overlay(self.source, expected)
        counts, mutated = {}, []
        last = expected.source_regions[-1]
        def source(a, n):
            value = self.source.read(a, n); key = (a, n)
            counts[key] = counts.get(key, 0) + 1
            if key == (last.address, last.size) and counts[key] == 3:
                self.source.cells[0x536EB170] ^= 1
                mutated.append(True)
            return value
        self.assertFalse(four.readback_windows(source, read, expected).passed)
        self.assertEqual(mutated, [True])

    def test_transition_rejects_two_different_original_snapshots(self):
        expected = self.expected(); _, read = overlay(self.source, expected)
        calls, switched = [], []
        def source(a, n):
            if (a, n) == (four.LIBRARY, 48):
                calls.append(True)
                # Eight reads complete the previous capture, derive and stability
                # checks. Switch as the next capture begins, leaving each version
                # internally stable but backed by a different original snapshot.
                if len(calls) == 9:
                    self.source.put(four.PRIMARY, b'\x01')
                    switched.append(True)
            return self.source.read(a, n)
        result = four.verify_transition(source, read, read, self.edits, self.edits,
                                        self.profiles, self.profiles, changed_slots=[])
        self.assertFalse(result.passed, result.checks)
        self.assertEqual(switched, [True])
        self.assertTrue(all(c['ok'] is True for c in result.checks[:-1]), result.checks)
        self.assertIn('different original snapshots', result.checks[-1]['detail'])


if __name__ == '__main__':
    unittest.main()

"""Independent four-look App readback and single-slot transition checks.

This module never imports a writer, planner, fitter, assembler or development
CLI. It checks guarded v2.10 source callbacks; whole-file identity and all other
payload differences remain the combined verifier's responsibility.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import struct
from . import film_verify as _legacy
from .film_verify import (
    FilmReadbackError, FilmReadbackResult, ExpectedWindow, CodeRegion,
    ProtectedRegion, va_to_offset, _check_post, _code_words, _dp, _mov16,
    _memory, _multiply,
)

FILL, POST = 0x536EF61C, 0x536EF6FC
DIRTY = FILL + 36
GETTER, POINT, REMAP, COMPOSER = 0x536EF7C8, 0x536EF668, 0x536EF860, 0x536EF88C
LIBRARY, PRIMARY, STANDARD, BOOT_TAIL = 0x55037604, 0x55018D94, 0x5501900C, 0x53DC27A4
SLOTS = (8, 9, 10, 11)
BINDINGS = ((18, 22, 23), (19,), (20, 24), (21,))


def _need(ok, message):
    if not ok:
        raise FilmReadbackError(message)


def _word(value):
    return struct.pack('<I', value)


def _matrix(rows):
    return struct.pack('<9h', *(v for row in rows for v in row))


def _branch(at, target, *, condition=14, link=False):
    delta = target - at - 8
    _need(delta % 4 == 0 and -(1 << 25) <= delta < (1 << 25), 'branch range')
    return condition << 28 | (11 if link else 10) << 24 | (delta // 4 & 0xFFFFFF)


class _Source:
    def __init__(self, read):
        _need(callable(read), 'immutable original callback required')
        self.callback, self.seen = read, {}

    def read(self, address, size):
        va_to_offset(address, size)
        parts = []
        for start in range(0, size, 512):
            count = min(512, size - start)
            at = address + start
            value = self.callback(at, count)
            _need(type(value) is bytes and len(value) == count, 'strict complete source bytes')
            key = (at, count)
            _need(key not in self.seen or self.seen[key] == value, 'source changed within derivation')
            self.seen[key] = value
            parts.append(value)
        return b''.join(parts)

    def stable(self):
        for (at, size), value in tuple(self.seen.items()):
            _need(self.read(at, size) == value, 'source changed within derivation')


def _edits(edits):
    clean = _legacy._edits(edits)
    _need(tuple(slot for slot, ident in clean) == SLOTS, 'complete current four-film configuration required')
    return clean


def resolve_profiles(edits, supplied=None):
    _edits(edits)
    return _legacy.resolve_profiles(edits, supplied)


@dataclass(frozen=True)
class FourSlotExpectation:
    slot: int
    film: str
    record: int
    matrix: int
    knots: tuple
    aliases: tuple
    post_entry: int
    profile: tuple


@dataclass(frozen=True)
class FourExpectations:
    data_windows: tuple
    code_regions: tuple
    expected_spans: tuple
    protected_regions: tuple
    selected_slots: tuple
    slots: tuple
    configuration: tuple
    source_regions: tuple


def _layout(pointers):
    a, b, c = pointers[3:6]
    return ((8, a + 408, a + 492, (a, a + 68, a + 136)),
            (9, b + 408, b + 492, (a + 204, a + 272, a + 340)),
            (10, c, c + 84, (b, b + 68, b + 136)),
            (11, c + 104, c + 188, (b + 204, b + 272, b + 340))), c + 208, c + 328


def _expected_knots(curve):
    """Independent dense exact normal equations, not a tridiagonal fitter."""
    coefficients = [[0 for _ in range(33)] for _ in range(33)]
    rhs = [0 for _ in range(33)]
    for sample, value in enumerate(curve):
        left, fraction = divmod(sample, 8)
        weights = ((left, 8 - fraction), (left + 1, fraction))
        for i, wi in weights:
            rhs[i] += wi * value * 8
            for j, wj in weights:
                coefficients[i][j] += wi * wj
    # A generic row elimination differs from the generator's separate diagonals.
    for column in range(33):
        pivot = coefficients[column][column]
        _need(pivot != 0, 'rational fit singular')
        for row in range(column + 1, 33):
            entry = coefficients[row][column]
            if entry == 0:
                continue
            ratio = Fraction(entry, pivot)
            for j in range(column, 33):
                coefficients[row][j] -= ratio * coefficients[column][j]
            rhs[row] -= ratio * rhs[column]
    solution = [Fraction(0) for _ in range(33)]
    for row in range(32, -1, -1):
        value = rhs[row] - sum(coefficients[row][j] * solution[j] for j in range(row + 1, 33))
        solution[row] = Fraction(value, coefficients[row][row])
    return tuple(min(16383, max(0, (2 * v.numerator + v.denominator) // (2 * v.denominator)))
                 for v in solution)


def _rebuild(knots):
    _need(len(knots) == 33 and all(type(v) is int and 0 <= v <= 16383 for v in knots),
          'strict 33 u14 stored points')
    values = []
    for i in range(256):
        k, t = divmod(i, 8)
        values.append(knots[k] + ((knots[k + 1] - knots[k]) * t // 8))
    return tuple(values)


def _errors(knots, curve):
    differences = [v - source for v, source in zip(_rebuild(knots), curve)]
    squares = sum(v * v for v in differences)
    return dict(max_abs_u14=max(abs(v) for v in differences),
                rms_u14=math.sqrt(squares / 256), lossless=squares == 0)


def _branch_check(word, at, target, *, condition=14, link=False):
    _need(word == _branch(at, target, condition=condition, link=link), 'A32 branch or condition changed')


def _fill(raw):
    w = _code_words(raw, 36)
    _dp(w[0], 2, 1, 2, 18)
    _dp(w[1], 10, 2, 0, 4, flags=True)
    _branch_check(w[2], FILL + 8, FILL + 20, condition=3)
    _dp(w[3], 10, 1, 0, 21, flags=True)
    _branch_check(w[4], FILL + 16, 0x536DD458)
    _dp(w[5], 4, 3, 3, 0x38000)
    _dp(w[6], 13, 0, 2, 2)
    _memory(w[7], 3, 2, 0xA98, load=False, byte=True)
    _need(w[8] == 0xE89DAFF8, 'original fill epilogue mask')


def _dirty(raw):
    w = _code_words(raw, 40)
    _need(w[0] == 0xE92D000C, 'dirty hook saves R2/R3')
    _need(w[1] == 0xE10F3000, 'dirty hook captures original APSR in R3')
    _memory(w[2], 4, 2, 0x1A8, byte=True)
    _dp(w[3], 2, 2, 2, 18)
    _dp(w[4], 10, 2, 0, 4, flags=True)
    _dp(w[5], 12, 1, 1, 1, condition=3)
    _need(w[6] == 0xE128F003, 'dirty hook restores APSR NZCVQ from R3')
    _need(w[7] == 0xE8BD000C, 'dirty hook restores R2/R3 and stack')
    _memory(w[8], 4, 1, 0xE, load=False, byte=True)
    _branch_check(w[9], DIRTY + 36, 0x536DD028)


def _getter(raw, table, fallback_table):
    w = _code_words(raw, 152)
    _need(w[0] == 0xE92D41F0, 'getter saved callee registers')
    for index, destination, source in ((1, 4, 1), (2, 5, 2), (3, 6, 3)):
        _dp(w[index], 13, 0, destination, source, immediate=False)
    _need(w[4] == 0xE51BC048, 'current parameter must come from caller fp-48')
    _memory(w[5], 12, 12, 8)
    _mov16(w[6], 2, table); _mov16(w[7], 2, table, True)
    _memory(w[8], 2, 3, 0); _dp(w[9], 10, 3, 0, 0, flags=True)
    _branch_check(w[10], GETTER + 40, GETTER + 100, condition=0)
    _dp(w[11], 10, 3, 0, 12, immediate=False, flags=True)
    _dp(w[12], 4, 2, 2, 4, condition=0)
    _branch_check(w[13], GETTER + 52, GETTER + 64, condition=0)
    _dp(w[14], 4, 2, 2, 16); _branch_check(w[15], GETTER + 60, GETTER + 32)
    for load, store, displacement, output in ((16, 17, 0, 4), (18, 19, 4, 5), (20, 21, 8, 6)):
        _memory(w[load], 2, 3, displacement); _memory(w[store], output, 3, 0, load=False)
    _dp(w[22], 13, 0, 3, 0); _memory(w[23], 0, 3, 0, load=False, byte=True)
    _need(w[24] == 0xE8BD81F0, 'selected getter returns readonly knot pointers')
    for index, destination, source in ((25, 1, 4), (26, 2, 5), (27, 3, 6)):
        _dp(w[index], 13, 0, destination, source, immediate=False)
    _branch_check(w[28], GETTER + 112, 0x536EEDF0, link=True)
    _mov16(w[29], 7, fallback_table); _mov16(w[30], 7, fallback_table, True)
    for move, call, output in ((31, 32, 4), (33, 34, 5), (35, 36, 6)):
        _dp(w[move], 13, 0, 0, output, immediate=False)
        _branch_check(w[call], GETTER + call * 4, REMAP, link=True)
    _need(w[37] == 0xE8BD81F0, 'fallback getter callee-register return')


def _point(raw):
    """Two rounding stages and unsigned Base clamp, independently decoded."""
    w = _code_words(raw, 100)
    _need(w[0] == 0xE52DE004, 'point only saves LR on stack')
    _dp(w[1], 13, 0, 2, (6 << 7) | (1 << 5), immediate=False)
    _dp(w[2], 10, 2, 0, 255, flags=True)
    _dp(w[3], 13, 0, 2, 255, condition=2)
    _dp(w[4], 0, 0, 12, 63)
    _dp(w[5], 13, 0, 12, 0, condition=2)
    _dp(w[6], 13, 0, 3, (3 << 7) | (1 << 5) | 2, immediate=False)
    _dp(w[7], 4, 1, 14, (1 << 7) | 3, immediate=False)
    _dp(w[8], 0, 2, 2, 7)
    _need(w[9] == 0xE1DE00B0 and w[10] == 0xE1DE30B2, 'point adjacent u16 readonly knots')
    _dp(w[11], 2, 3, 1, 0, immediate=False)
    _multiply(w[12], 1, 2, 1)
    _dp(w[13], 4, 0, 0, (3 << 7) | (2 << 5) | 1, immediate=False)
    _need(w[14] == 0xE1DE10B0, 'point first knot reread, no scratch')
    _dp(w[15], 2, 3, 3, 1, immediate=False)
    _dp(w[16], 4, 2, 2, 1)
    _multiply(w[17], 3, 2, 3)
    _dp(w[18], 4, 1, 1, (3 << 7) | (2 << 5) | 3, immediate=False)
    _dp(w[19], 2, 1, 1, 0, immediate=False)
    _multiply(w[20], 1, 12, 1)
    _dp(w[21], 10, 1, 0, 0, flags=True)
    _dp(w[22], 4, 1, 1, 63, condition=11)
    _dp(w[23], 4, 0, 0, (6 << 7) | (2 << 5) | 1, immediate=False)
    _need(w[24] == 0xE49DF004, 'point returns restoring its LR word')


def _composer(raw, table):
    w = _code_words(raw, 200)
    _need(w[0] == 0xE51B0048, 'composer current P comes from caller fp-48')
    _memory(w[1], 0, 0, 8)
    _mov16(w[2], 1, table); _mov16(w[3], 1, table, True)
    _memory(w[4], 1, 2, 0); _dp(w[5], 10, 2, 0, 0, flags=True)
    _branch_check(w[6], COMPOSER + 24, COMPOSER + 44, condition=0)
    _dp(w[7], 10, 0, 0, 2, immediate=False, flags=True)
    _branch_check(w[8], COMPOSER + 32, COMPOSER + 52, condition=0)
    _dp(w[9], 4, 1, 1, 16)
    _branch_check(w[10], COMPOSER + 40, COMPOSER + 16)
    _need(w[11] == 0xE51B3044, 'unmatched composer replays displaced native instruction')
    _branch_check(w[12], COMPOSER + 48, 0x536E87CC)
    for i, reg, displacement in ((13, 4, 0x44), (14, 7, 0x3C), (15, 8, 0x38), (16, 9, 0x34)):
        _need(w[i] == 0xE51B0000 | (reg << 12) | displacement, 'composer local object or readonly knot pointer')
    _dp(w[17], 13, 0, 10, 0)
    for start, curve_reg, output, weight in ((18, 7, 0x2A00, 77), (26, 8, 0x2C00, 150), (34, 9, 0x2E00, 29)):
        _need(w[start] == 0xE19400BA, 'composer indexed unsigned16 Base read')
        _dp(w[start+1], 13, 0, 1, curve_reg, immediate=False)
        _branch_check(w[start+2], COMPOSER + (start+2)*4, POINT, link=True)
        _dp(w[start+3], 4, 4, 1, output)
        _dp(w[start+4], 4, 1, 1, 8)
        _need(w[start+5] == 0xE18100BA, 'composer indexed output halfword store')
        _dp(w[start+6], 13, 0, 1, weight)
        _multiply(w[start+7], 5, 0, 1, None if start == 18 else 5)
    _dp(w[42], 13, 0, 0, (8 << 7) | (2 << 5) | 5, immediate=False)
    _dp(w[43], 4, 4, 1, 0x3000); _dp(w[44], 4, 1, 1, 8)
    _need(w[45] == 0xE18100BA, 'composer weighted Y halfword store')
    _dp(w[46], 4, 10, 10, 2); _dp(w[47], 10, 10, 0, 512, flags=True)
    _branch_check(w[48], COMPOSER + 192, COMPOSER + 72, condition=1)
    _branch_check(w[49], COMPOSER + 196, 0x536E89CC)


def _remap(raw):
    w = _code_words(raw, 44)
    _memory(w[0], 0, 1, 0)
    _dp(w[1], 13, 0, 2, 7, immediate=False)
    _dp(w[2], 13, 0, 3, 3)
    _memory(w[3], 2, 8, 8, pre=False)
    _dp(w[4], 10, 1, 0, 8, immediate=False, flags=True)
    _need(w[5] == 0x05121004, 'conditional safe pointer at postindexed table minus4')
    _need(w[6] == 0x05801000, 'conditional store only into this call output')
    _need(w[7] == 0x012FFF1E, 'matched pointer returns without reading another row')
    _dp(w[8], 2, 3, 3, 1, flags=True)
    _branch_check(w[9], REMAP + 36, REMAP + 12, condition=1)
    _need(w[10] == 0xE12FFF1E, 'unmatched fallback pointer retained')


def _guards():
    return ((0x536DD024, 0xE5C4100E, _branch(0x536DD024, DIRTY)),
            (0x536EF618, 0xEDDF0BE0, _branch(0x536EF618, 0x536EF6DC)),
            (0x536DD450, 0x159632D0, 0xE59632D0),
            (0x536DD454, _branch(0x536DD454, 0x536DD4B8, condition=0), _branch(0x536DD454, FILL)),
            (0x536E4774, _branch(0x536E4774, 0x536E4720, link=True), _branch(0x536E4774, POST, link=True)),
            (0x536E87C4, _branch(0x536E87C4, 0x536EEDF0, link=True), _branch(0x536E87C4, GETTER, link=True)),
            (0x536E87C8, 0xE51B3044, _branch(0x536E87C8, COMPOSER)),
            (0x536DBEB4, 0xE5D39788, 0xE3A09000),
            (0x536DC27C, _branch(0x536DC27C, 0x536DC818, condition=0), 0xE1A00000),
            (0x536DBEBC, 0xE5D32796, 0xE3A02000),
            (0x535131FC, _branch(0x535131FC, 0x53513274, condition=0), _branch(0x535131FC, 0x53513218, condition=0)),
            (0x536DBE98, 0xE1CE40B0, 0xE1CE10B0))


def derive_expected(original_read, edits, profiles):
    """Derive all four looks from source bytes and validated numeric requests."""
    selected = _edits(edits)
    _need(type(profiles) is dict, 'profile catalog required')
    values = []
    for slot, ident in selected:
        _need(ident in profiles, 'selected profile absent')
        values.append(_legacy._profile(profiles[ident], ident))
    source = _Source(original_read)
    pointers = struct.unpack('<12I', source.read(LIBRARY, 48))
    _need(all(p % 4 == 0 and 0x53EF0000 <= p <= 0x53F00000 - 512 for p in pointers),
          'original aligned curve banks')
    ordered = sorted(pointers)
    _need(all(b - a >= 512 for a, b in zip(ordered, ordered[1:])), 'original curve banks overlap')
    rows, post_table, lookup = _layout(pointers)
    fallback = pointers[5] + 408
    boot = {0x536EB0DC: 0xE302C7A4, 0x536EB0E0: 0xE345C3DC,
            0x536EB160: 0xE89C000F, 0x536EB164: 0xE59F6098,
            0x536EB168: 0xE59F5098, 0x536EB16C: 0xE59F4098,
            0x536EB170: 0xE59FE098, 0x536EB174: 0xE59F7098,
            0x536EB178: 0xE887000F, 0x536EB214: STANDARD + 68,
            0x536DD464: 0xE89DAFF8}
    for address, value in boot.items():
        _need(source.read(address, 4) == _word(value), 'original initializer or return guard')
    standard, tail = source.read(STANDARD, 84), source.read(BOOT_TAIL, 16)
    windows, slots, posts, keys = [], [], [], []
    def data(address, value, label):
        windows.append(ExpectedWindow(address, va_to_offset(address, len(value)), value,
                                      label, source.read(address, len(value))))
    for index, (row, (slot, ident), profile, aliases) in enumerate(zip(rows, selected, values, BINDINGS)):
        _, record, matrix, knots = row
        look, curves, post = profile
        data(record, standard[:4] + _word(matrix) + standard[8:68] + tail, 'record_' + str(slot))
        data(matrix, _matrix(look), 'matrix_' + str(slot))
        for channel, (address, curve) in enumerate(zip(knots, curves)):
            data(address, struct.pack('<33H', *_expected_knots(curve)),
                 'knots_' + str(slot) + '_' + str(channel))
        for alias in aliases:
            data(PRIMARY + alias * 4, _word(record), 'binding_' + str(alias))
        posts.append(_word(record) + _matrix(post) + bytes(2))
        keys.extend((record, *knots))
        slots.append(FourSlotExpectation(slot, ident, record, matrix, tuple(knots),
                                         tuple(aliases), post_table + index * 24,
                                         (look, curves, post)))
    data(post_table, b''.join(posts) + bytes(4)
         + _matrix(((512, 0, 0), (0, 512, 0), (0, 0, 512))) + bytes(2), 'post_table')
    data(lookup, struct.pack('<20I', *keys, 0, 0, 0, 0), 'lookup')
    data(fallback, struct.pack('<6I', *(v for pair in zip(pointers[3:6], pointers[6:9]) for v in pair)),
         'fallback_table')
    for address, before, after in _guards():
        _need(source.read(address, 4) == _word(before), 'original four-film patch guard')
        data(address, _word(after), 'guard_' + hex(address))
    code_specs = ((FILL, 36, 'four_fill', ()), (DIRTY, 40, 'four_dirty', ()),
                  (POST, 204, 'four_post', (post_table,)),
                  (GETTER, 152, 'four_getter', (lookup, fallback)),
                  (POINT, 100, 'four_point', ()), (COMPOSER, 200, 'four_composer', (lookup,)), (REMAP, 44, 'four_remap', ()))
    codes = tuple(CodeRegion(a, va_to_offset(a, n), n, role, ptrs, source.read(a, n))
                  for a, n, role, ptrs in code_specs)
    protected_specs = [(LIBRARY, 48, 'library'), (0x55037634, 132, 'secondary'),
                       (STANDARD, 84, 'standard'), (0x53D36400, 4096, 'old_arena'),
                       (0x536DD4B8, 88, 'cross_chain'), (FILL + 176, 16, 'unused_fill'),
                       (POST + 600, 68, 'unused_post'), (pointers[5] + 432, 80, 'bank5_tail')]
    protected_specs += [(p, 512, 'unused_bank_' + str(i)) for i, p in enumerate(pointers)
                        if i not in (3, 4, 5)]
    protected_specs += [(PRIMARY + i * 4, 4, 'unused_binding_' + str(i)) for i in range(26)
                        if i not in (18, 19, 20, 21, 22, 23, 24)]
    for row in slots:
        protected_specs += [(a + 66, 2, 'knot_pad_' + str(row.slot) + '_' + str(i))
                            for i, a in enumerate(row.knots)]
        protected_specs.append((row.matrix + 18, 2, 'matrix_pad_' + str(row.slot)))
    protected = tuple(ProtectedRegion(a, n, name, source.read(a, n))
                      for a, n, name in protected_specs)
    _need(len(protected) == 52, 'fixed protected-region count')
    spans = sorted([(w.offset, w.offset + len(w.data)) for w in windows]
                   + [(c.offset, c.offset + c.size) for c in codes])
    _need(len(spans) == 49 and sum(b - a for a, b in spans) == 2276, 'fixed four-film span budget')
    _need(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'physical write overlap')
    for region in protected:
        a = va_to_offset(region.address, region.size)
        _need(all(not (lo < a + region.size and hi > a) for lo, hi in spans), 'protected physical overlap')
    source.stable()
    original_dependencies = tuple(ProtectedRegion(a, n, 'source_dependency', raw)
                                  for (a, n), raw in sorted(source.seen.items()))
    configuration = tuple((s.slot, s.film, *s.profile) for s in slots)
    return FourExpectations(tuple(windows), codes, tuple(spans), protected, SLOTS,
                            tuple(slots), configuration, original_dependencies)


def _profile_dict(slot):
    _need(type(slot) is FourSlotExpectation and type(slot.slot) is int
          and slot.slot in SLOTS and type(slot.film) is str, 'typed slot expectation')
    _need(type(slot.profile) is tuple and len(slot.profile) == 3, 'immutable profile snapshot')
    look, curves, post = slot.profile
    for rows in (look, curves, post):
        _need(type(rows) is tuple and all(type(row) is tuple for row in rows), 'nested immutable profile')
    return dict(schema=1, id=slot.film, model='GR III', firmware='2.10',
                look_matrix_q13=[list(row) for row in look], curves_u14=[list(row) for row in curves],
                post_matrix_q512=[list(row) for row in post])


def _expectation_shapes(value):
    _need(type(value) is FourExpectations, 'independent four-expectation contract required')
    for name in ('data_windows', 'code_regions', 'expected_spans', 'protected_regions',
                 'selected_slots', 'slots', 'configuration', 'source_regions'):
        _need(type(getattr(value, name)) is tuple, 'immutable expectation field: ' + name)
    _need(value.selected_slots == SLOTS and all(type(v) is int for v in value.selected_slots),
          'typed complete selected slots')
    _need(len(value.slots) == 4, 'four immutable slot objects')
    _need(len(value.configuration) == 4, 'complete immutable configuration')
    for item in value.configuration:
        _need(type(item) is tuple and len(item) == 5 and type(item[0]) is int
              and type(item[1]) is str, 'typed configuration identity')
        for rows in item[2:]:
            _need(type(rows) is tuple and all(type(row) is tuple
                  and all(type(v) is int for v in row) for row in rows),
                  'typed immutable configuration numbers')
    for w in value.data_windows:
        _need(type(w) is ExpectedWindow and type(w.address) is type(w.offset) is int
              and type(w.data) is type(w.original) is bytes and type(w.label) is str,
              'typed immutable expected window')
    for c in value.code_regions:
        _need(type(c) is CodeRegion and type(c.address) is type(c.offset) is type(c.size) is int
              and type(c.role) is str and type(c.original) is bytes and type(c.pointers) is tuple
              and all(type(p) is int for p in c.pointers), 'typed code expectation')
    for r in value.protected_regions + value.source_regions:
        _need(type(r) is ProtectedRegion and type(r.address) is type(r.size) is int
              and type(r.label) is str and type(r.original) is bytes, 'typed source/protected expectation')
    for span in value.expected_spans:
        _need(type(span) is tuple and len(span) == 2 and all(type(v) is int for v in span),
              'typed physical expectation span')
    for slot in value.slots:
        _need(type(slot) is FourSlotExpectation and type(slot.record) is type(slot.matrix)
              is type(slot.post_entry) is int and type(slot.knots) is type(slot.aliases) is tuple
              and all(type(v) is int for v in slot.knots + slot.aliases), 'typed immutable slot layout')


_CLOSED_ERRORS = (ValueError, TypeError, KeyError, IndexError, OverflowError, struct.error,
                  AttributeError, OSError)


def readback_windows(original_read, modified_read, expectations):
    """Return a closed result; only validated windows authorize combined deltas."""
    checks = []
    try:
        _expectation_shapes(expectations)
        requests, profiles = [], {}
        for slot in expectations.slots:
            profile = _profile_dict(slot)
            _need(slot.film not in profiles or profiles[slot.film] == profile,
                  'shared profile identifier has conflicting snapshots')
            profiles[slot.film] = profile
            requests.append(dict(kind='film', slot=slot.slot, film=slot.film))
        derived = derive_expected(original_read, requests, profiles)
        _need(derived == expectations, 'original or independently derived expectation changed')
        checks.append(dict(id='four_source_and_expectation_identity', ok=True, detail=''))
        modified = _Source(modified_read)
        accepted = list(expectations.data_windows)
        for window in expectations.data_windows:
            _need(modified.read(window.address, len(window.data)) == window.data,
                  'four-film data mismatch: ' + window.label)
        checks.append(dict(id='four_numeric_data_and_bindings', ok=True, detail=''))
        for code in expectations.code_regions:
            actual = modified.read(code.address, code.size)
            if code.role == 'four_fill':
                _fill(actual)
            elif code.role == 'four_dirty':
                _dirty(actual)
            elif code.role == 'four_post':
                _check_post(actual, code.address, code.pointers)
            elif code.role == 'four_getter':
                _getter(actual, *code.pointers)
            elif code.role == 'four_point':
                _point(actual)
            elif code.role == 'four_composer':
                _composer(actual, *code.pointers)
            elif code.role == 'four_remap':
                _remap(actual)
            else:
                raise FilmReadbackError('unknown four-film code role')
            accepted.append(ExpectedWindow(code.address, code.offset, actual,
                                           'validated_' + code.role, code.original))
        checks.append(dict(id='four_all_code_fields_and_targets', ok=True, detail=''))
        for region in expectations.protected_regions:
            _need(modified.read(region.address, region.size) == region.original,
                  'protected four-film region mismatch: ' + region.label)
        checks.append(dict(id='four_protected_regions', ok=True, detail='52 physical preservation regions'))
        # Recheck the entire captured dependency set after modified callback reads.
        modified.stable()
        source = _Source(original_read)
        for region in expectations.source_regions:
            _need(source.read(region.address, region.size) == region.original, 'original callback changed')
        source.stable()
        return FilmReadbackResult(True, tuple(checks), tuple(accepted), expectations.expected_spans)
    except _CLOSED_ERRORS as exc:
        checks.append(dict(id='four_closed_failure', ok=False, detail=str(exc)))
        return FilmReadbackResult(False, tuple(checks), (), ())


def verify_transition(original_read, previous_read, modified_read, previous_edits, edits,
                      previous_profiles, profiles, *, changed_slots):
    """Verify both complete versions before checking an exact change declaration."""
    checks, verified = [], []
    for label, reader, requests, catalog in (('previous', previous_read, previous_edits, previous_profiles),
                                             ('next', modified_read, edits, profiles)):
        try:
            expected = derive_expected(original_read, requests, catalog)
            result = readback_windows(original_read, reader, expected)
            checks.extend(dict(item, id=label + '_' + item['id']) for item in result.checks)
            verified.append((expected, result))
        except _CLOSED_ERRORS as exc:
            checks.append(dict(id=label + '_four_closed_failure', ok=False, detail=str(exc)))
            verified.append((None, None))
    if any(result is None or result.passed is not True for expected, result in verified):
        return FilmReadbackResult(False, tuple(checks), (), ())
    try:
        _need(type(changed_slots) in (list, tuple) and all(type(s) is int and s in SLOTS for s in changed_slots)
              and len(changed_slots) == len(set(changed_slots)), 'typed unique changed slots required')
        previous, following = verified[0][0], verified[1][0]
        _need(previous.source_regions == following.source_regions,
              'previous and next use different original snapshots')
        actual = tuple(a.slot for a, b in zip(previous.slots, following.slots)
                       if (a.film, a.profile) != (b.film, b.profile))
        _need(tuple(sorted(changed_slots)) == actual, 'changed slots differ from complete configuration delta')
        checks.append(dict(id='four_exact_changed_slot_declaration', ok=True, detail=str(actual)))
        before, after = _Source(previous_read), _Source(modified_read)
        for old, new in zip(previous.slots, following.slots):
            _need((old.slot, old.record, old.matrix, old.knots, old.aliases, old.post_entry)
                  == (new.slot, new.record, new.matrix, new.knots, new.aliases, new.post_entry),
                  'slot layout changed between versions')
            if old.slot in actual:
                continue
            ranges = ((old.record, 84), (old.matrix, 18), (old.post_entry, 24))
            ranges += tuple((a, 66) for a in old.knots)
            ranges += tuple((PRIMARY + i * 4, 4) for i in old.aliases)
            for address, size in ranges:
                _need(before.read(address, size) == after.read(address, size), 'unchanged slot bytes differ')
        for code in previous.code_regions:
            _need(before.read(code.address, code.size) == after.read(code.address, code.size),
                  'fixed four-film code changed in transition')
        for window in previous.data_windows:
            if window.label in ('lookup', 'fallback_table'):
                _need(before.read(window.address, len(window.data)) == after.read(window.address, len(window.data)),
                      'fixed four-film dispatch table changed')
        before.stable(); after.stable()
        source = _Source(original_read)
        for region in following.source_regions:
            _need(source.read(region.address, region.size) == region.original,
                  'original callback changed during transition')
        source.stable()
        checks.append(dict(id='four_unchanged_slots_and_fixed_dispatch', ok=True, detail=''))
        return FilmReadbackResult(True, tuple(checks), verified[1][1].expected_windows,
                                  verified[1][1].expected_spans)
    except _CLOSED_ERRORS as exc:
        checks.append(dict(id='four_transition_closed_failure', ok=False, detail=str(exc)))
        return FilmReadbackResult(False, tuple(checks), (), ())



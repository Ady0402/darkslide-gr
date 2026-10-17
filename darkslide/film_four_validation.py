"""Four independently replaceable looks; small development plans only."""
import hashlib
import math
import struct
from fractions import Fraction
from .film_requests import FilmRequestError, validate_batch
from .film_profiles import validate_profile
from .film_patch_plan import PlanImage, from_official_payload, _branch
from .film_arm_assemble import assemble
from .film_writer import _init_tail, HDR_FIXES, RETRO_FIXES, SLOT_INFO
from ._vendor.gr3_film_hooks import csp_src, csp_entry
from ._vendor.gr3_four_curve_hooks import getter_source, point_source, composer_source, remap_source

LIB, PRIMARY, STANDARD = 0x55037604, 0x55018D94, 0x5501900C
FILL, FILL_END, POST, POST_END = 0x536EF61C, 0x536EF6DC, 0x536EF6FC, 0x536EF998
ORIGINAL_BYTES = 59718388
ORIGINAL_SHA = '53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703'
SLOTS = (8, 9, 10, 11)


def expand_knots(knots):
    if type(knots) not in (tuple, list) or len(knots) != 33 or any(type(v) is not int or not 0 <= v <= 16383 for v in knots):
        raise FilmRequestError('曲线压缩节点格式错误')
    return tuple(knots[i // 8] + ((knots[i // 8 + 1] - knots[i // 8]) * (i % 8) >> 3) for i in range(256))


def fit_knots(curve):
    """Local tridiagonal least-squares fit, using the published step-8 format.

    Clipping and quantization are reported through reconstruction errors. This
    does not imply lossless compression or a measured camera colour error.
    """
    if type(curve) is not list or len(curve) != 256 or any(type(v) is not int or not 0 <= v <= 16383 for v in curve):
        raise FilmRequestError('需要完整的256点u14曲线')
    diagonal, upper, rhs = [0] * 33, [0] * 32, [0] * 33
    for i, value in enumerate(curve):
        k, fraction = divmod(i, 8)
        b, a = fraction, 8 - fraction
        diagonal[k] += a * a
        diagonal[k + 1] += b * b
        upper[k] += a * b
        rhs[k] += a * value * 8
        rhs[k + 1] += b * value * 8
    for k in range(1, 33):
        ratio = Fraction(upper[k - 1]) / diagonal[k - 1]
        diagonal[k] -= ratio * upper[k - 1]
        rhs[k] -= ratio * rhs[k - 1]
    solution = [Fraction(0)] * 33
    solution[-1] = rhs[-1] / diagonal[-1]
    for k in range(31, -1, -1):
        solution[k] = (rhs[k] - upper[k] * solution[k + 1]) / diagonal[k]
    knots = tuple(min(16383, max(0, math.floor(v + Fraction(1, 2)))) for v in solution)
    rebuilt = expand_knots(knots)
    errors = [a - b for a, b in zip(rebuilt, curve)]
    return knots, dict(max_abs_u14=max(abs(v) for v in errors),
                       rms_u14=math.sqrt(sum(v * v for v in errors) / 256),
                       lossless=all(v == 0 for v in errors))


def fill_source():
    return '''
        sub r2, r1, #18
        cmp r2, #4
        blo S
        cmp r1, #21
        b abs(0x536dd458)
    S:  add r3, r3, #0x38000
        mov r2, #2
        strb r2, [r3, #0xa98]
        .word 0xe89daff8
    '''


def dirty_source():
    # 2.10 DC860 overwrites controller+E at DD024. Its +1A8 is the
    # current setting tone (stored at DCD FC). Keep this call's flags and
    # temporaries, then request Gamma rebuild for only tones18..21.
    return """
        push {r2,r3}
        mrs r3, APSR
        ldrb r2, [r4, #0x1a8]
        sub r2, r2, #18
        cmp r2, #4
        orrlo r1, r1, #1
        msr APSR_nzcvq, r3
        pop {r2,r3}
        strb r1, [r4, #0xe]
        b abs(0x536dd028)
    """


def layout(pointers):
    """Stable slot layout; changing one profile never relocates another."""
    banks = pointers[3:6]
    rows = []
    for i, slot in enumerate(SLOTS):
        knot_bank = banks[0 if i < 2 else 1]
        knot_base = knot_bank + (i % 2) * 204
        if i == 0:
            record, matrix = banks[0] + 408, banks[0] + 492
        elif i == 1:
            record, matrix = banks[1] + 408, banks[1] + 492
        else:
            record, matrix = banks[2] + (i - 2) * 104, banks[2] + (i - 2) * 104 + 84
        rows.append(dict(slot=slot, record=record, matrix=matrix,
                         knots=tuple(knot_base + c * 68 for c in range(3))))
    return rows, banks[2] + 208, banks[2] + 328


def plan(read, edits, profiles):
    requests = validate_batch(edits)
    if tuple(e['slot'] for e in requests) != SLOTS:
        raise FilmRequestError('四卷验证需要提供四个位置的当前胶片，可独立替换任一卷')
    if not callable(read) or type(profiles) is not dict:
        raise FilmRequestError('需要只读原件及四卷相机数据')
    try:
        resolved = {e['slot']: validate_profile(profiles[e['film']], e['film']) for e in requests}
    except KeyError as error:
        raise FilmRequestError('缺少四卷中的相机数据') from error
    pointers = struct.unpack('<12I', read(LIB, 48))
    if any(p % 4 or not 0x53EF0000 <= p <= 0x53F00000 - 512 for p in pointers):
        raise FilmRequestError('原厂曲线存放位置不匹配')
    if any(b - a < 512 for a, b in zip(sorted(pointers), sorted(pointers)[1:])):
        raise FilmRequestError('原厂曲线范围重叠')
    rows, post_table, lookup = layout(pointers)
    fallback_table = pointers[5] + 408
    tail, stock = _init_tail(read), read(STANDARD, 84)
    if int.from_bytes(read(0x536DD464, 4), 'little') != 0xE89DAFF8:
        raise FilmRequestError('原厂填充返回不匹配')
    post = assemble(csp_src(post_table), POST)
    getter_at = POST + len(post)
    getter_probe = assemble(getter_source(lookup, fallback_table, POST), getter_at)
    remap_at = getter_at + len(getter_probe)
    remap = assemble(remap_source(), remap_at)
    getter = assemble(getter_source(lookup, fallback_table, remap_at), getter_at)
    fill = assemble(fill_source(), FILL)
    dirty_at = FILL + len(fill)
    dirty = assemble(dirty_source(), dirty_at)
    point_at = dirty_at + len(dirty)
    point = assemble(point_source(), point_at)
    composer_at = remap_at + len(remap)
    composer = assemble(composer_source(lookup, point_at), composer_at)
    if len(fill) + len(dirty) + len(point) > FILL_END - FILL or composer_at + len(composer) > POST_END:
        raise FilmRequestError('四卷验证代码超出原位空间')
    guards = [(0x536EF618, 0xEDDF0BE0, _branch(0x536EF618, 0x536EF6DC)),
              (0x536DD450, 0x159632D0, 0xE59632D0),
              (0x536DD454, _branch(0x536DD454, 0x536DD4B8, condition=0), _branch(0x536DD454, FILL)),
              (0x536E4774, _branch(0x536E4774, 0x536E4720, link=True), _branch(0x536E4774, POST, link=True)),
              (0x536E87C4, _branch(0x536E87C4, 0x536EEDF0, link=True), _branch(0x536E87C4, getter_at, link=True)),
              (0x536E87C8, 0xE51B3044, _branch(0x536E87C8, composer_at))]
    guards.append((0x536DD024, 0xE5C4100E, _branch(0x536DD024, dirty_at)))
    guards += list(HDR_FIXES) + list(RETRO_FIXES)
    indices = tuple(i for slot in SLOTS for i in SLOT_INFO[slot][1])
    allowed = [(FILL, FILL_END), (POST, POST_END)]
    allowed += [(p, p + 512) for p in pointers[3:6]]
    allowed += [(a, a + 4) for a, _, _ in guards]
    allowed += [(PRIMARY + i * 4, PRIMARY + i * 4 + 4) for i in indices]
    image = PlanImage(read, tuple(allowed), max_bytes=8192)
    for a, before, after in guards:
        image.guarded_word(a, before, after)
    posts, keys, errors = [], [], []
    for row, edit in zip(rows, requests):
        fitted = resolved[row['slot']]
        clone = bytearray(stock)
        clone[4:8], clone[68:84] = struct.pack('<I', row['matrix']), tail
        image.write(row['record'], bytes(clone))
        image.write(row['matrix'], struct.pack('<9h', *(v for r in fitted['look_matrix_q13'] for v in r)))
        channel_errors = []
        for at, curve in zip(row['knots'], fitted['curves_u14']):
            knots, error = fit_knots(curve)
            image.write(at, struct.pack('<33H', *knots))
            channel_errors.append(error)
        errors.append(dict(slot=row['slot'], film=edit['film'], channels=channel_errors))
        posts.append(csp_entry(row['record'], fitted['post_matrix_q512']))
        keys.extend((row['record'], *row['knots']))
        for index in SLOT_INFO[row['slot']][1]:
            image.write(PRIMARY + index * 4, struct.pack('<I', row['record']))
    image.write(post_table, b''.join(posts) + csp_entry(0, [[512, 0, 0], [0, 512, 0], [0, 0, 512]]))
    image.write(lookup, struct.pack('<20I', *keys, 0, 0, 0, 0))
    fallback = tuple(v for old, safe in zip(pointers[3:6], pointers[6:9]) for v in (old, safe))
    image.write(fallback_table, struct.pack('<6I', *fallback))
    for at, code in ((FILL, fill), (dirty_at, dirty), (point_at, point), (POST, post), (getter_at, getter), (remap_at, remap), (composer_at, composer)):
        image.write(at, code)
    return dict(windows=image.seal(), selected_slots=SLOTS, records=rows, compression_errors=errors,
                getter=getter_at, point_sampler=point_at, curve_composer=composer_at, remap=remap_at, fallback_table=fallback_table,
                fallback_reused_bank_outputs_remapped=True, unknown_record_visual_preservation_verified=False,
                post_table=post_table, lookup=lookup,
                area_a_used=len(fill)+len(dirty)+len(point), dirty_hook=dirty_at, area_b_used=composer_at + len(composer) - POST,
                stored_knots_per_channel=33, rebuilt_points_per_channel=256,
                shared_library_pointer_writes=False, old_private_arena_used=False,
                four_independent_films=True, full_image_created=False, device_verified=False,
                curve_storage='readonly_knots_direct_sample', expanded_scratch_bytes=0,
                same_gamma_concurrent_calls_verified=False)


def plan_official_payload(raw, edits, profiles):
    if type(raw) is not bytes or len(raw) != ORIGINAL_BYTES or hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA:
        raise FilmRequestError('四卷验证只接受固定官方 GR III 2.10 原件')
    return plan(from_official_payload(raw, ()).reader, edits, profiles)

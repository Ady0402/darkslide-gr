"""Cross Process development plan with fixed stock curve banks; no full export.

Reuses the MIT post-matrix hook and compiler adaptation credited in
_vendor/GR3_FILM_MODS_LICENSE.txt. Local placement and selector logic by LiorMoment.
"""
import hashlib
import struct
from .film_requests import FilmRequestError, validate_batch
from .film_profiles import validate_profile
from .film_patch_plan import PlanImage, from_official_payload, _branch
from .film_arm_assemble import assemble
from ._vendor.gr3_film_hooks import csp_src, csp_entry
from .film_writer import _init_tail

ORIGINAL_SIZE = 59718388
ORIGINAL_SHA256 = '53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703'
LIB, RECORDS, STD = 0x55037604, 0x55018D94, 0x5501900C
FILL, FILL_END = 0x536EF61C, 0x536EF6DC
POST, POST_END = 0x536EF6FC, 0x536EF998
CODE_PAGE = 0x536EF000
RET = 0xE89DAFF8


def fill_source():
    return f'''
        cmp r1, #21
        bne abs(0x536dd458)
        add r3, r3, #0x38000
        mov r2, #2
        strb r2, [r3, #0xa98]
        .word {RET:#x}
    '''


def plan(reader, edit, profile):
    """Single Cross replacement only; the supplied reader must be immutable."""
    request = validate_batch([edit])[0]
    if request['slot'] != 11:
        raise FilmRequestError('最小验证版只支持交叉冲洗位置')
    fitted = validate_profile(profile, request['film'])
    source = reader
    if not callable(source):
        raise FilmRequestError('需要只读原件')

    def read(address, count):
        if type(address) is not int or type(count) is not int or not 0 < count <= 512:
            raise FilmRequestError('最小验证读取范围错误')
        if not 0 <= address < address + count <= 2**32:
            raise FilmRequestError('最小验证读取越界')
        value = source(address, count)
        if type(value) is not bytes or len(value) != count:
            raise FilmRequestError('最小验证原件读取不完整')
        return value

    pointers = struct.unpack('<12I', read(LIB, 48))
    ordered = sorted(pointers)
    if any(p % 2 or not 0x53EF0000 <= p <= 0x53F00000 - 512 for p in pointers):
        raise FilmRequestError('原厂曲线存放位置不匹配')
    if any(b - a < 512 for a, b in zip(ordered, ordered[1:])):
        raise FilmRequestError('原厂曲线范围重叠')
    if int.from_bytes(read(RECORDS + 21 * 4, 4), 'little') != STD:
        raise FilmRequestError('原厂交叉冲洗记录绑定不匹配')
    if int.from_bytes(read(0x536DD464, 4), 'little') != RET:
        raise FilmRequestError('填充函数返回结构不匹配')
    tail = _init_tail(read)
    template = bytearray(read(STD, 84))
    post_stub = assemble(csp_src(0), POST)
    record_at = POST + len(post_stub)
    matrix_at = record_at + 84
    table_at = (matrix_at + 18 + 3) & ~3
    table = csp_entry(record_at, fitted['post_matrix_q512']) + csp_entry(
        0, [[512, 0, 0], [0, 512, 0], [0, 0, 512]])
    used_end = table_at + len(table)
    fill = assemble(fill_source(), FILL)
    post = assemble(csp_src(table_at), POST)
    if len(fill) > FILL_END - FILL or len(post) != len(post_stub) or used_end > POST_END:
        raise FilmRequestError('最小验证代码和记录超出原位空间')
    if any(a & ~0xFFF != CODE_PAGE for a in (FILL, FILL + len(fill) - 1, POST, used_end - 1)):
        raise FilmRequestError('最小验证数据未与代码处于同页')
    template[4:8] = struct.pack('<I', matrix_at)
    template[68:84] = tail
    matrix = struct.pack('<9h', *[v for row in fitted['look_matrix_q13'] for v in row])
    guards = (
        (0x536EF618, 0xEDDF0BE0, _branch(0x536EF618, 0x536EF6DC)),
        (0x536DD450, 0x159632D0, 0xE59632D0),
        (0x536DD454, _branch(0x536DD454, 0x536DD4B8, condition=0), _branch(0x536DD454, FILL)),
        (0x536E4774, _branch(0x536E4774, 0x536E4720, link=True), _branch(0x536E4774, POST, link=True)),
    )
    allowed = ((FILL, FILL_END), (POST, POST_END), (RECORDS + 84, RECORDS + 88))
    allowed += tuple((a, a + 4) for a, _, _ in guards)
    allowed += tuple((p, p + 512) for p in pointers[3:6])
    image = PlanImage(read, allowed, max_bytes=4096)
    for a, before, after in guards:
        image.guarded_word(a, before, after)
    image.write(FILL, fill)
    image.write(POST, post)
    image.write(record_at, bytes(template))
    image.write(matrix_at, matrix)
    image.write(table_at, table)
    image.write(RECORDS + 84, struct.pack('<I', record_at))
    for pointer, curve in zip(pointers[3:6], fitted['curves_u14']):
        image.write(pointer, struct.pack('<256H', *curve))
    windows = image.seal()
    return dict(schema=1, kind='cross_minimal_validation', model='GR III', firmware='2.10',
                selected_slots=(11,), film=request['film'], windows=windows,
                record=record_at, matrix=matrix_at, post_table=table_at,
                curve_pointers=tuple(pointers[3:6]), selector=2,
                area_a_used=len(fill), area_b_used=used_end - POST,
                code_data_page=CODE_PAGE, shared_pointer_writes=False,
                old_private_arena_used=False, full_image_created=False,
                production_available=False, native_effect_verified=False,
                raw_playback_verified=False)


def plan_official_payload(raw, edit, profile):
    if type(raw) is not bytes or len(raw) != ORIGINAL_SIZE or hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        raise FilmRequestError('最小验证只接受指定的官方 GR III 2.10 原件')
    image = from_official_payload(raw, ())
    return plan(image.reader, edit, profile)

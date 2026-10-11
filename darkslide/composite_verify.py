from . import package_inspect
"""Independent combined readback. Imports the reader only, never a writer.

Expected bytes are derived from the immutable official file and requested edits;
the generator's declared spans are not used to authorize payload differences.
JPEG padding is accepted only as zero-filled COM segments inserted before SOS.
Entropy/pixel decoding remains the caller's separate image validation step.
"""
import hashlib
import struct
from . import fwread

IDENTIFIERS = ((358, 4), (548, 268), (354, 269), (357, 270), (350, 271),
               (352, 272), (232, 274), (346, 275), (356, 276), (351, 277),
               (50, 278), (23, 273), (347, 279), (348, 280))
DIARY_PATH = b"B:\\Resource\\Jpeg\\GB_Diary.jpg"


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sum32(data):
    _need(len(data) % 4 == 0, "unaligned sum")
    return sum(x[0] for x in struct.iter_unpack('<I', data)) & 0xffffffff


def _sos(jpeg):
    _need(type(jpeg) is bytes and jpeg[:2] == b'\xff\xd8' and
          jpeg[-2:] == b'\xff\xd9', 'JPEG boundaries')
    pos = 2
    while pos + 4 <= len(jpeg):
        _need(jpeg[pos] == 255, 'JPEG marker')
        marker, length = jpeg[pos + 1], int.from_bytes(jpeg[pos + 2:pos + 4], 'big')
        _need(length >= 2 and pos + 2 + length <= len(jpeg), 'JPEG segment length')
        if marker == 0xda:
            return pos
        _need(marker not in (0xd8, 0xd9, 0x00), 'unexpected JPEG marker')
        pos += 2 + length
    raise ValueError('missing SOS')


def _padding_only(submitted, actual):
    a, b = _sos(submitted), _sos(actual)
    if actual[:a] != submitted[:a] or actual[b:] != submitted[a:]:
        return False
    pos = a
    while pos < b:
        if actual[pos:pos + 2] != b'\xff\xfe' or pos + 4 > b:
            return False
        length = int.from_bytes(actual[pos + 2:pos + 4], 'big')
        end = pos + 2 + length
        if length < 2 or end > b or any(actual[pos + 4:end]):
            return False
        pos = end
    return pos == b


def _resources(payload):
    head = 53123096
    _need(payload[head:head + 8] == b'RES\0\0\0\0\0' and
          struct.unpack_from('<I', payload, head + 12)[0] == 35, 'RES identity')
    rows, at = [], head + 16
    for _ in range(35):
        _need(at + 36 <= len(payload) - 4, 'RES header bound')
        length = struct.unpack_from('<I', payload, at + 32)[0]
        _need(length > 0 and at + 36 + length <= len(payload) - 4, 'RES body bound')
        rows.append((at, at + 36, length, payload[at:at + 32].split(b'\0', 1)[0]))
        at += 36 + length
    _need(at == len(payload) - 4, 'RES tail')
    return rows


def _container(raw):
    return package_inspect.inspect(raw)


def verify(official, result, edits, template, jpeg=None):
    """Return checks; failures are closed and do not authorize a download.

Same request signature as build_composite. No modified BIN is read from disk.
"""
    checks = []

    def add(key, ok, detail=''):
        checks.append(dict(id=key, title=key, ok=bool(ok), detail=detail))

    try:
        _need(type(official) is bytes and _sha(official) == fwread.V210_INPUT_SHA256,
              'immutable official input')
        out = result['output']
        _need(type(out) is bytes, 'output bytes')
        add('input', True)
        add('output_sha', _sha(out) == result['output_sha256'])
        add('header_version', out[:128] == official[:128])
        add('file_sum', _sum32(out) == 0)
        oldfoot, oldmeta, oldend = _container(official)
        newfoot, newmeta, newend = _container(out)
        add('container_bounds_padding', True)
        before, after = fwread.unpack(official[:oldend]), fwread.unpack(out[:newend])
        _need(len(before) == len(after), 'payload size')
        add('independent_unpack', True)
        add('payload_sum', _sum32(after) == 0)
        add('footer_identity', oldfoot[:3] == newfoot[:3] and oldfoot[4] == newfoot[4])
        add('metadata', oldmeta == newmeta)
        p = fwread.Payload(before)
        expected, spans = bytearray(before), []

        def write(at, data):
            end = at + len(data)
            _need(0 <= at < end <= len(before) - 4 and
                  not any(at < y and end > x for x, y in spans), 'expected edit overlap/bounds')
            expected[at:end] = data
            spans.append((at, end))

        _need(type(edits) is list and len(edits) <= 7 and (edits or jpeg is not None), 'request')
        _need(type(template) is dict and template.get('reviewed') is True and
              template.get('model') == 'GR III' and template.get('firmware') == '2.10' and
              type(template.get('slots')) is list and len(template['slots']) == 14, 'template')
        seen = set()
        for edit in edits:
            _need(type(edit) is dict, 'edit object')
            no, kind = edit['slot'], edit['kind']
            _need(type(no) is int and 1 <= no <= 14 and type(kind) is str and
                  kind in ('icon', 'name') and (kind, no) not in seen, 'edit identity')
            seen.add((kind, no))
            icon, string = IDENTIFIERS[no - 1]
            slot = template['slots'][no - 1]
            _need(type(slot['no']) is int and slot['no'] == no and
                  type(slot['icon_id']) is int and slot['icon_id'] == icon and
                  type(slot['string_id']) is int and slot['string_id'] == string, 'template mapping')
            if kind == 'icon':
                _need(set(edit) == {'kind', 'slot', 'icon_id', 'pixels'} and
                      type(edit['icon_id']) is int and edit['icon_id'] == icon and
                      no in (1, 7, 11, 12) and slot['icon'] in ('test', 'open'), 'icon scope')
                info, native = p.icon_pixels(icon)
                px = edit['pixels']
                _need(type(px) is bytes and len(px) == 6400 and len(native) == 6400, 'icon size')
                for y in range(40):
                    for x in range(40):
                        alpha = px[(y * 40 + x) * 4 + 3]
                        _need(alpha in (0, 255) and (alpha != 0) ==
                              (native[(y * 40 + x) * 4 + 3] != 0) ==
                              (1 <= x < 39 and 2 <= y < 38), 'icon alpha')
                    if 2 <= y < 38:
                        at = (y * 40 + 1) * 4
                        write(info['payload_offset'] + at, px[at:at + 152])
            else:
                _need(set(edit) == {'kind', 'slot', 'string_id', 'text'} and
                      type(edit['string_id']) is int and edit['string_id'] == string and
                      no in (7, 11, 12) and slot['rename'] in ('test', 'open'), 'name scope')
                en, zh = p.string(string, 'en'), p.string(string, 'zh-CN')
                text = edit['text']
                _need(type(text) is str and 0 < len(text) <= len(en['text']) and
                      all(32 <= ord(c) <= 126 for c in text) and text == text.strip(' ') and
                      '  ' not in text and en['text'] == slot['factory_en'], 'name text')
                capacity = en['length_byte'] * 2
                value = text.encode('utf-16-le') + b'\0\0'
                write(en['text_offset'], value + bytes(capacity - len(value)))
                write(en['record_offset'], bytes((len(text) + 1,)))
                pointer = before[en['record_offset'] + 4:en['record_offset'] + 8]
                write(zh['record_offset'], bytes((len(text) + 1, 1, 0, 0)) + pointer)
        add('icon_name_expected', True)
        q = fwread.Payload(after, pinned=False)
        name_requests = {e['slot']: e for e in edits if e['kind'] == 'name'}
        semantic_ok = True
        for no, (icon, string) in enumerate(IDENTIFIERS, 1):
            info, raw = p.icon_pixels(icon)
            _, got = q.icon_pixels(icon)
            at = info['payload_offset']
            semantic_ok = semantic_ok and got == expected[at:at + len(raw)]
            for language in ('en', 'zh-CN', 'ja'):
                want = (name_requests[no]['text'] if no in name_requests and
                        language in ('en', 'zh-CN') else p.string(string, language)['text'])
                semantic_ok = semantic_ok and q.string(string, language)['text'] == want
        add('readback_icons_names', semantic_ok)
        records = _resources(before)
        if jpeg is not None:
            diary = [row for row in records if row[3] == DIARY_PATH]
            _need(len(diary) == 1, 'Diary record')
            head, body, capacity, _ = diary[0]
            _need(capacity == 112509, 'fixed Diary capacity')
            desc = p.u32(0x55002b78 + 4 * 12)
            desc_at = p.off(desc)
            width, height, path_va = struct.unpack_from('<HHI', before, desc_at)
            _need((width, height) == (720, 480), 'Diary descriptor')
            at = p.off(path_va)
            _need(before[at:at + len(DIARY_PATH) + 1] == DIARY_PATH + b'\0', 'Diary path')
            actual = after[body:body + capacity]
            _need(_padding_only(jpeg, actual), 'JPEG altered beyond zero COM padding')
            write(body, actual)
            write(head, b'A')
            write(at, b'A')
            for request in (2, 10, 11, 12):
                write(p.off(0x55002b78 + 4 * request), struct.pack('<I', desc))
            add('a_path_four_requests_fixed_slot_jpeg', True)
        check_value = (2 ** 32 - _sum32(expected[:-4])) % (2 ** 32)
        expected[-4:] = check_value.to_bytes(4, 'little')
        # This exact comparison also protects all other icons, languages, request
        # pointers, RES headers/bodies, RTOS code, and every unedited payload byte.
        add('entire_payload_matches_independent_request', after == expected)
        add('payload_sha', _sha(after) == result['payload_sha256_after'])
    except (ValueError, TypeError, KeyError, IndexError, struct.error,
            fwread.FirmwareReadError) as exc:
        add('closed_failure', False, str(exc))
    return checks


def all_ok(checks):
    return type(checks) is list and bool(checks) and all(c.get('ok') is True for c in checks)

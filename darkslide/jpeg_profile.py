"""Single-scan JPEG inspection and fixed-length comment insertion."""
from dataclasses import dataclass


class ProfileError(ValueError):
    pass


def ensure(condition, explanation):
    if not condition:
        raise ProfileError(explanation)


@dataclass(frozen=True)
class Segment:
    code: int
    start: int
    following: int
    content: bytes


def segments_of(image):
    ensure(type(image) is bytes and image.startswith(bytes.fromhex('ffd8')) and
           image.endswith(bytes.fromhex('ffd9')), 'Image boundaries are invalid')
    cursor, sections = 2, []
    while cursor < len(image):
        ensure(cursor + 4 <= len(image) and image[cursor] == 255, 'Segment header is incomplete')
        count = int.from_bytes(image[cursor + 2:cursor + 4], 'big')
        next_cursor = cursor + 2 + count
        ensure(count >= 2 and next_cursor <= len(image), 'Segment size exceeds the image')
        section = Segment(image[cursor + 1], cursor, next_cursor, image[cursor + 4:next_cursor])
        sections.append(section)
        cursor = next_cursor
        if section.code == 218:
            return sections
    raise ProfileError('Image does not contain a scan')


def inspect(image):
    sections = segments_of(image)
    permitted = {192, 196, 219, 221, 224, 254, 218}
    ensure(all(section.code in permitted for section in sections), 'Image uses an unsupported segment')
    grouped = {}
    for section in sections:
        grouped.setdefault(section.code, []).append(section)
    ensure(219 in grouped and 196 in grouped, 'Image has no quantization or entropy tables')
    ensure(len(grouped.get(192, [])) == 1, 'Image requires exactly one baseline frame')
    frame = grouped[192][0].content
    ensure(len(frame) == 15, 'Frame component count is unsupported')
    precision, height, width, channels = (frame[0], int.from_bytes(frame[1:3], 'big'),
                                          int.from_bytes(frame[3:5], 'big'), frame[5])
    components = tuple(tuple(frame[i:i + 3]) for i in (6, 9, 12))
    ensure((precision, width, height, channels) == (8, 720, 480, 3), 'Frame dimensions or depth are unsupported')
    ensure(tuple(x[0] for x in components) == (1, 2, 3) and
           tuple(x[1] for x in components) == (34, 17, 17), 'Frame color sampling is unsupported')
    scan = sections[-1]
    selectors = scan.content
    ensure(len(selectors) == 10 and selectors[0] == 3 and
           tuple(selectors[i] for i in (1, 3, 5)) == (1, 2, 3) and
           selectors[-3:] == bytes((0, 63, 0)), 'Scan component layout is unsupported')
    # Entropy contents are checked for framing only. Pixel decoding belongs to
    # the independent image validator used before export.
    search = scan.following
    while True:
        prefix = image.find(b'\xff', search)
        ensure(prefix >= 0 and prefix + 1 < len(image), 'Scan ending is absent')
        code = image[prefix + 1]
        if code == 0 or 208 <= code <= 215:
            search = prefix + 2
            continue
        ensure(code == 217 and prefix == len(image) - 2, 'Scan contains unexpected marker data')
        break
    return dict(width=width, height=height, precision=precision, sampling='4:2:0',
                sos_offset=scan.start, entropy_offset=scan.following)


def comment_sizes(missing):
    """Plan all segment extents using quotient/remainder, without a fill loop."""
    ensure(type(missing) is int and missing >= 0, 'Requested image extent is too small')
    ensure(missing == 0 or missing >= 4, 'Image leaves insufficient room for a comment')
    full, tail = divmod(missing, 65537)
    lengths = [65537] * full
    if tail:
        if tail < 4:
            lengths[-1] -= 4
            tail += 4
        lengths.append(tail)
    return lengths


def fill_comments(image, capacity):
    info = inspect(image)
    sizes = comment_sizes(capacity - len(image))
    comments = b''.join(bytes.fromhex('fffe') + (extent - 2).to_bytes(2, 'big') +
                        bytes(extent - 4) for extent in sizes)
    cut = info['sos_offset']
    return b''.join((image[:cut], comments, image[cut:]))

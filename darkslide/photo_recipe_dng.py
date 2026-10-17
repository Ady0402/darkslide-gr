"""Offline DNG recipe reader and copy-only XMP writer.

Read XMP tag 700 or the experimental d534 entry inside RICOH DNGPrivateData.
No pixel processing, MakerNote rewriting or camera installation. Existing XMP
is refused to avoid destroying another editor's metadata. All original bytes
except the TIFF root-IFD pointer remain at their original file positions.
"""
import base64
import binascii
import struct
import xml.etree.ElementTree as ET

from . import photo_recipe as recipe

NS = 'urn:darkslide:photo-film-recipe:1.0/'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
PROPERTY = '{' + NS + '}FilmRecipe'
MAX_XMP = 131072
MAX_DNG = 512 * 1024 * 1024
PRIVATE_TAG = 0xd534
SIZES = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8, 13:4}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _ifd0(data):
    _need(type(data) is bytes and 8 <= len(data) <= MAX_DNG, 'DNG 文件长度不支持')
    _need(data[:2] in (b'II', b'MM'), '需要 TIFF 格式的 DNG')
    endian = '<' if data[:2] == b'II' else '>'
    magic, offset = struct.unpack_from(endian+'HI', data, 2)
    _need(magic == 42 and 8 <= offset <= len(data)-6, '不支持的 TIFF 头')
    count = struct.unpack_from(endian+'H', data, offset)[0]
    _need(0 < count <= 4096 and offset+6+12*count <= len(data), 'DNG 目录越界')
    entries = {}
    for i in range(count):
        at = offset+2+12*i
        tag, kind, n, pointer = struct.unpack_from(endian+'HHII', data, at)
        _need(tag not in entries and kind in SIZES and n > 0, 'DNG 目录项重复或不支持')
        size = n*SIZES[kind]
        value_at = at+8 if size <= 4 else pointer
        _need(8 <= value_at <= len(data) and size <= len(data)-value_at, 'DNG 数据越界')
        entries[tag] = (data[at:at+12], kind, n, value_at, size)
    _need(50706 in entries and entries[50706][1:3] == (1, 4) and
          data[entries[50706][3]] == 1, '缺少支持的 DNGVersion')
    nxt = struct.unpack_from(endian+'I', data, offset+2+12*count)[0]
    _need(nxt == 0 or 8 <= nxt <= len(data)-6, 'DNG 后续目录越界')
    return endian, entries, nxt


def _model(data, entries):
    item = entries.get(272)
    _need(item is not None and item[1] == 2 and item[4] <= 128, '缺少相机机型')
    raw = data[item[3]:item[3]+item[4]]
    _need(raw.endswith(b'\0'), '相机机型未终止')
    _need(raw.rstrip(b'\0 ').strip() == b'RICOH GR IIIx', '这份配方只适用于 GR IIIx 照片')


def _xmp(packet):
    recipe.decode(packet)
    encoded = base64.b64encode(packet).decode('ascii')
    out = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="'+RDF+'">'
           '<rdf:Description rdf:about="" xmlns:ds="'+NS+'">'
           '<ds:FilmRecipe>'+encoded+'</ds:FilmRecipe>'
           '</rdf:Description></rdf:RDF></x:xmpmeta>').encode('utf-8')
    _need(len(out) <= MAX_XMP, 'XMP 配方超过容量')
    return out


def _from_xmp(value, allow_missing=False):
    _need(len(value) <= MAX_XMP, 'XMP 超过读取容量')
    # Reject DTD/entity declarations and non-UTF8 forms before XML parsing.
    try:
        text = value.decode('utf-8')
    except UnicodeError as error:
        raise ValueError('不支持的 XMP 编码') from error
    _need('\0' not in text and '<!DOCTYPE' not in text.upper() and
          '<!ENTITY' not in text.upper(), 'XMP 不允许实体或 DTD')
    try:
        root = ET.fromstring(text)
        found = list(root.iter(PROPERTY))
        attrs = [v for node in root.iter() for k,v in node.attrib.items() if k == PROPERTY]
        if allow_missing and not found and not attrs:
            return None
        _need(len(found)+len(attrs) == 1, '照片配方缺失或有冲突')
        if found:
            _need(not list(found[0]) and not found[0].attrib, '不支持的配方属性结构')
            encoded = found[0].text or ''
        else:
            encoded = attrs[0]
        packet = base64.b64decode(''.join(encoded.split()), validate=True)
    except (ET.ParseError, binascii.Error, UnicodeError) as error:
        raise ValueError('照片配方编码错误') from error
    recipe.decode(packet)
    return packet


def _from_private(value):
    """Read only the verified RICOH eight-byte header + single-IFD layout.

    Offsets are relative to the private blob including its header, not the
    enclosing TIFF. A recognized but malformed directory cannot be ignored:
    that could conceal a conflicting recipe behind otherwise valid XMP.
    """
    if value[:8] not in (b'RICOH\0II', b'RICOH\0MM'):
        return None
    _need(len(value) >= 14, '私有配方目录截断')
    endian = '<' if value[6:8] == b'II' else '>'
    count = struct.unpack_from(endian+'H', value, 8)[0]
    end = 14 + 12*count
    _need(count <= 4096 and end <= len(value), '私有配方目录越界')
    _need(struct.unpack_from(endian+'I', value, end-4)[0] == 0,
          '不支持的私有后续目录')
    tags = set()
    packet = None
    packet_range = None
    payloads = []
    for i in range(count):
        at = 10 + 12*i
        tag, kind, n, pointer = struct.unpack_from(endian+'HHII', value, at)
        _need(tag not in tags and kind in SIZES, '私有目录项重复或不支持')
        tags.add(tag)
        size = n*SIZES[kind]
        start = at+8 if size <= 4 else pointer
        _need(start <= len(value) and size <= len(value)-start,
              '私有配方数据越界')
        if size > 4:
            _need(start >= end, '私有配方数据与目录重叠')
            payloads.append((tag, start, start+size))
        if tag == PRIVATE_TAG:
            _need(kind == 7 and 1600 <= n <= 24+1572+65536+4,
                  '私有配方类型或长度不支持')
            packet = value[start:start+size]
            recipe.decode(packet)
            packet_range = (start, start+size)
    if packet_range:
        a, b = packet_range
        _need(all(tag == PRIVATE_TAG or b <= lo or hi <= a
                  for tag, lo, hi in payloads), '私有配方与其他载荷重叠')
    return packet


def embed(data, packet):
    """Return a new file; callers must write exclusively to a separate path.

    The caller must know the historical recipe. This function cannot infer it
    from a factory slot number. Camera acceptance of appended IFDs is untested.
    """
    endian, entries, nxt = _ifd0(data)
    _model(data, entries)
    _need(700 not in entries, '照片已有 XMP，保留原数据；本工具不合并或覆盖')
    _need(len(entries) < 4096, 'DNG 目录已满')
    xmp = _xmp(packet)
    out = bytearray(data)
    out.extend(b'\0' * (len(out) % 2))
    xmp_at = len(out)
    out.extend(xmp)
    out.extend(b'\0' * (len(out) % 2))
    ifd_at = len(out)
    records = {tag: row[0] for tag, row in entries.items()}
    records[700] = struct.pack(endian+'HHII', 700, 1, len(xmp), xmp_at)
    out.extend(struct.pack(endian+'H', len(records)))
    out.extend(b''.join(records[tag] for tag in sorted(records)))
    out.extend(struct.pack(endian+'I', nxt))
    out[4:8] = struct.pack(endian+'I', ifd_at)
    _need(len(out) <= MAX_DNG, 'DNG 输出超过容量')
    result = bytes(out)
    _need(extract(result) == packet, '照片配方读回不一致')
    return result


def extract(data):
    endian, entries, nxt = _ifd0(data)
    _model(data, entries)
    packets = []
    if 50740 in entries:
        raw, kind, count, at, size = entries[50740]
        _need(kind in (1, 7), 'DNGPrivateData 标签类型不支持')
        private = _from_private(data[at:at+size])
        if private is not None:
            packets.append(private)
    if 700 in entries:
        raw, kind, count, at, size = entries[700]
        _need(kind == 1 and count <= MAX_XMP, 'XMP 标签类型或长度不支持')
        xmp = _from_xmp(data[at:at+size], allow_missing=True)
        if xmp is not None:
            packets.append(xmp)
    _need(packets, '照片未保存 Darkslide 配方，不能从槽位编号推断旧配方')
    _need(all(packet == packets[0] for packet in packets), '照片内两种配方载体冲突')
    return packets[0]

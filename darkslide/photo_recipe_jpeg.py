"""Read complete IIIx recipes from the bounded DSRECIPE APP15 carrier.

Independent of the native writer: walk markers (including entropy escapes and
restart markers), validate EXIF model, ordered chunks, lengths, padding and the
portable packet CRC/schema. Never search image entropy for a packet signature.
"""
import struct
from . import photo_recipe

MAGIC = b'DSRECIPE'
HEADER = struct.Struct('<8s4B3I')
MAX_JPEG = 512 * 1024 * 1024
CHUNK = 60000


def _need(ok, why):
    if not ok:
        raise ValueError(why)


def markers(data):
    _need(type(data) is bytes and 4 <= len(data) <= MAX_JPEG and data[:2] == b'\xff\xd8',
          '需要完整 JPEG 文件')
    pos = 2
    scan = False
    had_scan = False
    had_frame = False
    while pos < len(data):
        if scan:
            at = data.find(b'\xff', pos)
            _need(at >= 0, 'JPEG 扫描数据未结束')
            pos = at
        start = pos
        _need(data[pos] == 255, 'JPEG 标记边界错误')
        while pos < len(data) and data[pos] == 255:
            pos += 1
        _need(pos < len(data), 'JPEG 标记截断')
        marker = data[pos]
        pos += 1
        if scan and (marker == 0 or 0xd0 <= marker <= 0xd7):
            continue
        _need(marker not in (0, 0xd8) and not 0xd0 <= marker <= 0xd7, 'JPEG 标记顺序错误')
        scan = False
        if marker == 0xd9:
            _need(had_frame and had_scan and pos == len(data), 'JPEG 缺少图像或存在尾随数据')
            return
        if marker == 1:
            continue
        _need(pos+2 <= len(data), 'JPEG 段长度截断')
        length = int.from_bytes(data[pos:pos+2], 'big')
        _need(length >= 2 and pos+length <= len(data), 'JPEG 段越界')
        payload = data[pos+2:pos+length]
        yield marker, payload, start, pos+length, had_scan
        if marker in (0xc0, 0xc1, 0xc2):
            _need(len(payload) >= 6 and len(payload) == 6+3*payload[5], 'JPEG 帧头错误')
            had_frame = True
        if marker == 0xda:
            _need(had_frame and payload and len(payload) == 4+2*payload[0], 'JPEG 扫描头错误')
            scan = had_scan = True
        pos += length
    raise ValueError('JPEG 缺少结束标记')


def _model(exif):
    data = exif[6:]
    _need(len(data) >= 8 and data[:2] in (b'II', b'MM'), 'EXIF 头错误')
    endian = '<' if data[:2] == b'II' else '>'
    magic, offset = struct.unpack_from(endian+'HI', data, 2)
    _need(magic == 42 and 8 <= offset <= len(data)-6, 'EXIF 目录越界')
    count = struct.unpack_from(endian+'H', data, offset)[0]
    _need(count <= 4096 and offset+6+count*12 <= len(data), 'EXIF 目录截断')
    models = []
    for i in range(count):
        at = offset+2+12*i
        tag, kind, n, pointer = struct.unpack_from(endian+'HHII', data, at)
        if tag != 272:
            continue
        _need(kind == 2 and 1 <= n <= 128, 'EXIF 机型类型错误')
        start = at+8 if n <= 4 else pointer
        _need(8 <= start <= len(data)-n, 'EXIF 机型越界')
        value = data[start:start+n]
        _need(value.endswith(b'\0'), 'EXIF 机型未终止')
        models.append(value.rstrip(b'\0 ').strip())
    _need(models == [b'RICOH GR IIIx'], '这份配方只适用于 GR IIIx 照片')


def extract(data):
    parts = []
    exifs = []
    total = None
    count = None
    offset = 0
    for marker, payload, start, end, after_scan in markers(data):
        if marker == 0xe1 and payload.startswith(b'Exif\0\0'):
            _need(not after_scan, 'EXIF 位于扫描数据之后')
            exifs.append(payload)
        if marker != 0xef or not payload.startswith(MAGIC):
            continue
        _need(not after_scan and len(payload) >= HEADER.size, 'JPEG 配方段位置或头部错误')
        magic, version, index, number, padding, size, at, n = HEADER.unpack_from(payload)
        _need(version == 1 and 1600 <= size <= photo_recipe.MAX_PACKET and
              number == (size+CHUNK-1)//CHUNK and index == len(parts) and index < number and
              at == offset and n == min(CHUNK, size-at), 'JPEG 配方分块顺序或长度错误')
        _need(total in (None, size) and count in (None, number), 'JPEG 配方分块冲突')
        last = index+1 == number
        _need(padding <= 31 and (last or padding == 0), 'JPEG 配方填充错误')
        tail = bytes(padding)+b'\xff\xd8' if last else b''
        _need(len(payload) == HEADER.size+n+len(tail) and payload[HEADER.size+n:] == tail,
              'JPEG 配方段截断或尾部错误')
        parts.append(payload[HEADER.size:HEADER.size+n])
        total, count, offset = size, number, at+n
    _need(len(exifs) == 1, 'JPEG 缺少唯一 EXIF 机型记录')
    _model(exifs[0])
    _need(parts, '照片未保存 Darkslide 配方，不能从槽位编号推断旧配方')
    _need(len(parts) == count and offset == total, 'JPEG 配方分块不完整')
    packet = b''.join(parts)
    photo_recipe.decode(packet)
    return packet

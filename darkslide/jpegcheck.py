"""Full entropy decode check for the shutdown JPEG (standard library only).

The structural contract in shared_shutdown checks markers, size and sampling.
This module goes one step further and walks every Huffman code of the scan:
all 1350 MCUs of a 720x480 4:2:0 baseline image must decode with the file's
own tables, without restart markers, and the scan must end exactly at EOI.
No pixels are produced; a file that passes is one the camera's baseline
decoder can read to the end.
"""


class JpegCheckError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise JpegCheckError(message)


WIDTH, HEIGHT = 720, 480
MCUS = (WIDTH // 16) * (HEIGHT // 16)          # 4:2:0 → 16x16 MCU → 45 x 30 = 1350
BLOCKS = ((1, 4), (2, 1), (3, 1))               # component id, blocks per MCU


def _segments(data):
    need(data[:2] == b"\xff\xd8", "缺少 JPEG 开头")
    pos = 2
    while True:
        need(pos + 4 <= len(data) and data[pos] == 0xFF, "JPEG 段结构不对")
        marker = data[pos + 1]
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        need(length >= 2 and pos + 2 + length <= len(data), "JPEG 段长度越界")
        body = data[pos + 4:pos + 2 + length]
        yield marker, body, pos + 2 + length
        if marker == 0xDA:
            return
        pos += 2 + length


def _huffman(bits, values):
    """Canonical code table: {(length, code): symbol}."""
    need(sum(bits) == len(values) and len(values) <= 256, "霍夫曼表长度不对")
    table, code, k = {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            need(code < (1 << length) - (1 if length == 16 else 0), "霍夫曼表编码越界")
            table[(length, code)] = values[k]
            code += 1
            k += 1
        code <<= 1
    return table


class _Bits:
    def __init__(self, data, start):
        self.data, self.pos, self.byte, self.left = data, start, 0, 0

    def bit(self):
        if self.left == 0:
            need(self.pos < len(self.data), "压缩数据提前结束")
            b = self.data[self.pos]
            if b == 0xFF:
                need(self.pos + 1 < len(self.data), "压缩数据提前结束")
                nxt = self.data[self.pos + 1]
                need(nxt == 0x00, "压缩数据中出现不允许的标记 FF%02X" % nxt)
                self.pos += 2
            else:
                self.pos += 1
            self.byte, self.left = b, 8
        self.left -= 1
        return (self.byte >> self.left) & 1

    def bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def symbol(self, table):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            sym = table.get((length, code))
            if sym is not None:
                return sym
        raise JpegCheckError("压缩数据里有霍夫曼表之外的编码")


def check(data):
    """Raise JpegCheckError unless the whole scan decodes. Returns a summary."""
    need(type(data) is bytes and data[-2:] == b"\xff\xd9", "缺少 JPEG 结尾")
    quant, dc, ac, comps, scan, start = set(), {}, {}, {}, None, None
    for marker, body, end in _segments(data):
        if marker == 0xDB:
            i = 0
            while i < len(body):
                pq, tq = body[i] >> 4, body[i] & 15
                need(pq == 0 and tq <= 3, "量化表必须是 8 位基线表")
                need(i + 65 <= len(body), "量化表长度不对")
                quant.add(tq)
                i += 65
        elif marker == 0xC4:
            i = 0
            while i < len(body):
                tc, th = body[i] >> 4, body[i] & 15
                need(tc in (0, 1) and th <= 1, "霍夫曼表必须是基线表")
                need(i + 17 <= len(body), "霍夫曼表长度不对")
                bits = list(body[i + 1:i + 17])
                n = sum(bits)
                need(i + 17 + n <= len(body), "霍夫曼表长度不对")
                (dc if tc == 0 else ac)[th] = _huffman(bits, list(body[i + 17:i + 17 + n]))
                i += 17 + n
        elif marker == 0xC0:
            need(len(body) == 15 and body[0] == 8 and body[5] == 3, "必须是 8 位三通道基线 JPEG")
            need(int.from_bytes(body[1:3], "big") == HEIGHT and int.from_bytes(body[3:5], "big") == WIDTH,
                 "尺寸必须是 720×480")
            for k in range(3):
                cid, samp, tq = body[6 + 3 * k], body[7 + 3 * k], body[8 + 3 * k]
                comps[cid] = dict(samp=samp, tq=tq)
            need({c: v["samp"] for c, v in comps.items()} == {1: 0x22, 2: 0x11, 3: 0x11}, "必须是 4:2:0 采样")
        elif marker == 0xDA:
            need(len(body) == 10 and body[0] == 3 and body[-3:] == b"\x00\x3f\x00", "必须是基线顺序扫描")
            scan = {body[1 + 2 * k]: (body[2 + 2 * k] >> 4, body[2 + 2 * k] & 15) for k in range(3)}
            start = end
        else:
            need(marker in (0xE0, 0xFE), "不支持的 JPEG 段 FF%02X（不允许重启间隔等）" % marker)
    need(comps and scan is not None, "缺少帧头或扫描头")
    need(set(scan) == {1, 2, 3}, "扫描通道不对")
    for cid, info in comps.items():
        need(info["tq"] in quant, "通道引用了不存在的量化表")
        td, ta = scan[cid]
        need(td in dc and ta in ac, "通道引用了不存在的霍夫曼表")
    reader = _Bits(data, start)
    for _ in range(MCUS):
        for cid, blocks in BLOCKS:
            td, ta = scan[cid]
            for _ in range(blocks):
                size = reader.symbol(dc[td])
                need(size <= 11, "直流系数位数越界")
                reader.bits(size)
                k = 1
                while k < 64:
                    rs = reader.symbol(ac[ta])
                    run, size = rs >> 4, rs & 15
                    if size == 0:
                        if run == 15:
                            k += 16
                            continue
                        break                      # end of block
                    k += run
                    need(k <= 63 and size <= 10, "交流系数越界")
                    reader.bits(size)
                    k += 1
                need(k <= 64, "交流系数越界")
    need(reader.left == 0 or reader.byte & ((1 << reader.left) - 1) == (1 << reader.left) - 1,
         "压缩数据结尾的填充位不对")
    need(reader.pos == len(data) - 2, "1350 个块解完后没有正好到结尾")
    return dict(width=WIDTH, height=HEIGHT, mcus=MCUS)

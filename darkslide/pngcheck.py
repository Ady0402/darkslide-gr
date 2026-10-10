"""Minimal PNG reader for the factory icon contract (stdlib only).

Factory preset icons are 40×40; the visible area x1–38, y2–37 (38×36) is fully
opaque and the 232-pixel border is fully transparent.
"""
import struct
import zlib

VISIBLE = (1, 2, 38, 36)


class PngError(ValueError):
    pass


def rgba_rows(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PngError("不是 PNG 文件")
    pos, idat, header = 8, b"", None
    while pos + 8 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + n
    if header is None:
        raise PngError("PNG 缺少文件头")
    width, height, depth, ctype, _, _, interlace = header
    if depth != 8 or ctype != 6 or interlace != 0:
        raise PngError("图标必须是 8 位 RGBA、非隔行 PNG")
    raw = zlib.decompress(idat)
    stride, bpp = width * 4, 4
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f != 0:
                raise PngError("PNG 数据损坏")
        rows.append(bytes(line))
        prev = line
    return width, height, rows


def check_icon(data):
    width, height, rows = rgba_rows(data)
    if (width, height) != (40, 40):
        raise PngError("图标必须是 40×40")
    vx, vy, vw, vh = VISIBLE
    for y, line in enumerate(rows):
        for x in range(width):
            alpha = line[x * 4 + 3]
            inside = vx <= x < vx + vw and vy <= y < vy + vh
            if inside and alpha != 255:
                raise PngError("图标可见区（38×36）必须完全不透明")
            if not inside and alpha != 0:
                raise PngError("图标四周的透明边必须保持完全透明")
    return True


def write_png(width, height, rgba):
    """Encode 8-bit RGBA bytes as a PNG (filter 0, zlib)."""
    if len(rgba) != width * height * 4:
        raise PngError("RGBA length does not match size")

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

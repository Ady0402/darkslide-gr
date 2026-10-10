"""Read-only access to a GR III 2.10 firmware file: unpack the container,
then read factory preset icons and menu strings.

Independent implementation of the firmware container format.
Nothing here writes or modifies firmware.
"""
import hashlib
import struct

MAX_OUTPUT = 128 * 1024 * 1024

# Layout of the decoded GR III 2.10 payload.
V210 = dict(
    payload_sha256="53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703",
    rtos_va=0x53000000, rtos_body=0x10870, rtos_size=0x10B55C0,
    data_lma=0x5407B540, data_ram=0x55000000, data_size=0x3A080,
    icon_index_ram=0x550020FC, icon_body=0x21284D0, icon_size=18354964, icon_max_id=670,
    string_array_ram=0x55002BAC, languages=21, string_ids=785,
)
V210_INPUT_SHA256 = "d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4"
LANG = {"ja": 0, "en": 1, "zh-TW": 18, "zh-CN": 19}


class FirmwareReadError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise FirmwareReadError(message)


def unpack(raw):
    """Decode the frame stream starting at 0x80. Returns the payload bytes."""
    cursor, out, n = 0x80, bytearray(), len(raw)
    while True:
        need(cursor + 2 <= n, "frame header beyond end of file")
        prefix = (raw[cursor] << 8) | raw[cursor + 1]
        cursor += 2
        if prefix == 0:
            return bytes(out)
        end = cursor + (prefix & 0x7FFF)
        need(end <= n, "frame beyond end of file")
        if prefix & 0x8000:
            out += raw[cursor:end]
            cursor = end
            continue
        while cursor < end:
            need(cursor + 2 <= end, "truncated flag word")
            flags = (raw[cursor] << 8) | raw[cursor + 1]
            cursor += 2
            for bit in range(15, -1, -1):
                if cursor >= end:
                    break
                if not (flags >> bit) & 1:
                    out.append(raw[cursor])
                    cursor += 1
                    continue
                need(cursor + 2 <= end, "truncated back-reference")
                first, second = raw[cursor], raw[cursor + 1]
                cursor += 2
                distance = ((first & 0xF8) << 5) | second
                count = first & 7
                if count == 7:
                    need(cursor < end, "truncated length byte")
                    count += raw[cursor]
                    cursor += 1
                if distance == 0:
                    need(cursor == end, "frame terminator before frame end")
                    break
                if count == 262:
                    while True:
                        need(cursor < end, "truncated long length")
                        extra = raw[cursor]
                        cursor += 1
                        count += extra
                        if extra != 255:
                            break
                count += 3
                need(distance <= len(out), "back-reference before start of output")
                need(len(out) + count <= MAX_OUTPUT, "decoded data too large")
                start = len(out) - distance
                if distance >= count:
                    out += out[start:start + count]
                else:
                    for i in range(count):
                        out.append(out[start + i])


class Payload:
    def __init__(self, payload, layout=V210, pinned=True):
        # pinned=False reads a modified payload with the same 2.10 layout
        # (used for read-back checks of generated files).
        if pinned:
            need(hashlib.sha256(payload).hexdigest() == layout["payload_sha256"],
                 "解码结果和已知的 GR III 2.10 不一致")
        self.p, self.L = payload, layout
        self._check_section(layout["rtos_body"], b"RTOS\0\0\0\0", layout["rtos_size"])
        self._check_section(layout["icon_body"], b"ICONBIN\0", layout["icon_size"])

    def _check_section(self, body, magic, size):
        head = self.p[body - 16:body]
        need(head[:8] == magic and struct.unpack_from("<I", head, 12)[0] == size, "section header mismatch")

    def off(self, va):
        L = self.L
        if L["data_ram"] <= va < L["data_ram"] + L["data_size"]:
            va = va - L["data_ram"] + L["data_lma"]
        need(L["rtos_va"] <= va < L["rtos_va"] + L["rtos_size"], "address outside RTOS image")
        return va - L["rtos_va"] + L["rtos_body"]

    def u32(self, va):
        return struct.unpack_from("<I", self.p, self.off(va))[0]

    # icons --------------------------------------------------------------
    def icon_descriptor(self, icon_id):
        need(0 < icon_id <= self.L["icon_max_id"], "icon id out of range")
        desc_va = self.u32(self.L["icon_index_ram"] + 4 * icon_id)
        width, height, pixel_index = struct.unpack_from("<HHI", self.p, self.off(desc_va))
        start = self.L["icon_body"] + 4 * pixel_index
        size = 4 * width * height
        need(4 * pixel_index + size <= self.L["icon_size"], "icon pixels outside ICONBIN")
        return dict(icon_id=icon_id, width=width, height=height, payload_offset=start, size=size)

    def icon_pixels(self, icon_id):
        d = self.icon_descriptor(icon_id)
        return d, self.p[d["payload_offset"]:d["payload_offset"] + d["size"]]

    # strings ------------------------------------------------------------
    def string(self, string_id, lang="en"):
        L = self.L
        li = LANG[lang]
        need(0 < string_id < L["string_ids"], "string id out of range")
        table = self.u32(L["string_array_ram"] + 4 * li)
        record = self.u32(table + 4 * string_id)
        need(record != 0, "empty string record")
        o = self.off(record)
        n, lines = self.p[o], self.p[o + 1]
        text_va = self.u32(record + 4)
        t = self.off(text_va)
        text = self.p[t:t + 2 * (n - 1)].decode("utf-16-le")
        need(self.p[t + 2 * (n - 1):t + 2 * n] == b"\0\0", "string not NUL-terminated")
        return dict(text=text, length_byte=n, lines=lines, record_offset=o, text_offset=t)


def icon_to_rgba(raw):
    """Machine icon words (R, G, B, 4th byte per pixel) -> RGBA bytes.
    4th byte 0 is the factory transparent key; everything else shows opaque."""
    out = bytearray(raw)
    for i in range(3, len(out), 4):
        out[i] = 0 if raw[i] == 0 else 255
    return bytes(out)


def rgba_to_icon(rgba):
    """RGBA bytes from a contract-checked 40x40 PNG -> machine icon words.
    Byte order is unchanged (R, G, B, A); alpha must already be 0 or 255."""
    need(len(rgba) == 6400, "icon must be 40x40 RGBA")
    for i in range(3, 6400, 4):
        need(rgba[i] in (0, 255), "icon alpha must be 0 or 255")
    return bytes(rgba)

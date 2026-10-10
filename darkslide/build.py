"""Deterministic, standard-library-only GR III 2.10 editor.

Independent implementation from the container/layout facts recorded in research
#359/#364 and the Darkslide interface. No third-party firmware code is imported.
Only returns bytes; the caller owns authorization and persistence.
"""
import hashlib
import struct


class BuildError(ValueError):
    pass


INPUT_SHA = "d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4"
PAYLOAD_SHA = "53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703"
INPUT_SIZE = 30391780
PAYLOAD_SIZE = 59718388
VERSION = b"\x02\x0a\x15\x1b"
SOURCE_SHA256 = "ba9510ad500380a8e62090ae5d4af875774e7d6eb45eb23f6b1ffae2e1f601d9"
MAP = ((358, 4, "Standard"), (548, 268, "Vivid"),
       (354, 269, "Monotone"), (357, 270, "Soft Monotone"),
       (350, 271, "Hard Monotone"), (352, 272, "Hi-Contrast B&W"),
       (232, 274, "Positive Film"), (346, 275, "Bleach Bypass"),
       (356, 276, "Retro"), (351, 277, "HDR Tone"),
       (50, 278, "Cross Processing"), (23, 273, "Negative Film"),
       (347, 279, "Custom1"), (348, 280, "Custom2"))
ICON_SLOTS = frozenset((1, 7, 11, 12))
NAME_SLOTS = frozenset((7, 11, 12))


def _require(condition, message):
    if not condition:
        raise BuildError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _exact(actual, expected):
    """JSON equality that does not accept True/1 or 40.0/40 aliases."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(_exact(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(_exact(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _sum(data):
    _require(len(data) % 4 == 0, "校验数据未按四字节对齐")
    return sum(v[0] for v in struct.iter_unpack("<I", data)) & 0xffffffff


def _decode(raw):
    """Validate the complete container and retain encoded frame boundaries."""
    _require(len(raw) >= 152 and len(raw) % 4 == 0, "固件容器长度错误")
    footer = struct.unpack_from("<6I", raw, len(raw) - 24)
    project, marker, kind, encoded, decoded, checksum = footer
    _require((project, marker, kind, decoded) ==
             (0x024c024c, 0xa55a5aa5, 2, PAYLOAD_SIZE), "固件页脚身份错误")
    _require(raw[0x38:0x3c] == VERSION and raw[0x50:0x54] == VERSION,
             "固件版本字错误")
    _require(_sum(raw) == 0, "固件容器校验错误")
    stop = 128 + encoded
    _require(stop <= len(raw) - 24, "压缩流越界")
    pos, output, frames = 128, bytearray(), []
    while pos < stop:
        begin, start = pos, len(output)
        _require(pos + 2 <= stop, "帧头截断")
        word = int.from_bytes(raw[pos:pos + 2], "big")
        pos += 2
        if word == 0:
            _require(pos == stop and len(output) == decoded, "流尾或解码长度错误")
            _require(_sum(output) == 0, "解码流校验错误")
            return bytes(output), frames, stop, footer
        end = pos + (word & 0x7fff)
        _require(end <= stop, "帧长度越界")
        literal = bool(word & 0x8000)
        if literal:
            output.extend(raw[pos:end])
            pos = end
        else:
            terminated = False
            while pos < end:
                _require(pos + 2 <= end, "标志字截断")
                flags = int.from_bytes(raw[pos:pos + 2], "big")
                pos += 2
                for bit in range(15, -1, -1):
                    if pos == end:
                        break
                    if flags & (1 << bit) == 0:
                        output.append(raw[pos])
                        pos += 1
                    else:
                        _require(pos + 2 <= end, "回溯码截断")
                        a, b = raw[pos:pos + 2]
                        pos += 2
                        distance, length = ((a & 0xf8) << 5) | b, a & 7
                        if length == 7:
                            _require(pos < end, "长度码截断")
                            length += raw[pos]
                            pos += 1
                        if distance == 0:
                            _require(pos == end, "帧终止码位置错误")
                            terminated = True
                            break
                        if length == 262:
                            while True:
                                _require(pos < end, "扩展长度码截断")
                                extra = raw[pos]
                                pos += 1
                                length += extra
                                if extra != 255:
                                    break
                        length += 3
                        _require(distance <= len(output) and len(output) + length <= decoded,
                                 "回溯范围错误")
                        source = len(output) - distance
                        if distance >= length:
                            output.extend(output[source:source + length])
                        else:
                            for i in range(length):
                                output.append(output[source + i])
                if terminated:
                    break
            _require(terminated, "压缩帧缺少终止码")
        _require(len(output) <= decoded, "解码流超长")
        frames.append((begin, end, start, len(output), literal))
    raise BuildError("压缩流缺少终止帧")


def _off(va, size=4):
    if 0x55000000 <= va < 0x5503a080:
        va = va - 0x55000000 + 0x5407b540
    _require(0x53000000 <= va and va + size <= 0x540b55c0, "RTOS地址越界")
    return va - 0x53000000 + 0x10870


def _u32(payload, va):
    return struct.unpack_from("<I", payload, _off(va))[0]


def _icon(payload, identifier):
    desc = _u32(payload, 0x550020fc + identifier * 4)
    w, h, index = struct.unpack_from("<HHI", payload, _off(desc, 8))
    size, start = w * h * 4, 0x21284d0 + index * 4
    _require(start + size <= 0x21284d0 + 18354964, "图标范围越界")
    return start, size, w, h


def _string(payload, identifier, language):
    table = _u32(payload, 0x55002bac + language * 4)
    record = _u32(payload, table + identifier * 4)
    r = _off(record, 8)
    count, lines, zeros = struct.unpack_from("<BBH", payload, r)
    _require(count >= 2 and lines == 1 and zeros == 0, "菜单字符串记录格式错误")
    va = struct.unpack_from("<I", payload, r + 4)[0]
    t = _off(va, count * 2)
    _require(va < 0x5407b540 and payload[t + (count - 1) * 2:t + count * 2] == b"\0\0",
             "菜单文本不是只读区原位字符串")
    try:
        text = payload[t:t + (count - 1) * 2].decode("utf-16-le")
    except UnicodeError as exc:
        raise BuildError("菜单文本编码错误") from exc
    return r, t, count, va, text


def _template(template):
    _require(type(template) is dict and template.get("reviewed") is True,
             "模板尚未复核，不能生成")
    _require(set(template) == {"schema", "id", "model", "firmware", "reviewed",
             "review_note", "official_inputs", "icon", "slots"}, "模板存在缺失或未知字段")
    _require(all(type(template[k]) is str for k in ("id", "model", "firmware", "review_note"))
             and template["id"] == "gr3-2.10-reviewed-1", "模板版本或文本类型错误")
    _require(type(template.get("schema")) is int and template["schema"] == 1 and
             template.get("model") == "GR III" and template.get("firmware") == "2.10",
             "不支持的模板身份")
    _require(_exact(template.get("official_inputs"),
             [{"filename": "fwdc239b.bin", "size": INPUT_SIZE, "sha256": INPUT_SHA}],
             ), "模板官方输入身份错误")
    _require(_exact(template.get("icon"), {"width": 40, "height": 40,
             "visible": {"x": 1, "y": 2, "width": 38, "height": 36}}), "模板图标布局错误")
    slots = template.get("slots")
    _require(type(slots) is list and len(slots) == 14, "模板槽位表错误")
    for no, item in enumerate(slots, 1):
        icon, string, text = MAP[no - 1]
        required = {"no", "name", "abbr", "mode", "icon_id", "string_id", "factory_en", "icon", "rename"}
        _require(type(item) is dict and set(item) in (required, required | {"note"}),
                 "模板槽位存在缺失或未知字段")
        _require(all(type(item[k]) is str for k in ("name", "abbr", "factory_en", "icon", "rename"))
                 and ("note" not in item or type(item["note"]) is str), "模板槽位文本类型错误")
        _require(type(item) is dict and all(type(item.get(k)) is int for k in
                 ("no", "mode", "icon_id", "string_id")), "模板编号必须为整数")
        _require((item["no"], item["mode"], item["icon_id"], item["string_id"],
                  item.get("factory_en")) == (no, no + 10, icon, string, text), "模板槽位映射错误")
        for field, allowed in (("icon", ICON_SLOTS), ("rename", NAME_SLOTS)):
            _require(item.get(field) in ("closed", "later", "test", "open"), "模板阶段错误")
            _require(no in allowed or item[field] not in ("test", "open"), "模板开放未经审核的槽位")
    return slots


def _literal(data):
    return b"".join((0x8000 | len(data[i:i + 0x6000])).to_bytes(2, "big") +
                    data[i:i + 0x6000] for i in range(0, len(data), 0x6000))


def build(official_bin, edits, template):
    """Apply reviewed icon/name edits to the pinned official firmware in memory."""
    slots = _template(template)
    _require(type(official_bin) is bytes and len(official_bin) == INPUT_SIZE and
             _sha(official_bin) == INPUT_SHA, "只能从官方 GR III 2.10 原件生成")
    _require(type(edits) is list and 0 < len(edits) <= 7, "改动清单必须非空且在首版范围内")
    seen = set()
    for edit in edits:
        _require(type(edit) is dict, "改动必须为对象")
        kind, no = edit.get("kind"), edit.get("slot")
        _require(type(kind) is str and kind in ("icon", "name") and type(no) is int and 1 <= no <= 14, "改动槽位或类型错误")
        fields = {"kind", "slot", "icon_id", "pixels"} if kind == "icon" else {"kind", "slot", "string_id", "text"}
        _require(set(edit) == fields, "改动存在缺失或未知字段")
        key = "icon_id" if kind == "icon" else "string_id"
        stage = "icon" if kind == "icon" else "rename"
        _require(type(edit[key]) is int and edit[key] == slots[no - 1][key] and
                 slots[no - 1][stage] in ("test", "open"), "该槽位或编号不允许修改")
        _require((kind, no) not in seen, "同一槽位重复改动")
        seen.add((kind, no))
        if kind == "icon":
            _require(type(edit["pixels"]) is bytes and len(edit["pixels"]) == 6400,
                     "图标必须是40×40 RGBA字节")
            _require(all(a in (0, 255) for a in edit["pixels"][3::4]), "图标alpha必须为0或255")
        else:
            text = edit["text"]
            limit = len(slots[no - 1]["factory_en"])
            _require(type(text) is str and 0 < len(text) <= limit and
                     all(32 <= ord(c) <= 126 for c in text) and
                     text == text.strip(" ") and "  " not in text, "预设名须为限长可打印ASCII且无多余空格")
    before, frames, stop, footer = _decode(official_bin)
    _require(_sha(before) == PAYLOAD_SHA, "官方解码数据身份错误")
    after, changes, ranges = bytearray(before), [], []

    def write(offset, value, what, edit=None):
        _require(0 <= offset <= len(after) - len(value) - 4, "目标范围越界")
        end = offset + len(value)
        _require(not any(offset < b and end > a for a, b in ranges), "改动目标重叠")
        if before[offset:end] == value:
            return
        after[offset:end] = value
        ranges.append((offset, end))
        entry = {"what": what, "offset": offset, "length": len(value)}
        if edit:
            entry.update(slot=edit["slot"])
            key = "icon_id" if edit["kind"] == "icon" else "string_id"
            entry[key] = edit[key]
        changes.append(entry)

    for edit in sorted(edits, key=lambda e: (e["slot"], e["kind"])):
        if edit["kind"] == "icon":
            pixels = edit["pixels"]
            _require(type(pixels) is bytes and len(pixels) == 6400, "图标必须是40×40 RGBA字节")
            start, size, w, h = _icon(before, edit["icon_id"])
            _require((size, w, h) == (6400, 40, 40), "原厂图标尺寸不匹配")
            for other in range(1, 671):
                if other == edit["icon_id"]:
                    continue
                a, length, _, _ = _icon(before, other)
                _require(not (a < start + size and a + length > start), "图标像素与其他编号共享，拒绝修改")
            for y in range(40):
                for x in range(40):
                    alpha = pixels[(y * 40 + x) * 4 + 3]
                    original = before[start + (y * 40 + x) * 4 + 3]
                    visible = 1 <= x < 39 and 2 <= y < 38
                    _require(alpha in (0, 255) and (alpha != 0) == (original != 0) and
                             (alpha != 0) == visible, "图标透明边或alpha不符合原厂规则")
                if 2 <= y < 38:
                    a = (y * 40 + 1) * 4
                    write(start + a, pixels[a:a + 152], "icon", edit)
        else:
            text = edit["text"]
            _require(type(text) is str, "预设名必须为字符串")
            en = _string(before, edit["string_id"], 1)
            zh = _string(before, edit["string_id"], 19)
            r, t, count, va, old = en
            _require(old == slots[edit["slot"] - 1]["factory_en"], "原厂英文名与模板不符")
            _require(0 < len(text) <= len(old) and all(32 <= ord(c) <= 126 for c in text) and
                     text == text.strip(" ") and "  " not in text, "预设名须为限长可打印ASCII且无多余空格")
            new = text.encode("utf-16-le") + b"\0\0"
            write(t, new + bytes(count * 2 - len(new)), "name_en_text", edit)
            write(r, bytes((len(text) + 1,)), "name_en_length", edit)
            write(zh[0], bytes((len(text) + 1, 1, 0, 0)) + struct.pack("<I", va), "name_zh_CN_record", edit)
    _require(changes, "改动未改变任何字节")
    checksum_offset = len(after) - 4
    struct.pack_into("<I", after, checksum_offset, (-_sum(after[:-4])) & 0xffffffff)
    if before[-4:] != after[-4:]:
        ranges.append((checksum_offset, len(after)))
        changes.append({"what": "payload_checksum", "offset": checksum_offset, "length": 4})
    segments, replaced = [], []
    for index, (a, b, start, end, literal) in enumerate(frames):
        low = start if literal else max(0, start - 8191)
        dirty = any(x < end and y > low for x, y in ranges)
        segments.append(_literal(after[start:end]) if dirty else official_bin[a:b])
        if dirty:
            replaced.append(index)
    stream = b"".join(segments) + b"\0\0"
    old_aligned = (stop + 3) & ~3
    tail = official_bin[old_aligned:-24]
    output = bytearray(official_bin[:128] + stream + bytes((-len(stream)) % 4) + tail)
    values = list(footer)
    values[3] = len(stream)
    values[5] = 0
    output.extend(struct.pack("<6I", *values))
    struct.pack_into("<I", output, len(output) - 4, (-_sum(output[:-4])) & 0xffffffff)
    output = bytes(output)
    # Always read back with this implementation. Independent caller readback is
    # still required; this check does not substitute for an independent decoder.
    readback, _, _, _ = _decode(output)
    _require(readback == after and _sum(output) == 0, "生成后读回核验失败")
    return {"output": output, "input_sha256": INPUT_SHA, "output_sha256": _sha(output),
            "payload_sha256_before": PAYLOAD_SHA, "payload_sha256_after": _sha(after),
            "version_word": "02 0A 15 1B", "payload_changes": changes,
            "container": {"frames_replaced": replaced, "header_changed": False,
                          "footer_fields_changed": ["encoded_size", "checksum"]},
            "builder": {"name": "Darkslide clean-room builder", "version": "1.0",
                        "source_sha256": SOURCE_SHA256,
                        "source_hash_scope": "build.py with SOURCE_SHA256 value replaced by 64 zeros"}}

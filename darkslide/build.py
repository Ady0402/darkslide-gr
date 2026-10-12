from . import package
"""Deterministic, standard-library-only GR III 2.10 editor.

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
SOURCE_SHA256 = "93cb1c518af94483698734c89cc25ff366b743be3e0e8580331090f482216408"
MAP = ((358, 4, "Standard"), (548, 268, "Vivid"),
       (354, 269, "Monotone"), (357, 270, "Soft Monotone"),
       (350, 271, "Hard Monotone"), (352, 272, "Hi-Contrast B&W"),
       (232, 274, "Positive Film"), (346, 275, "Bleach Bypass"),
       (356, 276, "Retro"), (351, 277, "HDR Tone"),
       (50, 278, "Cross Processing"), (23, 273, "Negative Film"),
       (347, 279, "Custom1"), (348, 280, "Custom2"))
ICON_SLOTS = frozenset(range(1, 13))
NAME_SLOTS = frozenset(range(2, 13))


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
    try:
        return package.word_total(data)
    except package.PackageError as exc:
        raise BuildError(str(exc)) from exc


def _decode(raw):
    try:
        archive = package.Package.read(raw)
        return archive.image, archive.frames, archive.stream_end, archive.trailer.values()
    except package.PackageError as exc:
        raise BuildError(str(exc)) from exc


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
             "模板不可用，不能生成")
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
        extra = set(item) - required if type(item) is dict else {None}
        _require(type(item) is dict and required <= set(item) and extra <= {"note", "name_max"},
                 "模板槽位存在缺失或未知字段")
        _require("name_max" not in item or (type(item["name_max"]) is int and no in NAME_SLOTS and
                 len(text) < item["name_max"] <= 12), "模板预设名上限错误")
        _require(all(type(item[k]) is str for k in ("name", "abbr", "factory_en", "icon", "rename"))
                 and ("note" not in item or type(item["note"]) is str), "模板槽位文本类型错误")
        _require(type(item) is dict and all(type(item.get(k)) is int for k in
                 ("no", "mode", "icon_id", "string_id")), "模板编号必须为整数")
        _require((item["no"], item["mode"], item["icon_id"], item["string_id"],
                  item.get("factory_en")) == (no, no + 10, icon, string, text), "模板槽位映射错误")
        for field, allowed in (("icon", ICON_SLOTS), ("rename", NAME_SLOTS)):
            _require(item.get(field) in ("closed", "later", "test", "open"), "模板阶段错误")
            _require(no in allowed or item[field] not in ("test", "open"), "模板开放了不支持的预设")
    return slots


def _literal(data):
    return package.raw_frames(data)


def build(official_bin, edits, template):
    from . import edit_core
    return edit_core.build(official_bin, edits, template)

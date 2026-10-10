"""Independent read-back of a generated firmware file.

Uses only darkslide.fwread (the independent unpacker), never the builder's decoder,
so writer and checker stay separate. Every check must pass before the file
is offered for download.
"""
import hashlib
import struct

from . import fwread

VISIBLE = (1, 2, 38, 36)


def _sum32(data):
    if len(data) % 4:
        return None
    return sum(struct.unpack("<%dI" % (len(data) // 4), data)) & 0xFFFFFFFF


def _ranges(changes):
    return [(c["offset"], c["offset"] + c["length"]) for c in changes]


def _diff_runs(a, b):
    """Byte ranges where a and b differ (same length)."""
    runs, i, n = [], 0, len(a)
    step = 4096
    while i < n:
        j = min(n, i + step)
        if a[i:j] != b[i:j]:
            for k in range(i, j):
                if a[k] != b[k]:
                    if runs and runs[-1][1] == k:
                        runs[-1][1] = k + 1
                    else:
                        runs.append([k, k + 1])
        i = j
    return runs


def _expected_icon(factory, pixels):
    """Visible 38×36 from the edit, border bytes from the factory icon."""
    out = bytearray(factory)
    vx, vy, vw, vh = VISIBLE
    for y in range(vy, vy + vh):
        a = (y * 40 + vx) * 4
        out[a:a + vw * 4] = pixels[a:a + vw * 4]
    return bytes(out)


def verify(official_bin, result, edits, template):
    """Return a list of {id, title, ok, detail}; all must be ok."""
    out = result["output"]
    checks = []

    def add(cid, title, ok, detail=""):
        checks.append(dict(id=cid, title=title, ok=bool(ok), detail=detail))

    add("input", "输入是官方 GR III 2.10 原件",
        hashlib.sha256(official_bin).hexdigest() == fwread.V210_INPUT_SHA256)
    add("sha", "输出 SHA 与生成核心报告一致",
        hashlib.sha256(out).hexdigest() == result["output_sha256"])
    add("header", "文件头 128 字节与原件相同（版本保持 2.10）", out[:128] == official_bin[:128])
    add("file_sum", "整文件 32 位加和为 0", _sum32(out) == 0)

    try:
        before = fwread.unpack(official_bin)
        after = fwread.unpack(out)
    except fwread.FirmwareReadError as exc:
        add("unpack", "独立解包生成的文件", False, str(exc))
        return checks
    add("unpack", "独立解包生成的文件", len(after) == len(before),
        "解码长度 %d" % len(after))
    if len(after) != len(before):
        return checks
    add("payload_sum", "解码数据加和为 0", _sum32(after) == 0)

    allowed = _ranges(result["payload_changes"])
    stray = [r for r in _diff_runs(before, after)
             if not any(a <= r[0] and r[1] <= b for a, b in allowed)]
    add("only_declared", "所有改动都在声明的位置", not stray,
        "越界改动 %d 处" % len(stray) if stray else "改动 %d 处" % len(result["payload_changes"]))

    p0 = fwread.Payload(before)
    p1 = fwread.Payload(after, pinned=False)
    icon_edits = {e["slot"]: e for e in edits if e["kind"] == "icon"}
    name_edits = {e["slot"]: e for e in edits if e["kind"] == "name"}
    icon_ok, name_ok, notes = True, True, []
    for slot in template["slots"]:
        no = slot["no"]
        _, f_px = p0.icon_pixels(slot["icon_id"])
        _, g_px = p1.icon_pixels(slot["icon_id"])
        want = _expected_icon(f_px, icon_edits[no]["pixels"]) if no in icon_edits else f_px
        if g_px != want:
            icon_ok = False
            notes.append("%s 图标不一致" % slot["name"])
        for lang in ("en", "zh-CN", "ja"):
            got = p1.string(slot["string_id"], lang)["text"]
            if no in name_edits and lang in ("en", "zh-CN"):
                exp = name_edits[no]["text"]
            else:
                exp = p0.string(slot["string_id"], lang)["text"]
            if got != exp:
                name_ok = False
                notes.append("%s %s 预设名不一致" % (slot["name"], lang))
    add("icons", "读回图标：改动的与设定一致，其余与原厂一致", icon_ok, "；".join(n for n in notes if "图标" in n))
    add("names", "读回预设名：英文和简中为新名，其他语言保持原厂", name_ok, "；".join(n for n in notes if "预设名" in n))
    return checks


def all_ok(checks):
    return bool(checks) and all(c["ok"] for c in checks)

"""Independent read-back of a shutdown-image build.

Uses only darkslide.fwread, never the generation core, and derives every
expected value from the official input itself. All checks must pass before
the file is stored or offered for download.
"""
import hashlib
import struct

from . import fwread

# Shutdown JPEG request table (runtime 0x55002B78, one pointer per request id)
# lives in the RTOS init data copied from 0x5407B540 to 0x55000000.
TABLE_RUNTIME = 0x55002B78
DATA_LMA = 0x5407B540
DATA_RUNTIME = 0x55000000
SHARED_REQUESTS = (2, 10, 11, 12)   # normal, ING, Urban, Diary
OTHER_REQUESTS = (3,)               # Collabo stays untouched
DIARY_PATH = b"B:\\Resource\\Jpeg\\GB_Diary.jpg"
# User updates skip every B: resource, so the shared image lives on A:.
# Only the drive letter of the RTOS read path and of the RES record changes.
NEW_DRIVE = ord("A")
JPEG_SIZE = (720, 480)


def _sum32(data):
    if len(data) % 4:
        return None
    return sum(struct.unpack("<%dI" % (len(data) // 4), data)) & 0xFFFFFFFF


def _table_va(request):
    return DATA_LMA + (TABLE_RUNTIME + 4 * request - DATA_RUNTIME)


def find_resource(payload, path):
    """Locate a RES record by its 32-byte NUL-padded path field; return (data_offset, length)."""
    field = path + bytes(32 - len(path))
    hits, at = [], payload.find(field)
    while at != -1:
        hits.append(at)
        at = payload.find(field, at + 1)
    found = []
    for h in hits:
        n = struct.unpack_from("<I", payload, h + 32)[0]
        body = payload[h + 36:h + 36 + n]
        if 0 < n < 4 * 1024 * 1024 and body[:2] == b"\xff\xd8" and body[-2:] == b"\xff\xd9":
            found.append((h + 36, n))
    return found


def strip_com(jpeg):
    """Drop COM (FFFE) segments that sit before SOS; return the rest unchanged."""
    out, pos = bytearray(jpeg[:2]), 2
    while pos + 4 <= len(jpeg) and jpeg[pos] == 0xFF:
        marker = jpeg[pos + 1]
        length = struct.unpack(">H", jpeg[pos + 2:pos + 4])[0]
        if marker == 0xDA:
            out += jpeg[pos:]
            return bytes(out)
        if marker != 0xFE:
            out += jpeg[pos:pos + 2 + length]
        pos += 2 + length
    return None


def _diff_runs(a, b):
    runs, i, n, step = [], 0, len(a), 4096
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


def verify(official_bin, output, jpeg):
    """Return a list of {id, title, ok, detail}; all must be ok."""
    checks = []

    def add(cid, title, ok, detail=""):
        checks.append(dict(id=cid, title=title, ok=bool(ok), detail=detail))

    add("input", "输入是官方 GR III 2.10 原件",
        hashlib.sha256(official_bin).hexdigest() == fwread.V210_INPUT_SHA256)
    add("header", "文件头 128 字节与原件相同（版本保持 2.10）", output[:128] == official_bin[:128])
    add("file_sum", "整文件 32 位加和为 0", _sum32(output) == 0)
    try:
        before = fwread.unpack(official_bin)
        after = fwread.unpack(output)
    except fwread.FirmwareReadError as exc:
        add("unpack", "独立解包生成的文件", False, str(exc))
        return checks
    add("unpack", "独立解包生成的文件", len(after) == len(before), "解码长度 %d" % len(after))
    if len(after) != len(before):
        return checks
    add("payload_sum", "解码数据加和为 0", _sum32(after) == 0)

    p0 = fwread.Payload(before)
    diary = find_resource(before, DIARY_PATH)
    add("diary_found", "在原件里找到 Diary 关机图位置", len(diary) == 1,
        "%d 处" % len(diary))
    if len(diary) != 1:
        return checks
    slot_at, slot_len = diary[0]
    record_at = slot_at - 36
    diary_desc = p0.u32(_table_va(12))
    rtos_at = p0.off(p0.u32(diary_desc + 4))
    add("rtos_path", "Diary 描述符指向的读取路径就是 Diary 图",
        before[rtos_at:rtos_at + len(DIARY_PATH) + 1] == DIARY_PATH + b"\0")

    allowed = [(slot_at, slot_at + slot_len), (len(after) - 4, len(after)),
               (rtos_at, rtos_at + 1), (record_at, record_at + 1)]
    for req in SHARED_REQUESTS:
        at = p0.off(_table_va(req))
        allowed.append((at, at + 4))
    stray = [r for r in _diff_runs(before, after)
             if not any(a <= r[0] and r[1] <= b for a, b in allowed)]
    add("only_declared", "改动只在关机图位置、3 个入口指向、2 个盘符和末尾校验", not stray,
        "越界改动 %d 处" % len(stray) if stray else "")

    p1 = fwread.Payload(after, pinned=False)
    shared_ok = all(p1.u32(_table_va(r)) == diary_desc for r in SHARED_REQUESTS)
    others_ok = all(p1.u32(_table_va(r)) == p0.u32(_table_va(r)) for r in OTHER_REQUESTS)
    add("requests", "普通 / ING / Urban / Diary 四个关机入口都指向同一位置", shared_ok)
    add("collabo", "合作款入口保持原厂", others_ok)

    drive_ok = (after[rtos_at] == NEW_DRIVE and after[record_at] == NEW_DRIVE and
                after[rtos_at + 1:rtos_at + len(DIARY_PATH) + 1] == before[rtos_at + 1:rtos_at + len(DIARY_PATH) + 1])
    add("drive", "读取路径和资源记录都改到 A 盘（只改盘符）", drive_ok)

    body = after[slot_at:slot_at + slot_len]
    header_same = after[record_at + 1:slot_at] == before[record_at + 1:slot_at]
    add("record", "关机图资源的长度和位置不变（不扩容）", header_same and len(body) == slot_len,
        "%d 字节" % slot_len)
    add("image", "写入的图片与提交的图片一致（仅多出填充段）", strip_com(body) == jpeg,
        "提交 %d 字节" % len(jpeg))
    return checks


def all_ok(checks):
    return bool(checks) and all(c["ok"] for c in checks)

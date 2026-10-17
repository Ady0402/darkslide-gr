"""User film LUTs kept with a project, and the built-in film catalog for the picker.

A user's .cube is stored as-is (it may carry its author's licence; it is never
added to the shared CC BY-SA film data). Turning it into camera parameters is a
separate fitting step; until a profile is attached the LUT can be previewed and
selected but not written.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from .film_requests import FilmRequestError, validate_request

FILM_ROOT = Path(__file__).resolve().parent.parent / "film_curves"
CATALOG = FILM_ROOT / "catalog.json"
MAX_CUBE = 8 * 1024 * 1024
USER_ID = re.compile(r"user_lut_[0-9a-f]{12}\Z")


class FilmLutError(ValueError):
    pass


def _need(ok, message):
    if not ok:
        raise FilmLutError(message)


def parse_cube(data):
    """(title, size, rows) of a 3D .cube; rows are (r, g, b) floats, red fastest."""
    _need(type(data) is bytes and 0 < len(data) <= MAX_CUBE, "LUT 文件为空或超过 8 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise FilmLutError("LUT 文件不是文本") from None
    title, size, rows, domain = "", None, [], ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "TITLE":
            title = line[5:].strip().strip('"')[:80]
        elif head == "LUT_3D_SIZE":
            _need(size is None and re.fullmatch(r"LUT_3D_SIZE\s+\d{1,3}", line, re.I), "LUT_3D_SIZE 写法错误")
            size = int(line.split()[1])
            _need(2 <= size <= 65, "LUT 网格必须在 2–65 之间")
        elif head == "LUT_1D_SIZE":
            raise FilmLutError("只支持 3D LUT，不支持 1D LUT")
        elif head in ("DOMAIN_MIN", "DOMAIN_MAX"):
            v = _floats(line.split()[1:], "DOMAIN")
            _need(len(v) == 3, "DOMAIN 写法错误")
            domain = (v, domain[1]) if head == "DOMAIN_MIN" else (domain[0], v)
        elif head[0].isdigit() or head[0] in "-+.":
            v = _floats(line.split(), "数据行")
            _need(len(v) == 3, "LUT 数据行必须是三个数")
            rows.append(tuple(v))
        else:
            raise FilmLutError("无法识别的 LUT 行：%s" % line[:24])
    _need(size is not None, "缺少 LUT_3D_SIZE")
    _need(len(rows) == size ** 3, "LUT 数据行数与网格大小不符")
    _need(tuple(domain[0]) == (0.0, 0.0, 0.0) and tuple(domain[1]) == (1.0, 1.0, 1.0), "只支持 0–1 输入范围的 LUT")
    _need(all(-0.5 <= x <= 1.5 for row in rows for x in row), "LUT 输出超出正常范围")
    return title, size, rows


def _floats(parts, what):
    try:
        values = [float(p) for p in parts]
    except ValueError:
        raise FilmLutError("%s 不是数字" % what) from None
    _need(all(math.isfinite(v) for v in values), "%s 含有非有限数值" % what)
    return values


def lut_id(data):
    return "user_lut_" + hashlib.sha256(data).hexdigest()[:12]


def display_name(filename, title):
    base = re.sub(r"\.cube$", "", str(filename or ""), flags=re.I)
    name = re.sub(r"[\x00-\x1f\x7f]", "", (title or base or "我的 LUT")).strip()[:40]
    return name or "我的 LUT"


def catalog():
    """Built-in films for the picker, each marked ready when its camera data exists."""
    from .film_profiles import ready_profile_ids
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise FilmLutError("胶片目录读取失败") from None
    ready = set(ready_profile_ids())
    films = []
    for item in data.get("films", []):
        validate_request({"kind": "film", "slot": 8, "film": item["id"]})
        films.append(dict(item, ready=item["id"] in ready))
    return dict(note=data.get("note", ""), credit=data.get("credit", ""), films=films)


def preview_path(ident):
    """The approximate preview LUT of a built-in film (not camera data)."""
    try:
        validate_request({"kind": "film", "slot": 8, "film": ident})
    except FilmRequestError:
        raise FilmLutError("无效的胶片编号") from None
    path = FILM_ROOT / "preview" / (ident + ".cube")
    _need(path.resolve().parent == (FILM_ROOT / "preview").resolve() and path.is_file(), "这卷胶片没有预览")
    return path

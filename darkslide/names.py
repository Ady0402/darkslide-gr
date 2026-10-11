"""Preset-name rules derived from the GR III 2.10 string tables.

The same rules run in web/names.js for live
feedback; this module is the authority the server applies before saving.
"""
import re

PRINTABLE_ASCII = re.compile(r"^[\x20-\x7e]*$")


def check_name(name, limit):
    """Return a list of {rule, ok, message} dicts; every rule must pass."""
    unsupported = sorted({ch for ch in name if not ("\x20" <= ch <= "\x7e")})
    results = [
        ("not_empty", len(name) > 0, "预设名不能为空"),
        ("length", len(name) <= limit, "长度 %d / %d" % (len(name), limit)),
        ("charset", not unsupported,
         "字符都在相机字库内" if not unsupported else "相机字库里没有：" + " ".join(unsupported)),
        ("single_line", "\n" not in name and "\r" not in name, "只能一行"),
        ("no_edge_space", name == name.strip(" "), "首尾不能有空格"),
        ("no_double_space", "  " not in name, "不能有连续空格"),
    ]
    return [dict(rule=r, ok=bool(ok), message=m) for r, ok, m in results]


def name_ok(name, limit):
    return all(item["ok"] for item in check_name(name, limit))

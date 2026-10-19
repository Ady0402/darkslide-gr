"""Bundle the interface translations into web/i18n-data.js.

    python3 tools/i18n_extract.py   # refresh tools/i18n/source.json after UI text changes
    python3 tools/i18n_build.py     # check and bundle

tools/i18n/en.json, ja.json and ko.json map each source string to English, Japanese and
Korean (keep %s, %d, {0} slots); extra-<code>.json adds text that lives in data files
(template preset names) or is pieced together at run time;
tools/i18n/zh-Hant.json holds OpenCC (cn -> twp) conversions of the same strings
plus a per-character map for text built at run time. Strings missing from en.json
are reported and stay Chinese on the page until translated.
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLOT = re.compile(r"%(?:\([^)]*\))?[-+ #0]*\d*(?:\.\d+)?[sdifr]|\{\d+\}")


LANGS = ("en", "ja", "ko")  # full tables; 繁體 also has a per-character fallback


def load(folder, code):
    """<code>.json plus extra-<code>.json (data-file and run-time pieces)."""
    table = json.loads((folder / ("%s.json" % code)).read_text(encoding="utf-8"))
    extra_path = folder / ("extra-%s.json" % code)
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    return table, extra


def problems(source, table, extra):
    """(placeholder mismatches, missing strings) for one language."""
    pairs = list(table.items()) + list(extra.items())
    bad = [k for k, v in pairs if collections.Counter(SLOT.findall(k)) != collections.Counter(SLOT.findall(v))]
    missing = [k for k in source if k not in table and k not in extra]
    return bad, missing


def build(report=True):
    """The bundled data, after checking placeholders; missing strings are reported."""
    folder = ROOT / "tools/i18n"
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    hant = json.loads((folder / "zh-Hant.json").read_text(encoding="utf-8"))
    data = {}
    extras = {}
    for code in LANGS:
        table, extra = load(folder, code)
        bad, missing = problems(source, table, extra)
        if bad:
            raise SystemExit("placeholders differ in %s.json: %r" % (code, bad[:5]))
        if missing and report:
            print("%d strings have no %s yet, e.g. %r" % (len(missing), code, missing[:3]), file=sys.stderr)
        data[code] = dict({k: v for k, v in table.items() if k in source}, **extra)
        extras[code] = extra
    data["hant"] = dict(strings={k: v for k, v in hant["strings"].items() if k in source or k in extras["en"]},
                        chars=hant["chars"])
    return data


def render(data):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return ("// Built by tools/i18n_build.py from tools/i18n/*.json; do not edit by hand.\n"
            "window.DarkslideI18nData = " + body + ";\n")


def main():
    data = build()
    out = ROOT / "web/i18n-data.js"
    out.write_text(render(data), encoding="utf-8")
    print("%s: %d English, %d 日本語, %d 한국어, %d 繁體 strings, %d chars" % (
        out.relative_to(ROOT), len(data["en"]), len(data["ja"]), len(data["ko"]),
        len(data["hant"]["strings"]), len(data["hant"]["chars"])), file=sys.stderr)


if __name__ == "__main__":
    main()

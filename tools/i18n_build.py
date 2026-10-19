"""Bundle the interface translations into web/i18n-data.js.

    python3 tools/i18n_extract.py   # refresh tools/i18n/source.json after UI text changes
    python3 tools/i18n_build.py     # check and bundle

tools/i18n/en.json maps each source string to English (keep %s, %d, {0} slots);
tools/i18n/extra-en.json adds text that lives in data files (template preset names) or
is pieced together at run time;
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


def main():
    folder = ROOT / "tools/i18n"
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    en = json.loads((folder / "en.json").read_text(encoding="utf-8"))
    hant = json.loads((folder / "zh-Hant.json").read_text(encoding="utf-8"))
    extra = json.loads((folder / "extra-en.json").read_text(encoding="utf-8"))
    bad = [k for k, v in list(en.items()) + list(extra.items()) if collections.Counter(SLOT.findall(k)) != collections.Counter(SLOT.findall(v))]
    if bad:
        sys.exit("placeholders differ in en.json: %r" % bad[:5])
    missing = [k for k in source if k not in en and k not in extra]
    if missing:
        print("%d strings have no English yet, e.g. %r" % (len(missing), missing[:3]), file=sys.stderr)
    data = dict(en=dict({k: v for k, v in en.items() if k in source}, **extra),
                hant=dict(strings={k: v for k, v in hant["strings"].items() if k in source or k in extra},
                          chars=hant["chars"]))
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    out = ROOT / "web/i18n-data.js"
    out.write_text("// Built by tools/i18n_build.py from tools/i18n/*.json; do not edit by hand.\n"
                   "window.DarkslideI18nData = " + body + ";\n", encoding="utf-8")
    print("%s: %d English, %d 繁體 strings, %d chars" % (out.relative_to(ROOT), len(data["en"]),
                                                         len(data["hant"]["strings"]), len(data["hant"]["chars"])),
          file=sys.stderr)


if __name__ == "__main__":
    main()

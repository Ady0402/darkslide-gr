#!/usr/bin/env python3
"""Set selftest reports of several platforms side by side.

    python3 desktop/scripts/compare_reports.py report-a.json report-b.json ...

Each report comes from `selftest.py --firmware ... --report`. Rows go from what the
platforms were given, through what the page made of it (icon and shutdown picture,
drawn by each platform's webview), to what the generator wrote. A row whose values
differ is marked ✕; the first such row is where the platforms part ways.
Exit code 0 when every row agrees.
"""
import json
import sys
from pathlib import Path


def rows(report):
    inputs = report.get("inputs", {})
    changes = report.get("changes") or {}
    manifest = report.get("manifest") or {}
    out = [
        ("input: official firmware", inputs.get("firmware")),
    ] + [("input: " + k, v) for k, v in sorted(inputs.items()) if k.startswith("cube ")] + [
        ("input: icon picture", inputs.get("icon")),
        ("input: shutdown picture", inputs.get("shutdown")),
        ("input: recipe", json.dumps(inputs.get("recipe"), sort_keys=True)),
        ("fitting component", (report.get("fitting") or {}).get("state")),
    ]
    for no, edit in sorted((k, v) for k, v in changes.items() if k != "shutdown"):
        for key, value in sorted(edit.items()):
            if isinstance(value, dict) and "asset" in value:
                out.append(("page: preset %s %s (40×40)" % (no, key), value.get("asset")))
                out.append(("page: preset %s %s source" % (no, key), value.get("source")))
                out.append(("page: preset %s %s crop" % (no, key), json.dumps(value.get("crop"), sort_keys=True)))
            else:
                out.append(("page: preset %s %s" % (no, key), json.dumps(value, sort_keys=True, ensure_ascii=False)))
    shutdown = changes.get("shutdown") or {}
    out += [
        ("page: shutdown JPEG", shutdown.get("asset")),
        ("page: shutdown JPEG quality", shutdown.get("quality")),
        ("page: shutdown source", shutdown.get("source")),
        ("generator: menu language", manifest.get("menu_language")),
        ("generator: changes written", json.dumps(manifest.get("summary"), sort_keys=True, ensure_ascii=False)),
        ("generator: payload after", manifest.get("payload_sha256_after")),
        ("generator: offline checks", "%d/%d passed" % (sum(1 for c in manifest.get("checks", []) if c.get("ok")), len(manifest.get("checks", [])))
         if manifest else None),
        ("firmware SHA-256", report.get("firmware_sha256")),
    ]
    return out


def main():
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:]]
    if len(reports) < 2:
        sys.exit("give two or more reports")
    names = ["%s/%s" % (r.get("platform"), r.get("machine")) for r in reports]
    tables = [dict(rows(r)) for r in reports]
    order = [label for label, _ in rows(reports[0])]
    for t in tables[1:]:
        order += [label for label in t if label not in order]
    differ = 0
    print("platforms: " + " | ".join(names))
    for label in order:
        values = [t.get(label) for t in tables]
        same = all(v == values[0] for v in values)
        differ += not same
        shown = values[0] if same else " | ".join(str(v) for v in values)
        print(("✓ " if same else "✕ ") + label + ": " + str(shown))
    print("\n%d of %d rows agree" % (len(order) - differ, len(order)))
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())

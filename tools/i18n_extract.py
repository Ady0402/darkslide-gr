"""Collect every Simplified Chinese UI string, for the interface translations.

    python3 tools/i18n_extract.py            # writes tools/i18n/source.json

Sources: text nodes and title/aria-label/placeholder/alt attributes in web/index.html,
string and template literals in web/*.js (template slots become {0}, {1}, ...), and
string literals in darkslide/*.py that are not docstrings (messages the server returns
to the page), and string values in templates/*.json and film_curves/*.json. The page translates at run time by exact match first, then by these
strings as patterns (%s, %d, {0} ... match any text) and fragments; see web/i18n.js.
"""
import html.parser
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[㐀-鿿]")
ATTRS = {"title", "aria-label", "placeholder", "alt"}


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


class Html(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ATTRS and v and CJK.search(v):
                self.found.append(norm(v))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and CJK.search(data):
            self.found.append(norm(data))


def js_literals(src):
    """String and template literals, skipping comments and (roughly) regex literals."""
    out, i, n = [], 0, len(src)
    prev = ""  # last significant character, to tell a regex from a division
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
            continue
        if src.startswith("/*", i):
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 2
            continue
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2]); j += 2; continue
                if src[j] == "\n":
                    break
                buf.append(src[j]); j += 1
            out.append(_unescape("".join(buf)))
            i, prev = j + 1, c
            continue
        if c == "`":
            j, buf, slot = i + 1, [], 0
            while j < n and src[j] != "`":
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2]); j += 2; continue
                if src.startswith("${", j):
                    depth, j = 1, j + 2
                    while j < n and depth:
                        depth += {"{": 1, "}": -1}.get(src[j], 0)
                        j += 1
                    buf.append("{%d}" % slot); slot += 1
                    continue
                buf.append(src[j]); j += 1
            out.append(_unescape("".join(buf)))
            i, prev = j + 1, c
            continue
        if c == "/" and prev in "(,=:[!&|?{};+-*%<>~^" + "\n":
            j = i + 1
            while j < n and src[j] not in "/\n":
                j += 2 if src[j] == "\\" else 1
            i, prev = j + 1, "/"
            continue
        if not c.isspace():
            prev = c
        i += 1
    return [norm(s) for s in out if CJK.search(s)]


def _unescape(s):
    try:
        return json.loads('"' + s.replace('"', '\\"').replace("\\'", "'").replace("\\`", "`") + '"')
    except ValueError:
        return s


def py_literals(src):
    out, prev_type = [], tokenize.NEWLINE
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.STRING and CJK.search(tok.string):
            body = tok.string.lstrip("rbuRBUfF")
            docstring = prev_type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL) and body[:3] in ('"""', "'''")
            if not docstring and not tok.string[:2].lower().startswith("f"):
                try:
                    out.append(norm(eval(tok.string, {}, {})))  # a plain literal
                except (SyntaxError, ValueError):
                    pass
        if tok.type not in (tokenize.COMMENT,):
            prev_type = tok.type
    return out


def main():
    found = {}
    parser = Html()
    parser.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
    for s in parser.found:
        found.setdefault(s, "index.html")
    for path in sorted((ROOT / "web").glob("*.js")):
        if path.name.startswith("i18n"):
            continue
        for s in js_literals(path.read_text(encoding="utf-8")):
            found.setdefault(s, path.name)
    for path in sorted((ROOT / "darkslide").glob("*.py")):
        for s in py_literals(path.read_text(encoding="utf-8")):
            found.setdefault(s, path.name)
    def walk(value, name):
        if isinstance(value, str):
            found.setdefault(norm(value), name)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item, name)
        elif isinstance(value, list):
            for item in value:
                walk(item, name)
    for path in sorted(list((ROOT / "templates").glob("*.json")) + list((ROOT / "film_curves").glob("*.json"))):
        walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    found = {k: v for k, v in found.items() if k and CJK.search(k)}
    out = ROOT / "tools/i18n/source.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(dict(sorted(found.items())), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print("%d strings -> %s" % (len(found), out.relative_to(ROOT)), file=sys.stderr)


if __name__ == "__main__":
    main()

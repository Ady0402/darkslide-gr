"""Local HTTP server for Darkslide: static pages plus a small JSON API, bound to 127.0.0.1 only.

The HTTP layer below `App` is written from our own spec (2026-10-11).
"""
import json
import logging
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import VERSION, fwread, fwzip, generate, names, pngcheck, shutdown_verify, template as tpl
from .identify import identify
from .paths import WEB_ROOT, data_root
from .store import SHUTDOWN_BUDGET, Store, StoreError, read_json, write_json

MAX_BODY = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, root=None, template_name="gr3_v210.json"):
        self.store = Store(root or data_root())
        self.template = tpl.load(template_name)
        self.detail = tpl.load_detail(self.template)

    def status(self):
        return dict(version=VERSION, template=self.template, detail=self.detail, projects=self.store.list_projects(),
                    builds=self.store.builds(), prefs=self.store.prefs(),
                    data_root=str(self.store.root),
                    shutdown=dict(budget=SHUTDOWN_BUDGET, width=720, height=480))

    def import_firmware(self, data, filename):
        if not data:
            raise ApiError(400, "文件是空的")
        result = identify(data, filename, self.template, self.store.builds())
        if result["kind"] == "official":
            self.store.put_input(data)
            self.extract_factory(result["sha256"], data)
        return result

    def extract_factory(self, digest, data):
        """Read factory icons and preset names from an official input (read-only)."""
        folder = self.store.factory_dir(digest)
        index = folder / "factory.json"
        if read_json(index) and read_json(index).get("template_id") == self.template["id"]:
            return read_json(index)
        payload = fwread.Payload(fwread.unpack(data))
        slots = {}
        for slot in self.template["slots"]:
            desc, pixels = payload.icon_pixels(slot["icon_id"])
            png = pngcheck.write_png(desc["width"], desc["height"], fwread.icon_to_rgba(pixels))
            (folder / "icons").mkdir(parents=True, exist_ok=True)
            (folder / "icons" / ("%d.png" % slot["no"])).write_bytes(png)
            names_by_lang = {lang: payload.string(slot["string_id"], lang)["text"] for lang in ("en", "zh-CN", "ja")}
            slots[str(slot["no"])] = dict(names=names_by_lang,
                                          name_matches_template=names_by_lang["en"] == slot["factory_en"])
        value = dict(template_id=self.template["id"], payload_sha256=fwread.V210["payload_sha256"], slots=slots)
        write_json(index, value)
        return value

    def factory(self, digest):
        folder = self.store.factory_dir(digest)
        value = read_json(folder / "factory.json")
        if value is None:
            if not self.store.has_input(digest):
                raise ApiError(404, "没有导入这个固件")
            value = self.extract_factory(digest, self.store.input_path(digest).read_bytes())
        return value

    def factory_shutdown(self, digest):
        """Factory normal shutdown image (GoodBye.jpg) from the imported official input, read-only, cached."""
        target = self.store.factory_dir(digest) / "shutdown.jpg"
        if not target.exists():
            if not self.store.has_input(digest):
                raise ApiError(404, "没有导入这个固件")
            payload = fwread.unpack(self.store.input_path(digest).read_bytes())
            found = shutdown_verify.find_resource(payload, b"B:\\Resource\\Jpeg\\GoodBye.jpg")
            if len(found) != 1:
                raise ApiError(422, "没有在固件里找到原厂关机图")
            at, n = found[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload[at:at + n])
        return target.read_bytes()

    def check_name(self, body):
        slot = tpl.slot(self.template, int(body.get("slot")))
        name = body.get("name")
        if not isinstance(name, str):
            raise ApiError(400, "预设名必须是文字")
        limit = len(slot["factory_en"])
        return dict(limit=limit, factory_en=slot["factory_en"], checks=names.check_name(name, limit),
                    ok=names.name_ok(name, limit))


# ---------------------------------------------------------------------------
# HTTP layer, written from our own spec.
#
# Every request takes the same path through `RequestHandler.respond`:
#   Host check -> Origin check (non-GET only) -> /api/ route table, or a static
#   file for GET -> exactly one reply.
# A route's result is rendered to bytes before anything goes on the wire, so a
# failure while rendering is mapped like any other. Exceptions become JSON
# errors through ERROR_REPLIES; anything not listed there is left to
# socketserver, as the spec lists no other.
# ---------------------------------------------------------------------------

LOOPBACK = "127.0.0.1"
LOCAL_HOSTNAMES = (LOOPBACK, "localhost")
JSON_TYPE = "application/json; charset=utf-8"
TEXT_TYPE = "text/plain; charset=utf-8"
BINARY_TYPE = "application/octet-stream"
# Sent right after the status line of every reply, the stdlib's own protocol
# errors included (see RequestHandler.send_response).
SAFETY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)
PREF_KEYS = ("preflight_seen", "guide_off", "guide_start_seen", "guide_work_seen")
# Seconds a single socket read or write may wait before the connection is dropped.
IDLE_TIMEOUT = 30
# A declared request body that the route never read (403, 404, 405, 413 ...) is
# read and thrown away after the reply, up to this many bytes, so the client can
# finish sending and then read the answer instead of a connection reset.
DISCARD_LIMIT = 1024 * 1024 * 1024

log = logging.getLogger("darkslide.http")


class Reply:
    """A reply that is more than "200 + JSON": another status, raw bytes, extra headers.

    `body` is a dict or list (sent as JSON) or bytes (sent as-is with `content_type`).
    """
    __slots__ = ("body", "status", "content_type", "headers")

    def __init__(self, body, status=200, content_type=None, headers=()):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = tuple(headers)


def disposition(filename):
    """The extra header that makes a browser save the body as `filename`."""
    return ("Content-Disposition", 'attachment; filename="%s"' % filename)


def render(reply, errors="strict"):
    """(status, headers, body bytes) for a route result (dict or list) or a Reply.

    Headers come as the route's own first, then Content-Type and Content-Length.
    `errors` is the UTF-8 error handler used for JSON text.
    """
    if not isinstance(reply, Reply):
        reply = Reply(reply)
    if isinstance(reply.body, (bytes, bytearray)):
        data, kind = bytes(reply.body), reply.content_type or BINARY_TYPE
    else:
        data = json.dumps(reply.body, ensure_ascii=False).encode("utf-8", errors)
        kind = reply.content_type or JSON_TYPE
    return reply.status, reply.headers + (("Content-Type", kind), ("Content-Length", str(len(data)))), data


# Exception -> (status, message). Checked in order: StoreError and
# FirmwareReadError are ValueErrors, so they must come before the generic row.
ERROR_REPLIES = (
    (ApiError, lambda exc: (exc.status, str(exc))),
    (StoreError, lambda exc: (400, str(exc))),
    (fwread.FirmwareReadError, lambda exc: (422, "读取固件失败：" + str(exc))),
    ((KeyError, ValueError, TypeError), lambda exc: (400, "请求参数错误")),
)


def error_reply(exc):
    """The JSON error reply for `exc`, or None when the spec does not map it."""
    for kinds, describe in ERROR_REPLIES:
        if isinstance(exc, kinds):
            status, message = describe(exc)
            return Reply({"error": message}, status)
    return None


def split_target(target):
    """(path, query) of a request target.

    As in v0.2, ";params" at the end of the last path segment are not part of
    the path: "/api/status;x" is "/api/status" (urlparse rather than urlsplit).
    """
    parts = urlparse(target)
    return parts.path, parts.query


def printable(text):
    """`text` with each non-printable character (ESC, BEL, CR ...) spelled as an escape."""
    return "".join(ch if ch.isprintable() else ascii(ch)[1:-1] for ch in text)


# --- static files -----------------------------------------------------------

def stays_inside(base, relative, flavour=os.path):
    """Text-only check, made before the filesystem is touched: does `relative`,
    joined onto the normalised absolute folder `base`, name something strictly
    below it? Refuses NUL bytes, absolute names, other drives and UNC shares
    (//host/share, \\\\host\\share) and ".." walks out of base. `flavour` is
    os.path, or posixpath / ntpath in tests.
    """
    if "\0" in relative:
        return False
    joined = flavour.normpath(flavour.join(base, relative))
    try:
        return joined != base and flavour.commonpath([base, joined]) == base
    except ValueError:  # another drive or share, or mixed absolute and relative
        return False


def static_target(root, url_path):
    """The regular file under `root` that `url_path` names, or None.

    "/" and "" mean index.html; otherwise one leading "/" is dropped and the rest
    is percent-decoded. The name must pass stays_inside first; then the resolved
    path (symlinks followed) must still be inside root and be a regular file.
    """
    if url_path in ("", "/"):
        relative = "index.html"
    else:
        relative = unquote(url_path[1:] if url_path.startswith("/") else url_path)
    base = Path(root).resolve()
    if not stays_inside(str(base), relative):
        return None
    try:
        target = (base / relative).resolve()
        if base in target.parents and target.is_file():
            return target
    except (OSError, ValueError, RuntimeError):  # over-long names, symlink loops
        pass
    return None


def static_type(path):
    # The whole path, not just the name: a bare "data:x.js" would be read as a data: URL.
    kind = mimetypes.guess_type(os.fspath(path))[0] or BINARY_TYPE
    if kind.startswith("text/") or kind == "application/javascript":
        kind += "; charset=utf-8"
    return kind


def static_reply(root, url_path):
    target = static_target(root, url_path)
    if target is not None:
        try:
            return Reply(target.read_bytes(), content_type=static_type(target))
        except OSError:  # vanished or unreadable since the check
            pass
    return Reply(b"not found", 404, TEXT_TYPE)


# --- API routes ---------------------------------------------------------------
# Each route is called as func(handler, **named_groups) and returns a dict/list
# (200 JSON) or a Reply.

def api_status(req):
    return req.app.status()


def api_import_firmware(req):
    filename = unquote(req.headers.get("X-Filename", ""))
    try:  # the official download is gr3_v210.zip; take fwdc239b.bin out of it
        data, filename = fwzip.unwrap(req.read_body(), filename)
    except fwzip.ZipError as e:
        raise ApiError(422, str(e))
    return req.app.import_firmware(data, filename)


def api_quit(req):
    req.after_reply = req.server.stop_soon
    return {"ok": True}


def api_check_name(req):
    return req.app.check_name(req.read_json())


def api_set_pref(req):
    body = req.read_json()
    key = body.get("key")
    if key not in PREF_KEYS:  # tuple, so an unhashable key is still just "unknown"
        raise ApiError(400, "未知设置")
    return req.store.set_pref(key, bool(body.get("value")))


def api_create_project(req):
    body = req.read_json()
    return req.store.create_project(body.get("title"), body.get("input_sha256"), req.app.template)


def api_factory_shutdown(req, digest):
    return Reply(req.app.factory_shutdown(digest), content_type="image/jpeg")


def api_factory(req, digest):
    return req.app.factory(digest)


def api_factory_icon(req, digest, n):
    req.app.factory(digest)
    icon = req.store.factory_dir(digest) / "icons" / ("%d.png" % int(n))
    if not icon.is_file():
        raise ApiError(404, "没有这个图标")
    return Reply(icon.read_bytes(), content_type="image/png")


def api_build_firmware(req, bid):
    data = req.store.build_path(bid, "fwdc239b.bin").read_bytes()
    return Reply(data, content_type=BINARY_TYPE, headers=[disposition("fwdc239b.bin")])


def api_build_manifest(req, bid):
    data = req.store.build_path(bid, "manifest.json").read_bytes()
    return Reply(data, content_type=JSON_TYPE, headers=[disposition("darkslide-manifest-%s.json" % bid)])


def api_get_project(req, pid):
    return req.store.get_project(pid)


def api_rename_project(req, pid):
    return req.store.rename_project(pid, req.read_json().get("title"))


def api_put_draft(req, pid):
    return req.store.put_draft(pid, req.read_json().get("changes"), req.app.template)


def api_save_project(req, pid):
    return req.store.save(pid, req.app.template)


def api_upload_asset(req, pid):
    data = req.read_body()
    if req.query == "kind=shutdown":
        return req.store.put_shutdown_jpeg(pid, data)
    return req.store.put_asset(pid, data, expect_icon=(req.query == "kind=icon"))


def api_get_asset(req, pid, digest):
    path = req.store.asset_path(pid, digest)
    kind = "image/jpeg" if path.suffix == ".jpg" else "image/png"
    return Reply(path.read_bytes(), content_type=kind)


def api_generate(req, pid):
    app, store = req.app, req.store
    if not app.template.get("reviewed"):
        raise ApiError(409, "模板不可用，不能生成")
    project = store.get_project(pid)
    source = store.input_path(project["input_sha256"])
    if not source.exists():
        raise ApiError(409, "找不到官方原件，请重新导入")
    try:
        output, manifest = generate.run(store, project, app.template, source.read_bytes())
    except generate.GenerateError as exc:
        return Reply({"error": str(exc), "checks": exc.checks}, 422)
    return store.put_build(output, manifest)


# Placeholders usable in route paths; everything else in a path is literal.
PATH_PARTS = {
    "<pid>": r"(?P<pid>p_[0-9a-f]{12})",
    "<bid>": r"(?P<bid>b_[0-9a-f]{12})",
    "<digest>": r"(?P<digest>[0-9a-f]{64})",
    "<n>": r"(?P<n>[0-9]{1,2})",
}


def path_pattern(spec):
    """Compile "/api/projects/<pid>/save" into a regex (used with fullmatch)."""
    pieces = re.split(r"(<[a-z]+>)", spec)
    return re.compile("".join(PATH_PARTS[p] if p in PATH_PARTS else re.escape(p) for p in pieces))


ROUTES = tuple((method, path_pattern(spec), func) for method, spec, func in (
    ("GET", "/api/status", api_status),
    ("POST", "/api/firmware", api_import_firmware),
    ("POST", "/api/quit", api_quit),
    ("POST", "/api/check-name", api_check_name),
    ("POST", "/api/prefs", api_set_pref),
    ("POST", "/api/projects", api_create_project),
    ("GET", "/api/factory/<digest>/shutdown.jpg", api_factory_shutdown),
    ("GET", "/api/factory/<digest>", api_factory),
    ("GET", "/api/factory/<digest>/icons/<n>.png", api_factory_icon),
    ("GET", "/api/builds/<bid>/firmware", api_build_firmware),
    ("GET", "/api/builds/<bid>/manifest", api_build_manifest),
    ("GET", "/api/projects/<pid>", api_get_project),
    ("PATCH", "/api/projects/<pid>", api_rename_project),
    ("PUT", "/api/projects/<pid>/draft", api_put_draft),
    ("POST", "/api/projects/<pid>/save", api_save_project),
    ("POST", "/api/projects/<pid>/assets", api_upload_asset),
    ("GET", "/api/projects/<pid>/assets/<digest>", api_get_asset),
    ("POST", "/api/projects/<pid>/generate", api_generate),
))


def find_route(method, path):
    """(func, named groups) for the first ROUTES row whose method matches and whose
    pattern matches the whole path; ApiError 404 when none does."""
    for verb, pattern, func in ROUTES:
        if verb == method:
            match = pattern.fullmatch(path)
            if match:
                return func, match.groupdict()
    raise ApiError(404, "not found")


# --- handler and server -------------------------------------------------------

class RequestHandler(BaseHTTPRequestHandler):
    """Serves one connection of a LocalServer; the application is `self.server.app`."""

    server_version = "Darkslide/" + VERSION
    # A request line without a version (HTTP/0.9 style) is answered as HTTP/1.0,
    # so that reply also gets a status line and headers.
    default_request_version = "HTTP/1.0"
    timeout = IDLE_TIMEOUT

    # Request state, reset by respond() for every request.
    query = ""
    after_reply = None
    _body = None

    @property
    def app(self):
        return self.server.app

    @property
    def store(self):
        return self.server.app.store

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def do_PUT(self):
        self.respond()

    def do_PATCH(self):
        self.respond()

    def parse_request(self):
        accepted = super().parse_request()
        if self.request_version == "HTTP/0.9":  # an explicit "HTTP/0.9" token: still reply with headers
            self.request_version = "HTTP/1.0"
        return accepted

    # -- the fixed order of section 二 --
    def respond(self):
        self.query, self.after_reply, self._body = "", None, None
        try:
            status, headers, data = render(self.route())
        except Exception as exc:  # noqa: BLE001 - mapped by table, others re-raised
            # (a socket timeout is re-raised too; handle_one_request then drops the connection quietly)
            mapped = error_reply(exc)
            if mapped is None:
                raise
            self.after_reply = None
            # messages may quote client text (a slot key, say); escape what UTF-8 cannot carry
            status, headers, data = render(mapped, errors="backslashreplace")
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)
        if self.after_reply is not None:
            self.after_reply()
        self.discard_unread_body()

    def route(self):
        port = self.server.server_address[1]
        hosts = ["%s:%d" % (name, port) for name in LOCAL_HOSTNAMES]
        if self.single_header("Host") not in hosts:
            raise ApiError(403, "forbidden host")
        if self.command != "GET" and self.headers.get_all("Origin") is not None:
            if self.single_header("Origin") not in ["http://" + host for host in hosts]:
                raise ApiError(403, "forbidden origin")
        path, self.query = split_target(self.path)
        if path.startswith("/api/"):
            func, groups = find_route(self.command, path)
            return func(self, **groups)
        if self.command != "GET":
            raise ApiError(405, "method not allowed")
        return static_reply(WEB_ROOT, path)

    def single_header(self, name):
        """The header's value if it appears exactly once, else None."""
        values = self.headers.get_all(name) or []
        return values[0] if len(values) == 1 else None

    # -- request body --
    def read_body(self):
        """The body by Content-Length (b"" when absent or 0); 413 above MAX_BODY.

        A Content-Length that is not a whole number >= 0 raises ValueError."""
        if self._body is None:
            size = int(self.headers.get("Content-Length") or 0)
            if size < 0:
                raise ValueError("negative Content-Length")
            if size > MAX_BODY:
                raise ApiError(413, "文件太大")
            self._body = self.rfile.read(size) if size else b""
        return self._body

    def read_json(self):
        """The body as a JSON object; an empty body counts as {}."""
        try:
            raw = self.read_body()
        except ValueError:  # unusable Content-Length: on JSON routes v0.2 called that malformed
            raise ApiError(400, "请求格式错误") from None
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            value = None
        if not isinstance(value, dict):
            raise ApiError(400, "请求格式错误")
        return value

    def discard_unread_body(self):
        """Read and drop a declared body the route never read (at most DISCARD_LIMIT bytes)."""
        if self._body is not None:
            return
        try:
            left = min(int(self.headers.get("Content-Length") or 0), DISCARD_LIMIT)
        except ValueError:
            return
        try:
            while left > 0:
                chunk = self.rfile.read(min(left, 256 * 1024))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:  # timed out or reset; the connection is closed next anyway
            pass

    # -- reply --
    def send_response(self, code, message=None):
        super().send_response(code, message)
        for name, value in SAFETY_HEADERS:
            self.send_header(name, value)

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s %s", self.address_string(), printable(fmt % args))


class LocalServer(ThreadingHTTPServer):
    """Threaded HTTP server for one App, listening on 127.0.0.1 only."""

    daemon_threads = True

    def __init__(self, address, app):
        if address[0] != LOOPBACK:
            raise ValueError("Darkslide 只监听 %s，不能绑定 %r" % (LOOPBACK, address[0]))
        self.app = app
        super().__init__(address, RequestHandler)

    def stop_soon(self):
        """Stop serve_forever without blocking the caller (shutdown() waits for the loop)."""
        threading.Thread(target=self.shutdown, name="darkslide-stop", daemon=True).start()


def create_server(port, root=None):
    """Bind an App over `root` (default data folder) to 127.0.0.1:port; not yet serving."""
    return LocalServer((LOOPBACK, port), App(root))

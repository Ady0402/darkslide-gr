"""Local HTTP server: static pages plus a small JSON API. Binds to 127.0.0.1 only."""
import json
import threading
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import VERSION, fwread, generate, names, pngcheck, template as tpl
from .identify import identify
from .paths import WEB_ROOT, data_root
from .store import Store, StoreError, read_json, write_json

MAX_BODY = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, root=None, template_name="gr3_v210.json"):
        self.store = Store(root or data_root())
        self.template = tpl.load(template_name)

    def status(self):
        return dict(version=VERSION, template=self.template, projects=self.store.list_projects(),
                    builds=self.store.builds(), prefs=self.store.prefs(),
                    data_root=str(self.store.root))

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

    def check_name(self, body):
        slot = tpl.slot(self.template, int(body.get("slot")))
        name = body.get("name")
        if not isinstance(name, str):
            raise ApiError(400, "预设名必须是文字")
        limit = len(slot["factory_en"])
        return dict(limit=limit, factory_en=slot["factory_en"], checks=names.check_name(name, limit),
                    ok=names.name_ok(name, limit))


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Darkslide/" + VERSION

        def log_message(self, fmt, *args):
            pass

        # helpers ----------------------------------------------------------
        def _host_ok(self):
            port = self.server.server_address[1]
            return self.headers.get("Host") in ("127.0.0.1:%d" % port, "localhost:%d" % port)

        def _origin_ok(self):
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            port = self.server.server_address[1]
            return origin in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port)

        def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError(413, "文件太大")
            return self.rfile.read(length) if length else b""

        def _json(self):
            try:
                value = json.loads(self._body() or b"{}")
            except ValueError:
                raise ApiError(400, "请求格式错误")
            if not isinstance(value, dict):
                raise ApiError(400, "请求格式错误")
            return value

        def _dispatch(self, method):
            if not self._host_ok():
                return self._send(403, dict(error="forbidden host"))
            if method != "GET" and not self._origin_ok():
                return self._send(403, dict(error="forbidden origin"))
            path = urlparse(self.path).path
            try:
                if path.startswith("/api/"):
                    return self._api(method, path)
                if method != "GET":
                    raise ApiError(405, "method not allowed")
                return self._static(path)
            except ApiError as exc:
                return self._send(exc.status, dict(error=str(exc)))
            except StoreError as exc:
                return self._send(400, dict(error=str(exc)))
            except fwread.FirmwareReadError as exc:
                return self._send(422, dict(error="读取固件失败：" + str(exc)))
            except (KeyError, ValueError, TypeError):
                return self._send(400, dict(error="请求参数错误"))

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_PATCH(self):
            self._dispatch("PATCH")

        # routes -----------------------------------------------------------
        def _api(self, method, path):
            store = app.store
            if path == "/api/status" and method == "GET":
                return self._send(200, app.status())
            if path == "/api/firmware" and method == "POST":
                filename = unquote(self.headers.get("X-Filename") or "")
                return self._send(200, app.import_firmware(self._body(), filename))
            if path == "/api/quit" and method == "POST":
                # answer first, then stop the server from another thread
                self._send(200, dict(ok=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return None
            if path == "/api/check-name" and method == "POST":
                return self._send(200, app.check_name(self._json()))
            if path == "/api/prefs" and method == "POST":
                body = self._json()
                if body.get("key") not in ("preflight_seen", "guide_off", "guide_start_seen", "guide_work_seen"):
                    raise ApiError(400, "未知设置")
                return self._send(200, store.set_pref(body["key"], bool(body.get("value"))))
            if path == "/api/projects" and method == "POST":
                body = self._json()
                return self._send(200, store.create_project(body.get("title"), body.get("input_sha256"), app.template))
            f = re.match(r"^/api/factory/([0-9a-f]{64})(?:/icons/(\d{1,2})\.png)?$", path)
            if f and method == "GET":
                if f.group(2) is None:
                    return self._send(200, app.factory(f.group(1)))
                app.factory(f.group(1))
                icon = store.factory_dir(f.group(1)) / "icons" / ("%d.png" % int(f.group(2)))
                if not icon.exists():
                    raise ApiError(404, "没有这个图标")
                return self._send(200, icon.read_bytes(), "image/png")
            b = re.match(r"^/api/builds/(b_[0-9a-f]{12})/(firmware|manifest)$", path)
            if b and method == "GET":
                if b.group(2) == "firmware":
                    data = store.build_path(b.group(1), "fwdc239b.bin").read_bytes()
                    return self._send(200, data, "application/octet-stream",
                                      {"Content-Disposition": 'attachment; filename="fwdc239b.bin"'})
                data = store.build_path(b.group(1), "manifest.json").read_bytes()
                return self._send(200, data, "application/json; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="darkslide-manifest-%s.json"' % b.group(1)})
            m = re.match(r"^/api/projects/(p_[0-9a-f]{12})(/.*)?$", path)
            if not m:
                raise ApiError(404, "not found")
            pid, rest = m.group(1), m.group(2) or ""
            if rest == "" and method == "GET":
                return self._send(200, store.get_project(pid))
            if rest == "" and method == "PATCH":
                return self._send(200, store.rename_project(pid, self._json().get("title")))
            if rest == "/draft" and method == "PUT":
                return self._send(200, store.put_draft(pid, self._json().get("changes"), app.template))
            if rest == "/save" and method == "POST":
                return self._send(200, store.save(pid, app.template))
            if rest == "/assets" and method == "POST":
                kind = urlparse(self.path).query
                return self._send(200, store.put_asset(pid, self._body(), expect_icon=(kind == "kind=icon")))
            a = re.match(r"^/assets/([0-9a-f]{64})$", rest)
            if a and method == "GET":
                return self._send(200, store.asset_path(pid, a.group(1)).read_bytes(), "image/png")
            if rest == "/generate" and method == "POST":
                if not app.template.get("reviewed"):
                    raise ApiError(409, "模板尚未复核，不能生成")
                project = store.get_project(pid)
                official = store.input_path(project["input_sha256"])
                if not official.exists():
                    raise ApiError(409, "找不到官方原件，请重新导入")
                try:
                    output, manifest = generate.run(store, project, app.template, official.read_bytes())
                except generate.GenerateError as exc:
                    return self._send(422, dict(error=str(exc), checks=exc.checks))
                return self._send(200, store.put_build(output, manifest))
            raise ApiError(404, "not found")

        def _static(self, path):
            rel = "index.html" if path in ("/", "") else unquote(path.lstrip("/"))
            target = (WEB_ROOT / rel).resolve()
            if WEB_ROOT.resolve() not in target.parents or not target.is_file():
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            return self._send(200, target.read_bytes(), ctype)

    return Handler


def serve(port=8787, root=None):
    app = App(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    return httpd

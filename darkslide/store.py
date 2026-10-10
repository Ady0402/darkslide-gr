"""Local data: imported inputs, projects (draft + saved versions), assets, builds.

Layout under the data root:
  inputs/<sha256>.bin
  projects/<id>/project.json      saved state (⌘S) and version list
  projects/<id>/draft.json        autosaved working copy
  projects/<id>/versions/<n>.json one file per ⌘S
  projects/<id>/assets/<sha256>.png
  builds.json, prefs.json
"""
import json
import os
import re
import secrets
import struct
import tempfile
import time
from pathlib import Path

from . import names, pngcheck, template as tpl
from .identify import sha256

PROJECT_ID = re.compile(r"^p_[0-9a-f]{12}$")
ASSET_ID = re.compile(r"^[0-9a-f]{64}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SOURCE_BYTES = 20 * 1024 * 1024


class StoreError(ValueError):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def png_size(data):
    if not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        raise StoreError("不是 PNG 文件")
    return struct.unpack(">II", data[16:24])


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # inputs -------------------------------------------------------------
    def put_input(self, data):
        digest = sha256(data)
        path = self.root / "inputs" / (digest + ".bin")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(str(tmp), str(path))
        return digest

    def input_path(self, digest):
        return self.root / "inputs" / (digest + ".bin")

    def factory_dir(self, digest):
        if not ASSET_ID.match(digest or ""):
            raise StoreError("固件编号无效")
        return self.root / "inputs" / digest

    def has_input(self, digest):
        return (self.root / "inputs" / (digest + ".bin")).exists()

    # projects -----------------------------------------------------------
    def _dir(self, project_id):
        if not PROJECT_ID.match(project_id or ""):
            raise StoreError("工程编号无效")
        path = self.root / "projects" / project_id
        if not (path / "project.json").exists():
            raise StoreError("找不到这个工程")
        return path

    def create_project(self, title, input_sha256, template):
        if not self.has_input(input_sha256):
            raise StoreError("请先导入官方固件")
        project_id = "p_" + secrets.token_hex(6)
        stamp = now()
        project = dict(schema=1, id=project_id, title=(title or "未命名").strip()[:40] or "未命名",
                       input_sha256=input_sha256, template_id=template["id"],
                       created_at=stamp, saved_at=None, changes={}, versions=[])
        path = self.root / "projects" / project_id
        write_json(path / "project.json", project)
        write_json(path / "draft.json", dict(changes={}, updated_at=stamp))
        return self.get_project(project_id)

    def list_projects(self):
        out = []
        for item in sorted((self.root / "projects").glob("p_*/project.json")):
            value = read_json(item, {})
            draft = read_json(item.parent / "draft.json", {})
            out.append(dict(id=value.get("id"), title=value.get("title"), saved_at=value.get("saved_at"),
                            input_sha256=value.get("input_sha256"),
                            updated_at=draft.get("updated_at"), changes=len(draft.get("changes", {}))))
        return sorted(out, key=lambda p: p.get("updated_at") or "", reverse=True)

    def get_project(self, project_id):
        path = self._dir(project_id)
        project = read_json(path / "project.json")
        draft = read_json(path / "draft.json", dict(changes={}, updated_at=None))
        project["draft"] = draft
        project["unsaved"] = draft.get("changes", {}) != project.get("changes", {})
        return project

    def rename_project(self, project_id, title):
        path = self._dir(project_id)
        project = read_json(path / "project.json")
        project["title"] = (title or "").strip()[:40] or project["title"]
        write_json(path / "project.json", project)
        return self.get_project(project_id)

    def put_draft(self, project_id, changes, template):
        path = self._dir(project_id)
        clean = self.validate_changes(project_id, changes, template, strict=False)
        write_json(path / "draft.json", dict(changes=clean, updated_at=now()))
        return self.get_project(project_id)

    def save(self, project_id, template):
        path = self._dir(project_id)
        project = read_json(path / "project.json")
        draft = read_json(path / "draft.json", dict(changes={}))
        clean = self.validate_changes(project_id, draft.get("changes", {}), template, strict=True)
        stamp = now()
        number = len(project.get("versions", [])) + 1
        write_json(path / "versions" / ("%d.json" % number), dict(changes=clean, saved_at=stamp))
        project.update(changes=clean, saved_at=stamp)
        project.setdefault("versions", []).append(dict(number=number, saved_at=stamp, changes=len(clean)))
        write_json(path / "project.json", project)
        return self.get_project(project_id)

    # assets -------------------------------------------------------------
    def put_asset(self, project_id, data, expect_icon=False):
        path = self._dir(project_id)
        if len(data) > MAX_SOURCE_BYTES:
            raise StoreError("图片太大（上限 20MB）")
        width, height = png_size(data)
        if expect_icon:
            try:
                pngcheck.check_icon(data)
            except pngcheck.PngError as exc:
                raise StoreError(str(exc))
        digest = sha256(data)
        target = path / "assets" / (digest + ".png")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return dict(asset=digest, width=width, height=height)

    def asset_path(self, project_id, asset):
        if not ASSET_ID.match(asset or ""):
            raise StoreError("图片编号无效")
        path = self._dir(project_id) / "assets" / (asset + ".png")
        if not path.exists():
            raise StoreError("找不到图片")
        return path

    # validation ---------------------------------------------------------
    def validate_changes(self, project_id, changes, template, strict):
        """Keep only well-formed edits on open slots. strict=True (⌘S) also
        requires every preset name to pass the rules; drafts may hold
        work-in-progress names."""
        if not isinstance(changes, dict):
            raise StoreError("改动格式错误")
        clean = {}
        for key, edit in changes.items():
            try:
                no = int(key)
                slot = tpl.slot(template, no)
            except (ValueError, KeyError):
                raise StoreError("没有这个槽位：%s" % key)
            if not isinstance(edit, dict):
                raise StoreError("槽位 %s 的改动格式错误" % key)
            out = {}
            if "name" in edit:
                if not tpl.can_edit(template, no, "rename"):
                    raise StoreError("%s 的预设名暂不开放" % slot["name"])
                name = edit["name"]
                if not isinstance(name, str):
                    raise StoreError("预设名必须是文字")
                if strict and not names.name_ok(name, len(slot["factory_en"])):
                    raise StoreError("%s 的预设名没有通过检查" % slot["name"])
                out["name"] = name
            if "icon" in edit:
                if not tpl.can_edit(template, no, "icon"):
                    raise StoreError("%s 的图标暂不开放" % slot["name"])
                icon = edit["icon"]
                if not isinstance(icon, dict) or icon.get("style") not in ("image", "factory"):
                    raise StoreError("%s 的图标格式错误" % slot["name"])
                self.asset_path(project_id, icon.get("asset"))
                if icon.get("source"):
                    self.asset_path(project_id, icon["source"])
                keep = ("asset", "source", "style", "crop", "text")
                out["icon"] = {k: icon[k] for k in keep if k in icon}
            if out:
                clean[str(no)] = out
        return clean

    # builds and prefs ----------------------------------------------------
    def builds(self):
        return read_json(self.root / "builds.json", [])

    def put_build(self, output, manifest):
        """Store a generated file that already passed every check."""
        build_id = "b_" + secrets.token_hex(6)
        folder = self.root / "builds" / build_id
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "fwdc239b.bin").write_bytes(output)
        manifest = dict(manifest, build_id=build_id)
        write_json(folder / "manifest.json", manifest)
        builds = self.builds()
        builds.append(dict(build_id=build_id, project_id=manifest["project_id"],
                           output_sha256=manifest["output_sha256"], created_at=manifest["created_at"]))
        write_json(self.root / "builds.json", builds)
        return manifest

    def build_path(self, build_id, name):
        if not re.match(r"^b_[0-9a-f]{12}$", build_id or "") or name not in ("fwdc239b.bin", "manifest.json"):
            raise StoreError("生成记录无效")
        path = self.root / "builds" / build_id / name
        if not path.exists():
            raise StoreError("找不到生成记录")
        return path

    def prefs(self):
        return read_json(self.root / "prefs.json", {})

    def set_pref(self, key, value):
        prefs = self.prefs()
        prefs[key] = value
        write_json(self.root / "prefs.json", prefs)
        return prefs

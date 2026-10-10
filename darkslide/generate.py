"""Glue between a saved project and the builder + independent check.

Order: saved project → edits → build (generation core, in memory) → verify
(independent read-back) → only if every check passes, the caller stores the file.
"""
import time

from . import build as builder, names, pngcheck, template as tpl, verify


class GenerateError(ValueError):
    def __init__(self, message, checks=None):
        super().__init__(message)
        self.checks = checks or []


def edits_from_changes(store, project_id, changes, template):
    edits = []
    for key in sorted(changes, key=int):
        slot = tpl.slot(template, int(key))
        change = changes[key]
        if "icon" in change:
            png = store.asset_path(project_id, change["icon"]["asset"]).read_bytes()
            pngcheck.check_icon(png)
            _, _, rows = pngcheck.rgba_rows(png)
            edits.append(dict(kind="icon", slot=slot["no"], icon_id=slot["icon_id"], pixels=b"".join(rows)))
        if "name" in change:
            if not names.name_ok(change["name"], len(slot["factory_en"])):
                raise GenerateError("%s 的预设名没有通过检查" % slot["name"])
            edits.append(dict(kind="name", slot=slot["no"], string_id=slot["string_id"], text=change["name"]))
    return edits


def summarize(changes, template):
    out = []
    for key in sorted(changes, key=int):
        slot = tpl.slot(template, int(key))
        icon = changes[key].get("icon")
        if icon:
            value = "原厂风格 " + icon.get("text", "") if icon.get("style") == "factory" else "自定义图片"
            out.append(dict(slot=slot["no"], preset=slot["name"], what="图标", value=value))
        if "name" in changes[key]:
            out.append(dict(slot=slot["no"], preset=slot["name"], what="预设名", value=changes[key]["name"]))
    return out


def run(store, project, template, official_bin):
    if project.get("unsaved"):
        raise GenerateError("有未保存的改动，请先保存（⌘S）")
    changes = project.get("changes") or {}
    if not changes:
        raise GenerateError("还没有改动")
    edits = edits_from_changes(store, project["id"], changes, template)
    try:
        result = builder.build(official_bin, edits, template)
    except builder.BuildError as exc:
        raise GenerateError("生成核心拒绝：%s" % exc)
    checks = verify.verify(official_bin, result, edits, template)
    if not verify.all_ok(checks):
        raise GenerateError("独立核对没有全部通过，不输出文件", checks)
    manifest = dict(
        schema=1, created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        project_id=project["id"], project_title=project["title"],
        project_version=len(project.get("versions", [])),
        template_id=template["id"], model=template["model"], firmware=template["firmware"],
        input_sha256=result["input_sha256"], output_sha256=result["output_sha256"],
        payload_sha256_before=result["payload_sha256_before"],
        payload_sha256_after=result["payload_sha256_after"],
        version_word=result["version_word"], summary=summarize(changes, template),
        payload_changes=result["payload_changes"], container=result["container"],
        builder=result["builder"], checks=checks,
        verification="离线核对通过；未经实机验证。刷机风险自负，刷机前请备好官方 2.10 救机卡。",
    )
    return result["output"], manifest

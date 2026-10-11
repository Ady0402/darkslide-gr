"""Glue between a saved project and the builder + independent check.

Order: saved project → edits → build (generation core, in memory) → verify
(independent read-back) → only if every check passes, the caller stores the file.
"""
import time

from . import composite_verify, compositor, names, pngcheck, rescue_gate, template as tpl


# Display titles for the composite checker's ids (presentation only).
CHECK_TITLES = {
    "input": "输入是官方 GR III 2.10 原件",
    "output_sha": "输出文件 SHA 与生成记录一致",
    "header_version": "文件头 128 字节与原件相同（版本保持 2.10）",
    "metadata": "元数据与原件相同",
    "footer_identity": "文件尾固定字段与原件相同",
    "container_bounds_padding": "压缩流边界、结束码与对齐正确",
    "file_sum": "整文件 32 位加和为 0",
    "independent_unpack": "独立解包生成的文件",
    "payload_sum": "解码数据加和为 0",
    "icon_name_expected": "按请求独立推导图标和预设名的预期内容",
    "a_path_four_requests_fixed_slot_jpeg": "关机图：四个入口指向同一位置、A 盘路径、图片只多出填充段",
    "entire_payload_matches_independent_request": "整份解码数据与独立推导的预期逐字节一致（没有任何越界改动）",
    "payload_sha": "解码数据 SHA 与生成记录一致",
    "readback_icons_names": "读回 14 个预设的图标和预设名（英文、简中、日文）",
    "closed_failure": "核对过程出错",
}


def titled(checks):
    return [dict(c, title=CHECK_TITLES.get(c["id"], c["title"])) for c in checks]


class GenerateError(ValueError):
    def __init__(self, message, checks=None):
        super().__init__(message)
        self.checks = checks or []


def slot_keys(changes):
    return sorted((k for k in changes if k != "shutdown"), key=int)


def edits_from_changes(store, project_id, changes, template):
    edits = []
    for key in slot_keys(changes):
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
        if change.get("grain") is True:
            if tpl.grain_stage(template, slot["no"]) != "menu":
                raise GenerateError("%s 的颗粒项不能由本工具开放" % slot["name"])
            edits.append(dict(kind="grain_menu", slot=slot["no"], mode=slot["mode"]))
    return edits


def summarize(changes, template):
    out = []
    if "shutdown" in changes:
        out.append(dict(slot=None, preset="关机画面", what="关机图",
                        value="自定义图片（%s 字节）" % changes["shutdown"].get("bytes", "?")))
    for key in slot_keys(changes):
        slot = tpl.slot(template, int(key))
        icon = changes[key].get("icon")
        if icon:
            value = "原厂风格 " + icon.get("text", "") if icon.get("style") == "factory" else "自定义图片"
            out.append(dict(slot=slot["no"], preset=slot["name"], what="图标", value=value))
        if "name" in changes[key]:
            out.append(dict(slot=slot["no"], preset=slot["name"], what="预设名", value=changes[key]["name"]))
        if changes[key].get("grain") is True:
            out.append(dict(slot=slot["no"], preset=slot["name"], what="颗粒项", value="开放（档位在相机详细设置里调）"))
    return out


def run(store, project, template, official_bin):
    """Icons, preset names and the shutdown image in one build: the composite
    core applies everything to one official payload and packs once; the
    composite checker re-derives the expected payload and reads it all back."""
    if project.get("unsaved"):
        raise GenerateError("有未保存的改动，请先保存（⌘S）")
    changes = project.get("changes") or {}
    if not changes:
        raise GenerateError("还没有改动")
    edits = edits_from_changes(store, project["id"], changes, template)
    # Grain is "暂不参与生成" until the generation core can write the
    # 3-byte menu change (count 9→10, append flag 2 + Particle ID 15). Keep it in
    # the project, leave it out of this build, and say so in the manifest.
    skipped = [tpl.slot(template, e["slot"])["name"] + " 颗粒项" for e in edits if e["kind"] == "grain_menu"]
    edits = [e for e in edits if e["kind"] != "grain_menu"]
    if not edits and "shutdown" not in changes:
        raise GenerateError("颗粒项暂不参与生成（写入核心还没交付），目前没有其他可以生成的改动。")
    jpeg = None
    if "shutdown" in changes:
        jpeg = store.asset_path(project["id"], changes["shutdown"]["asset"]).read_bytes()
    try:
        result = compositor.build_composite(official_bin, edits, template, jpeg)
    except compositor.CompositeError as exc:
        raise GenerateError("无法生成：%s" % exc)
    checks = titled(composite_verify.verify(official_bin, result, edits, template, jpeg))
    if not composite_verify.all_ok(checks):
        raise GenerateError("独立核对没有全部通过，不输出文件", checks)
    # Third layer, blind to the request: can the official 2.10 package still rescue the camera?
    rescue = rescue_gate.gate(official_bin, result["output"])
    checks += rescue
    if not rescue_gate.all_ok(rescue):
        raise GenerateError("救机门禁没有通过，不输出文件", checks)
    features = list(result.get("features") or [])
    manifest = dict(
        schema=1, created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        project_id=project["id"], project_title=project["title"],
        project_version=len(project.get("versions", [])),
        template_id=template["id"], model=template["model"], firmware=template["firmware"],
        input_sha256=result["input_sha256"], output_sha256=result["output_sha256"],
        payload_sha256_before=result["payload_sha256_before"],
        payload_sha256_after=result["payload_sha256_after"],
        version_word=result["version_word"], summary=summarize(changes, template),
        features=features, payload_changes=result["payload_changes"],
        container=result["container"], builder=result["builder"], checks=checks,
        skipped=skipped,
        rescue=dict(rescue_gate.RESCUE_NOTE),
        verification="离线核对通过。图标和预设名、关机画面各自已在 GR III 上实测；三类同时改动的组合尚未实测。刷机风险自负，刷机前请备好官方 2.10 救机卡。",
    )
    if jpeg is not None:
        manifest["feature"] = "shutdown" if features == ["shutdown"] else "composite"
        manifest["shutdown"] = dict(jpeg_bytes=len(jpeg), slot_bytes=result["shared_capacity"],
                                    requests=result["request_ids"], path=result["shared_path"])
    return result["output"], manifest

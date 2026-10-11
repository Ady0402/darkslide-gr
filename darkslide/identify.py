"""Classify an imported firmware file."""
import hashlib


def digest_of(blob):
    """Hex SHA-256 of a byte string (the content address used for inputs, assets and builds)."""
    return hashlib.sha256(blob).hexdigest()


sha256 = digest_of  # older name; tests/test_grain.py still imports it


def identify(data, filename, template, builds):
    """Return dict(kind=official|generated|rejected, sha256, reason, ...).

    builds: list of past build records (each with output_sha256 and project_id).
    """
    digest = digest_of(data)
    base = dict(sha256=digest, size=len(data), filename=filename)
    for item in template.get("official_inputs", []):
        if digest == item["sha256"]:
            return dict(base, kind="official", model=template["model"], firmware=template["firmware"],
                        reason="官方 %s %s 原件" % (template["model"], template["firmware"]))
    for build in builds:
        if build.get("output_sha256") == digest:
            return dict(base, kind="generated", project_id=build.get("project_id"),
                        reason="这是 Darkslide 生成的文件，请打开对应工程继续编辑")
    official = template.get("official_inputs", [{}])[0]
    if len(data) == official.get("size") and filename == official.get("filename"):
        reason = "文件名和大小像 %s %s，但内容不是官方原件（可能被改过）" % (template["model"], template["firmware"])
    elif filename.lower().startswith("fwdc") and filename.lower().endswith(".bin"):
        reason = "看起来是理光固件，但不是当前支持的 %s %s 官方原件" % (template["model"], template["firmware"])
    else:
        reason = "不是 %s %s 官方固件" % (template["model"], template["firmware"])
    return dict(base, kind="rejected", reason=reason)

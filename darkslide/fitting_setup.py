"""The optional camera-model component used by 拟合 (Unicorn 2.1.4).

Not shipped with Darkslide. `tools/setup_fitting.py` (run by the user's AI
assistant) or the page's first 拟合 downloads the one wheel for this computer from
PyPI, checks its size and SHA-256, and unpacks it into the user's Darkslide data
folder; nothing is installed into the system Python. Unicorn is GPL-2.0 licensed
(https://github.com/unicorn-engine/unicorn/blob/2.1.4/COPYING); see
THIRD_PARTY_NOTICES.md.
"""
import hashlib
import importlib
import json
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .paths import data_root

VERSION = "2.1.4"
PYPI = "https://files.pythonhosted.org/packages/"

# (sys.platform, machine) -> the cp37-abi3 wheel published on PyPI for Unicorn 2.1.4.
# Mac and Windows only (user, 2026-10-13). Whether a computer may fit is decided on
# that computer: the camera model must give the reference values (self_check).
WHEELS = {
    ("darwin", "arm64"): dict(
        file="unicorn-2.1.4-cp37-abi3-macosx_11_0_arm64.whl", size=12142730,
        sha256="d6c93e0f60328d8f4a1792af3f834137a28050fcc2305f2ec01efe8558a9844e",
        path="6c/ae/4943c6f8524d729ec7d5e69df6407ea05d710fe77471d91cecf3fc64eb57/"),
    ("darwin", "x86_64"): dict(
        file="unicorn-2.1.4-cp37-abi3-macosx_10_9_x86_64.whl", size=12958220,
        sha256="2a6f738fab5fabffa56af1e7bbf16ea1e91466c342f8dc64f125bd70f36c6b80",
        path="c8/a7/92b47771e2107a201632a199cec91e8a81ee8a071ca6b7e7d600d8c61ac9/"),
    ("win32", "amd64"): dict(
        file="unicorn-2.1.4-cp37-abi3-win_amd64.whl", size=15943079,
        sha256="d7107500c64ce5c168fbff6bef9485b5db1350050036f4cea568650cf8bdbdf5",
        path="70/3d/de7be9bd1addabe6d8a1369381f8a080400c349850e978689c5e18287957/"),
}

# sha256 of the compact JSON of the 256 base values on the official 2.10 firmware
# (darkslide.base_curve, model gr3-210-upstream-neutral-stubbed-v2). Anything else is not used.
REFERENCE_VALUES_SHA256 = "41aaa2193b51e4138fbb85b1fa220a128ec9d83aa92def5bf8ebafd4f299c18e"

PLATFORM_NAMES = {("darwin", "arm64"): "Mac（Apple 芯片）", ("darwin", "x86_64"): "Mac（Intel 芯片）",
                  ("win32", "amd64"): "Windows 64 位"}


class SetupError(RuntimeError):
    pass


def platform_key():
    return sys.platform, platform.machine().lower()


def wheel():
    return WHEELS.get(platform_key())


def deps_dir(root=None):
    return Path(root or data_root()) / "deps" / ("unicorn-" + VERSION)


def activate(root=None):
    """Put the installed component on sys.path (no-op when it is not there)."""
    folder = deps_dir(root)
    if (folder / "unicorn").is_dir() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
        importlib.invalidate_caches()
    return folder


def _check_file(root=None):
    return deps_dir(root) / "self_check.json"


def checked(root=None):
    """The last self check on this computer: {"ok": bool, ...} or None."""
    try:
        return json.loads(_check_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(root=None):
    key, w = platform_key(), wheel()
    installed = (deps_dir(root) / "unicorn").is_dir()
    check = checked(root) if installed else None
    if w is None:
        state, note = "unsupported", "拟合组件只支持 Mac 和 Windows 64 位。"
    elif not installed:
        state, note = "missing", "第一次拟合需要下载相机模拟组件（约 %d MB），只需一次。" % round(w["size"] / 1e6)
    elif check and not check.get("ok"):
        state, note = "failed", "这台电脑上相机模拟算出的结果和核对值不一致，拟合停用；其他功能照常。"
    elif check:
        state, note = "ready", "拟合组件已装好并通过自检。"
    else:
        state, note = "installed", "拟合组件已装好，第一次拟合时会自检一次。"
    return dict(state=state, note=note, platform=PLATFORM_NAMES.get(key, "%s %s" % key),
                version=VERSION, size=w["size"] if w else None, folder=str(deps_dir(root)))


def _download(w, target, fetch):
    digest, got = hashlib.sha256(), 0
    with fetch(PYPI + w["path"] + w["file"]) as res, open(target, "wb") as out:
        while True:
            chunk = res.read(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > w["size"]:
                raise SetupError("下载的文件比预期大，已停止")
            digest.update(chunk)
            out.write(chunk)
    if got != w["size"] or digest.hexdigest() != w["sha256"]:
        raise SetupError("下载的文件和 PyPI 公布的指纹不一致，已停止")


def _unpack(archive, dest):
    keep = ("unicorn/", "unicorn-%s.dist-info/" % VERSION)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith(keep):
                continue
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or "\\" in name:
                raise SetupError("组件包里有不安全的路径")
            out = dest.joinpath(*parts)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if info.external_attr >> 16 & 0o111:
                out.chmod(0o755)
    if not (dest / "unicorn" / "__init__.py").is_file():
        raise SetupError("组件包内容不完整")


def install(root=None, fetch=None):
    """Download, check and unpack the component for this computer."""
    w = wheel()
    if w is None:
        raise SetupError(status(root)["note"])
    final = deps_dir(root)
    if (final / "unicorn").is_dir():
        activate(root)
        return status(root)
    final.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".incoming-", dir=str(final.parent)))
    try:
        archive = work / w["file"]
        _download(w, archive, fetch or (lambda url: urllib.request.urlopen(url, timeout=60)))
        unpacked = work / "unpacked"
        unpacked.mkdir()
        _unpack(archive, unpacked)
        if final.exists():
            shutil.rmtree(final)
        unpacked.rename(final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    activate(root)
    return status(root)


def self_check(official_bin, contract=None, root=None):
    """Run the camera model once on the user's firmware and compare with the reference;
    the result is remembered on this computer. Raises SetupError when it does not match."""
    from . import base_curve
    activate(root)
    if contract is None:
        contract = base_curve.base_curve(official_bin)
    got = hashlib.sha256(json.dumps(contract["values"], separators=(",", ":")).encode()).hexdigest()
    result = dict(ok=got == REFERENCE_VALUES_SHA256, values_sha256=got, model_id=contract["model_id"],
                  platform="%s %s" % platform_key(), version=VERSION)
    if deps_dir(root).is_dir():
        _check_file(root).write_text(json.dumps(result), encoding="utf-8")
    if not result["ok"]:
        raise SetupError("组件能运行，但算出的基础曲线和核对值不一致，拟合停用")
    return result

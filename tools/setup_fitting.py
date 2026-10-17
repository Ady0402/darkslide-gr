"""Set up the optional 拟合 component (Unicorn 2.1.4) for Darkslide on this computer.

    python3 tools/setup_fitting.py [--status] [--firmware PATH]

Downloads the one PyPI wheel for this computer (Mac or Windows 64-bit), checks its
size and SHA-256, and unpacks it into the user's Darkslide data folder; nothing is
installed into the system Python and no pip is used. Then, when the official GR III
2.10 firmware is available (--firmware, or already imported into Darkslide), runs the
camera model once and compares it with the reference values.

Exit codes: 0 ready (or installed, self check pending), 1 failed, 2 this computer
is not supported. Everything else in Darkslide works without this component.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from darkslide import fitting_setup, fwread  # noqa: E402
from darkslide.paths import data_root  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="为 Darkslide 的「拟合」功能配置相机模拟组件")
    parser.add_argument("--status", action="store_true", help="只显示当前状态，不下载")
    parser.add_argument("--firmware", help="官方 GR III 2.10 固件（fwdc239b.bin）的路径，用于自检")
    args = parser.parse_args(argv)

    st = fitting_setup.status()
    print("电脑：%s；组件：Unicorn %s；位置：%s" % (st["platform"], st["version"], st["folder"]))
    if st["state"] == "unsupported":
        print(st["note"] + "拟合不可用，Darkslide 的其他功能照常。")
        return 2
    if args.status:
        print(st["note"])
        return 0 if st["state"] in ("ready", "installed", "missing") else 1
    try:
        if st["state"] == "missing":
            print("正在下载（约 %d MB），只需一次……" % round(st["size"] / 1e6))
            fitting_setup.install()
            print("已下载并核对指纹，装进 Darkslide 数据文件夹。")
        firmware = Path(args.firmware) if args.firmware else data_root() / "inputs" / (fwread.V210_INPUT_SHA256 + ".bin")
        if not firmware.is_file():
            print("组件已装好。还没找到官方固件：用户在 Darkslide 里导入固件后，第一次拟合时会自动自检。")
            return 0
        print("正在自检……")
        result = fitting_setup.self_check(firmware)
        print("自检通过：拟合功能可用（%s）。" % result["model_id"])
        return 0
    except fitting_setup.SetupError as exc:
        print("没有完成：%s。拟合不可用，Darkslide 的其他功能照常。" % exc)
        return 1
    except Exception as exc:  # network errors, the camera model failing to start, …
        print("没有完成：%s。拟合不可用，Darkslide 的其他功能照常。" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

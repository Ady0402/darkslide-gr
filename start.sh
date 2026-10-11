#!/bin/sh
# Darkslide 启动脚本（macOS / Linux）：用 python3 运行本脚本旁边的 launcher.py。
# 需要 Python 3.9 或更新版本；参数原样转交，例如 ./start.sh --no-browser
script_dir=$(dirname -- "$0")
if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3。请先安装 Python 3.9 或更新版本（python.org）。" >&2
  exit 1
fi
exec python3 "$script_dir/launcher.py" "$@"

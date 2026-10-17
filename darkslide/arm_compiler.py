"""Locate an installed LLVM clang. Never download tools or invoke a shell.

Object format, relocation and instruction contracts are checked by the callers;
discovering an executable does not certify a compiler version or host platform.
"""
import os
import shutil
import sys
from pathlib import Path

MAC_CLANG = '/Library/Developer/CommandLineTools/usr/bin/clang'


def resolve_clang():
    """An explicit override is authoritative: bad overrides must not fall back."""
    override = os.environ.get('DARKSLIDE_CLANG')
    if override is not None:
        if not override.strip():
            raise ValueError('DARKSLIDE_CLANG 不能为空，请指定 LLVM clang 可执行文件')
        found = shutil.which(override)
        if found:
            return found
        raise ValueError('DARKSLIDE_CLANG 不可执行：' + override)
    # Preserve the previously tested toolchain on existing macOS installs.
    candidates = [MAC_CLANG] if sys.platform == 'darwin' else []
    candidates.append('clang')
    if sys.platform == 'win32':
        for key in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
            root = os.environ.get(key)
            if root:
                candidates.append(str(Path(root)/'LLVM'/'bin'/'clang.exe'))
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    raise ValueError('缺少 LLVM clang（需支持 armv7a-none-eabi）；请安装后加入 PATH，'
                     '或设置 DARKSLIDE_CLANG 为可执行文件完整路径。不会自动安装。')

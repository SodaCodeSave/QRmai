#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载 MDUI 静态资源到 static/vendor/mdui/，实现前端资源自托管（不依赖 CDN）。

构建脚本（build_exe.py / build_nuitka.py）打包前会自动调用本模块；
也可以在本地开发时手动运行：
    python packaging/fetch_mdui.py [--force]
"""

import io
import sys
import tarfile
import urllib.request
from pathlib import Path

# 固定 MDUI 版本，升级时只需修改这里（构建时会据此自动重新下载）
MDUI_VERSION = "2.1.5"
TARBALL_URL = f"https://registry.npmjs.org/mdui/-/mdui-{MDUI_VERSION}.tgz"
# tarball 内路径 -> 本地文件名
FILES = {
    "package/mdui.css": "mdui.css",
    "package/mdui.global.js": "mdui.global.js",
}


def project_root():
    return Path(__file__).parent.absolute().parent


def mdui_dir(root=None):
    return (root or project_root()) / "static" / "vendor" / "mdui"


def is_up_to_date(dest=None):
    """检查本地文件是否存在且版本与 MDUI_VERSION 一致"""
    dest = dest or mdui_dir()
    version_file = dest / "VERSION"
    if not version_file.exists():
        return False
    if version_file.read_text(encoding="utf-8").strip() != MDUI_VERSION:
        return False
    return all((dest / name).exists() for name in FILES.values())


def download(root=None, force=False, quiet=False):
    """下载并解压 MDUI 资源到 static/vendor/mdui/，返回是否成功"""
    dest = mdui_dir(root)

    if not force and is_up_to_date(dest):
        if not quiet:
            print(f"MDUI v{MDUI_VERSION} 已就绪，跳过下载: {dest}")
        return True

    if not quiet:
        print(f"正在下载 MDUI v{MDUI_VERSION}: {TARBALL_URL}")

    try:
        with urllib.request.urlopen(TARBALL_URL, timeout=30) as resp:
            data = resp.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member, filename in FILES.items():
                try:
                    extracted = tar.extractfile(member)
                except KeyError:
                    extracted = None
                if extracted is None:
                    raise RuntimeError(f"压缩包中缺少 {member}")
                dest.mkdir(parents=True, exist_ok=True)
                (dest / filename).write_bytes(extracted.read())
        (dest / "VERSION").write_text(MDUI_VERSION + "\n", encoding="utf-8")
    except (OSError, tarfile.TarError, RuntimeError) as e:
        print(f"下载 MDUI 失败: {e}")
        if all((dest / name).exists() for name in FILES.values()):
            print("警告: 本地已存在旧版本 MDUI，将沿用现有文件（建议联网后重新构建）")
            return True
        print("本地没有可用的 MDUI 文件。请联网后重试，或手动运行:")
        print("    python packaging/fetch_mdui.py")
        return False

    if not quiet:
        total = sum((dest / n).stat().st_size for n in FILES.values())
        print(f"MDUI v{MDUI_VERSION} 已保存到 {dest}（{total / 1024:.0f} KB）")
    return True


def main():
    force = "--force" in sys.argv[1:]
    sys.exit(0 if download(force=force) else 1)


if __name__ == "__main__":
    main()

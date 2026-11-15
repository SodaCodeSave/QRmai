#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建 DaisyUI + Tailwind 样式到 static/vendor/daisyui/app.css。

样式需要 Node.js 才能编译。打包脚本（build_exe.py / build_nuitka.py）会在打包前
自动调用本模块；修改模板后本地开发时也可以手动运行：
    python packaging/build_css.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

OUTPUT_RELATIVE = Path("static") / "vendor" / "daisyui" / "app.css"


def project_root():
    return Path(__file__).parent.absolute().parent


def output_path(root=None):
    return (root or project_root()) / OUTPUT_RELATIVE


def node_available():
    """检查 Node.js 与 npm 是否可用"""
    return shutil.which("node") is not None and shutil.which("npm") is not None


def _run(args, cwd):
    """在项目根目录执行命令；Windows 下 npm 是 .cmd，需要走 cmd.exe"""
    if sys.platform == "win32":
        cmd = ["cmd", "/c"] + args
    else:
        cmd = args
    return subprocess.run(cmd, cwd=str(cwd))


def build(root=None, quiet=False):
    """安装前端依赖并构建样式，返回是否成功"""
    root = root or project_root()
    out = output_path(root)

    if not node_available():
        print("错误: 未找到 Node.js / npm，无法构建 DaisyUI 样式。")
        print("请安装 Node.js 18 或更高版本（https://nodejs.org/）后重试。")
        return False

    if not (root / "package.json").exists():
        print(f"错误: 找不到前端配置 {root / 'package.json'}")
        return False

    if not (root / "node_modules").exists():
        if not quiet:
            print("首次构建，正在安装前端依赖（npm install）...")
        result = _run(["npm", "install", "--no-audit", "--no-fund"], root)
        if result.returncode != 0:
            print("错误: npm install 失败，请检查网络或 npm 配置。")
            return False

    if not quiet:
        print("正在构建 DaisyUI 样式（npm run build:css）...")
    result = _run(["npm", "run", "build:css"], root)
    if result.returncode != 0:
        print("错误: Tailwind 构建失败，请检查 assets/app.css 与 templates/。")
        return False

    if not out.exists() or out.stat().st_size < 1000:
        print(f"错误: 构建产物缺失或异常: {out}")
        return False

    if not quiet:
        print(f"DaisyUI 样式已生成: {out}（{out.stat().st_size / 1024:.0f} KB）")
    return True


def main():
    sys.exit(0 if build() else 1)


if __name__ == "__main__":
    main()

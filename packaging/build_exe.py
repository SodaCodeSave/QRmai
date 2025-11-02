#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller打包脚本
用于将QRmai程序打包为可执行文件
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def build_executable():
    """使用PyInstaller打包可执行文件"""
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute().parent
    main_script = project_root / "main.py"
    
    # 检查主脚本是否存在
    if not main_script.exists():
        print(f"错误: 找不到主脚本 {main_script}")
        return False
    
    # 检查skin.png是否存在
    skin_exists = (project_root / "skin.png").exists()
    
    # 检查DLL文件是否存在
    libiconv_dll = project_root / "packaging" / "libiconv.dll"
    libzbar_dll = project_root / "packaging" / "libzbar-64.dll"
    dll_files_exist = libiconv_dll.exists() and libzbar_dll.exists()
    
    # 构建PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=QRmai",                    # 可执行文件名称
        "--console",                       # 保留控制台窗口
        "--onefile",                       # 打包为单个可执行文件
        "--clean",                         # 清理临时文件
        "--noconfirm",                     # 不询问确认
        "--log-level=INFO",               # 设置日志级别
        f"--distpath={project_root / 'dist'}",    # 输出目录
        f"--workpath={project_root / 'build'}",   # 构建目录
        f"--specpath={project_root}",             # spec文件目录
        "--strip",                        # 去除符号表以减小体积
    ]
    
    # 如果skin.png存在，则添加到数据文件中
    if skin_exists:
        cmd.extend(["--add-data", f"{project_root / 'skin.png'}{os.pathsep}."])
    
    # 添加templates文件夹到数据文件中
    templates_dir = project_root / "templates"
    if templates_dir.exists():
        cmd.extend(["--add-data", f"{templates_dir}{os.pathsep}templates"])
    
    # 如果DLL文件存在，则添加到数据文件中
    if dll_files_exist:
        cmd.extend(["--add-data", f"{libiconv_dll}{os.pathsep}."])
        cmd.extend(["--add-data", f"{libzbar_dll}{os.pathsep}."])
    else:
        print("警告: 未找到libiconv.dll和libzbar-64.dll文件，打包后的程序无法正常运行，请放入后重新打包")
        print("请将这些DLL文件放置在packaging目录中以确保程序正常运行")
        return False
    
    # 添加隐藏导入
    hidden_imports = [
        "pynput",
        "pygetwindow",
        "qrcode",
        "PIL",
        "mss",
        "pyzbar",
        "flask"
    ]
    
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])
    
    # 主脚本路径
    cmd.append(str(main_script))
    
    print("执行PyInstaller命令:")
    print(" ".join(cmd))
    print("\n开始打包...")
    
    try:
        # 执行PyInstaller命令
        result = subprocess.run(cmd, cwd=str(project_root), check=True)
        print("\n打包完成!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n打包失败: {e}")
        return False
    except FileNotFoundError:
        print("\n错误: 未找到PyInstaller。请确保已安装PyInstaller:")
        print("pip install pyinstaller")
        return False


def optimize_with_upx():
    """使用UPX进一步压缩可执行文件（如果可用）"""
    project_root = Path(__file__).parent.absolute().parent
    dist_dir = project_root / "dist"
    exe_file = dist_dir / "QRmai.exe"
    
    if not exe_file.exists():
        print("未找到可执行文件进行UPX压缩")
        return False
    
    # 检查UPX是否可用
    try:
        subprocess.run(["upx", "--version"], 
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("提示: UPX未安装，跳过额外压缩。安装UPX可进一步减小文件体积。")
        return False
    
    print("使用UPX压缩可执行文件...")
    try:
        subprocess.run(["upx", "--best", str(exe_file)], 
                      cwd=str(project_root), check=True)
        print("UPX压缩完成!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"UPX压缩失败: {e}")
        return False


def show_file_info():
    """显示生成的可执行文件信息"""
    project_root = Path(__file__).parent.absolute().parent
    dist_dir = project_root / "dist"
    exe_file = dist_dir / "QRmai.exe"
    
    if exe_file.exists():
        size = exe_file.stat().st_size
        print(f"\n生成的可执行文件信息:")
        print(f"路径: {exe_file}")
        print(f"大小: {size / 1024 / 1024:.2f} MB")
    else:
        print("未找到生成的可执行文件")


def cleanup():
    """清理构建过程中的临时文件"""
    project_root = Path(__file__).parent.absolute().parent
    build_dir = project_root / "build"
    spec_file = project_root / "QRmai.spec"
    
    # 删除构建目录
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"已删除构建目录: {build_dir}")
    
    # 删除spec文件
    if spec_file.exists():
        spec_file.unlink()
        print(f"已删除spec文件: {spec_file}")


def main():
    """主函数"""
    print("QRmai PyInstaller 打包脚本")
    print("=" * 40)
    
    # 检查依赖
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未安装PyInstaller")
        print("请先运行: pip install pyinstaller")
        return
    
    # 执行打包
    success = build_executable()
    
    if success:
        # UPX压缩（可选）
        optimize_with_upx()
        
        # 显示文件信息
        show_file_info()
        
        # 询问是否清理临时文件
        choice = input("\n是否删除构建过程中的临时文件? (y/N): ")
        if choice.lower() == 'y':
            cleanup()
        
        print("\n打包脚本执行完成!")
    else:
        print("\n打包过程中出现错误，请检查日志。")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller packaging script
Used to package the QRmai program as an executable
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def build_executable():
    """Use PyInstaller to package the executable"""
    # Get project root directory
    project_root = Path(__file__).parent.absolute().parent
    main_script = project_root / "main.py"

    # Check if main script exists
    if not main_script.exists():
        print(f"Error: Main script not found {main_script}")
        return False

    # Check if skin.png exists
    skin_exists = (project_root / "skin.png").exists()

    # Check if icon.png exists
    icon_exists = (project_root / "icon.png").exists()

    # ===== DLL 检测（改）=====
    packaging_dir = project_root / "packaging"
    required_dlls = ["libiconv.dll", "libzbar-64.dll"]

    if not packaging_dir.exists():
        print(f"Error: packaging directory not found: {packaging_dir}")
        return False

    missing = [n for n in required_dlls if not (packaging_dir / n).exists()]
    if missing:
        print(f"Error: Missing required DLLs: {missing}")
        print("Please place them in the packaging directory.")
        return False

    # 收集 packaging 目录下所有 DLL（含 libzbar 的依赖）
    all_dlls = sorted(packaging_dir.glob("*.dll"))
    if not all_dlls:
        print(f"Error: No DLL files found in {packaging_dir}")
        return False

    print("Found DLLs to package:")
    for dll in all_dlls:
        size_kb = dll.stat().st_size / 1024
        print(f"  - {dll.name} ({size_kb:.1f} KB)")
    # ===== DLL 检测结束 =====

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=QRmai",                    # Executable name
        "--console",                       # Keep console window
        "--onefile",                       # Package as single executable
        "--clean",                         # Clean temporary files
        "--noconfirm",                     # No confirmation prompt
        "--log-level=INFO",               # Set log level
        f"--distpath={project_root / 'dist'}",    # Output directory
        f"--workpath={project_root / 'build'}",   # Build directory
        f"--specpath={project_root}",             # Spec file directory
        # 注意: 不要用 --strip。实测外部 strip 工具会损坏 mingw DLL
        # (libiconv.dll 等), 导致冻结进程 LoadLibrary 报 WinError 998,
        # pyzbar 在启动时直接 ImportError 崩溃。
    ]

    # Add icon.png as executable icon if it exists
    if icon_exists:
        cmd.extend(["--icon", str(project_root / "icon.png")])

    # Add skin.png to data files if it exists
    if skin_exists:
        cmd.extend(["--add-data", f"{project_root / 'skin.png'}{os.pathsep}."])

    # Add templates folder to data files
    templates_dir = project_root / "templates"
    if templates_dir.exists():
        cmd.extend(["--add-data", f"{templates_dir}{os.pathsep}templates"])

    # Add version.txt to data files (required: updater reads it at runtime)
    version_file = project_root / "version.txt"
    if version_file.exists():
        cmd.extend(["--add-data", f"{version_file}{os.pathsep}."])
    else:
        print(f"Error: version file not found {version_file}")
        print("The packaged app cannot detect its own version without version.txt.")
        return False

    # Add config.json to data files
    config_file = project_root / "config.json"
    if config_file.exists():
        cmd.extend(["--add-data", f"{config_file}{os.pathsep}."])
    else:
        # If config.json doesn't exist, create a default one and add it
        print("Creating default config.json for packaging...")
        default_config = {
            "p1": [1087, 799],
            "p2": [945, 682],
            "token": "qrmai",
            "host": "0.0.0.0",
            "port": 5000,
            "qr_route": "/qrmai",
            "cache_duration": 60,
            "standalone_mode": False,
            "decode": {
                "time": 10,
                "retry_count": 10
            },
            "skin_format": "new",
            "dev_mode": False
        }

        import json
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=4)

        cmd.extend(["--add-data", f"{config_file}{os.pathsep}."])

    # ===== 打包所有 DLL（改）=====
    # 用 --add-binary 而不是 --add-data，让 PyInstaller 正确处理二进制
    for dll in all_dlls:
        cmd.extend(["--add-binary", f"{dll}{os.pathsep}."])
    # ===== DLL 打包结束 =====

    # Add hidden imports
    hidden_imports = [
        "pynput",
        "pygetwindow",
        "qrcode",
        "PIL",
        "mss",
        "pyzbar",
        "flask",
        "pywin32",
        "updater",
        "requests"
    ]

    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    # Main script path
    cmd.append(str(main_script))

    print("Executing PyInstaller command:")
    print(" ".join(cmd))
    print("\nStarting packaging...")

    try:
        # Execute PyInstaller command
        result = subprocess.run(cmd, cwd=str(project_root), check=True)
        print("\nPackaging completed!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\nPackaging failed: {e}")
        return False
    except FileNotFoundError:
        print("\nError: PyInstaller not found. Please make sure PyInstaller is installed:")
        print("pip install pyinstaller")
        return False


def optimize_with_upx():
    """Use UPX to further compress the executable (if available)"""
    project_root = Path(__file__).parent.absolute().parent
    dist_dir = project_root / "dist"
    exe_file = dist_dir / "QRmai.exe"

    if not exe_file.exists():
        print("Executable not found for UPX compression")
        return False

    # Check if UPX is available
    try:
        subprocess.run(["upx", "--version"],
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Note: UPX not installed, skipping extra compression. Installing UPX can further reduce file size.")
        return False

    print("Compressing executable with UPX...")
    try:
        subprocess.run(["upx", "--best", str(exe_file)],
                      cwd=str(project_root), check=True)
        print("UPX compression completed!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"UPX compression failed: {e}")
        return False


def show_file_info():
    """Show generated executable file information"""
    project_root = Path(__file__).parent.absolute().parent
    dist_dir = project_root / "dist"
    exe_file = dist_dir / "QRmai.exe"

    if exe_file.exists():
        size = exe_file.stat().st_size
        print(f"\nGenerated executable information:")
        print(f"Path: {exe_file}")
        print(f"Size: {size / 1024 / 1024:.2f} MB")
    else:
        print("Generated executable not found")


def cleanup():
    """Clean up temporary files from the build process"""
    project_root = Path(__file__).parent.absolute().parent
    build_dir = project_root / "build"
    spec_file = project_root / "QRmai.spec"

    # Remove build directory
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"Build directory removed: {build_dir}")

    # Remove spec file
    if spec_file.exists():
        spec_file.unlink()
        print(f"Spec file removed: {spec_file}")


def main():
    """Main function"""
    print("QRmai PyInstaller Packaging Script")
    print("=" * 40)

    # Check dependencies
    try:
        import PyInstaller
    except ImportError:
        print("Error: PyInstaller not installed")
        print("Please run: pip install pyinstaller")
        return

    # Execute packaging
    success = build_executable()

    if success:
        # UPX compression (optional)
        optimize_with_upx()

        # Show file information
        show_file_info()

        # Ask to clean up temporary files
        # Check if stdin is available (important for CI/CD environments)
        if sys.stdin.isatty():
            choice = input("\nDelete build temp files? (y/N): ")
            if choice.lower() == 'y':
                cleanup()
        else:
            # In non-interactive environments (like CI/CD), automatically clean up
            print("\nNon-interactive environment detected. Cleaning up temporary files...")
            cleanup()

        print("\nPackaging script completed!")
    else:
        print("\nPackaging failed, check logs.")


if __name__ == "__main__":
    main()
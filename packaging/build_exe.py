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

    # Check if DLL files exist
    libiconv_dll = project_root / "packaging" / "libiconv.dll"
    libzbar_dll = project_root / "packaging" / "libzbar-64.dll"
    dll_files_exist = libiconv_dll.exists() and libzbar_dll.exists()

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
        "--strip",                        # Strip symbols to reduce size
    ]

    # Add skin.png to data files if it exists
    if skin_exists:
        cmd.extend(["--add-data", f"{project_root / 'skin.png'}{os.pathsep}."])

    # Add templates folder to data files
    templates_dir = project_root / "templates"
    if templates_dir.exists():
        cmd.extend(["--add-data", f"{templates_dir}{os.pathsep}templates"])

    # Add DLL files to data files if they exist
    if dll_files_exist:
        cmd.extend(["--add-data", f"{libiconv_dll}{os.pathsep}."])
        cmd.extend(["--add-data", f"{libzbar_dll}{os.pathsep}."])
    else:
        print("Warning: libiconv.dll and libzbar-64.dll not found, the packaged program will not work properly, please place them and rebuild")
        print("Please place these DLL files in the packaging directory to ensure the program works properly")
        return False
    
    # Add hidden imports
    hidden_imports = [
        "pynput",
        "pygetwindow",
        "qrcode",
        "PIL",
        "mss",
        "pyzbar",
        "flask",
        "pywin32"
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
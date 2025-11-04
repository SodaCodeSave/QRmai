@echo off
REM QRmai Nuitka 打包脚本
REM 用于快速将QRmai程序打包为可执行文件

echo QRmai Nuitka 打包脚本
echo ================================
echo.

REM 检查Python环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到Python环境
    echo 请确保已安装Python并添加到系统PATH中
    pause
    exit /b 1
)

REM 检查Nuitka
python -m nuitka --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装Nuitka...
    pip install nuitka
    if %errorlevel% neq 0 (
        echo 错误: Nuitka安装失败
        pause
        exit /b 1
    )
)

REM 检查DLL文件
echo 检查必需的DLL文件...
if not exist "libiconv.dll" (
    echo 警告: 未找到libiconv.dll文件
    echo QRmai的二维码识别功能可能无法正常工作
    echo 请将libiconv.dll文件放置在packaging目录中
    echo.
)

if not exist "libzbar-64.dll" (
    echo 警告: 未找到libzbar-64.dll文件
    echo QRmai的二维码识别功能可能无法正常工作
    echo 请将libzbar-64.dll文件放置在packaging目录中
    echo.
)

REM 执行Nuitka打包脚本
echo 开始使用Nuitka打包...
python build_nuitka.py

if %errorlevel% equ 0 (
    echo.
    echo Nuitka打包完成!
    echo 生成的可执行文件位于项目根目录的 dist 目录中
) else (
    echo.
    echo Nuitka打包失败，请检查错误信息
)

pause
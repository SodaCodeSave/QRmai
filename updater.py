#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QRmai 自动更新模块
通过GitHub检查更新，自动下载并重启应用
感谢Qwen-3-Coder编写，AI太好用了你们知道吗
"""

import requests
import json
import os
import sys
import zipfile
import shutil
import subprocess
import time
from pathlib import Path

# 尝试解决SSL证书验证问题
try:
    import ssl
    import certifi
    import urllib3

    # 使用certifi提供的证书包
    requests.packages.urllib3.disable_warnings()
    # 创建一个使用系统证书的HTTP适配器
    http_adapter = requests.adapters.HTTPAdapter(
        pool_connections=10, pool_maxsize=10, max_retries=3
    )
except ImportError:
    pass

# GitHub仓库信息
GITHUB_REPO = "SodaCodeSave/QRmai"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}"
CURRENT_VERSION_FILE = "version.txt"  # 本地版本文件

# 创建一个全局session以复用连接
_session = None


def get_requests_session():
    """获取带有适当配置的requests session"""
    global _session
    if _session is None:
        _session = requests.Session()
        # 尝试使用certifi证书包
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            # 配置重试策略
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )

            adapter = HTTPAdapter(max_retries=retry_strategy)
            _session.mount("http://", adapter)
            _session.mount("https://", adapter)

            # 如果有certifi证书包，使用它
            try:
                import certifi

                _session.verify = certifi.where()
            except ImportError:
                pass

        except Exception as e:
            print(f"配置HTTP适配器时出错: {e}")
    return _session


def get_current_version():
    """获取当前版本"""
    if os.path.exists(CURRENT_VERSION_FILE):
        with open(CURRENT_VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    # 如果没有版本文件，从config.json中获取版本
    elif os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("version", "unknown")
        except:
            return "unknown"
    else:
        return "unknown"


def find_zip_asset(assets):
    """在assets中查找zip文件"""
    for asset in assets:
        if asset.get("name", "").endswith(".zip"):
            return asset.get("browser_download_url")
    return None


def get_latest_release():
    """获取GitHub上的最新发布版本"""
    try:
        # 使用配置好的session发送请求
        session = get_requests_session()
        response = session.get(f"{GITHUB_API_URL}/releases/latest", timeout=10)
        if response.status_code == 200:
            release_info = response.json()
            # 检查必需的字段是否存在
            if "tag_name" not in release_info:
                print("错误: GitHub API返回的数据缺少'tag_name'字段")
                return None

            # 从assets中查找zip文件下载链接
            assets = release_info.get("assets", [])
            zip_download_url = find_zip_asset(assets)

            # 如果没找到zip文件，仍然返回信息，但download_url为None
            return {
                "version": release_info["tag_name"],
                "name": release_info.get("name", release_info["tag_name"]),
                "published_at": release_info.get("published_at", ""),
                "download_url": zip_download_url,
                "assets": assets,  # 保留assets信息以供调试
                "body": release_info.get("body", ""),
            }
        else:
            print(f"获取版本信息失败: {response.status_code}")
            return None
    except requests.exceptions.SSLError as ssl_error:
        print(f"SSL证书验证失败: {str(ssl_error)}")
        print("尝试禁用SSL验证重新连接...")
        try:
            # 如果SSL验证失败，尝试禁用SSL验证重新连接
            session = get_requests_session()
            response = session.get(
                f"{GITHUB_API_URL}/releases/latest", timeout=10, verify=False
            )
            if response.status_code == 200:
                release_info = response.json()
                # 检查必需的字段是否存在
                if "tag_name" not in release_info:
                    print("错误: GitHub API返回的数据缺少'tag_name'字段")
                    return None

                # 从assets中查找zip文件下载链接
                assets = release_info.get("assets", [])
                zip_download_url = find_zip_asset(assets)

                return {
                    "version": release_info["tag_name"],
                    "name": release_info.get("name", release_info["tag_name"]),
                    "published_at": release_info.get("published_at", ""),
                    "download_url": zip_download_url,
                    "assets": assets,  # 保留assets信息以供调试
                    "body": release_info.get("body", ""),
                }
            else:
                print(f"获取版本信息失败: {response.status_code}")
                return None
        except Exception as e:
            print(f"禁用SSL验证后仍然出错: {str(e)}")
            return None
    except Exception as e:
        print(f"检查更新时出错: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


def compare_versions(v1, v2):
    """比较两个版本号，如果v1 > v2返回1，v1 < v2返回-1，相等返回0"""

    def normalize(v):
        # 移除 'v' 前缀并分割版本号
        v = v.lstrip("v")
        return [int(x) for x in v.split(".")]

    try:
        ver1 = normalize(v1)
        ver2 = normalize(v2)

        # 比较每个版本号部分
        for i in range(max(len(ver1), len(ver2))):
            part1 = ver1[i] if i < len(ver1) else 0
            part2 = ver2[i] if i < len(ver2) else 0

            if part1 > part2:
                return 1
            elif part1 < part2:
                return -1

        return 0
    except:
        # 如果版本号格式不正确，进行字符串比较作为备用
        if v1 > v2:
            return 1
        elif v1 < v2:
            return -1
        else:
            return 0


def is_new_version_available():
    """检查是否有新版本"""
    current_version = get_current_version()
    latest_release = get_latest_release()

    if not latest_release:
        return False, None

    # 使用版本比较函数
    comparison = compare_versions(latest_release["version"], current_version)

    if (
        current_version == "unknown" or comparison > 0
    ):  # 只有当最新版本大于当前版本时才认为有更新
        return True, latest_release
    else:
        return False, None


def download_with_mirror(download_url, session, timeout=30, verify=True):
    """使用原地址或镜像源下载文件"""
    # 首先尝试直接下载
    print(f"正在从原地址下载: {download_url}")
    try:
        response = session.get(
            download_url, timeout=timeout, stream=True, verify=verify
        )
        if response.status_code == 200:
            print("原地址下载成功")
            return response
        else:
            print(f"原地址下载失败: {response.status_code}")
    except Exception as e:
        print(f"原地址下载出错: {str(e)}")

    # 如果直接下载失败，尝试使用镜像源
    mirror_url = f"https://gh-proxy.com/{download_url}"
    print(f"正在尝试镜像源: {mirror_url}")
    try:
        response = session.get(mirror_url, timeout=timeout, stream=True, verify=verify)
        if response.status_code == 200:
            print("镜像源下载成功")
            return response
        else:
            print(f"镜像源下载失败: {response.status_code}")
    except Exception as e:
        print(f"镜像源下载出错: {str(e)}")

    # 额外镜像源
    extra_mirror_urls = [
        f"https://ghproxy.com/{download_url}",
        f"https://ghproxy.net/{download_url}",
        f"https://kgithub.com/{download_url}",
    ]

    for extra_mirror in extra_mirror_urls:
        print(f"正在尝试备用镜像源: {extra_mirror}")
        try:
            response = session.get(
                extra_mirror, timeout=timeout, stream=True, verify=verify
            )
            if response.status_code == 200:
                print("备用镜像源下载成功")
                return response
            else:
                print(f"备用镜像源下载失败: {response.status_code}")
        except Exception as e:
            print(f"备用镜像源下载出错: {str(e)}")
            continue

    return None


def download_and_extract_update(download_url, temp_dir="temp_update"):
    """下载并处理更新文件（zip格式）"""
    try:
        # 创建临时目录
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)

        # 下载更新文件
        print("正在下载更新...")
        session = get_requests_session()
        response = download_with_mirror(download_url, session)

        if response is None:
            raise Exception("所有下载源都失败了")

        if response.status_code != 200:
            raise Exception(f"下载失败: {response.status_code}")

        # 从Content-Disposition头部获取文件名，或从URL提取
        filename = None
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            import re

            fname = re.findall("filename=(.+)", content_disposition)
            if fname:
                filename = fname[0].strip('"')

        if not filename:
            filename = download_url.split("/")[-1]

        zip_path = os.path.join(temp_dir, filename)

        # 流式写入zip文件
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"更新包已保存到: {zip_path}")

        # 解压zip文件到临时目录
        print("正在解压更新包...")
        extract_dir = os.path.join(temp_dir, "extracted")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        print(f"更新包已解压到: {extract_dir}")
        print(f"解压内容: {os.listdir(extract_dir)}")
        return extract_dir
    except Exception as e:
        print(f"下载或处理更新时出错: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


def apply_update(update_dir):
    """应用更新（从zip提取的目录）"""
    try:
        # 检查是否为有效目录
        if not os.path.isdir(update_dir):
            print(f"更新路径不是有效目录: {update_dir}")
            return False

        # 在Windows上执行更新
        if sys.platform.startswith("win"):
            # 获取程序所在目录和主程序路径
            if getattr(sys, "frozen", False):
                app_dir = os.path.dirname(sys.executable)
            else:
                if hasattr(sys, "_MEIPASS"):
                    app_dir = os.path.dirname(sys.executable)
                else:
                    script_path = sys.argv[0] if sys.argv else "main.py"
                    script_path = os.path.abspath(script_path)
                    app_dir = os.path.dirname(script_path)

            print(f"应用目录: {app_dir}")

            # 创建替换脚本，在单独进程中执行替换操作
            script_content = f"""@echo off
chcp 65001 >nul 2>&1
cd /d "{app_dir}"
echo 正在等待当前程序关闭...
timeout /t 2 /nobreak >nul
echo 正在终止进程...
tasklist | findstr /i "main.exe QRmai.exe python.exe" >nul 2>&1
if %errorlevel% equ 0 (
    taskkill /f /im "main.exe" >nul 2>&1
    taskkill /f /im "QRmai.exe" >nul 2>&1
    taskkill /f /im "python.exe" >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo 正在复制更新文件...
copy /y "{update_dir}\\libiconv.dll" "{app_dir}\\" >nul 2>&1
copy /y "{update_dir}\\libzbar-64.dll" "{app_dir}\\" >nul 2>&1
if exist "main.exe" (
    del /f /q "main.exe" >nul 2>&1
)
copy /y "{update_dir}\\QRmai.exe" "{app_dir}\\main.exe" >nul 2>&1
if %errorlevel% equ 0 (
    echo 程序更新成功，正在启动...
    rmdir /s /q "{update_dir}" >nul 2>&1
    del "%~f0"
    start /wait "" "{app_dir}\\main.exe"
) else (
    echo 程序更新失败，请手动替换文件。
    pause
    rmdir /s /q "{update_dir}" >nul 2>&1
    del "%~f0"
)
"""

            # 将替换脚本保存到临时文件
            script_name = f"update_{int(time.time())}.bat"
            script_path = os.path.join(app_dir, script_name)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_content)

            print("正在启动更新程序...")
            subprocess.Popen(
                ["cmd", "/c", "start", "", "/wait", "cmd", "/c", script_path],
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            print("更新脚本已启动，应用程序将关闭并进行自我替换。")
            return True
        else:
            print("当前平台不支持自动更新")
            return False
    except Exception as e:
        print(f"应用更新时出错: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def update_version_file(new_version):
    """更新版本文件"""
    try:
        with open(CURRENT_VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(new_version)
        return True
    except Exception as e:
        print(f"更新版本文件时出错: {str(e)}")
        return False


def restart_application():
    """重启应用程序"""
    try:
        print("正在重启应用程序...")
        # 获取当前Python解释器路径
        python = sys.executable
        # 重启应用
        subprocess.Popen([python, "main.py"], cwd=os.getcwd())
        # 退出当前进程
        sys.exit(0)
    except Exception as e:
        print(f"重启应用时出错: {str(e)}")


def check_and_update():
    """检查并自动更新应用"""
    print("正在检查更新...")

    has_update, latest_release = is_new_version_available()

    if has_update and latest_release:
        print(f"发现新版本: {latest_release['version']}")
        print(f"更新说明: {latest_release['name']}")

        if latest_release["body"]:
            print(f"更新内容:\n{latest_release['body']}")

        # 如果有下载链接，则尝试下载更新
        if latest_release["download_url"]:
            update_dir = download_and_extract_update(latest_release["download_url"])
            if update_dir:
                if apply_update(update_dir):
                    print("程序已成功更新，应用程序将重新启动。")
                    return True
                else:
                    print("应用更新失败")
                    return False
            else:
                print("下载或处理更新失败")
                return False
        else:
            print("未找到zip下载链接")
            return False
            return False
    else:
        print("当前已是最新版本")
        return False


if __name__ == "__main__":
    # 如果直接运行此脚本，则执行检查更新
    check_and_update()

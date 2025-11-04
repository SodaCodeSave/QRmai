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
        pool_connections=10,
        pool_maxsize=10,
        max_retries=3
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
        with open(CURRENT_VERSION_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    # 如果没有版本文件，从config.json中获取版本
    elif os.path.exists('config.json'):
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('version', 'unknown')
        except:
            return 'unknown'
    else:
        return 'unknown'

def get_latest_release():
    """获取GitHub上的最新发布版本"""
    try:
        # 使用配置好的session发送请求
        session = get_requests_session()
        response = session.get(f"{GITHUB_API_URL}/releases/latest", timeout=10)
        if response.status_code == 200:
            release_info = response.json()
            # 检查必需的字段是否存在
            if 'tag_name' not in release_info:
                print("错误: GitHub API返回的数据缺少'tag_name'字段")
                return None
                
            return {
                'version': release_info['tag_name'],
                'name': release_info.get('name', release_info['tag_name']),
                'published_at': release_info.get('published_at', ''),
                'download_url': release_info.get('zipball_url') if release_info.get('assets') else None,
                'body': release_info.get('body', '')
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
            response = session.get(f"{GITHUB_API_URL}/releases/latest", timeout=10, verify=False)
            if response.status_code == 200:
                release_info = response.json()
                # 检查必需的字段是否存在
                if 'tag_name' not in release_info:
                    print("错误: GitHub API返回的数据缺少'tag_name'字段")
                    return None
                    
                return {
                    'version': release_info['tag_name'],
                    'name': release_info.get('name', release_info['tag_name']),
                    'published_at': release_info.get('published_at', ''),
                    'download_url': release_info.get('zipball_url') if release_info.get('assets') else None,
                    'body': release_info.get('body', '')
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

def is_new_version_available():
    """检查是否有新版本"""
    current_version = get_current_version()
    latest_release = get_latest_release()
    
    if not latest_release:
        return False, None
    
    current = current_version.lstrip('v')
    latest = latest_release['version'].lstrip('v')
    
    if current_version == 'unknown' or latest != current:
        return True, latest_release
    else:
        return False, None

def download_and_extract_update(download_url, temp_dir="temp_update"):
    """下载并处理更新文件（支持exe和zip格式）"""
    try:
        # 创建临时目录
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        # 下载更新文件
        print("正在下载更新...")
        try:
            session = get_requests_session()
            response = session.get(download_url, timeout=30)
        except requests.exceptions.SSLError as ssl_error:
            print(f"SSL证书验证失败: {str(ssl_error)}")
            print("尝试禁用SSL验证重新连接...")
            # 如果SSL验证失败，尝试禁用SSL验证重新连接
            session = get_requests_session()
            response = session.get(download_url, timeout=30, verify=False)
            
        if response.status_code != 200:
            raise Exception(f"下载失败: {response.status_code}")
        
        # 根据文件扩展名确定处理方式
        if download_url.endswith('.exe'):
            # 处理exe文件 (QRmai-{打包器}-windows-{版本号}.exe)
            print("检测到exe格式更新文件...")
            # 从URL中提取文件名
            filename = download_url.split('/')[-1]
            file_path = os.path.join(temp_dir, filename)
            
            # 保存exe文件
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            print(f"更新文件已保存到: {file_path}")
            # 对于exe文件，返回文件路径而不是解压目录
            return file_path
        else:
            # 处理原有的zip文件格式
            print("检测到zip格式更新文件...")
            # 保存到临时文件
            zip_path = os.path.join(temp_dir, "update.zip")
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            
            # 解压文件
            print("正在解压更新文件...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # 获取解压后的目录名（通常是一个带哈希值的目录）
            extracted_dirs = [d for d in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, d)) and d != "__MACOSX"]
            if not extracted_dirs:
                raise Exception("解压失败，未找到更新文件")
            
            extracted_dir = os.path.join(temp_dir, extracted_dirs[0])
            return extracted_dir
    except Exception as e:
        print(f"下载或处理更新时出错: {str(e)}")
        return None

def apply_update(update_path):
    """应用更新文件（支持exe和目录两种格式）"""
    try:
        # 检查是exe文件还是目录
        if os.path.isfile(update_path) and update_path.endswith('.exe'):
            # 处理exe文件 - 直接替换当前exe程序
            print("正在替换当前exe程序...")
            print(f"更新文件路径: {update_path}")
            
            # 在Windows上直接替换当前exe文件
            if sys.platform.startswith('win'):
                # 获取当前运行的exe文件路径
                current_exe = sys.executable
                print(f"当前exe文件路径: {current_exe}")
                
                # 创建替换脚本，在单独进程中执行替换操作
                # 这样可以避免在文件被占用时无法替换的问题
                script_content = f'''
@echo off
echo 等待应用程序关闭...
timeout /t 2 /nobreak >nul
echo 正在替换程序文件...
copy "{update_path}" "{current_exe}"
if %errorlevel% equ 0 (
    echo 程序更新成功!
) else (
    echo 程序更新失败!
)
del "%~f0"
"{current_exe}"
'''
                
                # 将替换脚本保存到临时文件
                script_path = os.path.join(os.path.dirname(current_exe), "update_script.bat")
                with open(script_path, 'w') as f:
                    f.write(script_content)
                
                # 启动替换脚本并退出当前进程
                subprocess.Popen([script_path], shell=True, close_fds=True)
                print("更新脚本已启动，应用程序将关闭并进行自我替换。")
                return True
            else:
                print("当前平台不支持exe更新文件")
                return False
        elif os.path.isdir(update_path):
            # 处理原有的目录格式（zip解压后的目录）
            print("正在应用更新...")
            # 获取当前目录下的所有文件和文件夹
            current_files = set(os.listdir('.'))
            
            # 获取解压目录下的所有文件和文件夹（排除.git等隐藏文件）
            update_files = set(os.listdir(update_path))
            update_files = {f for f in update_files if not f.startswith('.') and f != 'README.md'}
            
            # 复制更新文件（保留配置文件）
            protected_files = {'config.json', 'skin.png', 'version.txt'}
            
            for item in update_files:
                src = os.path.join(update_path, item)
                dst = os.path.join('.', item)
                
                # 保护重要文件不被覆盖
                if item in protected_files and os.path.exists(dst):
                    print(f"跳过保护文件: {item}")
                    continue
                
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    print(f"更新文件: {item}")
                elif os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    print(f"更新目录: {item}")
            
            return True
        else:
            print(f"未知的更新文件类型: {update_path}")
            return False
    except Exception as e:
        print(f"应用更新时出错: {str(e)}")
        return False

def update_version_file(new_version):
    """更新版本文件"""
    try:
        with open(CURRENT_VERSION_FILE, 'w', encoding='utf-8') as f:
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
        
        if latest_release['body']:
            print(f"更新内容:\n{latest_release['body']}")
        
        # 如果有下载链接，则尝试下载更新
        if latest_release['download_url']:
            update_path = download_and_extract_update(latest_release['download_url'])
            if update_path:
                # 应用更新
                if apply_update(update_path):
                    # 检查是exe文件还是目录格式
                    if os.path.isfile(update_path) and update_path.endswith('.exe'):
                        # 对于exe文件，程序已经自我替换了，不需要额外操作
                        print("程序已成功自我替换，应用程序将重新启动。")
                        return True
                    else:
                        # 对于目录格式，需要手动更新版本文件和清理临时文件
                        # 更新版本文件
                        if update_version_file(latest_release['version']):
                            print("更新成功!")
                            # 清理临时文件
                            shutil.rmtree("temp_update", ignore_errors=True)
                            return True
                        else:
                            print("版本文件更新失败")
                else:
                    print("应用更新失败")
            else:
                print("下载或处理更新失败")
        else:
            print("未找到下载链接")
    else:
        print("当前已是最新版本")
    
    return False

if __name__ == "__main__":
    # 如果直接运行此脚本，则执行检查更新
    check_and_update()
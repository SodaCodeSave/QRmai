#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QRmai 自动更新模块

流程：
1. 从 GitHub API 获取最新 release，并与本地版本号比较
2. 下载 exe 资产（多镜像回退 + 大小/sha256/MZ 校验）
3. 生成批处理脚本：等待本进程(PID)退出 -> 备份旧 exe -> 移入新 exe -> 重新启动

打包说明：
- version.txt 由 packaging/build_exe.py 通过 --add-data 打进单文件包内，
  新 exe 自带新版本号，更新完成后无需再写任何本地版本文件。
- 所有资源读取基于 sys._MEIPASS / __file__ / sys.executable，
  不依赖当前工作目录(CWD)。
"""

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# GitHub 仓库信息
GITHUB_REPO = "SodaCodeSave/QRmai"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}"

VERSION_FILENAME = "version.txt"
UPDATE_TEMP_PREFIX = "qrmai_update"
LEGACY_TEMP_DIR = "temp_update"  # 旧版 updater 遗留目录名，仅用于清理

# 直连 GitHub 失败时的镜像前缀（已按实际可用性筛选）
MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
]

# 最近一次错误信息，供 Web 路由返回给前端
last_error = ""

_session = None


# ---------------------------------------------------------------------------
# 基础路径
# ---------------------------------------------------------------------------


def is_frozen():
    """是否为 PyInstaller 打包后的 exe"""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """资源目录：打包后为 _MEIPASS 解压目录，源码运行时为本文件所在目录"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def app_dir():
    """程序(exe)所在目录"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    if sys.argv and sys.argv[0]:
        return Path(sys.argv[0]).resolve().parent
    return Path.cwd()


# ---------------------------------------------------------------------------
# 版本号解析与比较
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-_.])?(.*)$", re.IGNORECASE)
_SUFFIX_TOKEN_RE = re.compile(r"^[0-9A-Za-z]+(?:[-_.][0-9A-Za-z]+)*$")


def _parse_version(version):
    """解析版本号，返回 (数字核心 tuple, 后缀 str)；无法解析返回 None

    示例：
        "v2.5.0-b-alpha" -> ((2, 5, 0), "b-alpha")
        "v2.4.2-1"       -> ((2, 4, 2), "1")
        md5 哈希等非法输入 -> None
    """
    if version is None:
        return None
    text = str(version).strip()
    if not text:
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None
    core = tuple(int(part) for part in match.group(1).split(".") if part != "")
    if not core:
        return None
    suffix = match.group(2).strip()
    if suffix and not _SUFFIX_TOKEN_RE.match(suffix):
        return None
    return core, suffix


def _cmp_suffix(suffix1, suffix2):
    """比较预发布/构建后缀。空后缀表示正式版，优先级最高"""
    if suffix1 == suffix2:
        return 0
    if not suffix1:
        return 1
    if not suffix2:
        return -1
    tokens1 = [t for t in re.split(r"[-_.]", suffix1) if t]
    tokens2 = [t for t in re.split(r"[-_.]", suffix2) if t]
    for token1, token2 in zip(tokens1, tokens2):
        if token1 == token2:
            continue
        num1, num2 = token1.isdigit(), token2.isdigit()
        if num1 and num2:
            value1, value2 = int(token1), int(token2)
            return (value1 > value2) - (value1 < value2)
        if num1 != num2:
            # 与 semver 一致：纯数字标识优先级低于字母标识
            return -1 if num1 else 1
        lower1, lower2 = token1.lower(), token2.lower()
        return (lower1 > lower2) - (lower1 < lower2)
    return (len(tokens1) > len(tokens2)) - (len(tokens1) < len(tokens2))


def compare_versions(v1, v2):
    """比较两个版本号：v1 > v2 返回 1，v1 < v2 返回 -1，相等返回 0"""
    parsed1 = _parse_version(v1)
    parsed2 = _parse_version(v2)
    if parsed1 is None or parsed2 is None:
        # 兜底：无法解析时退化为不区分大小写的字符串比较
        text1 = str(v1 or "").lower()
        text2 = str(v2 or "").lower()
        return (text1 > text2) - (text1 < text2)
    core1, core2 = parsed1[0], parsed2[0]
    if core1 != core2:
        return (core1 > core2) - (core1 < core2)
    return _cmp_suffix(parsed1[1], parsed2[1])


def get_current_version():
    """获取当前版本号

    优先级：
    1. 打包内置的 version.txt（_MEIPASS，源码运行时为仓库根目录）
    2. exe 同目录的 version.txt（允许用户手动覆盖）
    3. exe 同目录 config.json 中的语义化版本号（拒绝 md5 之类的哈希值）
    4. 兜底返回 0.0.0（触发更新提示，而不是像旧版那样依赖 "unknown"）
    """
    for path in (bundle_dir() / VERSION_FILENAME, app_dir() / VERSION_FILENAME):
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if _parse_version(text):
                    return text
        except OSError:
            continue

    try:
        config_path = app_dir() / "config.json"
        if config_path.is_file():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            version = str(data.get("version", ""))
            if _parse_version(version):
                return version
    except Exception:
        pass

    return "0.0.0"


# ---------------------------------------------------------------------------
# HTTP 会话
# ---------------------------------------------------------------------------


def get_requests_session():
    """获取带重试策略与证书配置的 requests session"""
    global _session
    if _session is None:
        session = requests.Session()
        try:
            retry_kwargs = dict(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            try:
                retry = Retry(allowed_methods=["GET"], **retry_kwargs)
            except TypeError:  # 旧版 urllib3
                retry = Retry(method_whitelist=["GET"], **retry_kwargs)
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        except Exception as e:
            print(f"配置HTTP适配器时出错: {e}")
        try:
            import certifi

            session.verify = certifi.where()
        except ImportError:
            pass
        _session = session
    return _session


def _cafile_candidates():
    """按顺序尝试的 CA 证书文件：certifi 与系统默认位置"""
    candidates = []
    try:
        import certifi

        candidates.append(certifi.where())
    except ImportError:
        pass
    try:
        paths = ssl.get_default_verify_paths()
        for path in (paths.cafile, paths.openssl_cafile):
            if path and os.path.isfile(path) and path not in candidates:
                candidates.append(path)
    except Exception:
        pass
    return candidates


def http_get(url, stream=False, timeout=30):
    """带多 CA 回退的 GET 请求；所有证书源都失败时抛出 SSLError"""
    session = get_requests_session()
    candidates = _cafile_candidates() or [True]
    last_error = None
    for verify in candidates:
        try:
            return session.get(url, stream=stream, timeout=timeout, verify=verify)
        except requests.exceptions.SSLError as error:
            last_error = error
    raise last_error


# ---------------------------------------------------------------------------
# 检查更新
# ---------------------------------------------------------------------------


def _sha256_from_digest(digest):
    """从 GitHub asset 的 digest 字段(sha256:xxx)提取十六进制摘要"""
    if not digest or not isinstance(digest, str):
        return None
    digest = digest.strip().lower()
    if digest.startswith("sha256:") and len(digest) == 71:
        return digest[7:]
    return None


def find_exe_asset(assets, version=None):
    """在 release assets 中挑选 exe：优先精确匹配 QRmai-<version>-win.exe"""
    exes = [
        asset
        for asset in assets or []
        if str(asset.get("name", "")).lower().endswith(".exe")
    ]
    if not exes:
        return None
    if version:
        expected = f"qrmai-{version}-win.exe".lower()
        for asset in exes:
            if asset.get("name", "").lower() == expected:
                return asset
        for asset in exes:
            if version.lower() in asset.get("name", "").lower():
                return asset
    return exes[0]


def _release_from_json(info):
    """把 GitHub release JSON 转成内部结构，缺少必要字段时抛 ValueError"""
    if not isinstance(info, dict) or "tag_name" not in info:
        raise ValueError("GitHub API返回的数据缺少'tag_name'字段")
    assets = info.get("assets") or []
    asset = find_exe_asset(assets, info["tag_name"])
    return {
        "version": info["tag_name"],
        "name": info.get("name") or info["tag_name"],
        "published_at": info.get("published_at", ""),
        "body": info.get("body", ""),
        "download_url": asset.get("browser_download_url") if asset else None,
        "download_size": asset.get("size") if asset else None,
        "download_sha256": _sha256_from_digest(asset.get("digest")) if asset else None,
        "asset_name": asset.get("name") if asset else None,
        "assets": assets,
    }


def _set_request_error(error):
    """把异常转换成面向用户的错误信息"""
    global last_error
    if isinstance(error, requests.exceptions.HTTPError):
        status = error.response.status_code if error.response is not None else None
        if status in (403, 429):
            last_error = f"GitHub API 请求受限(HTTP {status})，可能触发了频率限制，请稍后再试"
        else:
            last_error = f"获取版本信息失败(HTTP {status})"
    elif isinstance(error, requests.exceptions.RequestException):
        last_error = f"无法连接 GitHub API: {error}"
    else:
        last_error = f"检查更新失败: {error}"


def _fetch_release_json(verify=None):
    """verify=None 时自动尝试 certifi/系统证书，False 时跳过验证"""
    url = f"{GITHUB_API_URL}/releases/latest"
    if verify is None:
        response = http_get(url, timeout=10)
    else:
        response = get_requests_session().get(url, timeout=10, verify=verify)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(
            f"HTTP {response.status_code}", response=response
        )
    return response.json()


def get_latest_release():
    """获取 GitHub 最新 release；失败返回 None 并设置 last_error"""
    global last_error
    last_error = ""
    try:
        info = _fetch_release_json()
    except requests.exceptions.SSLError:
        # 证书链异常时降级重试；下载内容仍会做 sha256/MZ 校验兜底
        try:
            requests.packages.urllib3.disable_warnings()
            info = _fetch_release_json(verify=False)
            print("警告: SSL证书验证失败，已降级为不验证连接（下载内容仍会校验）")
        except Exception as error:
            _set_request_error(error)
            return None
    except Exception as error:
        _set_request_error(error)
        return None

    try:
        return _release_from_json(info)
    except Exception as error:
        last_error = f"版本信息格式异常: {error}"
        return None


def is_new_version_available():
    """检查是否有新版本，返回 (has_update, release)"""
    current_version = get_current_version()
    latest_release = get_latest_release()
    if not latest_release:
        return False, None
    if compare_versions(latest_release["version"], current_version) > 0:
        return True, latest_release
    return False, None


# ---------------------------------------------------------------------------
# 下载与校验
# ---------------------------------------------------------------------------


def _mirror_candidates(download_url):
    return [download_url] + [prefix + download_url for prefix in MIRRORS]


def _download_label(url):
    try:
        return url.split("/")[2]
    except IndexError:
        return url


def _filename_from_response(response, url):
    """从 Content-Disposition 或 URL 提取安全的文件名"""
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", disposition, re.IGNORECASE)
    if not match:
        match = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
    else:
        from urllib.parse import urlsplit

        name = urlsplit(url).path.rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return name or "update.exe"


def download_update(
    download_url, dest_dir, expected_size=None, expected_sha256=None, timeout=60
):
    """下载 exe 并校验，返回保存路径；全部源失败时抛 RuntimeError

    校验项：
    - 文件名必须以 .exe 结尾（防止镜像返回 HTML 错误页）
    - 有 sha256 时强校验（来自 GitHub API 的 asset digest）
    - 有 size 时校验字节数
    - 文件头必须是 PE 的 MZ 魔数
    - 证书链无法验证时，只有在存在 sha256 的前提下才允许降级为不验证连接
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    errors = []

    for url in _mirror_candidates(download_url):
        label = _download_label(url)
        path = None
        try:
            try:
                response = http_get(url, stream=True, timeout=timeout)
            except requests.exceptions.SSLError:
                if not expected_sha256:
                    errors.append(f"{label}: SSL证书验证失败且无sha256，拒绝不安全下载")
                    continue
                print(f"警告: {label} SSL证书验证失败，降级为不验证连接（将强制sha256校验）")
                requests.packages.urllib3.disable_warnings()
                response = get_requests_session().get(
                    url, timeout=timeout, stream=True, verify=False
                )
            if response.status_code != 200:
                errors.append(f"{label}: HTTP {response.status_code}")
                continue

            filename = _filename_from_response(response, url)
            if not filename.lower().endswith(".exe"):
                errors.append(f"{label}: 拒绝非exe文件({filename})")
                continue

            path = dest_dir / filename
            sha256 = hashlib.sha256()
            total = 0
            with open(path, "wb") as file_obj:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        file_obj.write(chunk)
                        sha256.update(chunk)
                        total += len(chunk)

            with open(path, "rb") as file_obj:
                magic = file_obj.read(2)
            if magic != b"MZ":
                errors.append(f"{label}: 不是有效的exe文件(缺少MZ头)")
                path.unlink(missing_ok=True)
                continue
            if expected_size is not None and total != expected_size:
                errors.append(f"{label}: 文件大小不符({total} != {expected_size})")
                path.unlink(missing_ok=True)
                continue
            if expected_sha256 and sha256.hexdigest().lower() != expected_sha256.lower():
                errors.append(f"{label}: sha256校验失败")
                path.unlink(missing_ok=True)
                continue

            print(f"下载成功({label}): {path} ({total} 字节)")
            return str(path)
        except Exception as error:
            errors.append(f"{label}: {error}")
            if path is not None:
                Path(path).unlink(missing_ok=True)

    raise RuntimeError("所有下载源均失败: " + "; ".join(errors))


# ---------------------------------------------------------------------------
# 自替换
# ---------------------------------------------------------------------------


def build_update_script(new_exe, target_exe, pid, launch=True, log_file=None):
    """生成自我替换的批处理内容（纯 ASCII，避免代码页/乱码问题）

    脚本职责：
    1. 轮询等待 pid 退出（不 taskkill，更不碰 python.exe；
       用 ping 计时而不是 timeout —— timeout 在 stdin 被重定向时会直接中止脚本）
    2. 旧 exe 备份为 .bak
    3. 新 exe 移动到原 exe 路径（失败则回滚 .bak）
    4. 重新启动新 exe

    注意：bat 不自删除（cmd 在文件被删除后继续读取会报
    “找不到批处理文件”并返回 1），由 cleanup_after_update 在下次启动时清理。
    """
    new_exe = str(Path(new_exe).resolve())
    target_exe = str(Path(target_exe).resolve())
    pid = int(pid)
    log_file = str(log_file) if log_file else str(Path(tempfile.gettempdir()) / "qrmai_update.log")

    lines = [
        "@echo off",
        "setlocal",
        'set "NEW=' + new_exe + '"',
        'set "TGT=' + target_exe + '"',
        'set "LOG=' + log_file + '"',
        'echo [%date% %time%] update start pid=' + str(pid) + ' new=%NEW% tgt=%TGT% >> "%LOG%"',
        "echo QRmai update: waiting for the current program to exit...",
        "set /a WAITED=0",
        ":wait",
        'tasklist /FI "PID eq ' + str(pid) + '" | findstr /C:"' + str(pid) + '" >nul',
        "if errorlevel 1 goto replacing",
        "set /a WAITED=%WAITED%+1",
        "if %WAITED% GEQ 600 goto wait_timeout",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":wait_timeout",
        'echo [%date% %time%] timeout waiting for pid ' + str(pid) + ' >> "%LOG%"',
        "echo QRmai update: timed out waiting for the current program to exit.",
        "echo The new file was not applied. Press any key to close...",
        "pause >nul",
        "exit /b 1",
        ":replacing",
        'echo [%date% %time%] process exited, replacing... >> "%LOG%"',
        'echo QRmai update: replacing program file...',
        'if exist "%TGT%" move /y "%TGT%" "%TGT%.bak" >nul',
        'move /y "%NEW%" "%TGT%" >nul',
        "if errorlevel 1 goto rollback",
        'echo [%date% %time%] starting new exe >> "%LOG%"',
    ]
    if launch:
        lines.append('start "" "%TGT%"')
    lines += [
        'del /f /q "%TGT%.bak" >nul 2>&1',
        'exit /b 0',
        ":rollback",
        'echo [%date% %time%] move failed, rolling back >> "%LOG%"',
        "echo QRmai update: replace failed, the old version was restored.",
        "echo See update.log. Press any key to close...",
        'if exist "%TGT%.bak" move /y "%TGT%.bak" "%TGT%" >nul',
        "pause >nul",
        "exit /b 1",
    ]
    return "\n".join(lines) + "\n"


def apply_update(update_path):
    """用新 exe 替换当前正在运行的程序（仅打包后的 exe 支持）"""
    global last_error
    update_path = Path(update_path)
    if not update_path.is_file() or update_path.suffix.lower() != ".exe":
        last_error = f"更新文件不是exe: {update_path}"
        print(last_error)
        return False

    if not is_frozen():
        last_error = "当前以源码方式运行，请手动替换程序文件"
        print(last_error + f"（新文件已下载到 {update_path}）")
        return False

    if not sys.platform.startswith("win"):
        last_error = "当前平台不支持自动替换"
        print(last_error)
        return False

    target_exe = Path(sys.executable).resolve()
    pid = os.getpid()
    work_dir = Path(tempfile.gettempdir()) / f"{UPDATE_TEMP_PREFIX}_{pid}"
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        last_error = f"无法创建更新临时目录: {error}"
        print(last_error)
        return False

    log_file = work_dir / "update.log"
    script_path = work_dir / "update.bat"
    script_content = build_update_script(
        update_path, target_exe, pid, launch=True, log_file=log_file
    )
    try:
        # bat 要求 ASCII，用 ascii 编码写出，彻底避免 BOM/代码页问题
        script_path.write_text(script_content, encoding="ascii", errors="replace")
        subprocess.Popen(
            ["cmd", "/c", str(script_path)],
            cwd=str(work_dir),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as error:
        last_error = f"启动更新脚本失败: {error}"
        print(last_error)
        return False

    print(f"更新脚本已启动，等待本进程(PID {pid})退出后替换 {target_exe}")
    print("程序将在 2 秒后退出以完成更新...")
    threading.Thread(target=_delayed_exit, args=(2.0,), daemon=True).start()
    return True


def _delayed_exit(delay=2.0):
    """给 HTTP 响应留出发送时间后强制退出，让更新脚本接管替换"""
    time.sleep(delay)
    os._exit(0)


def cleanup_after_update():
    """程序启动时清理更新残留（备份文件、临时目录），失败静默"""
    if is_frozen():
        target = Path(sys.executable).resolve()
        for stale in (Path(str(target) + ".bak"),):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
    for legacy in (Path.cwd() / LEGACY_TEMP_DIR, app_dir() / LEGACY_TEMP_DIR):
        if legacy.is_dir():
            shutil.rmtree(legacy, ignore_errors=True)
    try:
        for stale_dir in Path(tempfile.gettempdir()).glob(f"{UPDATE_TEMP_PREFIX}_*"):
            shutil.rmtree(stale_dir, ignore_errors=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 编排入口
# ---------------------------------------------------------------------------


def check_and_update():
    """检查并执行更新

    返回值：
        "updated"   已启动自我替换（本进程随后退出）
        "no_update" 当前已是最新版本
        "failed"    下载/替换失败（详见 last_error）
        "error"     无法获取版本信息（详见 last_error）
    """
    global last_error
    print("正在检查更新...")
    has_update, latest_release = is_new_version_available()
    if last_error:
        print(f"检查更新失败: {last_error}")
        return "error"
    if not has_update or not latest_release:
        print("当前已是最新版本")
        return "no_update"

    print(f"发现新版本: {latest_release['version']}")
    print(f"更新名称: {latest_release['name']}")
    if latest_release.get("body"):
        print(f"更新内容:\n{latest_release['body']}")

    if not latest_release.get("download_url"):
        last_error = "该版本没有可下载的exe资产"
        print(last_error)
        return "failed"

    print(f"找到exe下载链接: {latest_release['download_url']}")
    dest_dir = Path(tempfile.gettempdir()) / f"{UPDATE_TEMP_PREFIX}_{os.getpid()}"
    try:
        update_path = download_update(
            latest_release["download_url"],
            dest_dir,
            expected_size=latest_release.get("download_size"),
            expected_sha256=latest_release.get("download_sha256"),
        )
    except Exception as error:
        last_error = str(error)
        print(f"下载更新失败: {error}")
        return "failed"

    if apply_update(update_path):
        print("更新脚本已接管，程序将自动替换并重启。")
        return "updated"
    print(f"应用更新失败: {last_error}")
    return "failed"


if __name__ == "__main__":
    status = check_and_update()
    if status in ("failed", "error"):
        sys.exit(1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updater 模块测试（无第三方测试框架依赖，直接 `python tests/test_updater.py` 运行）"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import updater  # noqa: E402

PASSED = []


def ok(name):
    PASSED.append(name)
    print(f"  [PASS] {name}")


def test_compare_versions():
    cases = [
        ("v2.4.3", "v2.4.2", 1),
        ("v2.4.2", "v2.4.3", -1),
        ("v2.4.2", "v2.4.2", 0),
        ("2.4.2", "v2.4.2", 0),
        ("v2.4.10", "v2.4.9", 1),  # 旧版字符串比较会判错
        ("v10.0.0", "v9.0.0", 1),
        ("v2.4.2-1", "v2.4.2-2", -1),
        ("v2.4.2-2", "v2.4.2-1", 1),
        ("v2.5.0-b-alpha", "v2.5.0-a-alpha", 1),
        ("v2.5.0-a-alpha", "v2.5.0-b-alpha", -1),
        ("v2.5.0-a-alpha", "v2.5.0", -1),  # 预发布 < 正式版
        ("v2.5.0", "v2.5.0-b-alpha", 1),
        ("v2.4.3-fix-1", "v2.4.10", -1),  # 后缀不能压过数字核心
        ("v2.4.3-fix-1", "v2.4.3-fix-1", 0),
        ("v2.5.0-b-alpha", "v2.5.0-b-alpha", 0),
    ]
    for v1, v2, expected in cases:
        actual = updater.compare_versions(v1, v2)
        assert actual == expected, f"compare_versions({v1!r}, {v2!r}) = {actual}, 期望 {expected}"
    ok(f"compare_versions {len(cases)} 组用例")


def test_parse_version_rejects_garbage():
    for bad in [None, "", "bfa024453fb5c7281d3948401446e7cb", "unknown", "latest", "vabc"]:
        assert updater._parse_version(bad) is None, f"应拒绝 {bad!r}"
    assert updater._parse_version("v2.5.0-b-alpha") == ((2, 5, 0), "b-alpha")
    assert updater._parse_version("v2.10.0") == ((2, 10, 0), "")
    ok("_parse_version 解析与拒绝 md5/垃圾值")


def test_get_current_version_dev_and_frozen():
    # 源码模式：读仓库根目录的 version.txt
    on_disk = (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip()
    assert updater.get_current_version() == on_disk, "源码模式应读到 version.txt"
    ok(f"get_current_version 源码模式 = {on_disk}")

    # 模拟冻结模式：version.txt 打包在 _MEIPASS
    fake_meipass = tempfile.mkdtemp(prefix="qrmai_fake_meipass_")
    try:
        (Path(fake_meipass) / "version.txt").write_text("v9.9.9\n", encoding="utf-8")
        sys._MEIPASS = fake_meipass
        try:
            assert updater.get_current_version() == "v9.9.9"
        finally:
            del sys._MEIPASS
        ok("get_current_version 冻结模式读 _MEIPASS/version.txt")
    finally:
        shutil.rmtree(fake_meipass, ignore_errors=True)

    # config.json 里的 md5 版本号必须被拒绝，回退到 0.0.0
    fake_dir = tempfile.mkdtemp(prefix="qrmai_fake_appdir_")
    real_bundle, real_app = updater.bundle_dir, updater.app_dir
    try:
        (Path(fake_dir) / "config.json").write_text(
            json.dumps({"version": "bfa024453fb5c7281d3948401446e7cb"}),
            encoding="utf-8",
        )
        updater.bundle_dir = lambda: Path(fake_dir)
        updater.app_dir = lambda: Path(fake_dir)
        assert updater.get_current_version() == "0.0.0", "md5 版本号不能当版本用"
        # 语义化版本号则接受
        (Path(fake_dir) / "config.json").write_text(
            json.dumps({"version": "v1.2.3"}), encoding="utf-8"
        )
        assert updater.get_current_version() == "v1.2.3"
        ok("get_current_version 拒绝 md5、接受语义化 config 版本")
    finally:
        updater.bundle_dir, updater.app_dir = real_bundle, real_app
        shutil.rmtree(fake_dir, ignore_errors=True)


def test_is_new_version_available():
    real_current = updater.get_current_version
    real_latest = updater.get_latest_release
    try:
        updater.get_current_version = lambda: "v2.5.0-b-alpha"
        updater.get_latest_release = lambda: {"version": "v2.4.2-1"}
        has_update, _ = updater.is_new_version_available()
        assert has_update is False, "本地版本更新时不应提示更新（旧版会恒 True）"

        updater.get_latest_release = lambda: {"version": "v2.6.0"}
        has_update, _ = updater.is_new_version_available()
        assert has_update is True

        updater.get_current_version = lambda: "0.0.0"  # 读不到版本的老 exe
        updater.get_latest_release = lambda: {"version": "v2.4.2-1"}
        has_update, _ = updater.is_new_version_available()
        assert has_update is True, "读不到版本时应提示更新"
        ok("is_new_version_available 不再恒 True")
    finally:
        updater.get_current_version, updater.get_latest_release = real_current, real_latest


def test_find_exe_asset():
    assets = [
        {"name": "notes.txt"},
        {"name": "QRmai-1.0.0-setup.exe"},
        {"name": "QRmai-v2.4.2-1-win.exe"},
    ]
    asset = updater.find_exe_asset(assets, "v2.4.2-1")
    assert asset["name"] == "QRmai-v2.4.2-1-win.exe", "应按版本号精确匹配"
    assert updater.find_exe_asset(assets)["name"] == "QRmai-1.0.0-setup.exe"
    assert updater.find_exe_asset([{"name": "a.txt"}]) is None
    assert updater._sha256_from_digest("sha256:" + "ab" * 32) == "ab" * 32
    assert updater._sha256_from_digest("md5:xyz") is None
    ok("find_exe_asset / sha256 digest 解析")


def _start_file_server(directory):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    def handler(*args, **kwargs):
        return QuietHandler(*args, directory=str(directory), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_download_and_verify():
    serve_dir = Path(tempfile.mkdtemp(prefix="qrmai_dl_"))
    real_mirrors = updater.MIRRORS
    updater.MIRRORS = []
    server = None
    try:
        exe_bytes = b"MZ" + os.urandom(4096)
        (serve_dir / "QRmai-v9.9.9-win.exe").write_bytes(exe_bytes)
        (serve_dir / "error.exe").write_bytes(b"<html>404 not found</html>")
        server, base = _start_file_server(serve_dir)
        dest = Path(tempfile.mkdtemp(prefix="qrmai_dldest_"))
        sha256 = hashlib.sha256(exe_bytes).hexdigest()

        # 正常下载 + sha256 校验
        path = updater.download_update(
            f"{base}/QRmai-v9.9.9-win.exe",
            dest,
            expected_size=len(exe_bytes),
            expected_sha256=sha256,
        )
        assert Path(path).read_bytes() == exe_bytes
        ok("download_update 成功下载并通过 size+sha256 校验")

        # sha256 不符必须失败
        try:
            updater.download_update(
                f"{base}/QRmai-v9.9.9-win.exe", dest / "bad1", expected_sha256="00" * 32
            )
        except RuntimeError as error:
            assert "sha256" in str(error)
        else:
            raise AssertionError("sha256 不符时必须拒绝")
        ok("download_update 拒绝 sha256 不符的文件")

        # 大小不符必须失败
        try:
            updater.download_update(
                f"{base}/QRmai-v9.9.9-win.exe", dest / "bad2", expected_size=1
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("size 不符时必须拒绝")
        ok("download_update 拒绝大小不符的文件")

        # 镜像返回 HTML 错误页必须失败（MZ 魔数检查）
        try:
            updater.download_update(f"{base}/error.exe", dest / "bad3")
        except RuntimeError as error:
            assert "MZ" in str(error), str(error)
        else:
            raise AssertionError("HTML 内容必须被拒绝")
        ok("download_update 拒绝非 PE 文件(HTML错误页)")
    finally:
        updater.MIRRORS = real_mirrors
        if server:
            server.shutdown()
        shutil.rmtree(serve_dir, ignore_errors=True)


def test_ssl_fallback_requires_sha256():
    """证书链验证失败时：有 sha256 才允许降级，否则拒绝下载"""
    import requests

    serve_dir = Path(tempfile.mkdtemp(prefix="qrmai_ssl_"))
    real_mirrors, real_http_get = updater.MIRRORS, updater.http_get
    updater.MIRRORS = []
    server = None
    try:
        exe_bytes = b"MZ" + os.urandom(1024)
        name = "QRmai-v8.8.8-win.exe"
        (serve_dir / name).write_bytes(exe_bytes)
        server, base = _start_file_server(serve_dir)
        sha256 = hashlib.sha256(exe_bytes).hexdigest()

        def force_ssl_error(*args, **kwargs):
            raise requests.exceptions.SSLError("forced certificate failure")

        updater.http_get = force_ssl_error
        dest = Path(tempfile.mkdtemp(prefix="qrmai_ssldest_"))

        try:
            updater.download_update(f"{base}/{name}", dest / "noshA")
        except RuntimeError as error:
            assert "sha256" in str(error) or "SSL" in str(error), str(error)
        else:
            raise AssertionError("无 sha256 时必须拒绝不安全下载")
        ok("SSL降级：无 sha256 时拒绝下载")

        path = updater.download_update(
            f"{base}/{name}", dest / "withsha", expected_sha256=sha256
        )
        assert Path(path).read_bytes() == exe_bytes
        ok("SSL降级：有 sha256 时允许并强制校验")
    finally:
        updater.MIRRORS, updater.http_get = real_mirrors, real_http_get
        if server:
            server.shutdown()
        shutil.rmtree(serve_dir, ignore_errors=True)


def test_build_update_script():
    content = updater.build_update_script(
        r"C:\Temp\new exe.exe", r"C:\Program Files\QRmai\QRmai.exe", 4321,
        launch=True, log_file=r"C:\Temp\update.log",
    )
    content.encode("ascii")  # 必须是纯 ASCII，避免 bat 代码页乱码
    assert "taskkill" not in content.lower(), "不允许 taskkill"
    assert "python.exe" not in content.lower(), "不允许杀 python.exe"
    assert "timeout /t" not in content.lower(), "timeout 在 stdin 重定向时会中止脚本"
    assert "ping -n 2" in content, "必须用 ping 计时"
    assert 'PID eq 4321' in content
    assert 'set "NEW=C:\\Temp\\new exe.exe"' in content
    assert 'set "TGT=C:\\Program Files\\QRmai\\QRmai.exe"' in content
    assert 'start "" "%TGT%"' in content
    assert '"%TGT%.bak"' in content
    assert "pause" in content, "失败分支要停下来提示用户"

    no_launch = updater.build_update_script("a.exe", "b.exe", 1, launch=False)
    assert 'start ""' not in no_launch
    assert no_launch.encode("ascii")
    ok("build_update_script 纯ASCII、无taskkill/timeout、含PID等待与回滚")


def test_apply_update_refuses_in_dev_mode():
    fake = Path(tempfile.mkdtemp(prefix="qrmai_apply_")) / "QRmai-v9-win.exe"
    fake.write_bytes(b"MZ")
    updater.last_error = ""
    assert updater.apply_update(fake) is False, "源码模式不允许自动替换"
    assert "源码" in updater.last_error
    ok("apply_update 源码模式安全拒绝")


def test_bat_replaces_file_e2e():
    """真实跑一遍 bat：等 PID 退出 -> 替换文件 -> 删除自身"""
    work = Path(tempfile.mkdtemp(prefix="qrmai_bat_"))
    try:
        old_exe = work / "app.exe"
        new_exe = work / "download.exe"
        old_exe.write_bytes(b"OLD")
        new_exe.write_bytes(b"NEW")
        log_file = work / "update.log"

        # 模拟正在运行的程序（bat 要等它退出）
        victim = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        script_path = work / "update.bat"
        script_path.write_text(
            updater.build_update_script(
                new_exe, old_exe, victim.pid, launch=False, log_file=log_file
            ),
            encoding="ascii",
        )

        bat = subprocess.Popen(
            ["cmd", "/c", str(script_path)], cwd=str(work),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(1.5)          # bat 进入等待循环
        victim.terminate()       # 模拟主进程退出
        out, err = bat.communicate(timeout=40)
        assert bat.returncode == 0, f"bat 返回 {bat.returncode}: {out!r} {err!r}"

        assert old_exe.read_bytes() == b"NEW", "旧文件必须被新文件替换"
        assert not new_exe.exists(), "新文件应已被移动走"
        assert not Path(str(old_exe) + ".bak").exists(), "备份应被清理"
        assert "update start" in log_file.read_text(encoding="ascii", errors="replace")
        ok("bat 端到端替换：PID等待 -> 替换 -> 清理备份")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_check_and_update_orchestration():
    """伪造 GitHub 响应，验证 check_and_update 全链路（下载+校验到 apply 前一环）"""
    serve_dir = Path(tempfile.mkdtemp(prefix="qrmai_flow_"))
    real_mirrors, real_latest = updater.MIRRORS, updater.get_latest_release
    updater.MIRRORS = []
    server = None
    try:
        exe_bytes = b"MZ" + os.urandom(2048)
        asset_name = "QRmai-v9.9.9-win.exe"
        (serve_dir / asset_name).write_bytes(exe_bytes)
        server, base = _start_file_server(serve_dir)
        updater.get_latest_release = lambda: {
            "version": "v9.9.9",
            "name": "v9.9.9",
            "published_at": "",
            "body": "",
            "download_url": f"{base}/{asset_name}",
            "download_size": len(exe_bytes),
            "download_sha256": hashlib.sha256(exe_bytes).hexdigest(),
            "asset_name": asset_name,
            "assets": [],
        }
        updater.last_error = ""
        status = updater.check_and_update()
        # 源码模式下走到 apply_update 被拒绝，说明下载与校验环节全部通过
        assert status == "failed", f"期望 failed, 实际 {status}"
        assert "源码" in updater.last_error, updater.last_error
        ok("check_and_update 下载/校验链路（止步于源码模式拒绝替换）")

        # 无更新时返回 no_update
        updater.get_latest_release = lambda: {"version": "v0.0.1"}
        updater.last_error = ""
        assert updater.check_and_update() == "no_update"
        ok("check_and_update 无更新返回 no_update")

        # API 不可达时返回 error 并带上错误信息
        def boom():
            updater.last_error = "无法连接 GitHub API: timeout"
            return None

        updater.get_latest_release = boom
        updater.last_error = ""
        assert updater.check_and_update() == "error"
        assert updater.last_error
        ok("check_and_update API失败返回 error（不再谎报最新版本）")
    finally:
        updater.MIRRORS, updater.get_latest_release = real_mirrors, real_latest
        if server:
            server.shutdown()
        shutil.rmtree(serve_dir, ignore_errors=True)


def test_cleanup_after_update():
    stale = Path(tempfile.gettempdir()) / f"{updater.UPDATE_TEMP_PREFIX}_999999"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "update.bat").write_text("@echo off", encoding="ascii")
    legacy = Path.cwd() / updater.LEGACY_TEMP_DIR
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old.exe").write_bytes(b"x")
    try:
        updater.cleanup_after_update()  # 不应抛异常
        assert not stale.exists(), "应清理更新临时目录"
        assert not legacy.exists(), "应清理旧版遗留的 temp_update 目录"
        ok("cleanup_after_update 清理临时/遗留目录")
    finally:
        shutil.rmtree(stale, ignore_errors=True)
        shutil.rmtree(legacy, ignore_errors=True)


def test_live_github_api():
    """真实调用 GitHub API（离线环境自动跳过）"""
    release = updater.get_latest_release()
    if release is None:
        print(f"  [SKIP] 真实 API 测试（{updater.last_error}）")
        return
    assert release["version"], "版本号不能为空"
    updater._parse_version(release["version"])
    ok(f"真实 GitHub API 最新版本 = {release['version']}, "
       f"asset = {release.get('asset_name')}, sha256 = {bool(release.get('download_sha256'))}")


def main():
    tests = [
        test_compare_versions,
        test_parse_version_rejects_garbage,
        test_get_current_version_dev_and_frozen,
        test_is_new_version_available,
        test_find_exe_asset,
        test_download_and_verify,
        test_ssl_fallback_requires_sha256,
        test_build_update_script,
        test_apply_update_refuses_in_dev_mode,
        test_bat_replaces_file_e2e,
        test_check_and_update_orchestration,
        test_cleanup_after_update,
        test_live_github_api,
    ]
    for test in tests:
        print(f"== {test.__name__} ==")
        test()
    print(f"\n全部通过: {len(PASSED)} 项")


if __name__ == "__main__":
    main()

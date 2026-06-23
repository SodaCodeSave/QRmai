#!/usr/bin/env python3
"""
QRmai 主入口 — 平台检测 + 服务启动
"""

import os
import sys
import json
import time
import hashlib

from qrmai.shared import (
    IS_LINUX,
    IS_WINDOWS,
    config,
    config_path,
    logger,
    resource_path,
    ensure_config_completeness,
    get_default_config,
)

# =============================================================================
# 平台分派：加载对应平台的 qrmai_action
# =============================================================================
if IS_WINDOWS:
    from qrmai.windows import qrmai_action
elif IS_LINUX:
    from qrmai.linux import qrmai_action, linux_setup, linux_shutdown
else:
    raise RuntimeError(f"不支持的操作系统: {sys.platform}")


# =============================================================================
# 程序入口点
# =============================================================================
def main():
    """QRmai 主入口：加载配置、初始化 server 并启动 Flask"""
    # 保存 / 补全配置文件
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config_from_file = json.load(f)
        config_merged = ensure_config_completeness(config_from_file)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_merged, f, ensure_ascii=False, indent=4)
        config.update(config_merged)
    else:
        default_cfg = get_default_config()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, ensure_ascii=False, indent=4)
        config.update(default_cfg)

    # 计算配置版本（用于会话安全校验）
    try:
        config["version"] = hashlib.md5(
            (config["token"] + str(os.path.getmtime(config_path))).encode()
        ).hexdigest()
    except FileNotFoundError:
        config["version"] = hashlib.md5(
            (config["token"] + str(time.time())).encode()
        ).hexdigest()

    # 初始化 server 模块，注入依赖
    from qrmai import server

    # 注入平台对应的截图函数
    if IS_LINUX:
        from qrmai.linux import linux_capture_screen as capture_screen
    else:
        from qrmai.windows import windows_capture_screen as capture_screen

    template_folder = resource_path("templates")
    server.init(qrmai_action, capture_screen, config, logger, template_folder)

    # =========================================================================
    # Linux: 启动时初始化劫持环境并启动微信
    # =========================================================================
    if IS_LINUX:
        linux_setup()  # pyright: ignore[reportPossiblyUnboundVariable]

    # 根据配置动态注册二维码路由
    qr_route = config.get("qr_route", "/qrmai")
    server.app.add_url_rule(qr_route, "qrmai", server.qrmai)

    # 启动Flask应用
    from webbrowser import open as open_webbrowser

    if config["host"] != "0.0.0.0":
        open_webbrowser(f"http://{config['host']}:{config['port']}/login")
    else:
        open_webbrowser(f"http://localhost:{config['port']}/login")

    try:
        server.app.run(
            host=config["host"], port=config["port"], debug=config["dev_mode"]
        )
    finally:
        if IS_LINUX:
            linux_shutdown()  # pyright: ignore[reportPossiblyUnboundVariable]


if __name__ == "__main__":
    main()

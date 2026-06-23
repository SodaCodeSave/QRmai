"""
QRmai Windows 平台代码
微信窗口定位 → 自动点击 → 截图解码 → 返回二维码
"""

import time
import subprocess
import ctypes

import psutil
from pynput.mouse import Controller as MouseController, Button
from mss import mss
import cv2
from pyzbar.pyzbar import decode
from win32 import win32gui, win32process
import win32con

from .shared import config, logger, apply_skin_to_qr, make_error_image

# DPI 感知设置（修复 Win10 缩放下鼠标偏移）
shcore = ctypes.windll.shcore
shcore.SetProcessDpiAwareness(2)

mouse = MouseController()


# ---- 进程管理 ----


def kill_wechat_process():
    """杀死 WeChatAppEx.exe 进程（Windows）"""
    try:
        killed_any = False
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"] and "WeChatAppEx.exe" in proc.info["name"]:
                proc.kill()
                logger.info(f"已杀死微信进程，PID: {proc.info['pid']}")
                killed_any = True
        if not killed_any:
            logger.info("未找到可杀死的WeChatAppEx.exe进程")
    except psutil.NoSuchProcess:
        logger.info("微信进程已终止")
    except psutil.AccessDenied:
        logger.warning("尝试杀死微信进程时访问被拒绝 - 可能需要提升权限")
    except Exception as e:
        logger.error(f"杀死微信进程时出错: {e}")
        try:
            subprocess.run(
                ["taskkill", "/f", "/im", "WeChatAppEx.exe"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=True,
            )
            logger.info("使用taskkill命令杀死微信进程")
        except subprocess.CalledProcessError:
            logger.warning("使用taskkill命令杀死微信进程失败")


# ---- 微信窗口定位 ----


def find_wechat_window_by_process():
    """通过查找 Weixin.exe 进程来获取微信窗口句柄"""

    def enum_windows_callback(hwnd, windows):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process = psutil.Process(pid)
            if process.name() and "Weixin.exe" in process.name():
                windows.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)
    return windows[0] if windows else None


# ---- 鼠标操作 ----


def _win_move_click(x, y):
    """Windows 下鼠标移动并点击"""
    mouse.position = (x, y)
    mouse.click(Button.left, 1)


# ---- Windows 屏幕截图（供 OpenCV 视觉识别使用） ----


def windows_capture_screen(monitor: int = 1):
    """
    Windows 全屏截图，返回 BGR 格式的 numpy 数组（OpenCV 原生格式）。

    Args:
        monitor: mss 监视器编号，1 = 主显示器

    Returns:
        BGR 图像 (H, W, 3) uint8
    """
    import numpy as np

    with mss() as sct:
        region = sct.monitors[monitor]
        sct_img = sct.grab(region)
        bgra = np.array(sct_img, dtype=np.uint8)
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return bgr


# ---- 核心二维码获取 ----


def windows_qrmai_action():
    """
    Windows 版二维码获取：
    1. 定位微信窗口 → 2. 自动点击获取二维码 → 3. 截图解码 → 4. 叠加皮肤返回
    5. 恢复鼠标到操作前位置
    """
    wechat_hwnd = find_wechat_window_by_process()
    if not wechat_hwnd:
        logger.warning("未找到Weixin.exe进程的窗口")
        kill_wechat_process()
        return make_error_image("Window\nnot found")

    # ── 保存操作前鼠标位置 ──
    orig_pos = mouse.position
    logger.info(f"[Windows] 已保存鼠标位置: {orig_pos}")

    try:
        activation_success = False
        for attempt in range(3):
            try:
                win32gui.ShowWindow(wechat_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(wechat_hwnd)
                win32gui.SetWindowPos(
                    wechat_hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
                activation_success = True
                break
            except Exception as e:
                logger.warning(f"第 {attempt + 1} 次尝试激活窗口失败: {e}")
                time.sleep(1)

        if not activation_success:
            logger.warning("无法激活微信窗口，将继续执行后续操作")

        # 点击 p1（生成二维码按钮位置）
        _win_move_click(config["p1"][0], config["p1"][1])
        time.sleep(2)

        # 点击 p2（二维码消息位置）
        _win_move_click(config["p2"][0], config["p2"][1])

        decoded_objects = None

        try:
            time.sleep(0.2)
            win32gui.ShowWindow(wechat_hwnd, win32con.SW_MINIMIZE)
        except Exception:
            pass

        for i in range(config["decode"]["retry_count"]):
            time.sleep(config["decode"]["time"] / config["decode"]["retry_count"])

            bgr = windows_capture_screen()
            image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            decoded_objects = decode(image)

            if decoded_objects and len(decoded_objects) > 0:
                break
            else:
                if i == config["decode"]["retry_count"] - 1:
                    kill_wechat_process()
                    return make_error_image("Unable\nto load\nQRCode\n(Timeout)")
                logger.info(
                    f"二维码解码失败 过{config['decode']['time'] / config['decode']['retry_count']}s后重试 "
                    f"({i + 1}/{config['decode']['retry_count']})"
                )

        qr_data = decoded_objects[0].data.decode("utf-8")
        result = apply_skin_to_qr(qr_data)
        kill_wechat_process()
        return result
    finally:
        # ── 恢复鼠标到操作前位置 ──
        try:
            mouse.position = orig_pos
            logger.info(f"[Windows] 鼠标已还原到 {orig_pos}")
        except Exception as e:
            logger.warning(f"[Windows] 鼠标还原失败: {e}")


# 统一入口
qrmai_action = windows_qrmai_action

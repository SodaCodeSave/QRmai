"""
QRmai Linux 平台代码
hacked-wechat 劫持环境 + Wayland/uinput 鼠标操控
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import psutil
from PIL import Image
from pyzbar.pyzbar import decode

from .shared import apply_skin_to_qr, config, logger, make_error_image

# Linux 微信可执行文件路径（可从配置覆盖）
WECHAT_BIN = config.get("wechat_bin", "/opt/wechat/wechat")


# =============================================================================
# Linux 鼠标控制（Wayland 优先 → uinput 回退）
# =============================================================================


def _is_wayland_session():
    """检测当前是否运行在 Wayland 会话下"""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


def _is_kde_gnome_wayland():
    """检测当前是否在 KDE 或 GNOME 的 Wayland 环境下

    wayland_automation 依赖 wlroots 的 zwlr_virtual_pointer_manager_v1 协议，
    而 KDE (KWin) 和 GNOME (Mutter) 使用各自专属的虚拟输入协议，
    无法兼容 wayland_automation，因此需要提前检测并回退到 uinput。
    """
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        or os.environ.get("XDG_SESSION_DESKTOP", "")
        or os.environ.get("DESKTOP_SESSION", "")
    )
    desktop_lower = desktop.lower()

    if "kde" in desktop_lower:
        return True
    if "gnome" in desktop_lower:
        return True
    if os.environ.get("KDE_FULL_SESSION", "").lower() == "true":
        return True

    return False


class LinuxMouse:
    """Linux 鼠标操控

    优先级：Wayland（zwlr_virtual_pointer_manager_v1）→ uinput（evdev 内核级）
    Wayland 下使用 wayland_automation 库，通过 Wayland 协议直接发送绝对坐标；
    非 Wayland（X11）下回退到 uinput 相对移动。
    """

    def __init__(self):
        self._wayland_mouse = None  # wayland_automation Mouse 实例
        self._ui = None  # evdev UInput 实例
        self._is_wayland = False
        self._last_x = 0
        self._last_y = 0

        # ── Wayland 路径（wlroots 系合成器：Sway, Hyprland, River 等）──
        if _is_wayland_session() and not _is_kde_gnome_wayland():
            try:
                from wayland_automation.mouse_controller import Mouse as WaylandMouse

                self._wayland_mouse = WaylandMouse()
                self._is_wayland = True
                logger.info(
                    "已初始化 Wayland 虚拟指针（zwlr_virtual_pointer_manager_v1）"
                )
                return
            except ImportError:
                logger.warning("wayland_automation 未安装，回退到 uinput")
            except Exception as e:
                logger.warning(f"Wayland 虚拟指针初始化失败（{e}），回退到 uinput")
        elif _is_kde_gnome_wayland():
            logger.info(
                "检测到 %s Wayland 环境，wayland_automation 不支持该合成器，使用 uinput",
                os.environ.get("XDG_CURRENT_DESKTOP", "未知桌面环境"),
            )

        # ── uinput 回退路径 ──
        try:
            from evdev import UInput
            from evdev import ecodes as ev_ecodes

            self._ev_ecodes = ev_ecodes
            self._ui = UInput(
                {
                    ev_ecodes.EV_KEY: [
                        ev_ecodes.BTN_LEFT,
                        ev_ecodes.BTN_RIGHT,
                    ],
                    ev_ecodes.EV_REL: [
                        ev_ecodes.REL_X,
                        ev_ecodes.REL_Y,
                    ],
                },
                name="qrmai-virtual-mouse",
            )
            logger.info("已初始化 uinput 虚拟鼠标设备（内核级操控）")
        except ImportError:
            logger.error(
                "evdev 库未安装，无法进行 Linux 鼠标操控。"
                "请安装 evdev: uv pip install evdev"
            )
            raise RuntimeError("evdev 库未安装，Linux 鼠标操控不可用")
        except Exception as e:
            logger.error(f"初始化 uinput 失败: {e}")
            raise RuntimeError(f"初始化 uinput 失败: {e}")

    def move_to(self, x: int, y: int):
        """将鼠标移动到屏幕绝对坐标"""
        self._last_x = x
        self._last_y = y

        if self._is_wayland and self._wayland_mouse:
            # Wayland: motion_absolute 直接支持绝对坐标
            self._wayland_mouse.click(x, y, button=None)
            time.sleep(0.02)
        elif self._ui:
            # uinput: 相对移动，先复位再移动到目标
            ev_ecodes = self._ev_ecodes
            self._ui.write(ev_ecodes.EV_REL, ev_ecodes.REL_X, -32767)
            self._ui.write(ev_ecodes.EV_REL, ev_ecodes.REL_Y, -32767)
            self._ui.write(ev_ecodes.EV_SYN, ev_ecodes.SYN_REPORT, 0)
            time.sleep(0.1)
            if x != 0:
                self._ui.write(ev_ecodes.EV_REL, ev_ecodes.REL_X, x)
            if y != 0:
                self._ui.write(ev_ecodes.EV_REL, ev_ecodes.REL_Y, y)
            self._ui.write(ev_ecodes.EV_SYN, ev_ecodes.SYN_REPORT, 0)
            time.sleep(0.05)
        else:
            logger.error("鼠标设备未初始化，无法移动鼠标")

    def click(self):
        """在当前鼠标位置执行左键点击"""
        if self._is_wayland and self._wayland_mouse:
            self._wayland_mouse.click(self._last_x, self._last_y, "left")
        elif self._ui:
            ev_ecodes = self._ev_ecodes
            self._ui.write(ev_ecodes.EV_KEY, ev_ecodes.BTN_LEFT, 1)
            self._ui.write(ev_ecodes.EV_SYN, ev_ecodes.SYN_REPORT, 0)
            time.sleep(0.05)
            self._ui.write(ev_ecodes.EV_KEY, ev_ecodes.BTN_LEFT, 0)
            self._ui.write(ev_ecodes.EV_SYN, ev_ecodes.SYN_REPORT, 0)
        else:
            logger.error("鼠标设备未初始化，无法点击")

    def move_click(self, x: int, y: int, delay: float = 0.1):
        """移动鼠标到 (x, y) 并点击

        Args:
            delay: 移动完成后等 delay 秒再点击（默认 0.1s）。
        """
        if self._is_wayland and self._wayland_mouse:
            self._wayland_mouse.click(x, y, button=None)
            self._last_x = x
            self._last_y = y
            time.sleep(delay)
            self._wayland_mouse.click(x, y, "left")
        else:
            self.move_to(x, y)
            time.sleep(delay)
            self.click()

    def close(self):
        """关闭鼠标设备"""
        if self._wayland_mouse:
            try:
                if hasattr(self._wayland_mouse, "sock") and self._wayland_mouse.sock:
                    self._wayland_mouse.sock.close()
            except Exception:
                pass
        if self._ui:
            try:
                self._ui.close()
            except Exception:
                pass


_linux_mouse = None


def _get_linux_mouse():
    """获取 LinuxMouse 全局单例（延迟初始化）"""
    global _linux_mouse
    if _linux_mouse is None:
        _linux_mouse = LinuxMouse()
    return _linux_mouse


# =============================================================================
# Linux 进程管理
# =============================================================================


def linux_kill_wechat_process():
    """杀死 Linux 下的微信进程（不包括 WeChatEx 内置浏览器进程）"""
    killed_any = False
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = proc.info["name"] or ""
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "wechat" in name.lower() or "wechat" in cmdline.lower():
                proc.kill()
                logger.info(f"已杀死微信进程，PID: {proc.info['pid']}")
                killed_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if not killed_any:
        logger.info("未找到可杀死的微信进程")


# =============================================================================
# hacked-wechat 核心逻辑
# =============================================================================


def _setup_fake_xdg_open(fake_bin_dir: Path, fifo_path: Path):
    """在工作目录内动态创建伪装的 xdg-open 脚本，拦截 HTTP(S) 链接写入 FIFO"""
    try:
        fake_bin_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"无法创建伪装 xdg-open 目录 {fake_bin_dir}: {e}")
        raise RuntimeError(f"无法创建伪装目录: {e}") from e

    xdg_open_path = fake_bin_dir / "xdg-open"

    script_content = f"""#!/bin/bash
URL="$1"
if [[ "$URL" =~ ^https?://wq\\.wahlap\\.net/qrcode/req/MAID[0-9A-Fa-f]+\\.html ]]; then
    echo "$URL" > "{fifo_path}"
    exit 0
else
    unset BROWSER
    exec /usr/bin/xdg-open "$@"
fi
"""
    try:
        xdg_open_path.write_text(script_content, encoding="utf-8")
    except OSError as e:
        logger.error(f"无法写入伪装 xdg-open 脚本 {xdg_open_path}: {e}")
        raise RuntimeError(f"无法写入 xdg-open 脚本: {e}") from e

    try:
        xdg_open_path.chmod(0o755)
    except OSError as e:
        logger.error(f"无法设置 xdg-open 可执行权限 {xdg_open_path}: {e}")
        raise RuntimeError(f"无法设置 xdg-open 权限: {e}") from e

    logger.info(f"已创建伪装的 xdg-open: {xdg_open_path}")


# =============================================================================
# URL 获取与二维码解码
# =============================================================================


def _fetch_url_and_decode_qr(url: str) -> str:
    """
    访问微信打开的链接，解析 HTML，下载 MAID 开头的二维码图像，
    使用 pyzbar 解码后返回二维码数据字符串。
    """
    http_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        )
    }

    logger.info(f"[Linux] 正在请求页面: {url[:80]}...")

    req = urllib.request.Request(
        url,
        headers=http_headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法访问链接: {e}")
    except Exception as e:
        raise RuntimeError(f"请求页面时出错: {e}")

    # 解析 HTML，提取 MAID 开头的图片 src
    match = re.search(
        r'<img\s+[^>]*src="([^"]*MAID[^"]*\.png[^"]*)"', html, re.IGNORECASE
    )
    if not match:
        # 回退：匹配任意 img 标签的 src
        match = re.search(r'<img\s+[^>]*src="([^"]+)"', html, re.IGNORECASE)

    if not match:
        raise RuntimeError("HTML 中未找到二维码图片链接")

    img_src = match.group(1)
    img_url = urljoin(url, img_src)
    logger.info(f"[Linux] 二维码图片链接: {img_url[:80]}...")

    # 下载二维码图片
    img_req = urllib.request.Request(
        img_url,
        headers=http_headers,
    )

    try:
        with urllib.request.urlopen(img_req, timeout=15) as resp:
            img_data = resp.read()
    except Exception as e:
        raise RuntimeError(f"下载二维码图片失败: {e}")

    # 使用 pyzbar 解码
    try:
        image = Image.open(BytesIO(img_data))
    except Exception as e:
        raise RuntimeError(f"无法打开下载的图片: {e}")

    decoded_objects = decode(image)

    if not decoded_objects or len(decoded_objects) == 0:
        raise RuntimeError("无法从下载的图片中解码二维码")

    qr_data = decoded_objects[0].data.decode("utf-8")
    logger.info(f"[Linux] 二维码解码成功: {qr_data[:50]}...")
    return qr_data


# =============================================================================
# 持久化劫持环境（启动时创建，全程复用）
# =============================================================================

_hacked_temp_dir = None
_hacked_fake_bin_dir = None
_hacked_fifo_path = None
_hacked_stop_event = threading.Event()
_url_queue = queue.Queue()
_wechat_proc = None
_wechat_recovered = False  # 标记是否从崩溃中恢复的微信进程

_STATE_FILE = Path(tempfile.gettempdir()) / "qrmai_state.json"


def _is_wechat_alive():
    """检查 _wechat_proc 是否仍在运行

    兼容 subprocess.Popen（首次启动）和 psutil.Process（崩溃恢复）两种类型。
    """
    global _wechat_proc
    if _wechat_proc is None:
        return False
    # 首次启动时 _wechat_proc 是 subprocess.Popen
    if isinstance(_wechat_proc, subprocess.Popen):
        return _wechat_proc.poll() is None
    # 崩溃恢复时 _wechat_proc 是 psutil.Process
    try:
        return _wechat_proc.is_running()
    except psutil.NoSuchProcess:
        return False


def _save_state():
    """保存当前劫持环境状态，用于崩溃后恢复"""
    if _wechat_proc is None or _hacked_temp_dir is None:
        return
    state = {
        "wechat_pid": _wechat_proc.pid,
        "temp_dir": str(_hacked_temp_dir),
        "fifo_path": str(_hacked_fifo_path),
        "fake_bin_dir": str(_hacked_fake_bin_dir),
    }
    try:
        _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        logger.info(f"[Linux] 已保存劫持环境状态 → {_STATE_FILE}")
    except Exception as e:
        logger.warning(f"[Linux] 保存状态文件失败: {e}")


def _try_recover_state():
    """
    尝试从上次崩溃中恢复劫持环境。
    返回 True 表示恢复成功（无需重新创建环境），False 表示需要新建。
    """
    global _hacked_temp_dir, _hacked_fake_bin_dir, _hacked_fifo_path, _wechat_proc
    global _wechat_recovered

    if not _STATE_FILE.exists():
        return False

    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False

    pid = state.get("wechat_pid")
    temp_dir = state.get("temp_dir")
    fifo_path = state.get("fifo_path")
    fake_bin_dir = state.get("fake_bin_dir")

    if not all([pid, temp_dir, fifo_path, fake_bin_dir]):
        return False

    # 检查微信进程是否仍在运行
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            logger.info("[Linux] 上次的微信进程已退出，将创建新的劫持环境")
            _STATE_FILE.unlink(missing_ok=True)
            return False
    except psutil.NoSuchProcess:
        logger.info("[Linux] 上次的微信进程不存在，将创建新的劫持环境")
        _STATE_FILE.unlink(missing_ok=True)
        return False

    # 检查 FIFO 和伪装的 xdg-open 是否还存在
    temp_path = Path(temp_dir)
    fifo = Path(fifo_path)
    fake_bin = Path(fake_bin_dir) / "xdg-open"

    if not temp_path.exists() or not fifo.exists() or not fake_bin.exists():
        logger.warning("[Linux] 上次的劫持环境文件不完整，将重建")
        _STATE_FILE.unlink(missing_ok=True)
        shutil.rmtree(str(temp_path), ignore_errors=True)
        return False

    # 恢复成功：复用已有环境
    _hacked_temp_dir = temp_path
    _hacked_fake_bin_dir = Path(fake_bin_dir)
    _hacked_fifo_path = fifo
    _wechat_proc = proc
    _wechat_recovered = True

    logger.info(f"[Linux] ♻ 已恢复劫持环境:")
    logger.info(f"        微信 PID: {pid}")
    logger.info(f"        临时目录: {_hacked_temp_dir}")
    logger.info(f"        FIFO:     {_hacked_fifo_path}")

    return True


def _setup_hacked_environment():
    """
    创建持久化的劫持环境：FIFO 管道 + 伪装的 xdg-open + 后台监听线程。
    如果检测到上次崩溃残留的有效环境，自动恢复复用。
    """
    global _hacked_temp_dir, _hacked_fake_bin_dir, _hacked_fifo_path

    # 尝试从崩溃中恢复
    if _try_recover_state():
        # 恢复成功，只需启动监听线程
        pass
    else:
        # 创建全新的劫持环境
        _hacked_temp_dir = Path(tempfile.mkdtemp(prefix="qrmai_"))
        _hacked_fake_bin_dir = _hacked_temp_dir / ".local_bin"
        _hacked_fifo_path = _hacked_temp_dir / ".link_pipe"

        os.mkfifo(_hacked_fifo_path)
        logger.info(f"[Linux] 已创建持久 FIFO: {_hacked_fifo_path}")

        _setup_fake_xdg_open(_hacked_fake_bin_dir, _hacked_fifo_path)

    def _persistent_listener(fifo_path):
        """持续从 FIFO 读取 URL，放入队列供多次请求消费"""
        logger.info("[Linux] 持久链接监听线程已启动")
        while not _hacked_stop_event.is_set() and fifo_path.exists():
            try:
                with open(fifo_path, "r", encoding="utf-8") as fifo:
                    for line in fifo:
                        if _hacked_stop_event.is_set():
                            break
                        url_string = line.strip()
                        if url_string:
                            logger.info(f"[Linux] 截获链接: {url_string}")
                            _url_queue.put(url_string)
            except (OSError, FileNotFoundError, ValueError):
                break
        logger.info("[Linux] 持久链接监听线程已退出")

    if _hacked_fifo_path is not None:
        listener = threading.Thread(
            target=_persistent_listener, args=(_hacked_fifo_path,), daemon=True
        )
        listener.start()
    else:
        logger.error("[Linux] FIFO 路径为空，监听线程无法启动")


def _find_existing_wechat():
    """查找已有微信进程，返回 psutil.Process 或 None"""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = proc.info["name"] or ""
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "wechat" in name.lower() or "wechat" in cmdline.lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def _launch_wechat_hacked():
    """以劫持环境启动微信（dbus-run-session + 伪装 PATH）"""
    global _wechat_proc

    env = os.environ.copy()
    env["PATH"] = f"{_hacked_fake_bin_dir}:{env.get('PATH', '')}"

    logger.info(f"[Linux] 正在启动微信: dbus-run-session {WECHAT_BIN}")
    # start_new_session=True → fork + setsid()，将微信进程放入独立的
    # 进程组和会话中，使其脱离 QRmai 进程树，脚本退出时不会被系统连带杀死。
    _wechat_proc = subprocess.Popen(
        ["dbus-run-session", WECHAT_BIN],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # 保存状态以便崩溃后恢复
    _save_state()


def _ensure_wechat_running():
    """
    确保微信在劫持环境下运行：
    - 已从崩溃恢复 → 跳过，直接使用
    - 无微信进程 → 启动
    - 已有微信进程 → 询问用户是否重启
    """
    global _wechat_recovered

    # 如果是从崩溃中恢复的微信进程，直接使用
    if _wechat_recovered:
        logger.info("[Linux] 使用从崩溃中恢复的微信进程，无需重启")
        return

    existing = _find_existing_wechat()

    if existing:
        logger.warning(f"检测到已有微信进程运行中 (PID: {existing.info['pid']})")
        print("")
        print("=" * 55)
        print("  ⚠️  检测到微信已在运行")
        print("  如果微信不是在 QRmai 劫持环境下启动的，")
        print("  二维码获取功能将无法正常工作。")
        print("=" * 55)

        if sys.stdin.isatty():
            answer = input("  是否重启微信以配合 QRmai？[y/N] ").strip().lower()
        else:
            logger.warning("非交互模式，将不重启现有微信进程")
            answer = "n"

        if answer == "y":
            logger.info("正在终止现有微信进程...")
            existing.kill()
            try:
                existing.wait(timeout=5)
            except psutil.TimeoutExpired:
                pass
            linux_kill_wechat_process()
            time.sleep(1)
        else:
            logger.warning(
                "请确保当前微信进程在 QRmai 劫持环境下启动，否则二维码获取可能失败。"
            )
            return

    _launch_wechat_hacked()


def _cleanup_hacked_environment(keep=False):
    """清理持久化劫持环境（程序退出时调用）

    Args:
        keep: 如果为 True，保留微信进程、临时目录和状态文件，
              以便下次启动时通过 _try_recover_state() 自动链接。
    """
    global _wechat_proc
    _hacked_stop_event.set()

    if keep:
        # 保留模式：更新状态文件、不杀进程、不删目录
        logger.info("[Linux] 保留 hacked-wechat 环境以供下次启动复用")
        _save_state()
        return

    # ── 完整清理模式 ──
    # 删除状态文件，避免下次启动误恢复已退出进程的残留
    _STATE_FILE.unlink(missing_ok=True)

    if _is_wechat_alive():
        # ── 微信仍在运行 ──
        logger.info("[Linux] 正在终止微信进程...")
        _wechat_proc.terminate()
        try:
            _wechat_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _wechat_proc.kill()
        except psutil.TimeoutExpired:
            _wechat_proc.kill()

    # 额外确保所有微信进程都被终止（处理 dbus-run-session 退出但
    # 微信进程幸存的情况）
    linux_kill_wechat_process()

    if _hacked_temp_dir is not None:
        try:
            shutil.rmtree(_hacked_temp_dir, ignore_errors=True)
            logger.info("[Linux] 已清理劫持环境临时目录")
        except Exception:
            pass


def linux_shutdown():
    """Linux 退出时调用：询问用户是否保留 hacked-wechat 环境

    由 main.py 在 server.app.run() 的 finally 块中调用，
    确保在 Flask 正常退出后执行用户交互。
    """
    print("")
    print("=" * 55)
    print("  QRmai 正在退出...")
    print("=" * 55)

    if sys.stdin.isatty():
        answer = (
            input(
                "  是否保留 hacked-wechat 环境以便下次启动自动链接？\n"
                "  （保留后微信将继续运行，下次启动 QRmai 时将自动复用）[y/N] "
            )
            .strip()
            .lower()
        )
    else:
        logger.info("[Linux] 非交互模式，将完整清理劫持环境")
        answer = "n"

    if answer == "y":
        _cleanup_hacked_environment(keep=True)
        logger.info("[Linux] hacked-wechat 环境已保留，下次启动时将自动链接")
        print("  ✅ hacked-wechat 环境已保留，下次启动将自动链接")
    else:
        _cleanup_hacked_environment(keep=False)
        logger.info("[Linux] 劫持环境已完全清理")


# =============================================================================
# Linux 版 qrmai_action
# =============================================================================


def linux_qrmai_action():
    """
    Linux 版二维码获取：
    1. 保存鼠标位置 → 获取鼠标实例，确认微信在运行
    2. 点击 p1（微信二维码按钮）→ 等待 → 点击 p2（二维码消息）
       （p2 点击触发 xdg-open → FIFO → URL 入队）
    3. 从队列取出链接 → 访问页面 → 解析 MAID 图片 → pyzbar 解码
    4. 叠加皮肤 → 返回二维码图像
    5. 恢复鼠标到操作前位置
    """
    timeout = config.get("wechat_url_timeout", 30)

    # ── 保存操作前鼠标位置 ──
    orig_x, orig_y = 0, 0
    try:
        if _is_wayland_session():
            from wayland_automation import mouse_position_generator

            gen = mouse_position_generator(interval=0.05)
            try:
                pos = next(gen)
                if pos:
                    orig_x, orig_y = pos
                    logger.info(f"[Linux] 已保存鼠标位置: ({orig_x}, {orig_y})")
            finally:
                gen.close()
        else:
            from pynput.mouse import Controller as PynputMouse

            pos = PynputMouse().position
            orig_x, orig_y = pos
            logger.info(f"[Linux] 已保存鼠标位置: ({orig_x}, {orig_y})")
    except Exception as e:
        logger.warning(f"[Linux] 无法获取鼠标位置 ({e})，操作后不会还原")

    # 检查微信是否仍在运行
    if _wechat_proc is not None and not _is_wechat_alive():
        logger.warning("[Linux] 微信进程已退出，正在重新启动...")
        _launch_wechat_hacked()
        time.sleep(3)  # 等微信窗口就绪

    # 清空队列中可能残留的旧 URL
    while not _url_queue.empty():
        try:
            _url_queue.get_nowait()
        except queue.Empty:
            break

    # 获取鼠标实例并执行点击
    mouse = _get_linux_mouse()

    # 点击 p1（生成二维码按钮位置）
    logger.info(f"[Linux] 点击 p1 ({config['p1']}) 生成二维码")
    mouse.move_click(config["p1"][0], config["p1"][1])
    time.sleep(2)

    # 点击 p2（二维码消息位置 → 触发 xdg-open 将 URL 写入 FIFO）
    # 微信对点击不敏感，若半秒内未获取到链接则补点一次
    url = None
    for attempt in range(2):
        logger.info(
            f"[Linux] 点击 p2 ({config['p2']}) 打开链接"
            + (f" (第{attempt + 1}次)" if attempt > 0 else "")
        )
        mouse.move_click(config["p2"][0], config["p2"][1], delay=0)
        mouse.move_click(config["p2"][0], config["p2"][1], delay=0)
        try:
            url = _url_queue.get(timeout=1 if attempt == 0 else timeout)
            break
        except queue.Empty:
            if attempt == 0:
                logger.info("[Linux] 未获取到链接，半秒后重试点击 p2")

    try:
        if url is None:
            logger.error(f"[Linux] 等待微信链接超时 ({timeout}s)")
            return make_error_image(f"Waiting for\nWeChat link\ntimed out ({timeout}s)")

        logger.info(f"[Linux] 从队列取出链接: {url[:80]}...")
        qr_data = _fetch_url_and_decode_qr(url)
        return apply_skin_to_qr(qr_data)
    except Exception as e:
        logger.error(f"[Linux] 二维码获取失败: {e}")
        return make_error_image(str(e))
    finally:
        # ── 恢复鼠标到操作前位置 ──
        if orig_x != 0 or orig_y != 0:
            try:
                mouse.move_to(orig_x, orig_y)
                logger.info(f"[Linux] 鼠标已还原到 ({orig_x}, {orig_y})")
            except Exception as e:
                logger.warning(f"[Linux] 鼠标还原失败: {e}")


# 统一入口
qrmai_action = linux_qrmai_action


# =============================================================================
# Linux 屏幕截图（供 OpenCV 视觉识别使用）
# =============================================================================


def linux_capture_screen() -> "np.ndarray":
    """
    Linux 全屏截图，返回 BGR 格式的 numpy 数组（OpenCV 原生格式）。

    - Wayland → grim 命令
    - X11    → mss 库

    Returns:
        BGR 图像 (H, W, 3) uint8
    """
    import numpy as np

    if _is_wayland_session():
        return _capture_screen_grim()
    else:
        return _capture_screen_mss()


def _capture_screen_grim() -> "np.ndarray":
    """
    使用 grim 命令截图（Wayland 环境）。
    grim 是 wlroots-based Wayland 合成器的标准截图工具。

    Returns:
        BGR 图像 (H, W, 3) uint8
    """
    import cv2
    import numpy as np

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="qrmai_grim_")
        os.close(fd)

        subprocess.run(
            ["grim", tmp_path],
            check=True,
            timeout=10,
            capture_output=True,
        )

        img = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("cv2.imread 返回 None，截图文件可能为空或损坏")

        logger.debug(f"[Linux] grim 截图成功: {img.shape[1]}x{img.shape[0]}")
        return img

    except FileNotFoundError:
        raise RuntimeError(
            "未找到 grim 命令，请安装: sudo apt install grim  (Debian/Ubuntu) "
            "或 sudo pacman -S grim  (Arch)"
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode().strip() if e.stderr else ""
        raise RuntimeError(f"grim 截图失败 (code={e.returncode}): {stderr}")
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _capture_screen_mss(monitor: int = 1) -> "np.ndarray":
    """
    使用 mss 库截图（X11 环境）。

    Args:
        monitor: mss 监视器编号，1 = 主显示器

    Returns:
        BGR 图像 (H, W, 3) uint8
    """
    import cv2
    import numpy as np
    from mss import mss

    with mss() as sct:
        region = sct.monitors[monitor]
        sct_img = sct.grab(region)
        bgra = np.array(sct_img, dtype=np.uint8)
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return bgr


# =============================================================================
# 初始化辅助（供 main.py 调用）
# =============================================================================


def linux_setup():
    """Linux 启动时的初始化：建立劫持环境 + 启动微信

    退出清理由 main.py 通过 try/finally 调用 linux_shutdown() 完成，
    不再使用 atexit，以便在退出前与用户交互（是否保留 hacked-wechat）。
    """
    logger.info("[Linux] 正在初始化劫持环境...")
    _setup_hacked_environment()
    _ensure_wechat_running()
    logger.info("[Linux] 劫持环境初始化完成")

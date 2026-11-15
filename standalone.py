"""舞萌丨中二公众号独立窗口的自动位置识别

独立窗口模式（config.json 中的 standalone_mode）下，程序不再依赖屏幕绝对坐标 p1/p2：

1. 按窗口标题找到「舞萌 | 中二」公众号的独立窗口；
2. 在窗口截图底部找到导航栏，定位「玩家二维码」标签的中心；
3. 点击后用 zbar 尝试解码；二维码缩略图太小时，先在截图里定位这个「黑白方块」
   并点击放大，再从放大后的画面解码。位置全部相对窗口计算，窗口移动、缩放或
   更换分辨率后都无需重新配置。
"""

import ctypes
import logging
import subprocess
import time
from ctypes import wintypes

import psutil
from PIL import Image, ImageChops, ImageFilter, ImageStat
from mss import mss
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button, Controller as MouseController
from pyzbar.pyzbar import decode

try:
    from win32 import win32gui, win32process
    import win32con

    HAS_WIN32 = True
except ImportError:  # 允许在非 Windows 环境下单独测试图像识别逻辑
    HAS_WIN32 = False

logger = logging.getLogger(__name__)

# 独立窗口标题中包含的关键字（窗口标题形如「舞萌 | 中二」）
WINDOW_KEYWORDS = ("舞萌", "中二")

# 亮度与导航栏背景色相差多少视为「有内容」
INK_DELTA = 18
# 分隔线：整行几乎都与背景色不同
FULL_WIDTH_RATIO = 0.55
# 只在窗口底部这个比例范围内寻找导航栏
NAV_BAND_RATIO = 0.35
# 行与行之间允许的空隙（图标与文字之间），超过则认为导航栏已结束
INK_GAP_ROWS = 4
# 列方向：一列中有内容的像素占比达到多少才算「有字」
LABEL_MIN_COL_RATIO = 0.02
# 同一标签内文字之间的列空隙（按 100% 缩放约 2-4px），超过则视为两个标签
LABEL_GAP_COLS = 12
# 识别到的标签中心离窗口中心最远的比例，超过则认为是误判
LABEL_MAX_OFFSET_RATIO = 0.3

# 二维码缩略图识别参数：按 4x4 像素一格统计边缘密集程度
EDGE_CELL = 4
EDGE_THRESHOLD = 45
EDGE_CELL_RATIO = 0.3
# 只考虑窗口下半部分、且高度在以下范围内的正方形区域
QR_MIN_SIZE_RATIO = 0.035
QR_MAX_SIZE_RATIO = 0.3
QR_MIN_FILL = 0.6
QR_MIN_ASPECT = 0.75
QR_MAX_ASPECT = 1.35

DWMWA_EXTENDED_FRAME_BOUNDS = 9

_mouse = MouseController()
_keyboard = KeyboardController()

# 上一次成功返回的二维码数据：登录二维码是一次性的，再次识别到同一个说明新二维码还没生成
_last_qr_data = None


def find_standalone_window(keywords=WINDOW_KEYWORDS):
    """查找「舞萌丨中二」公众号的独立窗口

    Returns:
        (hwnd, title) 或 None
    """
    if not HAS_WIN32:
        return None

    candidates = []

    def enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or not all(keyword in title for keyword in keywords):
            return True
        candidates.append((hwnd, title))
        return True

    win32gui.EnumWindows(enum_callback, None)
    if not candidates:
        return None

    # 标题完全一致的优先；存在多个时优先已还原的窗口（最小化的窗口坐标是占位值），
    # 其次是标题最短的（避免误选长标题的其它窗口）
    candidates.sort(
        key=lambda item: (
            item[1] != "舞萌 | 中二",
            win32gui.IsIconic(item[0]),
            len(item[1]),
        )
    )
    return candidates[0]


def window_rect(hwnd):
    """获取窗口在屏幕上的位置（不含阴影），返回 (left, top, width, height)"""
    rect = wintypes.RECT()
    try:
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr == 0 and rect.right > rect.left and rect.bottom > rect.top:
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return (left, top, right - left, bottom - top)


def usable_rect(rect):
    """窗口位置是否可用（排除最小化窗口的 -32000 占位坐标和过小的尺寸）"""
    left, top, width, height = rect
    return width >= 120 and height >= 120 and left > -10000 and top > -10000


def window_dpi(hwnd):
    """获取窗口所在显示器的缩放（96 表示 100%）"""
    try:
        return ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd)) or 96
    except Exception:
        return 96


def activate_window(hwnd):
    """恢复并前置窗口，保证截图不会被其它窗口遮挡"""
    try:
        # 只恢复最小化的窗口，避免把最大化的窗口还原成普通尺寸
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.warning(f"[独立窗口] 前置窗口失败: {e}")

    # 置顶再取消置顶：绕过后台进程无法切换前台窗口的限制
    try:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
        )
    except Exception:
        pass

    time.sleep(0.3)


# 微信内置浏览器（公众号网页 / 文章 / 二维码页面）的进程名
BROWSER_PROCESS_NAME = "WeChatAppEx"
# 发送 WM_CLOSE 后等待窗口消失的时间（秒）
CLOSE_WAIT = 2.0
# 兜底 taskkill 之后再等待的时间（秒）
TASKKILL_WAIT = 1.5


def _process_name(pid):
    """按 PID 取进程名，取不到时返回空字符串"""
    try:
        return psutil.Process(pid).name() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""
    except Exception:
        return ""


def _is_browser_process(name):
    """进程是否属于微信内置浏览器"""
    return BROWSER_PROCESS_NAME.lower() in (name or "").lower()


def _window_pid(hwnd):
    """取窗口所属进程的 PID"""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return 0


def list_browser_windows():
    """列出当前可见的微信内置浏览器窗口，返回 [(hwnd, 标题, pid), ...]

    只收录内置浏览器进程（WeChatAppEx）的窗口。公众号聊天窗口由微信主客户端
    承载，不会出现在这里，因此关闭浏览器窗口时不会影响聊天窗口。
    """
    if not HAS_WIN32:
        return []

    windows = []

    def enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True

        pid = _window_pid(hwnd)
        if not _is_browser_process(_process_name(pid)):
            return True

        windows.append((hwnd, title, pid))
        return True

    win32gui.EnumWindows(enum_callback, None)
    return windows


def _window_alive(hwnd):
    """窗口是否还在（已销毁或已隐藏都算关闭完成）"""
    try:
        return bool(win32gui.IsWindow(hwnd)) and bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


def _wait_closed(windows, timeout):
    """等待一批窗口关闭，返回是否全部关闭"""
    deadline = time.time() + max(float(timeout), 0)
    while True:
        if not any(_window_alive(hwnd) for hwnd, _, _ in windows):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.1)


def _request_close(hwnd, use_syscommand=False):
    """向窗口投递关闭请求

    use_syscommand=True 时投递 WM_SYSCOMMAND/SC_CLOSE，也就是点右上角叉号
    时窗口收到的那条消息，部分窗口不响应 WM_CLOSE 但会响应它。
    """
    if use_syscommand:
        win32gui.PostMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
    else:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def _close_windows(windows, wait=CLOSE_WAIT):
    """关闭给定的窗口，返回是否全部关闭

    按 WM_CLOSE → WM_SYSCOMMAND/SC_CLOSE → 不带 /F 的 taskkill 逐级尝试，前一级
    不生效才用下一级。三种方式都只是请求窗口自己退出，不会强制结束进程。
    """
    if not windows:
        logger.info("[关闭窗口] 未找到需要关闭的微信浏览器窗口")
        return True

    for use_syscommand in (False, True):
        for hwnd, title, _ in windows:
            if not _window_alive(hwnd):
                continue
            try:
                _request_close(hwnd, use_syscommand)
                label = "SC_CLOSE" if use_syscommand else "WM_CLOSE"
                logger.info(f"[关闭窗口] 已发送 {label} 关闭请求: {title or '（无标题）'}")
            except Exception as e:
                logger.warning(f"[关闭窗口] 发送关闭请求失败（{title}）: {e}")

        if _wait_closed(windows, wait if not use_syscommand else wait / 2):
            logger.info("[关闭窗口] 微信浏览器窗口已关闭")
            return True

    # 兜底：不带 /F 的 taskkill，同样是向窗口投递关闭请求
    remaining = [item for item in windows if _window_alive(item[0])]
    if not remaining:
        return True

    logger.info(
        f"[关闭窗口] {len(remaining)} 个窗口未响应关闭请求，改用 taskkill 请求关闭"
    )
    for _, title, pid in remaining:
        # taskkill 会波及该进程的所有顶层窗口，只对内置浏览器进程使用
        if not _is_browser_process(_process_name(pid)):
            logger.info(f"[关闭窗口] 跳过非内置浏览器窗口: {title}")
            continue
        try:
            subprocess.run(
                ["taskkill", "/pid", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        except Exception as e:
            logger.warning(f"[关闭窗口] taskkill 调用失败（{title}）: {e}")

    if _wait_closed(remaining, TASKKILL_WAIT):
        logger.info("[关闭窗口] 微信浏览器窗口已关闭（taskkill）")
        return True

    logger.warning("[关闭窗口] 窗口未响应关闭请求，保持原状")
    return False


def foreground_browser_window():
    """当前前台窗口若是微信内置浏览器，返回它的句柄"""
    if not HAS_WIN32:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return None
    if not hwnd:
        return None
    if not _is_browser_process(_process_name(_window_pid(hwnd))):
        return None
    return hwnd


class BrowserWindowTracker:
    """记录本次流程打开的微信内置浏览器窗口，结束时关闭

    公众号里的网页（二维码页面）由内置浏览器以独立窗口打开，标题固定为「微信」，
    无法按标题定位。因此在流程开始时快照已有窗口，把之后新出现的、以及被切到
    前台的窗口记为本次打开的，结束时只关这些窗口；用户原本开着的窗口不受影响。
    """

    def __init__(self):
        self._before = {hwnd for hwnd, _, _ in list_browser_windows()}
        self._opened = set()

    @property
    def opened(self):
        """本次流程打开的窗口句柄集合"""
        return set(self._opened)

    def note(self):
        """记录此刻打开的浏览器窗口（在每次点击之后调用）"""
        if not HAS_WIN32:
            return

        for hwnd, _, _ in list_browser_windows():
            if hwnd not in self._before:
                self._opened.add(hwnd)

        # 复用已有窗口时句柄不变，但窗口会被切到前台显示二维码页面
        hwnd = foreground_browser_window()
        if hwnd:
            self._opened.add(hwnd)

    def close_opened(self, wait=CLOSE_WAIT):
        """关闭本次流程打开的浏览器窗口，返回是否已全部关闭"""
        if not HAS_WIN32:
            return True

        self.note()
        targets = [item for item in list_browser_windows() if item[0] in self._opened]
        if not targets:
            logger.info("[关闭窗口] 本次流程没有打开新的微信浏览器窗口")
            return True

        logger.info(f"[关闭窗口] 关闭本次流程打开的 {len(targets)} 个浏览器窗口")
        return _close_windows(targets, wait)

    def note_after_click(self, timeout=1.2):
        """点击后等待窗口出现再记录，最多等 timeout 秒"""
        deadline = time.time() + max(float(timeout), 0.2)
        while True:
            self.note()
            if self.opened or time.time() >= deadline:
                return
            time.sleep(0.15)


def capture_region(rect):
    """截取屏幕上指定区域，返回 PIL 图像"""
    left, top, width, height = rect
    monitor = {"left": left, "top": top, "width": width, "height": height}
    with mss() as sct:
        shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def capture_screen():
    """截取整个虚拟桌面（图片查看器等窗口可能超出独立窗口）"""
    with mss() as sct:
        shot = sct.grab(sct.monitors[0])
    return Image.frombytes("RGB", shot.size, shot.rgb)


def nav_band(image, dpi=96):
    """定位底部导航栏，返回 (起始行, 结束行)；识别失败返回 None

    截图最底部是窗口的圆角/边框，先排除再分析，否则会被当成导航栏分隔线。
    """
    width, height = image.size
    bottom_margin = max(int(14 * dpi / 96), 6)
    band_bottom = height - bottom_margin
    band_top = int(height * (1 - NAV_BAND_RATIO))
    if band_bottom - band_top < 8:
        return None

    ratios = _row_ink_ratios(image, band_top, band_bottom)

    # 优先找导航栏上方的整行分隔线
    line_rows = [i for i, ratio in enumerate(ratios) if ratio >= FULL_WIDTH_RATIO]
    if line_rows:
        return band_top + line_rows[-1] + 1, band_bottom

    # 次选：最下方一段连续的图标/文字，即导航栏标签
    return _lowest_ink_band(ratios, band_top)


def locate_player_qr_button(image, dpi=96, band=None):
    """定位窗口底部导航栏中的「玩家二维码」标签

    「玩家二维码」位于底部导航栏中间，但左右还有其它标签和图标，窗口正中不一定
    正好落在它上面。因此在导航栏文字带内按列找出各个标签，取中心最靠近窗口中心
    的那个标签。

    Returns:
        窗口内坐标 (x, y)
    """
    width, height = image.size
    if band is None:
        band = nav_band(image, dpi)
    if band is not None:
        logger.info(f"[独立窗口] 底部导航栏: {band}")
        return _center_label_x(image, band), (band[0] + band[1]) // 2

    # 兜底：按 DPI 估算导航栏高度（96 DPI 下约 44px）
    y = max(height - int(22 * dpi / 96), 0)
    logger.warning(f"[独立窗口] 未能识别导航栏，使用默认位置: y={y}")
    return width // 2, y


def _center_label_x(image, band):
    """在导航栏文字带内找出最靠近窗口中心的标签，返回其水平中心"""
    width = image.width
    clusters = _label_clusters(_column_ink_ratios(image, band))
    if not clusters:
        logger.warning("[独立窗口] 未识别到导航栏标签，使用窗口中心")
        return width // 2

    center = width / 2
    min_width = max(int(width * 0.01), 4)
    max_width = int(width * 0.4)

    best_x = None
    best_distance = None
    for left, right in clusters:
        cluster_width = right - left + 1
        if not min_width <= cluster_width <= max_width:
            continue
        cluster_center = (left + right) / 2
        distance = abs(cluster_center - center)
        if best_distance is None or distance < best_distance:
            best_x, best_distance = cluster_center, distance

    if best_x is None or best_distance > width * LABEL_MAX_OFFSET_RATIO:
        logger.warning("[独立窗口] 导航栏标签位置异常，使用窗口中心")
        return width // 2

    logger.info(f"[独立窗口] 「玩家二维码」标签中心: x={int(round(best_x))}")
    return int(round(best_x))


def _column_ink_ratios(image, band):
    """统计导航栏文字带每一列「有内容」像素的占比，背景色取该区域的中位数"""
    top, bottom = band
    gray = image.convert("L")
    width = gray.width
    rows = min(bottom, gray.height) - max(top, 0)
    if rows <= 0 or width <= 0:
        return []

    top = max(top, 0)
    pixels = gray.crop((0, top, width, top + rows)).tobytes()
    background = sorted(pixels)[len(pixels) // 2]

    inks = [0] * width
    for row in range(rows):
        start = row * width
        for column, value in enumerate(pixels[start : start + width]):
            if abs(value - background) > INK_DELTA:
                inks[column] += 1
    return [ink / rows for ink in inks]


def _label_clusters(ratios):
    """把相邻的有字列聚成一个标签，返回 [(起始列, 结束列), ...]"""
    clusters = []
    start = None
    last_ink = None
    for column, ratio in enumerate(ratios):
        if ratio < LABEL_MIN_COL_RATIO:
            continue
        if start is None:
            start = column
        elif column - last_ink - 1 > LABEL_GAP_COLS:
            clusters.append((start, last_ink))
            start = column
        last_ink = column
    if start is not None:
        clusters.append((start, last_ink))
    return clusters


def _row_ink_ratios(image, band_top, band_bottom):
    """统计每一行「有内容」像素的占比，背景色取自导航栏底部空白处"""
    gray = image.convert("L")
    width, height = gray.size
    if band_bottom <= band_top or width <= 0:
        return []

    sample_top = max(band_bottom - 6, band_top)
    sample = gray.crop((0, sample_top, width, band_bottom)).tobytes()
    background = sorted(sample)[len(sample) // 2]

    pixels = gray.crop((0, band_top, width, band_bottom)).tobytes()
    ratios = []
    for row in range(band_bottom - band_top):
        start = row * width
        line = pixels[start : start + width]
        ink = sum(1 for value in line if abs(value - background) > INK_DELTA)
        ratios.append(ink / width)
    return ratios


def _lowest_ink_band(ratios, band_top):
    """从下往上找到最后一段连续的内容行，返回其 (起始行, 结束行)"""
    ink_rows = [i for i, ratio in enumerate(ratios) if ratio > 0.01]
    if not ink_rows:
        return None

    end = ink_rows[-1]
    ink_set = set(ink_rows)
    start = end
    gap = 0
    row = end - 1
    while row >= 0:
        if row in ink_set:
            start = row
            gap = 0
        else:
            gap += 1
            if gap > INK_GAP_ROWS:
                break
        row -= 1

    return band_top + start, band_top + end


def find_qrcodes(image):
    """识别截图中的二维码，按「由下到上」排序（最新的消息在最下面）

    Returns:
        [{"data": str, "left": int, "top": int, "width": int, "height": int}, ...]
    """
    codes = _decode_qrcodes(image)
    if not codes:
        # 小尺寸二维码在低分辨率窗口中不易识别，放大后再试一次
        scale = 2
        enlarged = image.resize(
            (image.width * scale, image.height * scale), Image.LANCZOS
        )
        codes = _decode_qrcodes(enlarged)
        for code in codes:
            code["left"] //= scale
            code["top"] //= scale
            code["width"] //= scale
            code["height"] //= scale

    codes.sort(key=lambda code: code["top"] + code["height"], reverse=True)
    return codes


def _decode_qrcodes(image):
    codes = []
    for item in decode(image.convert("L")):
        try:
            data = item.data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rect = item.rect
        codes.append(
            {
                "data": data,
                "left": rect.left,
                "top": rect.top,
                "width": rect.width,
                "height": rect.height,
            }
        )
    return codes


def find_qr_thumbnails(image, bottom=None):
    """在截图中寻找二维码缩略图（密集黑白小方块）的位置

    Args:
        image: 窗口截图
        bottom: 只在此行以上寻找（通常是导航栏起始行）

    Returns:
        [{"left", "top", "width", "height"}, ...]，按由下到上排序
    """
    width, height = image.size
    top_limit = int(height * 0.3)
    bottom_limit = bottom if bottom is not None else int(height * 0.95)
    if bottom_limit <= top_limit + 10:
        return []

    crop = image.crop((0, top_limit, width, bottom_limit))
    gray = crop.convert("L")
    crop_width, crop_height = gray.size

    # 边缘密集程度：二维码内部布满了黑白跳变
    edges = gray.filter(ImageFilter.FIND_EDGES).point(
        lambda value: 255 if value > EDGE_THRESHOLD else 0
    )
    cells_x = max(crop_width // EDGE_CELL, 1)
    cells_y = max(crop_height // EDGE_CELL, 1)
    density = (
        edges.resize((cells_x, cells_y), Image.BOX)
        .point(lambda value: 255 if value > 255 * EDGE_CELL_RATIO else 0)
        .tobytes()
    )

    min_side = max(int(height * QR_MIN_SIZE_RATIO), 16)
    max_side = int(height * QR_MAX_SIZE_RATIO)

    candidates = []
    for left, top, box_width, box_height, fill in _components(
        density, cells_x, cells_y, EDGE_CELL
    ):
        if not (min_side <= box_width <= max_side and min_side <= box_height <= max_side):
            continue
        aspect = box_width / box_height
        if not (QR_MIN_ASPECT <= aspect <= QR_MAX_ASPECT) or fill < QR_MIN_FILL:
            continue
        # 头像贴在窗口最左边，二维码在消息气泡内，跳过靠左的候选
        if left < width * 0.1:
            continue
        if not _looks_like_qr(gray, left, top, box_width, box_height):
            continue
        candidates.append(
            {
                "left": left,
                "top": top + top_limit,
                "width": box_width,
                "height": box_height,
            }
        )

    candidates.sort(key=lambda item: item["top"] + item["height"], reverse=True)
    return candidates


def _components(mask, cells_x, cells_y, cell_size):
    """在粗粒度的边缘掩码上做连通域分析，返回 (left, top, width, height, fill)"""
    components = []
    visited = bytearray(cells_x * cells_y)

    for start in range(cells_x * cells_y):
        if not mask[start] or visited[start]:
            continue

        stack = [start]
        visited[start] = 1
        min_x = max_x = start % cells_x
        min_y = max_y = start // cells_x
        cells = 0

        while stack:
            index = stack.pop()
            cells += 1
            x = index % cells_x
            y = index // cells_x
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y

            for nx, ny in (
                (x + 1, y),
                (x - 1, y),
                (x, y + 1),
                (x, y - 1),
                (x + 1, y + 1),
                (x + 1, y - 1),
                (x - 1, y + 1),
                (x - 1, y - 1),
            ):
                if 0 <= nx < cells_x and 0 <= ny < cells_y:
                    neighbor = ny * cells_x + nx
                    if mask[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)

        box_width = (max_x - min_x + 1) * cell_size
        box_height = (max_y - min_y + 1) * cell_size
        if box_width < 12 or box_height < 12:
            continue
        fill = cells / ((max_x - min_x + 1) * (max_y - min_y + 1))
        components.append(
            (min_x * cell_size, min_y * cell_size, box_width, box_height, fill)
        )

    return components


def _looks_like_qr(gray, left, top, width, height):
    """校验候选区域：白底（静区）+ 约一半的黑白像素"""
    width_max, height_max = gray.size
    if left + width > width_max or top + height > height_max or left < 0 or top < 0:
        return False

    region = gray.crop((left, top, left + width, top + height))
    dark = sum(1 for value in region.tobytes() if value < 110) / (width * height)
    if not 0.15 <= dark <= 0.65:
        return False

    margin = 3
    left_m = max(left - margin, 0)
    top_m = max(top - margin, 0)
    right_m = min(left + width + margin, width_max)
    bottom_m = min(top + height + margin, height_max)
    quiet = gray.crop((left_m, top_m, right_m, bottom_m))
    return ImageStat.Stat(quiet).mean[0] >= 150


def press_escape():
    """关闭图片查看器，回到聊天界面"""
    try:
        _keyboard.press(Key.esc)
        _keyboard.release(Key.esc)
    except Exception as e:
        logger.warning(f"[独立窗口] 关闭图片查看器失败: {e}")


def _close_viewer(tracker, viewer_opened):
    """收起放大的二维码

    点缩略图后打开的可能是微信内置浏览器窗口，也可能是应用内的图片查看器：
    前者用关闭窗口的方式收起，后者按 Esc 返回聊天界面。Esc 是全局按键，会落到
    当时的前台窗口上，所以只有在没打开浏览器窗口时才按，避免误关聊天窗口。
    """
    if tracker.opened:
        return tracker.close_opened()
    if viewer_opened:
        press_escape()
    return True


def _click(screen_x, screen_y):
    _mouse.position = (screen_x, screen_y)
    _mouse.click(Button.left, 1)


def _pick_qrcode(image, nav_top=None):
    """从截图中取出最下方（最新）的可用二维码"""
    codes = find_qrcodes(image)
    if nav_top is not None:
        codes = [
            code for code in codes if code["top"] + code["height"] < nav_top - 2
        ]
    return codes[0] if codes else None


def _pick_largest_qrcode(image):
    """取截图中面积最大的二维码（用于整屏截图中的图片查看器）"""
    codes = find_qrcodes(image)
    if not codes:
        return None
    return max(codes, key=lambda code: code["width"] * code["height"])


def _chat_updated(before, after, nav_top):
    """聊天区域是否出现了新内容（公众号机器人是否已经回复）

    比较两张窗口截图：新增的消息会带来文字、二维码等高对比像素，
    单纯的光标闪烁或悬停高亮不足以触发。
    """
    width = min(before.width, after.width)
    height = nav_top if nav_top else min(before.height, after.height)
    height = min(height, before.height, after.height) - 2
    if width <= 0 or height <= 40:
        return True

    area = (0, 36, width, height)
    diff = ImageChops.difference(
        before.crop(area).convert("L"), after.crop(area).convert("L")
    )
    changed = sum(1 for value in diff.tobytes() if value >= 10)
    return changed / (area[2] * (area[3] - area[1])) >= 0.001


def _finish(code, rect, attempt):
    """记录日志并返回二维码数据"""
    global _last_qr_data
    _last_qr_data = code["data"]

    center_x = code["left"] + code["width"] // 2
    center_y = code["top"] + code["height"] // 2
    logger.info(
        "[独立窗口] 识别到二维码（第 %s 次尝试）: 位置 (%s, %s)，大小 %sx%s",
        attempt + 1,
        rect[0] + center_x,
        rect[1] + center_y,
        code["width"],
        code["height"],
    )
    return code["data"], True


def qrcode_from_standalone_window(retry_count=10, timeout=10):
    """在独立窗口中自动定位「玩家二维码」按钮与生成的二维码

    Args:
        retry_count: 解码重试次数
        timeout: 解码总超时时间（秒）

    Returns:
        (二维码数据 或 None, 是否找到独立窗口)
    """
    window = find_standalone_window()
    if window is None:
        logger.warning("[独立窗口] 未找到标题包含「舞萌」「中二」的窗口")
        return None, False

    hwnd, title = window
    logger.info(f"[独立窗口] 找到窗口: {title}")
    activate_window(hwnd)
    rect = window_rect(hwnd)
    # 窗口刚恢复时 DWM 可能仍返回最小化时的占位坐标（-32000），稍等重读
    for _ in range(10):
        if usable_rect(rect):
            break
        time.sleep(0.2)
        activate_window(hwnd)
        rect = window_rect(hwnd)
    if not usable_rect(rect):
        logger.warning(f"[独立窗口] 窗口位置异常: {rect}")
        return None, True
    logger.info(
        "[独立窗口] 窗口位置: %s，大小: %sx%s", (rect[0], rect[1]), rect[2], rect[3]
    )

    image = capture_region(rect)
    dpi = window_dpi(hwnd)
    band = nav_band(image, dpi)
    nav_top = band[0] if band else None
    button_x, button_y = locate_player_qr_button(image, dpi, band)

    click_x = rect[0] + button_x
    click_y = rect[1] + button_y
    logger.info(f"[独立窗口] 点击「玩家二维码」: ({click_x}, {click_y})")

    # 先把鼠标移到按钮上再截图，避免鼠标悬停高亮被当成聊天内容变化
    _mouse.position = (click_x, click_y)
    time.sleep(0.2)
    image_before = capture_region(rect)
    # 点击前先快照已有窗口，之后据此判断哪些窗口是本次流程打开的
    tracker = BrowserWindowTracker()
    _mouse.click(Button.left, 1)

    attempts = max(1, int(retry_count))
    interval = max(float(timeout), 0.5) / attempts

    # 等待公众号机器人的回复出现在聊天底部
    time.sleep(min(2.0, max(interval, 0.5)))

    opened_viewer = False
    clicks = 0
    try:
        for attempt in range(attempts):
            time.sleep(interval)

            image = capture_region(rect)
            code = _pick_qrcode(image, nav_top)
            # 只有聊天区域出现了新内容（机器人已回复），且不是上次返回的二维码才算数
            if (
                code
                and code["data"] != _last_qr_data
                and _chat_updated(image_before, image, nav_top)
            ):
                return _finish(code, rect, attempt)

            # 已经点开了大图：图片查看器可能超出独立窗口，再截一次整屏
            if opened_viewer:
                code = _pick_largest_qrcode(capture_screen())
                if code and code["data"] != _last_qr_data:
                    return _finish(code, rect, attempt)
                # 大图里还是上一次的二维码，说明新二维码还没生成，关掉继续等
                _close_viewer(tracker, opened_viewer)
                opened_viewer = False
                logger.info("[独立窗口] 二维码尚未更新，继续等待")
                continue

            # 窗口里识别不到二维码：缩略图太小，先找到它的位置再点开看大图
            if clicks < 3 and _chat_updated(image_before, image, nav_top):
                thumbnails = find_qr_thumbnails(
                    image, nav_top if nav_top is not None else int(image.height * 0.95)
                )
                if thumbnails:
                    thumbnail = thumbnails[0]
                    center_x = thumbnail["left"] + thumbnail["width"] // 2
                    center_y = thumbnail["top"] + thumbnail["height"] // 2
                    logger.info(
                        "[独立窗口] 识别到二维码位置: (%s, %s)，点击放大",
                        rect[0] + center_x,
                        rect[1] + center_y,
                    )
                    _click(rect[0] + center_x, rect[1] + center_y)
                    opened_viewer = True
                    clicks += 1
                    tracker.note_after_click(max(interval, 0.5))
                    time.sleep(max(interval, 0.5))
                    continue

            logger.info(
                f"[独立窗口] 未识别到二维码，等待重试 ({attempt + 1}/{attempts})"
            )
    finally:
        # 收起二维码页面，公众号聊天窗口保留（只最小化，下次取码还要用）
        _close_viewer(tracker, opened_viewer)
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        except Exception:
            pass

    logger.warning("[独立窗口] 二维码识别超时")
    return None, True

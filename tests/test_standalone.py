#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""standalone 模块测试（无第三方测试框架依赖，直接 `python tests/test_standalone.py` 运行）

只测试图像识别部分：底部导航栏定位、二维码缩略图定位、二维码解码。
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import qrcode  # noqa: E402

import standalone  # noqa: E402

PASSED = []
QR_DATA = "https://maimai.wahlap.com/maimai-dx/login?token=ABCDEF123456"


def ok(name):
    PASSED.append(name)
    print(f"  [PASS] {name}")


def make_window(width=520, height=460, nav_height=38, dark=False):
    """构造一个类似独立窗口的截图，返回 (图像, 导航栏起始行, 二维码中心)"""
    background = "#1E1E1E" if dark else "#EDEDED"
    card = "#2B2B2B" if dark else "#F2F2F2"
    text = "#E6E6E6" if dark else "#222222"
    divider = "#3C3C3C" if dark else "#E3E3E3"

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=12)

    draw.rectangle([0, 0, width, 28], fill="#333333" if dark else "#F7F7F7")
    draw.text((16, 8), "舞萌 | 中二", font=font, fill=text)

    # 消息卡片
    draw.rectangle([48, height - nav_height - 170, width - 120, height - nav_height - 40], fill=card)
    draw.text((60, height - nav_height - 160), "舞萌DX / 中二节奏 登入二维码", font=font, fill=text)
    draw.text((60, height - nav_height - 130), "把下方二维码对准机台扫描处", font=font, fill=text)

    # 头像（左下角，容易被误认为二维码）
    draw.ellipse([12, height - nav_height - 140, 44, height - nav_height - 108], fill="#F3D34A")

    qr = qrcode.make(QR_DATA).convert("RGB")
    qr_size = 46
    qr_image = qr.resize((qr_size, qr_size), Image.LANCZOS)
    qr_left = width - 200
    qr_top = height - nav_height - 100
    image.paste(qr_image, (qr_left, qr_top))

    # 底部导航栏
    nav_top = height - nav_height
    draw.rectangle([0, nav_top, width, height], fill="#F7F7F7" if not dark else "#262626")
    draw.line([0, nav_top, width, nav_top], fill=divider)
    labels = ["我的记录", "玩家二维码", "资讯"]
    for index, label in enumerate(labels):
        center_x = width * (1 + 2 * index) / 6
        left, _, right, _ = draw.textbbox((0, 0), label, font=font)
        draw.text((center_x - (right - left) / 2, nav_top + 10), label, font=font, fill=text)

    return image, nav_top, (qr_left + qr_size // 2, qr_top + qr_size // 2)


def test_nav_bar_top():
    for dark in (False, True):
        image, nav_top, _ = make_window(dark=dark)
        band = standalone.nav_band(image)
        assert band is not None, f"dark={dark} 未能识别导航栏"
        detected = band[0]
        assert abs(detected - nav_top) <= 3, f"dark={dark} 导航栏识别为 {detected}，期望 {nav_top}"
    ok("nav_bar_top 亮色/深色主题")


def test_nav_band_with_weak_divider():
    """分隔线太浅时按标签文字定位，且不能把窗口底部圆角边框当成导航栏"""
    image, nav_top, _ = make_window()
    draw = ImageDraw.Draw(image)
    # 很浅的分隔线（与背景只差 10）和窗口底部深色边框
    draw.line([0, nav_top, image.width, nav_top], fill="#F5F5F5")
    draw.rectangle([0, image.height - 2, image.width, image.height], fill="#9A9A9A")
    draw.rectangle([0, image.height - 8, 40, image.height], fill="#D0D0D0")

    band = standalone.nav_band(image)
    assert band is not None, "未能识别导航栏"
    assert band[0] >= nav_top - 6, f"导航栏起点 {band[0]} 不应高于 {nav_top}"
    x, y = standalone.locate_player_qr_button(image)
    assert nav_top <= y <= image.height - 10, f"按钮 y={y} 不在导航栏内"
    ok("nav_band 弱分隔线 + 底部边框")


def test_locate_player_qr_button():
    image, nav_top, _ = make_window()
    x, y = standalone.locate_player_qr_button(image)
    assert abs(x - image.width // 2) <= 4, f"按钮 x 坐标为 {x}，期望窗口正中 {image.width // 2}"
    assert nav_top <= y <= image.height, f"按钮 y 坐标 {y} 不在导航栏内（{nav_top}-{image.height}）"
    ok("locate_player_qr_button 取底部导航栏正中")


def _make_nav_window(width, height, clusters, nav_height=44):
    """按列范围画出一排导航标签，返回 (图像, 导航栏起始行)"""
    image = Image.new("RGB", (width, height), "#EDEDED")
    draw = ImageDraw.Draw(image)
    nav_top = height - nav_height
    draw.rectangle([0, nav_top, width, height], fill="#F7F7F7")
    draw.line([0, nav_top, width, nav_top], fill="#E3E3E3")
    for left, right in clusters:
        draw.rectangle([left, nav_top + 12, right, nav_top + 24], fill="#222222")
    return image, nav_top


def test_locate_player_qr_button_offset():
    """真实布局：左侧多个入口、右侧用户图标，中间标签不在窗口正中"""
    width, height = 657, 631
    clusters = [(68, 145), (265, 333), (471, 520), (612, 627)]
    image, nav_top = _make_nav_window(width, height, clusters)
    x, y = standalone.locate_player_qr_button(image)
    expected = (265 + 333) / 2
    assert abs(x - expected) <= 2, f"按钮 x={x}，期望「玩家二维码」标签中心 {expected}"
    assert x < width // 2, "中间标签应位于窗口中心左侧（右侧还有用户图标）"
    assert nav_top < y < height, f"按钮 y={y} 不在导航栏内"
    ok("locate_player_qr_button 识别偏移的中间标签")


def test_locate_player_qr_button_wide_left_icon():
    """左侧有较宽图标时，不应把图标当成「玩家二维码」"""
    width, height = 600, 500
    clusters = [(40, 110), (150, 175), (270, 330), (430, 470), (560, 580)]
    image, nav_top = _make_nav_window(width, height, clusters, nav_height=38)
    x, _ = standalone.locate_player_qr_button(image)
    assert abs(x - 300) <= 2, f"按钮 x={x}，期望最靠近窗口中心的标签中心 300"
    ok("locate_player_qr_button 跳过左侧宽图标")


def test_locate_player_qr_button_fallback():
    # 没有导航栏时按 DPI 兜底，不应抛异常
    image = Image.new("RGB", (400, 300), "white")
    x, y = standalone.locate_player_qr_button(image, dpi=144)
    assert x == 200 and 0 <= y < 300
    ok("locate_player_qr_button 无导航栏时兜底")


def test_usable_rect():
    assert standalone.usable_rect((1234, 210, 657, 631)), "正常窗口应可用"
    assert not standalone.usable_rect((-31993, -32000, 146, 21)), "最小化占位坐标应被排除"
    assert not standalone.usable_rect((100, 100, 100, 100)), "过小的窗口应被排除"
    ok("usable_rect 排除最小化占位坐标")


def test_find_qr_thumbnails():
    image, nav_top, qr_center = make_window()
    thumbnails = standalone.find_qr_thumbnails(image, nav_top)
    assert thumbnails, "未找到二维码缩略图"
    best = thumbnails[0]
    center_x = best["left"] + best["width"] // 2
    center_y = best["top"] + best["height"] // 2
    assert abs(center_x - qr_center[0]) <= 8, f"二维码中心 x={center_x}，期望 {qr_center[0]}"
    assert abs(center_y - qr_center[1]) <= 8, f"二维码中心 y={center_y}，期望 {qr_center[1]}"
    # 头像贴在窗口最左侧，不应被选中
    assert best["left"] > image.width * 0.1
    ok("find_qr_thumbnails 找到二维码并跳过头像")


def test_find_qrcodes_order_and_data():
    image, nav_top, qr_center = make_window(width=520, height=620)
    big = qrcode.make(QR_DATA).convert("RGB").resize((150, 150))
    image.paste(big, (100, 100))
    codes = standalone.find_qrcodes(image)
    assert codes, "未识别出二维码"
    assert codes[0]["data"] == QR_DATA, f"解码结果不符: {codes[0]['data']}"
    # 最下方（最新）的二维码应排在最前
    assert codes[0]["top"] > 100, "排序错误：应优先返回最下方的二维码"
    ok("find_qrcodes 解码并按由下到上排序")


def test_chat_updated():
    image, nav_top, _ = make_window()
    assert not standalone._chat_updated(image, image.copy(), nav_top), "无变化时不应判定为已更新"

    new_message = image.copy()
    draw = ImageDraw.Draw(new_message)
    draw.rectangle([80, nav_top - 100, 320, nav_top - 20], fill="#F2F2F2")
    draw.rectangle([250, nav_top - 90, 300, nav_top - 30], fill="#111111")
    assert standalone._chat_updated(image, new_message, nav_top), "新消息应被识别为聊天更新"

    nav_only = image.copy()
    ImageDraw.Draw(nav_only).rectangle([10, nav_top + 2, 120, nav_top + 12], fill="#999999")
    assert not standalone._chat_updated(image, nav_only, nav_top), "导航栏变化不应算作聊天更新"
    ok("_chat_updated 区分新消息与导航栏变化")


def _patch(module, **attrs):
    """临时替换模块属性，返回原值用于恢复"""
    originals = {}
    for name, value in attrs.items():
        originals[name] = getattr(module, name)
        setattr(module, name, value)
    return originals


def _restore(module, originals):
    for name, value in originals.items():
        setattr(module, name, value)


class _DummyMouse:
    def __init__(self):
        self.position = (0, 0)
        self.clicks = []

    def click(self, button, count=1):
        self.clicks.append(self.position)


def _run_flow(images, screen_image):
    """用假的截图/点击跑一遍独立窗口流程，返回 (数据, 鼠标点击位置, 按 Esc 次数)"""
    mouse = _DummyMouse()
    state = {"index": 0}

    def fake_capture(rect):
        index = min(state["index"], len(images) - 1)
        state["index"] += 1
        return images[index]

    originals = _patch(
        standalone,
        find_standalone_window=lambda: (123, "舞萌 | 中二"),
        activate_window=lambda hwnd: None,
        window_rect=lambda hwnd: (0, 0, images[0].width, images[0].height),
        window_dpi=lambda hwnd: 96,
        capture_region=fake_capture,
        capture_screen=lambda: screen_image,
        press_escape=lambda: None,
        _mouse=mouse,
        _last_qr_data=None,
        win32gui=type(
            "Gui",
            (),
            {
                "ShowWindow": staticmethod(lambda *args: None),
                "EnumWindows": staticmethod(lambda callback, extra: True),
                "GetForegroundWindow": staticmethod(lambda: 0),
            },
        ),
        time=_FakeClock(),
    )
    try:
        data, found = standalone.qrcode_from_standalone_window(retry_count=3, timeout=3)
    finally:
        _restore(standalone, originals)
    return data, found, mouse.clicks


def test_flow_direct_decode():
    base, nav_top, _ = make_window()
    new_image = base.copy()
    big = qrcode.make(QR_DATA).convert("RGB").resize((150, 150))
    new_image.paste(big, (180, nav_top - 190))

    data, found, clicks = _run_flow([base, base, new_image], base)
    assert found, "应找到独立窗口"
    assert data == QR_DATA, f"应直接解码出新二维码，实际 {data}"
    # 第一次点击是底部「玩家二维码」按钮
    assert clicks and abs(clicks[0][0] - base.width // 2) <= 4
    ok("独立窗口流程：直接解码二维码")


def test_flow_click_thumbnail_to_enlarge():
    base, nav_top, qr_center = make_window()
    # 机器人回复前：同一个位置没有二维码
    before = base.copy()
    before.paste(Image.new("RGB", (60, 60), "#F2F2F2"), (qr_center[0] - 30, qr_center[1] - 30))
    # 聊天里只有一个小尺寸二维码（无法直接解码），放大后的图片查看器才能解码
    viewer = Image.new("RGB", base.size, "#000000")
    big = qrcode.make(QR_DATA).convert("RGB").resize((300, 300))
    viewer.paste(big, (100, 150))

    data, found, clicks = _run_flow([before, before, base, base, base], viewer)
    assert found, "应找到独立窗口"
    assert data == QR_DATA, f"应通过放大图片解码，实际 {data}"
    # 第一次点按钮，第二次点二维码缩略图
    assert len(clicks) >= 2, f"应点击二维码缩略图，实际点击 {clicks}"
    assert abs(clicks[1][0] - qr_center[0]) <= 10, f"缩略图 x 位置错误: {clicks[1]} vs {qr_center}"
    assert abs(clicks[1][1] - qr_center[1]) <= 10, f"缩略图 y 位置错误: {clicks[1]} vs {qr_center}"
    ok("独立窗口流程：点击二维码缩略图放大后解码")


class _FakeClock:
    """假时钟：sleep 只推进虚拟时间，测试不必真等"""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _FakeGui:
    """假的 win32gui：维护一张窗口表，用于验证关闭逻辑"""

    def __init__(self, windows):
        # windows: {hwnd: {"title": 标题, "pid": 进程号}}
        self.windows = windows
        self.posted = []
        self.ignores_close = set()
        self.foreground = 0

    def IsWindowVisible(self, hwnd):
        return hwnd in self.windows

    def IsWindow(self, hwnd):
        return hwnd in self.windows

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowText(self, hwnd):
        return self.windows[hwnd]["title"]

    def EnumWindows(self, callback, extra):
        for hwnd in list(self.windows):
            if callback(hwnd, extra) is False:
                break
        return True

    def PostMessage(self, hwnd, message, wparam, lparam):
        self.posted.append((hwnd, message))
        # 正常响应 WM_CLOSE 的窗口会从表里消失；指定 ignores_close 的窗口模拟无响应
        if hwnd not in self.ignores_close:
            self.windows.pop(hwnd, None)
        return True


PROCESS_NAMES = {4000: "WeChatAppEx.exe", 5000: "Weixin.exe"}


def _close_env(windows):
    """搭一套假的窗口/进程环境，返回 (假 GUI, taskkill 调用记录, 原值)"""
    gui = _FakeGui(windows)
    clock = _FakeClock()
    taskkills = []

    def fake_run(args, **kwargs):
        taskkills.append(args)
        pid = int(args[2])
        for hwnd, info in list(gui.windows.items()):
            if info["pid"] == pid:
                gui.windows.pop(hwnd)
        return None

    originals = _patch(
        standalone,
        win32gui=gui,
        win32con=type(
            "Con",
            (),
            {"WM_CLOSE": 16, "WM_SYSCOMMAND": 274, "SC_CLOSE": 61516},
        ),
        win32process=type(
            "Proc",
            (),
            {
                "GetWindowThreadProcessId": staticmethod(
                    lambda hwnd: (0, gui.windows[hwnd]["pid"])
                )
            },
        ),
        _process_name=lambda pid: PROCESS_NAMES.get(pid, ""),
        time=clock,
        subprocess=type(
            "Sub", (), {"run": staticmethod(fake_run), "CREATE_NO_WINDOW": 0}
        ),
    )
    return gui, taskkills, originals


def test_close_only_browser_windows():
    """只关内置浏览器窗口，公众号聊天窗口不受影响"""
    gui, taskkills, originals = _close_env(
        {
            100: {"title": "微信", "pid": 4000},  # 内置浏览器窗口
            200: {"title": "舞萌丨中二", "pid": 5000},  # 公众号聊天窗口
        }
    )
    try:
        closed = standalone._close_windows(standalone.list_browser_windows())
    finally:
        _restore(standalone, originals)

    assert closed, "内置浏览器窗口应被关闭"
    assert gui.posted == [(100, 16)], f"只应向浏览器窗口发送 WM_CLOSE，实际 {gui.posted}"
    assert 200 in gui.windows, "公众号聊天窗口不应被关闭"
    assert taskkills == [], "正常响应时不需要 taskkill"
    ok("只关内置浏览器窗口，不动公众号聊天窗口")


def test_chat_window_is_never_targeted():
    """只有公众号聊天窗口时没有关闭对象，窗口原样保留"""
    gui, taskkills, originals = _close_env({300: {"title": "舞萌丨中二", "pid": 5000}})
    try:
        windows = standalone.list_browser_windows()
        closed = standalone._close_windows(windows)
    finally:
        _restore(standalone, originals)

    assert windows == [], f"聊天窗口不应出现在关闭列表里: {windows}"
    assert closed
    assert gui.posted == [], f"不应向聊天窗口发任何消息: {gui.posted}"
    assert taskkills == []
    assert 300 in gui.windows
    ok("公众号聊天窗口不会进入关闭列表")


def test_close_falls_back_to_graceful_taskkill():
    """窗口不响应 WM_CLOSE 时，用不带 /F 的 taskkill 继续请求关闭"""
    gui, taskkills, originals = _close_env({100: {"title": "微信", "pid": 4000}})
    gui.ignores_close.add(100)
    try:
        closed = standalone._close_windows(standalone.list_browser_windows())
    finally:
        _restore(standalone, originals)

    assert closed, "taskkill 之后窗口应已关闭"
    assert gui.posted == [(100, 16), (100, 274)], f"应逐级尝试关闭: {gui.posted}"
    assert taskkills == [["taskkill", "/pid", "4000"]], f"taskkill 参数错误: {taskkills}"
    ok("窗口无响应时兜底用 taskkill 且不带 /F")


def test_tracker_closes_only_windows_opened_by_flow():
    """只关本次流程新弹出的浏览器窗口，开跑前已存在的窗口不受影响"""
    gui, taskkills, originals = _close_env(
        {
            100: {"title": "微信", "pid": 4000},  # 开跑前就开着的浏览器窗口
            200: {"title": "微信", "pid": 5000},  # 微信主窗口
        }
    )
    try:
        tracker = standalone.BrowserWindowTracker()
        # 流程中弹出二维码网页窗口并切到前台
        gui.windows[300] = {"title": "微信", "pid": 4000}
        gui.foreground = 300
        tracker.note()
        closed = tracker.close_opened()
    finally:
        _restore(standalone, originals)

    assert closed, "新弹出的浏览器窗口应被关闭"
    assert [hwnd for hwnd, _ in gui.posted] == [300], f"关闭对象错误: {gui.posted}"
    assert 100 in gui.windows, "开跑前已存在的浏览器窗口不应被关闭"
    assert 200 in gui.windows, "微信主窗口不应被关闭"
    assert taskkills == []
    ok("BrowserWindowTracker 只关本次流程新开的窗口")


def test_tracker_treats_foreground_window_as_opened():
    """复用旧窗口时句柄不变，只要被切到前台就视为本次流程打开的"""
    gui, _, originals = _close_env({100: {"title": "微信", "pid": 4000}})
    try:
        tracker = standalone.BrowserWindowTracker()
        gui.foreground = 100  # 流程点击后这个窗口被切到前台
        tracker.note()
        closed = tracker.close_opened()
    finally:
        _restore(standalone, originals)

    assert closed, "被切到前台的浏览器窗口应被关闭"
    assert [hwnd for hwnd, _ in gui.posted] == [100]
    ok("BrowserWindowTracker 把前台浏览器窗口算作本次打开")


def test_close_viewer_prefers_closing_browser_window():
    """有浏览器窗口时只关窗口，不按 Esc —— Esc 会落到前台聊天窗口上"""
    gui, _, originals = _close_env({100: {"title": "微信", "pid": 4000}})
    presses = []
    try:
        originals.update(_patch(standalone, press_escape=lambda: presses.append(1)))
        tracker = standalone.BrowserWindowTracker()
        gui.foreground = 100
        tracker.note()
        standalone._close_viewer(tracker, True)
    finally:
        _restore(standalone, originals)

    assert [hwnd for hwnd, _ in gui.posted] == [100], f"应关闭浏览器窗口: {gui.posted}"
    assert presses == [], "有浏览器窗口时不应按 Esc"
    ok("收起二维码页面只关浏览器窗口，不按 Esc")


def test_close_viewer_skips_escape_without_viewer():
    """没点开任何东西时不按 Esc"""
    gui, _, originals = _close_env({})
    presses = []
    try:
        originals.update(_patch(standalone, press_escape=lambda: presses.append(1)))
        tracker = standalone.BrowserWindowTracker()
        standalone._close_viewer(tracker, False)
    finally:
        _restore(standalone, originals)

    assert presses == [], "未点开查看器时不应按 Esc"
    assert gui.posted == []
    ok("未点开查看器时不按 Esc")


def main():
    test_nav_bar_top()
    test_nav_band_with_weak_divider()
    test_locate_player_qr_button()
    test_locate_player_qr_button_offset()
    test_locate_player_qr_button_wide_left_icon()
    test_locate_player_qr_button_fallback()
    test_usable_rect()
    test_find_qr_thumbnails()
    test_find_qrcodes_order_and_data()
    test_chat_updated()
    test_flow_direct_decode()
    test_flow_click_thumbnail_to_enlarge()
    test_close_only_browser_windows()
    test_chat_window_is_never_targeted()
    test_close_falls_back_to_graceful_taskkill()
    test_tracker_closes_only_windows_opened_by_flow()
    test_tracker_treats_foreground_window_as_opened()
    test_close_viewer_prefers_closing_browser_window()
    test_close_viewer_skips_escape_without_viewer()
    print(f"\n全部通过：{len(PASSED)} 项")


if __name__ == "__main__":
    main()

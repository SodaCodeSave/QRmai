"""
QRmai 共享模块 — 平台无关的工具函数、日志、配置初始化
"""

import sys
import os
import json
import time
import logging
from io import BytesIO

# =============================================================================
# 平台检测
# =============================================================================
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform == "linux"

if not (IS_WINDOWS or IS_LINUX):
    raise RuntimeError(f"不支持的操作系统: {sys.platform}")


# =============================================================================
# 资源路径工具
# =============================================================================
def resource_path(relative_path):
    """获取资源文件的绝对路径"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# =============================================================================
# 日志初始化
# =============================================================================
def setup_logging():
    """配置日志，将日志保存到logs文件夹"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    logs_dir = os.path.join(base_path, "logs")

    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    log_file = os.path.join(logs_dir, time.strftime("%Y-%m-%d") + ".log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.handlers:
        logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, logs_dir


# =============================================================================
# 日志实例
# =============================================================================
logger, logs_dir = setup_logging()
logger.info(f"日志系统初始化 - 平台: {sys.platform}")

# Werkzeug 日志也写入文件
werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.setLevel(logging.INFO)
werkzeug_handler = logging.FileHandler(
    os.path.join(logs_dir, time.strftime("%Y-%m-%d") + ".log"), encoding="utf-8"
)
werkzeug_handler.setLevel(logging.INFO)
werkzeug_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
werkzeug_handler.setFormatter(werkzeug_formatter)
werkzeug_logger.addHandler(werkzeug_handler)


# =============================================================================
# 配置管理
# =============================================================================
def get_default_config():
    """获取默认配置项"""
    return {
        "p1": [1087, 799],
        "p2": [945, 682],
        "token": "qrmai",
        "host": "0.0.0.0",
        "port": 5000,
        "qr_route": "/qrmai",
        "standalone_mode": False,
        "decode": {"time": 10, "retry_count": 10},
        "skin_format": "new",
        "skin_mode": "random",          # "random" 随机 / "fixed" 固定
        "skin_index": 0,                 # 固定模式下使用的皮肤序号（0-based）
        "skin_images": [],               # 已上传的皮肤文件名列表，如 ["skin_1.png", "skin_2.png"]
        "custom_skin_path": "./skin.png",  # 向后兼容旧版
        "custom_skin_qrcode_size": 576,
        "custom_skin_qrcode_point": [106, 638],
        "dev_mode": False,
        # OpenCV 视觉识别配置
        "p1_image": "",                  # 用户上传的 P1 图片路径（相对于 img/）
        "p2_image": "",                  # 用户上传的 P2 图片路径
        "auto_detect_p1p2": False,
        "template_threshold": 0.8,
        # Linux 专用配置
        "wechat_bin": "/opt/wechat/wechat",
        "wechat_url_timeout": 30,
    }


def ensure_config_completeness(config):
    """确保配置项完整，缺失的项用默认值补全"""
    default_config = get_default_config()
    for key, default_value in default_config.items():
        if key not in config:
            config[key] = default_value
        elif isinstance(default_value, dict) and isinstance(config[key], dict):
            for sub_key, sub_default_value in default_value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = sub_default_value
    return config


# 加载配置
config = {}
config_path = resource_path("config.json")
if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

config = ensure_config_completeness(config)


# =============================================================================
# 二维码图像生成（Windows/Linux 共用）
# =============================================================================
def _make_transparent_resized_qr(qr_img, config):
    """将 QR 图像的白色区域透明化并缩放到皮肤所需尺寸。"""
    from PIL import Image

    qr_img = qr_img.convert("RGBA")
    width, height = qr_img.size
    for x in range(width):
        for y in range(height):
            r, g, b, a = qr_img.getpixel((x, y))
            if r > 200 and g > 200 and b > 200:
                qr_img.putpixel((x, y), (255, 255, 255, 0))

    if config["skin_format"] == "custom":
        size = int(config["custom_skin_qrcode_size"])
    else:
        size = 576
    return qr_img.resize((size, size))


def _get_paste_point(config):
    """根据皮肤格式返回二维码粘贴坐标 (x, y)。"""
    fmt = config["skin_format"]
    if fmt == "new":
        return (106, 638)
    elif fmt == "old":
        return (106, 1060)
    else:
        return tuple(config["custom_skin_qrcode_point"])


def _resolve_skin_path():
    """
    根据 skin_mode / skin_index / skin_images 配置解析当前应使用的皮肤文件路径。

    优先级：
      1. 用户上传的皮肤（skin_images 列表）— 根据 skin_mode 选择
      2. 旧版兼容: 当前目录的 skin.png 或 custom_skin_path
      3. 无皮肤

    Returns:
        (skin_path, skin_label) — skin_path 为文件路径或 None; skin_label 为显示名
    """
    skin_images = config.get("skin_images", [])

    # ── 用户上传的皮肤 ──
    if skin_images:
        skin_mode = config.get("skin_mode", "random")

        if skin_mode == "random":
            import random
            chosen = random.choice(skin_images)
        else:
            idx = config.get("skin_index", 0)
            # 确保索引有效
            if idx < 0 or idx >= len(skin_images):
                idx = 0
            chosen = skin_images[idx]

        skin_path = os.path.join(_IMG_DIR, chosen)
        if os.path.isfile(skin_path):
            logger.info(f"[Skin] 使用{'随机' if skin_mode == 'random' else '固定'}皮肤: {chosen}")
            return skin_path, chosen
        else:
            logger.warning(f"[Skin] 皮肤文件不存在: {skin_path}")

    # ── 旧版兼容: 当前目录的 skin.png ──
    skin_fmt = config.get("skin_format", "new")
    if os.path.isfile("skin.png"):
        if skin_fmt == "custom":
            cp = config.get("custom_skin_path", "./skin.png")
            if os.path.isfile(cp):
                return cp, os.path.basename(cp)
        return "skin.png", "skin.png"

    # ── custom 模式但 skin.png 不存在 ──
    if skin_fmt == "custom":
        cp = config.get("custom_skin_path", "./skin.png")
        if os.path.isfile(cp):
            return cp, os.path.basename(cp)

    return None, None


def apply_skin_to_qr(qr_data: str) -> BytesIO:
    """
    将解码得到的二维码数据生成二维码图像，如果有皮肤文件则叠加。
    支持多皮肤上传（随机 / 固定选择）。
    返回包含 PNG 图像的 BytesIO 对象。
    """
    import qrcode
    from PIL import Image

    img_io = BytesIO()
    qr_img = qrcode.make(qr_data)

    skin_path, skin_label = _resolve_skin_path()

    if skin_path:
        skin = Image.open(skin_path)
        resized_qr = _make_transparent_resized_qr(qr_img, config)
        paste_point = _get_paste_point(config)
        skin.paste(resized_qr, paste_point, mask=resized_qr)
        skin.save(img_io, format="PNG")
    else:
        qr_img.save(img_io, format="PNG")

    img_io.seek(0)
    return img_io


def make_error_image(message: str) -> BytesIO:
    """创建包含错误信息的 PNG 图像"""
    from PIL import Image, ImageDraw, ImageFont

    img_io = BytesIO()
    im = Image.new("L", (200, 100), "#FFFFFF")
    font = ImageFont.load_default(size=23)
    draw = ImageDraw.Draw(im)
    draw.text((10, 10), message, font=font, fill="#000000")
    im.save(img_io, format="PNG")
    img_io.seek(0)
    return img_io


# =============================================================================
# OpenCV 视觉识别 — P1 / P2 自动定位
# =============================================================================

_IMG_DIR = resource_path("img")


def _get_template_path(name: str):
    """按优先级查找模板图：用户模板 > 开发者模板，均无则返回 None"""
    user_path = os.path.join(_IMG_DIR, f"{name}_user.png")
    dev_path = os.path.join(_IMG_DIR, f"{name}.png")

    if os.path.isfile(user_path):
        logger.info(f"[OpenCV] 使用用户模板: {user_path}")
        return user_path
    elif os.path.isfile(dev_path):
        logger.info(f"[OpenCV] 使用开发者模板: {dev_path}")
        return dev_path
    else:
        logger.warning(
            f"[OpenCV] 未找到模板图 {name}（已检查 {user_path} 和 {dev_path}）"
        )
        return None


def _image_to_bgr(image):
    """
    将多种输入格式统一转换为 OpenCV BGR ndarray。
    支持: ndarray / BytesIO / PIL Image / 文件路径 str
    """
    import numpy as np
    import cv2

    if isinstance(image, np.ndarray):
        arr = image
    elif isinstance(image, BytesIO):
        image.seek(0)
        arr = np.frombuffer(image.read(), dtype=np.uint8)
        arr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif isinstance(image, str):
        arr = cv2.imread(image, cv2.IMREAD_COLOR)
    else:
        try:
            from PIL import Image

            if isinstance(image, Image.Image):
                arr = np.array(image.convert("RGB"))
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            else:
                raise TypeError(f"不支持的图像类型: {type(image)}")
        except ImportError:
            raise TypeError(f"不支持的图像类型: {type(image)}")

    if arr is None or arr.size == 0:
        raise ValueError("图像数据为空")

    if len(arr.shape) == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif arr.shape[2] == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

    return arr


def _match_template_multiscale(
    screen,
    template_path,
    threshold=0.8,
    scales=(0.6, 0.8, 1.0, 1.2, 1.5),
    pick_mode="best",
):
    """
    多尺度模板匹配。在不同缩放比例下查找模板，返回匹配的中心坐标。

    适应不同屏幕分辨率 / DPI 缩放下的 UI 元素尺寸差异。

    Args:
        pick_mode: 多匹配选择策略
            - "best"   默认，选择置信度最高的匹配
            - "bottom" 选择 Y 坐标最大（最靠下）的匹配，适用于 P2

    Returns:
        [x, y] 或 None
    """
    import cv2
    import numpy as np

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        logger.error(f"[OpenCV] 无法读取模板图: {template_path}")
        return None

    # 收集所有超过阈值的匹配候选: (center_x, center_y, confidence, scale, h, w)
    candidates = []

    for scale in scales:
        tw = int(template.shape[1] * scale)
        th = int(template.shape[0] * scale)
        if tw < 10 or th < 10 or tw > screen.shape[1] or th > screen.shape[0]:
            continue

        scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_LINEAR)
        result = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)

        # 找出所有超过阈值的匹配位置
        locations = np.where(result >= threshold)
        count = len(locations[0])

        if count > 0:
            logger.debug(f"[OpenCV] 缩放 {scale:.1f}x -> {count} 个匹配超过阈值")
            for py, px in zip(*locations):
                confidence = float(result[py, px])
                center_x = px + tw // 2
                center_y = py + th // 2
                candidates.append((center_x, center_y, confidence, scale, th, tw))
        else:
            max_val = float(result.max())
            logger.debug(
                f"[OpenCV] 缩放 {scale:.1f}x -> 0 个匹配 (max_val={max_val:.3f})"
            )

    if not candidates:
        logger.warning(
            f"[OpenCV] 模板 {os.path.basename(template_path)} 无匹配超过阈值 "
            f"({threshold})"
        )
        return None

    # 根据策略选择最佳匹配
    if pick_mode == "bottom":
        # 选择 Y 坐标最大（最靠下）的匹配
        best = max(candidates, key=lambda c: c[1])  # c[1] = center_y
        logger.info(f"[OpenCV] 底部策略: 从 {len(candidates)} 个候选中选择最靠下的匹配")
    else:
        # 默认：选择置信度最高的匹配
        best = max(candidates, key=lambda c: c[2])  # c[2] = confidence

    center_x, center_y, confidence, scale, th, tw = best

    logger.info(
        f"[OpenCV] 匹配成功: {os.path.basename(template_path)} "
        f"-> [{center_x}, {center_y}] "
        f"(scale={scale:.1f}x, confidence={confidence:.3f}, "
        f"候选数={len(candidates)})"
    )
    return [int(center_x), int(center_y)]


def detect_p1p2(image, threshold=None):
    """
    从屏幕截图中自动识别 P1 / P2 的坐标。

    Args:
        image:     屏幕截图，支持 ndarray / BytesIO / PIL Image / 文件路径
        threshold: 匹配置信度阈值，默认使用 config 中的 template_threshold

    Returns:
        (p1, p2) — 各自为 [x, y] 或 None

    Example:
        p1, p2 = detect_p1p2(screenshot_bytes)
        # p1 = [1788, 654], p2 = [1427, 559]
    """
    if threshold is None:
        threshold = config.get("template_threshold", 0.8)

    screen = _image_to_bgr(image)
    logger.debug(
        f"[OpenCV] 开始识别 P1/P2，屏幕尺寸: {screen.shape[1]}x{screen.shape[0]}"
    )

    p1 = None
    p1_template = _get_template_path("p1")
    if p1_template:
        p1 = _match_template_multiscale(screen, p1_template, threshold)
    else:
        logger.warning("[OpenCV] 无 P1 模板图，跳过 P1 识别")

    p2 = None
    p2_template = _get_template_path("p2")
    if p2_template:
        p2 = _match_template_multiscale(
            screen, p2_template, threshold, pick_mode="bottom"
        )
    else:
        logger.warning("[OpenCV] 无 P2 模板图，跳过 P2 识别")

    return p1, p2

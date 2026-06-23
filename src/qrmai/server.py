# Flask框架相关模块
import glob
import json
import os
import re
import threading
from functools import wraps
from io import BytesIO
from uuid import uuid4

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from qrmai.shared import IS_LINUX

# 初始化Flask应用
app = Flask(__name__)
app.secret_key = str(uuid4())  # 在生产环境中应该使用更安全的密钥

# 请求锁，防止并发访问
request_lock = threading.Lock()

# 以下变量由 main.py 通过 init() 注入
_config = None
_logger = None
_qrmai_action = None
_capture_screen = None


def init(qrmai_action, capture_screen, config, logger, template_folder):
    """初始化 server 模块，注入来自 main.py 的依赖"""
    global _qrmai_action, _capture_screen, _config, _logger
    _qrmai_action = qrmai_action
    _capture_screen = capture_screen
    _config = config
    _logger = logger
    app.template_folder = template_folder


def require_auth(f):
    """装饰器：要求用户认证"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查基础认证状态
        if "authenticated" not in session:
            return redirect(url_for("login"))

        # 检查配置版本是否匹配（增强安全性）
        if "config_version" not in session or session["config_version"] != _config.get(
            "version"
        ):
            # 配置已更改，需要重新登录
            session.pop("authenticated", None)
            session.pop("config_version", None)
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        token = request.form.get("token")
        if token and token == _config["token"]:
            session["authenticated"] = True
            # 存储配置版本信息到session中，用于增强安全性
            session["config_version"] = _config.get("version")
            _logger.info(f"来自{request.remote_addr}的成功登录请求")
            return {"success": True}
        else:
            _logger.info(f"来自{request.remote_addr}的登录请求失败")
            return {"success": False}
    _logger.info(f"{request.remote_addr}尝试进入登录页面")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("authenticated", None)
    return "", 204


@app.route("/settings", methods=["GET", "POST"])
@require_auth
def settings():
    if request.method == "POST":
        # 读取POST参数并更新config
        token_updated = False
        old_token = _config["token"]

        # 处理所有表单字段，包括布尔值字段
        # 首先处理布尔值字段，确保未选中的开关也能正确处理
        boolean_fields = ["standalone_mode"]
        for field in boolean_fields:
            if field in _config:
                # 检查表单中是否包含该字段
                _config[field] = field in request.form and request.form[
                    field
                ].lower() in ("true", "1", "yes", "on")

        # 处理其他字段
        for key, value in request.form.items():
            # 跳过已处理的布尔值字段
            if key in boolean_fields:
                continue

            if key in _config:
                # 尝试将字符串转换为对应类型（int/float/list）
                if isinstance(_config[key], bool):
                    _config[key] = value.lower() in ("true", "1", "yes", "on")
                elif isinstance(_config[key], int):
                    _config[key] = int(value)
                elif isinstance(_config[key], float):
                    _config[key] = float(value)
                elif isinstance(_config[key], list) and "," in value:
                    _config[key] = [
                        int(v) if v.isdigit() else v for v in value.split(",")
                    ]
                else:
                    _config[key] = value
                # 检查是否更新了token
                if key == "token" and value != old_token:
                    token_updated = True
            elif key == "qr_route":  # 处理新的配置项
                _config[key] = value
            elif key in ("skin_mode", "skin_index"):
                if key == "skin_index":
                    _config[key] = int(value)
                else:
                    _config[key] = value

        # 保存更新后的config到文件
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(_config, f, ensure_ascii=False, indent=4)
        # 如果token被更新，需要更新配置版本信息
        if token_updated:
            import hashlib
            import time as _time

            try:
                config_version = hashlib.md5(
                    (_config["token"] + str(os.path.getmtime("config.json"))).encode()
                ).hexdigest()
            except FileNotFoundError:
                config_version = hashlib.md5(
                    (_config["token"] + str(_time.time())).encode()
                ).hexdigest()
            _config["version"] = config_version
            # 更新session中的配置版本信息
            session["config_version"] = config_version
        return "配置已更新", 200
    # GET请求时返回设置页面
    return render_template("settings.html", config=_config, is_linux=IS_LINUX)


def _check_auth():
    """双通道认证：session（设置页面）或 token（直接 API 调用）"""
    if request.args.get("token") == _config.get("token"):
        return True
    if "authenticated" in session:
        if "config_version" in session and session["config_version"] == _config.get("version"):
            return True
    return False


@app.route("/detect_positions", endpoint="detect_positions", methods=["GET", "POST"])
def detect_positions():
    """
    OpenCV 自动识别 P1/P2 坐标并直接保存到配置（无需确认）。

    认证方式：
      - 设置页面调用：通过 session 认证
      - 直接 API 调用：通过 ?token= 查询参数认证（与 /qrmai 一致）
    """
    if not _check_auth():
        return jsonify({"error": "未授权"}), 403

    from qrmai.shared import detect_p1p2

    if _capture_screen is None:
        return jsonify({"error": "截图功能未初始化"}), 500

    try:
        _logger.info("[Server] 收到自动识别位置请求")
        screen = _capture_screen()
        p1, p2 = detect_p1p2(screen)

        if p1 is None and p2 is None:
            return jsonify({
                "error": "未能识别任何位置，请确认 img/ 目录下有模板图"
            }), 422

        # 自动保存识别结果到配置
        saved = []
        if p1 is not None:
            _config["p1"] = p1
            saved.append("p1")
        if p2 is not None:
            _config["p2"] = p2
            saved.append("p2")
        _save_config()

        result = {"success": True, "saved": saved}
        if p1 is not None:
            result["p1"] = p1
        if p2 is not None:
            result["p2"] = p2

        _logger.info(f"[Server] 识别并保存结果: {result}")
        return jsonify(result)

    except Exception as e:
        _logger.error(f"[Server] 自动识别失败: {e}")
        return jsonify({"error": str(e)}), 500

# =============================================================================
# 图片上传端点
# =============================================================================

def _ensure_img_dir():
    """确保 img/ 目录存在"""
    from qrmai.shared import resource_path
    img_dir = resource_path("img")
    os.makedirs(img_dir, exist_ok=True)
    return img_dir


def _next_skin_number():
    """获取下一个可用的皮肤编号"""
    img_dir = _ensure_img_dir()
    existing = glob.glob(os.path.join(img_dir, "skin_*.png"))
    nums = []
    for path in existing:
        m = re.search(r"skin_(\d+)\.png$", os.path.basename(path))
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


@app.route("/img/<path:filename>")
def serve_img(filename):
    """提供 img/ 目录下的静态文件"""
    from qrmai.shared import resource_path
    return send_from_directory(resource_path("img"), filename)


@app.route("/upload_p1", methods=["POST"])
@require_auth
def upload_p1():
    """上传 P1 模板图片"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400
    img_dir = _ensure_img_dir()
    filepath = os.path.join(img_dir, "p1_user.png")
    file.save(filepath)
    _config["p1_image"] = "p1_user.png"
    _save_config()
    _logger.info(f"[Server] P1 模板已上传: {filepath}")
    return jsonify({"success": True, "filename": "p1_user.png"})


@app.route("/upload_p2", methods=["POST"])
@require_auth
def upload_p2():
    """上传 P2 模板图片"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400
    img_dir = _ensure_img_dir()
    filepath = os.path.join(img_dir, "p2_user.png")
    file.save(filepath)
    _config["p2_image"] = "p2_user.png"
    _save_config()
    _logger.info(f"[Server] P2 模板已上传: {filepath}")
    return jsonify({"success": True, "filename": "p2_user.png"})


@app.route("/upload_skin", methods=["POST"])
@require_auth
def upload_skin():
    """上传皮肤图片"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400
    img_dir = _ensure_img_dir()
    num = _next_skin_number()
    filename = f"skin_{num}.png"
    filepath = os.path.join(img_dir, filename)
    file.save(filepath)
    skin_images = _config.get("skin_images", [])
    skin_images.append(filename)
    _config["skin_images"] = skin_images
    _save_config()
    _logger.info(f"[Server] 皮肤已上传: {filepath} (共 {len(skin_images)} 个)")
    return jsonify({"success": True, "filename": filename, "index": len(skin_images) - 1, "total": len(skin_images)})


@app.route("/delete_skin", methods=["POST"])
@require_auth
def delete_skin():
    """删除皮肤或 P1/P2 用户模板图片"""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "未指定文件名"}), 400

    img_dir = _ensure_img_dir()
    filepath = os.path.join(img_dir, filename)

    # P1/P2 模板文件单独处理
    if filename in ("p1_user.png", "p2_user.png"):
        if os.path.isfile(filepath):
            os.remove(filepath)
        if filename == "p1_user.png":
            _config["p1_image"] = ""
        else:
            _config["p2_image"] = ""
        _save_config()
        _logger.info(f"[Server] 用户模板已删除: {filename}")
        return jsonify({"success": True})

    skin_images = _config.get("skin_images", [])
    if filename not in skin_images:
        return jsonify({"error": "皮肤不存在"}), 404
    if os.path.isfile(filepath):
        os.remove(filepath)
    skin_images.remove(filename)
    _config["skin_images"] = skin_images
    if _config.get("skin_index", 0) >= len(skin_images) and skin_images:
        _config["skin_index"] = 0
    _save_config()
    _logger.info(f"[Server] 皮肤已删除: {filename} (剩余 {len(skin_images)} 个)")
    return jsonify({"success": True, "remaining": len(skin_images)})


def _save_config():
    """保存配置到 config.json"""
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(_config, f, ensure_ascii=False, indent=4)


@app.route("/check_update", methods=["POST"])
@require_auth
def check_update():
    """检查更新的路由"""
    try:
        from qrmai import updater

        # 检查是否有新版本
        has_update, latest_release = updater.is_new_version_available()

        if has_update and latest_release:
            return jsonify(
                {
                    "has_update": True,
                    "version": latest_release["version"],
                    "name": latest_release["name"],
                    "published_at": latest_release["published_at"],
                    "body": latest_release["body"],
                }
            )
        else:
            return jsonify({"has_update": False, "message": "当前已是最新版本"})
    except Exception as e:
        return jsonify({"error": True, "message": f"检查更新时出错: {str(e)}"}), 500


@app.route("/_qrmai", endpoint="qrmai")
def qrmai():
    """
    处理二维码路由请求的函数
    每次请求均实时生成二维码，不使用缓存
    """
    # 验证token，如果与配置不符则返回403错误
    if request.args.get("token") != _config["token"]:
        return Response("403 Forbidden", status=403)

    with request_lock:
        img_io = _qrmai_action()
        img_io.seek(0)
        return Response(BytesIO(img_io.getvalue()), mimetype="image/png")


@app.route("/manual_update", methods=["POST"])
@require_auth
def manual_update():
    """手动更新的路由"""
    try:
        from qrmai import updater

        # 检查是否有新版本并执行更新
        has_update, latest_release = updater.is_new_version_available()

        if has_update and latest_release:
            # 执行更新
            success = updater.check_and_update()

            if success:
                # 更新成功，返回200状态码
                return "", 200
            else:
                # 更新失败
                return jsonify({"error": True, "message": "更新失败"}), 500
        else:
            # 无更新可用，返回204状态码
            return "", 204
    except Exception as e:
        return jsonify({"error": True, "message": f"手动更新时出错: {str(e)}"}), 500

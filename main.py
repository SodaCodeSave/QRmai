# 标准库导入
import json  # JSON操作库
import os
import sys
import time  # 时间相关操作
from io import BytesIO  # 用于处理字节流

# Flask框架相关模块
from flask import Flask, render_template, request, Response, session, redirect, url_for, jsonify

# 外部库导入
import psutil  # 进程管理库
import subprocess  # 用于运行系统命令

def resource_path(relative_path):
    """获取资源文件的绝对路径"""
    try:
        # PyInstaller创建临时文件夹，将路径存储在_MEIPASS中
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# 图形界面自动化和图像处理相关库
from pynput.mouse import Controller as MouseController, Button  # 鼠标控制库
import pygetwindow as gw  # 窗口管理库
import qrcode  # 二维码生成库
from PIL import Image, ImageDraw, ImageFont  # 图像处理库
from mss import mss  # 屏幕截图库
from pyzbar.pyzbar import decode  # 二维码解码库
from uuid import uuid4

# Windows API 相关库用于操作进程窗口
import ctypes
from ctypes import wintypes
from win32 import win32gui, win32process
import win32con

# 初始化鼠标控制器
mouse = MouseController()

# 以下两行代码修复了Win10在系统缩放下第一次请求时鼠标移动位置偏移的bug
# 导入 Shcore.dll
shcore = ctypes.windll.shcore
# 设置 DPI 感知模式：0 = 无感知，1 = 系统级感知，2 = 每显示器感知
shcore.SetProcessDpiAwareness(2)   # 每显示器高 DPI 感知

def get_default_config():
    """获取默认配置项"""
    return {
        "p1": [1087, 799],
        "p2": [945, 682],
        "token": "qrmai",
        "host": "0.0.0.0",
        "port": 5000,
        "qr_route": "/qrmai",  # 二维码访问路径
        "cache_duration": 60,
        "standalone_mode": False,
        "decode": {
            "time": 10,
            "retry_count": 10
        },
        "skin_format": "new",
        "custom_skin_path": "./skin.png",
        "custom_skin_qrcode_size": 576,
        "custom_skin_qrcode_point": [106,638],
        "dev_mode": False
    }


def ensure_config_completeness(config):
    """确保配置项完整，缺失的项用默认值补全"""
    default_config = get_default_config()

    # 检查并补全顶层配置项
    for key, default_value in default_config.items():
        if key not in config:
            config[key] = default_value
        # 对于嵌套字典，也需要检查完整性
        elif isinstance(default_value, dict) and isinstance(config[key], dict):
            for sub_key, sub_default_value in default_value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = sub_default_value

    return config


def kill_wechat_process():
    """
    杀死WeChatAppEx.exe进程
    """
    try:
        # 方法1: 使用psutil查找并终止进程
        killed_any = False
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] and 'WeChatAppEx.exe' in proc.info['name']:
                proc.kill()  # 终止进程
                print(f"已杀死微信进程，PID: {proc.info['pid']}")
                killed_any = True

        if not killed_any:
            print("未找到可杀死的WeChatAppEx.exe进程")
    except psutil.NoSuchProcess:
        print("微信进程已终止")
    except psutil.AccessDenied:
        print("尝试杀死微信进程时访问被拒绝 - 可能需要提升权限")
    except Exception as e:
        print(f"杀死微信进程时出错: {e}")
        # 备用方法: 尝试使用taskkill命令
        try:
            subprocess.run(['taskkill', '/f', '/im', 'WeChatAppEx.exe'],
                          creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            print("使用taskkill命令杀死微信进程")
        except subprocess.CalledProcessError:
            print("使用taskkill命令杀死微信进程失败")

# 读取配置文件
config = {}
config_path = resource_path('config.json')
if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

# 确保配置项完整
config = ensure_config_completeness(config)

# 更新配置版本信息（如果尚未存在）
if 'version' not in config:
    import hashlib
    import time
    import os
    try:
        config_version = hashlib.md5((config['token'] + str(os.path.getmtime(config_path))).encode()).hexdigest()
    except FileNotFoundError:
        config_version = hashlib.md5((config['token'] + str(time.time())).encode()).hexdigest()
    config['version'] = config_version

# 初始化Flask应用
app = Flask(__name__, template_folder=resource_path('templates'))
app.secret_key = str(uuid4())  # 在生产环境中应该使用更安全的密钥

# 添加全局变量用于缓存
request_lock = False  # 请求锁，防止并发访问
last_qr_bytes = None  # 上次生成的二维码字节数据
last_qr_time = 0  # 上次生成二维码的时间戳

def require_auth(f):
    """装饰器：要求用户认证"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查基础认证状态
        if 'authenticated' not in session:
            return redirect(url_for('login'))

        # 检查配置版本是否匹配（增强安全性）
        if 'config_version' not in session or session['config_version'] != config.get('version'):
            # 配置已更改，需要重新登录
            session.pop('authenticated', None)
            session.pop('config_version', None)
            return redirect(url_for('login'))

        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        token = request.form.get('token')
        if token and token == config['token']:
            session['authenticated'] = True
            # 存储配置版本信息到session中，用于增强安全性
            session['config_version'] = config.get('version')
            return {'success': True}
        else:
            return {'success': False}
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('authenticated', None)
    return '', 204

def find_wechat_window_by_process():
    """
    通过查找Weixin.exe进程来获取微信窗口句柄
    """
    def enum_windows_callback(hwnd, windows):
        if not win32gui.IsWindowVisible(hwnd):
            return True

        # 获取窗口关联的进程ID
        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        # 根据进程ID获取进程名称
        try:
            process = psutil.Process(pid)
            if process.name() and 'Weixin.exe' in process.name():
                windows.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return True

    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    return windows[0] if windows else None

def qrmai_action():
    """
    核心功能函数：执行二维码获取操作
    1. 定位并激活微信窗口
    2. 自动点击指定位置获取二维码
    3. 截屏并识别二维码
    4. 将二维码与皮肤合成并返回
    """
    # 创建字节流对象用于存储最终的图片数据
    img_io = BytesIO()

    # 直接查找Weixin.exe进程的窗口，而不是通过标题
    wechat_hwnd = find_wechat_window_by_process()
    if not wechat_hwnd:
        print("未找到Weixin.exe进程的窗口")
        # 杀死微信进程并返回错误信息
        kill_wechat_process()
        im = Image.new("L", (100, 100), "#FFFFFF")
        font = ImageFont.load_default(size=23)
        draw = ImageDraw.Draw(im)
        draw.text((0, 0), "Window\nnot found", font=font, fill="#000000")
        im.save(img_io, format='PNG')
        img_io.seek(0)
        return img_io

    # 尝试激活窗口，添加重试机制和错误处理
    activation_success = False
    for attempt in range(3):  # 最多尝试3次
        try:
            # 恢复窗口（如果被最小化）
            win32gui.ShowWindow(wechat_hwnd, win32con.SW_RESTORE)
            # 将窗口置于前台并激活
            win32gui.SetForegroundWindow(wechat_hwnd)
            # 设置窗口为最顶层
            win32gui.SetWindowPos(wechat_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            activation_success = True
            break
        except Exception as e:
            print(f"第 {attempt + 1} 次尝试激活窗口失败: {e}")
            time.sleep(1)  # 等待1秒后重试
            pass

    # 如果激活窗口失败，给出友好提示
    if not activation_success:
        print("无法激活微信窗口，将继续执行后续操作")
        # 不中断流程，继续执行后续操作

    def move_click(x, y):
        """
        移动鼠标并点击的辅助函数
        :param x: x坐标
        :param y: y坐标
        """

        mouse.position = (x,y)
        mouse.click(Button.left, 1)

    # 点击第一个位置(p1) - 通常是"舞萌 | 中二服务号生成二维码按钮的位置"
    move_click(config["p1"][0], config["p1"][1])

    # 等待2秒确保界面响应
    time.sleep(2)

    # 点击第二个位置(p2) - 通常是"生成后的二维码的消息的位置"
    move_click(config["p2"][0], config["p2"][1])

    # 初始化解码结果
    decoded_objects = None

    # 最小化微信窗口以减少干扰
    # 这里需要处理基于窗口句柄的最小化
    try:
        time.sleep(0.2) #等待0.2秒再最小化，以免还没有点击到二维码就最小化了
        win32gui.ShowWindow(wechat_hwnd, win32con.SW_MINIMIZE)
    except:
        pass

    # 根据配置进行多次尝试解码二维码
    for i in range(config["decode"]["retry_count"]):
        # 每次尝试间隔一定时间
        time.sleep(config["decode"]["time"] / config["decode"]["retry_count"])

        # 使用mss截取整个屏幕
        with mss() as sct:
            # monitors[1] 表示第一个显示器
            screenshot = sct.grab(sct.monitors[1])
            # 将截图转换为PIL图像对象
            image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

        # 解码二维码
        decoded_objects = decode(image)

        # 如果成功解码到二维码则跳出循环
        if decoded_objects and len(decoded_objects) > 0:
            break
        else:
            # 如果是最后一次尝试仍然失败，则返回错误信息
            if i == config["decode"]["retry_count"] - 1:
                # 杀死微信进程
                kill_wechat_process()

                # 创建一个提示错误的图像
                im = Image.new("L", (100, 100), "#FFFFFF")  # 创建白色背景图像
                font = ImageFont.load_default(size=23)  # 加载默认字体
                draw = ImageDraw.Draw(im)  # 创建绘图对象
                # 绘制错误信息文本
                draw.text((0, 0), "Unable\nto load\nQRCode\n(Timeout)", font=font, fill="#000000")
                im.save(img_io, format='PNG')  # 保存图像到字节流
                img_io.seek(0)  # 将指针移到开始位置

                return img_io  # 返回错误图像
            # 打印重试信息
            print(f"二维码解码失败 过{config['decode']['time'] / config['decode']['retry_count']}s后重试 ({i+1}/{config['decode']['retry_count']})")

    # 使用解码得到的数据生成新的二维码
    qr_img = qrcode.make(decoded_objects[0].data.decode("utf-8"))

    import os
    # 如果skin.png存在，则将二维码与皮肤合成
    if "skin.png" in os.listdir():

        if config["skin_format"] == "custom":
            skin = Image.open(config["custom_skin_path"])
        else:
            skin = Image.open("skin.png")  # 打开皮肤图片
        qr_img = qr_img.convert('RGBA')  # 转换二维码为RGBA模式

        # 获取二维码尺寸
        width, height = qr_img.size

        # 将二维码中的白色区域替换为透明
        for x in range(width):
            for y in range(height):
                r, g, b, a = qr_img.getpixel((x, y))  # 获取当前像素的颜色值
                if r > 200 and g > 200 and b > 200:  # 判断是否为接近白色的像素
                    qr_img.putpixel((x, y), (255, 255, 255, 0))  # 替换为透明像素

        # 调整二维码大小为576x576
        if config["skin_format"] == "custom":
            qrcode_size = int(config["custom_skin_qrcode_size"])
            resized_qr = qr_img.resize((qrcode_size, qrcode_size))
        else:
            resized_qr = qr_img.resize((576, 576))

        # 根据皮肤格式配置确定粘贴位置
        if config["skin_format"] == "new":
            # 新版皮肤格式，二维码居中
            skin.paste(resized_qr, (106, 638), mask=resized_qr)  # 使用 resize 后的图像作为 mask
        elif config["skin_format"] == "old":
            # 旧版皮肤格式，二维码靠下
            skin.paste(resized_qr, (106, 1060), mask=resized_qr)  # 使用 resize 后的图像作为 mask
        else:
            qrcode_point = (config["custom_skin_qrcode_point"][0], config["custom_skin_qrcode_point"][1])
            skin.paste(resized_qr, qrcode_point, mask=resized_qr)

        # 保存合成后的图像到字节流
        skin.save(img_io, format='PNG')

    #如果没找到skin.png，就判断是不是自定义
    elif config["skin_format"] == "custom":

        skin = Image.open(config["custom_skin_path"])  # 打开皮肤图片
        qr_img = qr_img.convert('RGBA')  # 转换二维码为RGBA模式

        # 获取二维码尺寸
        width, height = qr_img.size

        # 将二维码中的白色区域替换为透明
        for x in range(width):
            for y in range(height):
                r, g, b, a = qr_img.getpixel((x, y))  # 获取当前像素的颜色值
                if r > 200 and g > 200 and b > 200:  # 判断是否为接近白色的像素
                    qr_img.putpixel((x, y), (255, 255, 255, 0))  # 替换为透明像素

        # 调整二维码大小为用户设置的
        qrcode_size = int(config["custom_skin_qrcode_size"])
        resized_qr = qr_img.resize((qrcode_size, qrcode_size))

        # 获取用户设置的二维码坐标
        qrcode_point = (config["custom_skin_qrcode_point"][0],config["custom_skin_qrcode_point"][1])
        skin.paste(resized_qr, qrcode_point, mask=resized_qr)

        skin.save(img_io, format='PNG')
    else:
        # 如果没有皮肤文件，则直接保存原始二维码
        qr_img.save(img_io, format='PNG')

    # 将字节流指针移到开始位置
    img_io.seek(0)

    # 杀死微信进程
    kill_wechat_process()

    # 返回包含二维码图像的字节流
    return img_io

# 定义路由 /qrmai
@app.route('/')
def qrmai():
    """
    处理 /qrmai 路由请求的函数
    包含身份验证、缓存机制和并发控制
    """
    # 验证token，如果与配置不符则返回403错误
    if request.args.get('token') != config['token']:
        return Response('403 Forbidden', status=403)

    # 引入全局变量
    global request_lock, last_qr_bytes, last_qr_time

    # 获取当前时间戳
    current_time = time.time()

    # 获取缓存持续时间，默认60秒
    cache_duration = config.get('cache_duration', 60)

    # 如果有正在进行的请求，等待直到请求完成
    while request_lock:
        time.sleep(0.5)
        print("等待请求完成...")

    # 检查缓存是否有效（存在且未过期）
    if last_qr_bytes and (current_time - last_qr_time) < cache_duration:
        # 返回缓存的二维码图像
        return Response(BytesIO(last_qr_bytes), mimetype='image/png')

    # 设置请求锁，防止并发访问
    request_lock = True
    try:
        # 执行二维码获取操作
        img_io = qrmai_action()
        img_io.seek(0)  # 将指针移到开始位置

        # 更新缓存数据
        last_qr_bytes = img_io.getvalue()
        last_qr_time = current_time

        # 返回新生成的二维码图像
        return Response(BytesIO(last_qr_bytes), mimetype='image/png')
    finally:
        # 释放请求锁
        request_lock = False

@app.route('/settings', methods=['GET', 'POST'])
@require_auth
def settings():
    if request.method == 'POST':
        # 读取POST参数并更新config
        token_updated = False
        old_token = config['token']

        # 处理所有表单字段，包括布尔值字段
        # 首先处理布尔值字段，确保未选中的开关也能正确处理
        boolean_fields = ['standalone_mode']
        for field in boolean_fields:
            if field in config:
                # 检查表单中是否包含该字段
                config[field] = field in request.form and request.form[field].lower() in ('true', '1', 'yes', 'on')

        # 处理其他字段
        for key, value in request.form.items():
            # 跳过已处理的布尔值字段
            if key in boolean_fields:
                continue

            if key in config:
                # 尝试将字符串转换为对应类型（int/float/list）
                if isinstance(config[key], bool):
                    config[key] = value.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(config[key], int):
                    config[key] = int(value)
                elif isinstance(config[key], float):
                    config[key] = float(value)
                elif isinstance(config[key], list) and ',' in value:
                    config[key] = [int(v) if v.isdigit() else v for v in value.split(',')]
                else:
                    config[key] = value
                # 检查是否更新了token
                if key == 'token' and value != old_token:
                    token_updated = True
            elif key == "qr_route":  # 处理新的配置项
                config[key] = value
                # 二维码路由路径更改，需要更新路由
                # 注意：在当前请求中无法动态修改路由，需要重启服务

        # 保存更新后的config到文件
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        # 如果token被更新，需要更新配置版本信息
        if token_updated:
            import hashlib
            import time
            import os
            try:
                config_version = hashlib.md5((config['token'] + str(os.path.getmtime(config_path))).encode()).hexdigest()
            except FileNotFoundError:
                config_version = hashlib.md5((config['token'] + str(time.time())).encode()).hexdigest()
            config['version'] = config_version
            # 更新session中的配置版本信息
            session['config_version'] = config_version
        return '配置已更新', 200
    # GET请求时返回设置页面
    return render_template('settings.html', config=config)

@app.route('/check_update', methods=['POST'])
@require_auth
def check_update():
    """检查更新的路由"""
    try:
        # 导入updater模块
        import updater

        # 检查是否有新版本
        has_update, latest_release = updater.is_new_version_available()

        if has_update and latest_release:
            return jsonify({
                'has_update': True,
                'version': latest_release['version'],
                'name': latest_release['name'],
                'published_at': latest_release['published_at'],
                'body': latest_release['body']
            })
        else:
            return jsonify({
                'has_update': False,
                'message': '当前已是最新版本'
            })
    except Exception as e:
        return jsonify({
            'error': True,
            'message': f'检查更新时出错: {str(e)}'
        }), 500

@app.route('/manual_update', methods=['POST'])
@require_auth
def manual_update():
    """手动更新的路由"""
    try:
        # 导入updater模块
        import updater

        # 检查是否有新版本并执行更新
        has_update, latest_release = updater.is_new_version_available()

        if has_update and latest_release:
            # 执行更新
            success = updater.check_and_update()

            if success:
                # 更新成功，返回200状态码
                return '', 200
            else:
                # 更新失败
                return jsonify({
                    'error': True,
                    'message': '更新失败'
                }), 500
        else:
            # 无更新可用，返回204状态码
            return '', 204
    except Exception as e:
        return jsonify({
            'error': True,
            'message': f'手动更新时出错: {str(e)}'
        }), 500


# 读取配置文件
config = {}
config_path = resource_path('config.json')
if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

# 确保配置项完整
config = ensure_config_completeness(config)

# 更新配置版本信息（如果尚未存在）
if 'version' not in config:
    import hashlib
    import time
    import os
    try:
        config_version = hashlib.md5((config['token'] + str(os.path.getmtime(config_path))).encode()).hexdigest()
    except FileNotFoundError:
        config_version = hashlib.md5((config['token'] + str(time.time())).encode()).hexdigest()
    config['version'] = config_version

# 程序入口点
if __name__ == '__main__':
    import hashlib
    import time

    # 读取配置文件
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config_from_file = json.load(f)
        config = ensure_config_completeness(config_from_file)
        # 保存补全后的配置
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        # 添加配置版本标识，用于增强认证安全性
        try:
            config_version = hashlib.md5((config['token'] + str(os.path.getmtime(config_path))).encode()).hexdigest()
        except FileNotFoundError:
            config_version = hashlib.md5((config['token'] + str(time.time())).encode()).hexdigest()
        config['version'] = config_version
    else:
        # 如果config.json不存在，则创建默认配置文件
        config = get_default_config()
        # 保存默认配置到文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        # 添加配置版本标识
        config_version = hashlib.md5((config['token'] + str(time.time())).encode()).hexdigest()
        config['version'] = config_version

    # 根据配置动态注册二维码路由
    qr_route = config.get('qr_route', '/qrmai')
    app.add_url_rule(qr_route, 'qrmai', qrmai)

    # 启动Flask应用，使用配置中的主机和端口
    from webbrowser import open as open_webbrowser
    if config["host"] != "0.0.0.0":
        open_webbrowser(f'http://{config["host"]}:{config["port"]}/login')
    else:
        open_webbrowser(f'http://localhost:{config["port"]}/login')
    app.run(host=config["host"], port=config["port"], debug=config["dev_mode"])
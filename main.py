"""
QRmai - 一个用于获取并返回二维码图片的服务端程序
适用于只有基本联网安卓设备（如：手表、翻页手机）的情况下的出勤场景
"""

# 导入所需的库
from flask import Flask, Response, request  # Flask框架相关模块
import io  # 用于处理字节流
import time  # 时间相关操作

# 图形界面自动化和图像处理相关库
import pyautogui  # GUI自动化库
import pygetwindow as gw  # 窗口管理库
import qrcode  # 二维码生成库
from PIL import Image, ImageDraw, ImageFont  # 图像处理库
from mss import mss  # 屏幕截图库
from pyzbar.pyzbar import decode  # 二维码解码库

# 初始化Flask应用
app = Flask(__name__)

# 添加全局变量用于缓存
# request_lock: 请求锁，防止并发请求
# last_qr_bytes: 上一次生成的二维码字节数据
# last_qr_time: 上一次生成二维码的时间戳
request_lock = False
last_qr_bytes = None
last_qr_time = 0

def qrmai_action():
    """
    核心功能函数：执行二维码获取操作
    1. 定位并激活微信窗口
    2. 自动点击指定位置获取二维码
    3. 截屏并识别二维码
    4. 将二维码与皮肤合成并返回
    """
    # 创建字节流对象用于存储最终的图片数据
    img_io = io.BytesIO()
    
    # 根据配置选择窗口标题
    # standalone_mode为True时使用"舞萌丨中二"，否则使用"微信"
    window_title = "舞萌丨中二" if config.get('standalone_mode', False) else "微信"
    wechat = gw.getWindowsWithTitle(window_title)[0]
    
    # 如果窗口被最小化则恢复，然后激活窗口
    if wechat.isMinimized:
        wechat.restore()
    wechat.activate()

    def move_click(x, y):
        """
        移动鼠标并点击的辅助函数
        :param x: x坐标
        :param y: y坐标
        """
        pyautogui.moveTo(x, y)
        pyautogui.click()

    # 点击第一个位置(p1) - 通常是"舞萌 | 中二服务号生成二维码按钮的位置"
    move_click(config["p1"][0], config["p1"][1])

    # 等待2秒确保界面响应
    time.sleep(2)
    
    # 点击第二个位置(p2) - 通常是"生成后的二维码的消息的位置"
    move_click(config["p2"][0], config["p2"][1])
    
    # 初始化解码结果
    decoded_objects = None
    
    # 最小化微信窗口以减少干扰
    wechat.minimize()
    
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
                # 关闭微信窗口
                window = gw.getWindowsWithTitle("微信")[0]
                window.close()
                
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
            print(f"二维码解码失败 过{config["decode"]["time"] / config["decode"]["retry_count"]}s后重试 ({i+1}/{config["decode"]["retry_count"]})")
    
    # 使用解码得到的数据生成新的二维码
    qr_img = qrcode.make(decoded_objects[0].data.decode("utf-8"))

    import os
    # 如果skin.png存在，则将二维码与皮肤合成
    if "skin.png" in os.listdir():
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
        resized_qr = qr_img.resize((576, 576))
        
        # 根据皮肤格式配置确定粘贴位置
        if config["skin_format"] == "new":
            # 新版皮肤格式，二维码居中
            skin.paste(resized_qr, (106, 638), mask=resized_qr)  # 使用 resize 后的图像作为 mask
        else:
            # 旧版皮肤格式，二维码靠下
            skin.paste(resized_qr, (106, 1060), mask=resized_qr)  # 使用 resize 后的图像作为 mask

        # 保存合成后的图像到字节流
        skin.save(img_io, format='PNG')
    else:
        # 如果没有皮肤文件，则直接保存原始二维码
        qr_img.save(img_io, format='PNG')

    # 将字节流指针移到开始位置
    img_io.seek(0)

    # 关闭微信窗口
    window = gw.getWindowsWithTitle("微信")[0]
    window.close()

    # 返回包含二维码图像的字节流
    return img_io

# 定义路由 /qrmai
@app.route('/qrmai')
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
        return Response(io.BytesIO(last_qr_bytes), mimetype='image/png')

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
        return Response(io.BytesIO(last_qr_bytes), mimetype='image/png')
    finally:
        # 释放请求锁
        request_lock = False

# 程序入口点
if __name__ == '__main__':
    # 导入json模块用于读取配置文件
    import json
    
    # 读取配置文件
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    # 启动Flask应用，使用配置中的主机和端口
    app.run(host=config["host"], port=config["port"])
# QRmai

> 帮您在只有基本联网安卓设备（如：手表、翻盖手机）的情况下也能轻松出勤！

在服务端中获取二维码并将图片返回到客户端，灵感来源于[MaimaiHelper](https://github.com/SomeUtils/MaimaiHelper)

## 为什么使用QRmai

1. 具有更多的自定义选项
2. 兼容MaimaiHelper APP
3. 想不出来了

## 下载

[123云盘](https://www.123865.com/s/4FlLVv-yI48d)

[Github Release](https://github.com/SodaCodeSave/QRmai/releases/latest)

## 部署教程

1. 安装[Python3](https://www.python.org/downloads/)
2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 运行main.py

```bash
python main.py
```

4. 访问http://127.0.0.1:5000/qrmai?token=qrmai

## 皮肤

将你下载好的皮肤放在程序同目录，并重命名为skin.png

制作好的皮肤可以在这里下载：[123云盘](https://www.123865.com/s/4FlLVv-yI48d)

## 配置文件

```
{
  "p1": [1087, 799], // 舞萌 | 中二服务号生成二维码按钮的位置
  "p2": [945, 682], // 生成后的二维码的消息的位置
  "token": "qrmai", // 访问二维码的token
  "host": "127.0.0.1", // 服务器地址 设置成0.0.0.0即可内网访问
  "port": 5000, // 服务器端口
  "cache_duration": 60, // 二维码缓存时间（秒），默认60秒
  "standalone_mode": false // "舞萌丨中二"公众号是否为使用独立窗口显示
}
```